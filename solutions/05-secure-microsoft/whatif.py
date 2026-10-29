#!/usr/bin/env python3
"""Preview an infrastructure change with Azure what-if, and fail if it touches anything you did not mean to change.

Two ways to run it
  On your checkout, signed in with `az login`:
    python whatif.py
    python whatif.py --expect Microsoft.Storage/storageAccounts --expect "Microsoft.Network/private*"
  In Azure, for a pull request. The posture-whatif Container Apps job runs it for every open pull request that changes
  solutions/05-secure-microsoft/infra/ (the Logic App posture-preview starts the job):
    python whatif.py --pull-request 123

What it does
  1. Checks the Bicep before compiling it. A pull request's Bicep is untrusted input: Bicep's load functions
     (loadTextContent and the like), readEnvironmentVariable, externalInput, and module or import paths can read files on
     the machine that compiles them, including the process environment. So the preview refuses a template that calls one
     of those functions, references a registry module, or references a path outside solutions/05-secure-microsoft/infra/
     and app/infra/. It checks every file the template reaches through module and import statements.
  2. Resolves the azd parameters file (infra/main.parameters.json) the way azd does: ${NAME} and ${NAME=default} come from
     environment variables first, then from the azd environment (`azd env get-values`). For a pull request, the
     parameters file and bicepconfig.json come from the default branch, never from the pull request, and only the azd
     names the template needs are substituted.
  3. Runs an Azure Resource Manager what-if of infra/resources.bicep against the resource group. Nothing is deployed.
     --validation-level ProviderNoRbac lets an identity that can read the resources and run deployment operations
     (Reader plus Policy Enrollments Contributor) preview a change it has no right to deploy.
  4. Separates the change from what-if noise. Raw what-if output also lists values it can only compute during deployment
     and defaults Azure sets, on resources nobody touched. So it also previews the template that was last deployed (the
     `resources` deployment `azd provision` creates) and reports only what differs between the two previews.
  5. Fails when a change touches a resource type that matches no --expect pattern, so a remediation pull request cannot
     quietly change something else.

For a pull request it posts a sanitized summary as a comment (which resources would be created, modified, or left in
place, and PASS or FAIL) and sets the commit status posture/what-if. It never posts raw what-if output, property values,
or compiler messages. GUIDs and the random token in resource names (the 13 letters and digits in `st<token>`) appear as
`…` everywhere. The GitHub token never reaches the processes that compile or preview the template.

Exit codes: 0 only expected changes (or none), 1 unexpected changes or a refused template, 2 configuration or Azure error.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path, PurePosixPath

SOLUTION_INFRA = "solutions/05-secure-microsoft/infra"
APP_INFRA = "app/infra"
ENTRY = f"{SOLUTION_INFRA}/resources.bicep"
PARAMETERS = f"{SOLUTION_INFRA}/main.parameters.json"
# Configuration a pull request cannot change for its own preview.
TRUSTED_FROM_MAIN = (PARAMETERS, f"{APP_INFRA}/bicepconfig.json")
# The resource types a storage-networking remediation is expected to touch.
DEFAULT_EXPECT = ["Microsoft.Storage/storageAccounts", "Microsoft.Network/virtualNetworks", "Microsoft.Network/private*"]
# azd names a pull request preview may substitute into the parameters file. Nothing else from the job's environment.
PR_PARAMETER_NAMES = {"AZURE_ENV_NAME", "AZURE_LOCATION", "AZURE_PRINCIPAL_ID", "AZURE_PRINCIPAL_TYPE"}
TOKEN_VARIABLE = "POSTURE_GITHUB_TOKEN"
STATUS_CONTEXT = "posture/what-if"
COMMENT_MARKER = "<!-- posture:what-if -->"

AZ = shutil.which("az") or "az"
PLACEHOLDER = re.compile(r"\$\{(?P<name>[A-Za-z0-9_]+)(?:=(?P<default>[^}]*))?\}")
CHANGES = ("Create", "Delete", "Modify")
NOT_PREVIEWABLE = ("Deploy", "Unsupported")
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
NAME_TOKEN = re.compile(r"(?<![a-z0-9])[a-z0-9]{13}(?![a-z0-9])")
# Functions that read files or the environment while the template compiles, and statements that pull in other files.
READS_AT_COMPILE_TIME = re.compile(r"\b(load[A-Za-z0-9_]*|readEnvironmentVariable|externalInput)\s*\(", re.I)
REFERENCES = (
    re.compile(r"\bmodule\s+[A-Za-z_]\w*\s+'([^']*)'"),
    re.compile(r"\bfrom\s+'([^']*)'"),
    re.compile(r"\b(?:import|extension|using|extends)\s+'([^']*)'"),
)


class Masker:
    """Hides what identifies a deployment: GUIDs, and the random token that azd-style templates put in every resource name
    of a group (13 letters and digits, as in `st<token>` and `vnet-<token>`). learn() finds the token in resource names:
    a 13-character word with letters and digits, or a 13-character ending that several names share."""

    def __init__(self) -> None:
        self.tokens: set[str] = set()

    def learn(self, names: list[str]) -> None:
        lowered = {n.lower() for n in names if n}
        endings = Counter(n[-13:] for n in lowered if len(n) > 13 and re.fullmatch(r"[a-z0-9]{13}", n[-13:]))
        self.tokens |= {t for t, count in endings.items() if count >= 2}
        self.tokens |= {t for n in lowered for t in NAME_TOKEN.findall(n) if re.search(r"\d", t) and re.search(r"[a-z]", t)}

    def __call__(self, text: str) -> str:
        for token in sorted(self.tokens, key=len, reverse=True):
            text = re.sub(re.escape(token), "…", text, flags=re.I)
        return GUID.sub("…", text)


mask = Masker()


class ConfigError(RuntimeError):
    pass


class CompileError(RuntimeError):
    """The template did not compile. Its messages stay in the job's log; they are never posted."""


def child_environment() -> dict[str, str]:
    """The environment for az and Bicep: everything except the GitHub token."""
    env = dict(os.environ)
    env.pop(TOKEN_VARIABLE, None)
    return env


def az(*args: str) -> str:
    proc = subprocess.run([AZ, *args, "--only-show-errors"], capture_output=True, text=True, encoding="utf-8",
                          env=child_environment())
    if proc.returncode != 0:
        raise ConfigError(f"az {' '.join(args[:3])} failed: {proc.stderr.strip()[:1500]}")
    return proc.stdout


# ---------- The template check ----------
def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def without_comments(text: str) -> str:
    """The Bicep text with // and /* */ comments blanked out (newlines kept, so line numbers stay). Strings, string
    interpolation (which can nest strings: '${f('//')}'), and ''' multi-line strings are tracked, so text inside a string
    is never taken for a comment."""
    out = list(text)
    i, n = 0, len(text)
    # Each open string interpolation remembers the brace depth of its expression.
    interpolations: list[int] = []
    depth = 0
    in_string = False
    while i < n:
        if in_string:
            if text[i] == "\\":
                i += 2
            elif text[i] == "'":
                in_string = False
                i += 1
            elif text.startswith("${", i):
                interpolations.append(depth)
                depth = 0
                in_string = False
                i += 2
            else:
                i += 1
            continue
        if text.startswith("'''", i):
            end = text.find("'''", i + 3)
            i = n if end < 0 else end + 3
        elif text[i] == "'":
            in_string = True
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out[i:end] = " " * (end - i)
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out[i:end] = [c if c == "\n" else " " for c in text[i:end]]
            i = end
        elif text[i] == "{":
            depth += 1
            i += 1
        elif text[i] == "}":
            if depth == 0 and interpolations:
                depth = interpolations.pop()
                in_string = True
            else:
                depth -= 1
            i += 1
        else:
            i += 1
    return "".join(out)


def check_templates(root: Path, entry: Path) -> list[str]:
    """Problems that make a template unsafe to compile, as `file:line: reason`. Follows module and import statements
    from the entry template; every file it reaches must stay inside the solution's infra/ or app/infra/."""
    root = root.resolve()
    allowed = [(root / SOLUTION_INFRA).resolve(), (root / APP_INFRA).resolve()]
    problems: list[str] = []
    seen: set[Path] = set()
    queue = [entry.resolve()]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        shown = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            if re.search(r"templateLink|relativePath", text, re.I):
                problems.append(f"{shown}: a JSON template that links another template")
            continue
        # Load functions are refused even in comments (fail closed); references are read from the code only.
        for match in READS_AT_COMPILE_TIME.finditer(text):
            problems.append(f"{shown}:{line_of(text, match.start())}: calls {match[1]}(), which reads files or the "
                            "environment while the template compiles")
        code = without_comments(text)
        for pattern in REFERENCES:
            for match in pattern.finditer(code):
                reference, where = match[1], f"{shown}:{line_of(code, match.start())}"
                if not reference or ":" in reference or "\\" in reference:
                    problems.append(f"{where}: references a registry module or an absolute path; only relative paths in "
                                    "this repository are previewed")
                    continue
                target = (path.parent / reference).resolve()
                if not any(target.is_relative_to(folder) for folder in allowed):
                    problems.append(f"{where}: references a path outside {SOLUTION_INFRA}/ and {APP_INFRA}/")
                    continue
                if target.suffix.lower() not in (".bicep", ".json") or not target.is_file():
                    problems.append(f"{where}: references a file that is not a Bicep or JSON template of the pull request")
                    continue
                queue.append(target)
    return problems


# ---------- Parameters ----------
def project_dir(template: Path) -> Path | None:
    """The azd project (folder with azure.yaml) that owns the template."""
    return next((p for p in template.resolve().parents if (p / "azure.yaml").exists()), None)


@lru_cache(maxsize=1)
def azd_values(project: Path | None) -> dict[str, str]:
    if project is None or not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=project,
                          env=child_environment())
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else {}
    except json.JSONDecodeError:
        return {}


@lru_cache(maxsize=1)
def signed_in_user() -> str | None:
    try:
        return az("ad", "signed-in-user", "show", "--query", "id", "--output", "tsv").strip() or None
    except ConfigError:
        return None


def resolve_parameters(path: Path, declared: set[str], project: Path | None, only: set[str] | None = None) -> dict:
    """azd-style substitution, keeping only the parameters the resource-group template declares. With `only`, names outside
    that set resolve to their default and are never read from the environment."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    def lookup(name: str) -> str | None:
        if only is not None:
            return os.environ.get(name) if name in only else None
        found = os.environ.get(name) or azd_values(project).get(name)
        if not found and name == "AZURE_PRINCIPAL_ID":
            found = signed_in_user()  # azd resolves it the same way at provision time and does not save it
        return found

    def substitute(match: re.Match) -> str:
        resolved = lookup(match["name"]) or match["default"]
        if resolved is None:
            raise ConfigError(f"{match['name']} is not set: run `azd provision` in {project or 'the project'} or export it")
        return resolved

    parameters = {}
    for name, spec in raw["parameters"].items():
        if name not in declared:
            continue
        item = spec.get("value")
        if isinstance(item, str) and PLACEHOLDER.search(item):
            text = PLACEHOLDER.sub(substitute, item)
            item = {"true": True, "false": False}.get(text, text)
        parameters[name] = {"value": item}
    return {"contentVersion": "1.0.0.0", "parameters": parameters}


def deployed_baseline(resource_group: str, deployment: str) -> tuple[dict, dict] | None:
    """Template and parameters of the last deployment with this name in the resource group, or None."""
    try:
        template = json.loads(az("deployment", "group", "export", "--resource-group", resource_group, "--name", deployment))
        used = json.loads(az("deployment", "group", "show", "--resource-group", resource_group, "--name", deployment,
                             "--query", "properties.parameters", "--output", "json"))
    except (ConfigError, json.JSONDecodeError):
        return None
    return template, {"contentVersion": "1.0.0.0",
                      "parameters": {k: {"value": v["value"]} for k, v in (used or {}).items() if "value" in v}}


# ---------- What-if ----------
def what_if(resource_group: str, template: dict, parameters: dict, folder: Path, label: str) -> dict:
    (folder / f"{label}.template.json").write_text(json.dumps(template), encoding="utf-8")
    (folder / f"{label}.parameters.json").write_text(json.dumps(parameters), encoding="utf-8")
    result = json.loads(az("deployment", "group", "what-if", "--resource-group", resource_group,
                           "--name", f"whatif-{label}-{int(time.time())}",
                           "--template-file", str(folder / f"{label}.template.json"),
                           "--parameters", f"@{folder / f'{label}.parameters.json'}",
                           "--validation-level", "ProviderNoRbac", "--no-pretty-print", "--output", "json"))
    if (result.get("status") or "Succeeded") != "Succeeded":
        raise ConfigError(f"what-if {result.get('status')}: {json.dumps(result.get('error'))[:1500]}")
    return result


def resource_type(resource_id: str) -> str:
    """Microsoft.Storage/storageAccounts/blobServices for .../providers/Microsoft.Storage/storageAccounts/st/blobServices/default."""
    parts = resource_id.split("/providers/")[-1].split("/")
    return "/".join([parts[0], *parts[1::2]])


def computed_type(expression: str) -> str:
    """The type of a resource whose id what-if could only show as a template expression (its name is computed at deployment)."""
    match = re.search(r"'(Microsoft\.[A-Za-z]+/[A-Za-z/]+)'", expression)
    return f"{match[1] if match else 'a resource'} (name computed during deployment)"


def leaves(deltas: list[dict] | None, prefix: str = "") -> dict[str, tuple[str, str, str]]:
    """Flattened property changes: path -> (kind, before, after), as JSON text so two previews compare exactly."""
    flat: dict[str, tuple[str, str, str]] = {}
    for delta in deltas or []:
        segment = f"[{delta['path']}]" if str(delta["path"]).isdigit() else f"{'.' if prefix else ''}{delta['path']}"
        path = prefix + segment
        if delta.get("children"):
            flat.update(leaves(delta["children"], path))
        else:
            flat[path] = (delta.get("propertyChangeType") or "",
                          json.dumps(delta.get("before"), sort_keys=True), json.dumps(delta.get("after"), sort_keys=True))
    return flat


def changes_by_resource(result: dict) -> dict[str, dict]:
    return {c["resourceId"].lower(): {"id": c["resourceId"], "kind": c["changeType"], "leaves": leaves(c.get("delta"))}
            for c in result.get("changes", [])}


def unresolved(text: str) -> bool:
    """A value what-if cannot compute before deployment, shown as the raw template expression."""
    return text.startswith('"[') and text.endswith(']"')


def attributable(head: dict[str, dict], base: dict[str, dict] | None) -> tuple[list[dict], int]:
    """Changes the template makes compared with the baseline preview (or, without one, the raw preview minus noise)."""
    found, noise = [], 0
    for key, change in head.items():
        if change["kind"] not in CHANGES:
            continue
        before = (base or {}).get(key, {"kind": "NoChange", "leaves": {}})
        if base is not None and change["kind"] == before["kind"] and change["leaves"] == before["leaves"]:
            noise += 1  # the same difference with and without this template change
            continue
        own = {p: v for p, v in change["leaves"].items() if before["leaves"].get(p) != v and v[0] != "NoEffect"}
        if base is None:
            own = {p: v for p, v in own.items() if not unresolved(v[2]) and v[0] != "Delete"}
        if change["kind"] == "Modify" and not own:
            noise += 1
            continue
        found.append({"kind": change["kind"], "type": resource_type(change["id"]),
                      "name": change["id"].rstrip("/").split("/")[-1], "leaves": own})
    return found, noise


def left_in_place(head: dict[str, dict], base: dict[str, dict] | None) -> list[str]:
    """Resources the deployed template manages that this template no longer declares. Incremental deployments never
    delete, so they stay until someone removes them."""
    if base is None:
        return []
    return sorted(f"`{resource_type(c['id'])}` `{c['id'].rstrip('/').split('/')[-1]}`" for key, c in base.items()
                  if c["kind"] in ("NoChange", "Modify") and head.get(key, {}).get("kind") == "Ignore")


def describe(path: str, change: tuple[str, str, str]) -> str:
    kind, before, after = change

    def short(text: str) -> str:
        return text if len(text) <= 160 else text[:157] + "..."
    if kind == "Create":
        return f"`{path}`: added `{short(after)}`"
    if kind == "Delete":
        return f"`{path}`: removed (was `{short(before)}`)"
    return f"`{path}`: `{short(before)}` → `{short(after)}`"


def preview(template: Path, parameters_file: Path, resource_group: str, expect: list[str], baseline_deployment: str,
            project: Path | None, only: set[str] | None = None) -> dict:
    """Compile, preview, and classify. Raises CompileError when the template does not compile."""
    try:
        compiled = json.loads(az("bicep", "build", "--file", str(template), "--stdout"))
    except (ConfigError, json.JSONDecodeError) as exc:
        raise CompileError(str(exc)) from None
    parameters = resolve_parameters(parameters_file, set(compiled.get("parameters", {})), project, only)
    baseline = deployed_baseline(resource_group, baseline_deployment)
    print(f"what-if → {resource_group} (nothing is deployed)"
          + (f", compared with the deployed `{baseline_deployment}` template" if baseline else "") + "...", flush=True)
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=2) as pool:
        head_job = pool.submit(what_if, resource_group, compiled, parameters, Path(tmp), "head")
        base_job = pool.submit(what_if, resource_group, *baseline, Path(tmp), "base") if baseline else None
        head_result = head_job.result()
        base_result = base_job.result() if base_job else None
    head = changes_by_resource(head_result)
    base = changes_by_resource(base_result) if base_result else None
    mask.learn([c["id"].rstrip("/").split("/")[-1] for c in [*head.values(), *(base or {}).values()]])
    changes, noise = attributable(head, base)
    for change in changes:
        change["expected"] = any(fnmatch.fnmatchcase(change["type"].lower(), p.lower()) for p in expect)
    return {
        "changes": changes,
        "noise": noise,
        "baseline": base is not None,
        "remaining": left_in_place(head, base),
        "previewless": sorted({resource_type(c["id"]) if c["id"].startswith("/") else computed_type(c["id"])
                               for c in head.values() if c["kind"] in NOT_PREVIEWABLE}),
        "unexpected": [c for c in changes if not c["expected"]],
    }


def summary(outcome: dict, expect: list[str], resource_group: str, intro: str, details: bool) -> str:
    """The preview as Markdown. Without details it lists resources and counts only, never property values."""
    lines = [f"### Azure what-if preview · `{resource_group}`", "", intro, ""]
    if outcome["changes"]:
        lines += ["| Change | Resource type | Resource | |", "| --- | --- | --- | --- |"]
        for c in outcome["changes"]:
            properties = f" ({len(c['leaves'])} propert{'y' if len(c['leaves']) == 1 else 'ies'})" if c["kind"] == "Modify" else ""
            lines.append(f"| {c['kind']}{properties} | `{c['type']}` | `{c['name']}` | "
                         f"{'✅ expected' if c['expected'] else '⚠️ unexpected'} |")
            if details:
                lines += [f"  - {describe(p, v)}" for p, v in sorted(c["leaves"].items())]
        lines.append("")
    else:
        lines += ["No resource would be created, modified, or deleted.", ""]
    if outcome["remaining"]:
        lines.append(f"- No longer in the template, so the deployment leaves them in place (incremental deployments never "
                     f"delete): {', '.join(outcome['remaining'])}. Remove them yourself if they should go.")
    if outcome["noise"]:
        lines.append(f"- {outcome['noise']} other resource(s) show differences what-if reports on every run (values it can "
                     "only compute during deployment, defaults Azure sets). " + ("They are identical with and without "
                     "this change, so they are not counted." if outcome["baseline"] else "Only properties the template "
                     "sets are counted."))
    if outcome["previewless"]:
        lines.append(f"- Not previewable by what-if: {', '.join(outcome['previewless'])}.")
    lines += ["", f"**PASS**: every change is an expected resource type ({', '.join(expect) or 'none expected'})."
              if not outcome["unexpected"] else f"**FAIL**: {len(outcome['unexpected'])} unexpected change(s); expected "
              f"only {', '.join(expect) or 'no changes'}."]
    return mask("\n".join(lines))


# ---------- Pull request mode (runs in Azure) ----------
class GitHub:
    """The few GitHub REST calls the preview needs, with the fine-grained token for this repository."""

    def __init__(self, repository: str, token: str) -> None:
        self.repository, self.token = repository, token

    def call(self, method: str, path: str, body: dict | None = None):
        url = f"https://api.github.com/repos/{self.repository}/{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "posture-whatif"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers),
                                        timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ConfigError(f"GitHub {method} {path.split('?')[0]} failed: HTTP {exc.code}") from None
        return json.loads(raw) if raw else None

    def file(self, path: str, ref: str) -> bytes:
        return base64.b64decode(self.call("GET", f"contents/{path}?ref={ref}")["content"])


def fetch_templates(github: GitHub, sha: str, sandbox: Path) -> None:
    """The pull request's Bicep and JSON files under the two infra folders, and the trusted configuration from main.
    Only regular files are written; nothing else from the pull request reaches the sandbox."""
    tree = github.call("GET", f"git/trees/{sha}?recursive=1")
    if tree.get("truncated"):
        raise ConfigError("the repository tree is too large to read in one call")
    for item in tree["tree"]:
        path = item["path"]
        if item["type"] != "blob" or item.get("mode") not in ("100644", "100755") or path in TRUSTED_FROM_MAIN:
            continue
        if not path.startswith((f"{SOLUTION_INFRA}/", f"{APP_INFRA}/")) or not path.lower().endswith((".bicep", ".json")):
            continue
        parts = PurePosixPath(path).parts
        if ".." in parts or any(not part for part in parts):
            continue
        target = sandbox.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(github.call("GET", f"git/blobs/{item['sha']}")["content"]))
    for path in TRUSTED_FROM_MAIN:
        target = sandbox.joinpath(*PurePosixPath(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(github.file(path, "main"))


def post_comment(github: GitHub, number: int, text: str) -> None:
    """Create the preview comment, or update the one an earlier preview of this pull request posted."""
    body = f"{text}\n{COMMENT_MARKER}"
    comments = github.call("GET", f"issues/{number}/comments?per_page=100") or []
    earlier = next((c for c in comments if COMMENT_MARKER in (c.get("body") or "")), None)
    if earlier:
        github.call("PATCH", f"issues/comments/{earlier['id']}", {"body": body})
    else:
        github.call("POST", f"issues/{number}/comments", {"body": body})


def sign_in() -> None:
    """Sign the Azure CLI in with the job's managed identity."""
    client_id = os.environ.get("AZURE_CLIENT_ID")
    az("login", "--identity", *(["--client-id", client_id] if client_id else []), "--output", "none")


def preview_pull_request(number: int, expect: list[str], baseline_deployment: str) -> int:
    # Read the token once and drop it from the environment, so no child process inherits it.
    token = os.environ.pop(TOKEN_VARIABLE, "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    resource_group = os.environ.get("AZURE_RESOURCE_GROUP", "")
    if not token or token == "not-set" or not repository or not resource_group:
        print("error: POSTURE_GITHUB_TOKEN, GITHUB_REPOSITORY, and AZURE_RESOURCE_GROUP must be set", file=sys.stderr)
        return 2
    github = GitHub(repository, token)
    pull = github.call("GET", f"pulls/{number}")
    if pull.get("state") != "open":
        print(f"pull request #{number} is {pull.get('state')}: nothing to preview")
        return 0
    sha = pull["head"]["sha"]

    def status(state: str, description: str) -> None:
        github.call("POST", f"statuses/{sha}", {"state": state, "context": STATUS_CONTEXT, "description": description[:140]})

    print(f"previewing pull request #{number} at {sha[:7]}", flush=True)
    try:
        return report_pull_request(github, number, sha, status, expect, baseline_deployment, resource_group)
    except Exception as exc:  # noqa: BLE001 - whatever fails, the commit status must not stay pending
        print(f"error: {type(exc).__name__}: {mask(str(exc))}", file=sys.stderr)
        try:
            status("error", "The preview failed in Azure; see the posture-whatif job's log")
        except Exception as again:  # noqa: BLE001
            print(f"error: the commit status could not be set either: {mask(str(again))}", file=sys.stderr)
        return 2


def report_pull_request(github: GitHub, number: int, sha: str, status, expect: list[str], baseline_deployment: str,
                        resource_group: str) -> int:
    """Preview the pull request's Bicep, then report: a sanitized comment and the commit status posture/what-if."""
    try:
        changed = [f["filename"] for f in github.call("GET", f"pulls/{number}/files?per_page=100") or []
                   if f["filename"].startswith(f"{SOLUTION_INFRA}/")]
        uncovered = [p.removeprefix("solutions/05-secure-microsoft/") for p in changed if p != ENTRY]
        intro = (f"`{ENTRY}` at `{sha[:7]}`, compared with what is deployed now. Previewed in Azure by the `posture-whatif` "
                 "Container Apps job; nothing was deployed."
                 + (f" Other changed files this preview does not cover: {', '.join(f'`{p}`' for p in uncovered)}."
                    if uncovered else ""))
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            fetch_templates(github, sha, sandbox)
            entry = sandbox.joinpath(*PurePosixPath(ENTRY).parts)
            if not entry.is_file():
                raise ConfigError(f"{ENTRY} is not in the pull request")
            problems = check_templates(sandbox, entry)
            if problems:
                lines = [f"### Azure what-if preview · `{resource_group}`", "",
                         "**Refused**: the pull request's Bicep was not compiled or previewed, because it could read files "
                         "or the environment of the machine that compiles it:", "", *[f"- {p}" for p in problems[:10]], "",
                         f"Previews compile only Bicep under `{SOLUTION_INFRA}/` and `{APP_INFRA}/`, without load "
                         "functions, readEnvironmentVariable, externalInput, or registry modules."]
                post_comment(github, number, "\n".join(lines))
                status("failure", "Refused: the Bicep reads files or references paths outside infra/")
                print("\n".join(problems))
                return 1
            sign_in()
            outcome = preview(entry, sandbox.joinpath(*PurePosixPath(PARAMETERS).parts), resource_group, expect,
                              baseline_deployment, None, only=PR_PARAMETER_NAMES)
    except CompileError as exc:
        print(f"compile error (kept out of the pull request): {mask(str(exc))}", file=sys.stderr)
        post_comment(github, number, f"### Azure what-if preview · `{resource_group}`\n\n**FAIL**: the pull request's Bicep "
                     f"did not compile, so nothing was previewed. Run `az bicep build --file {ENTRY}` on your checkout to "
                     "see why.")
        status("failure", "The Bicep did not compile")
        return 1
    except (ConfigError, json.JSONDecodeError, OSError) as exc:
        print(f"error: {mask(str(exc))}", file=sys.stderr)
        status("error", "The preview could not run; see the posture-whatif job in Azure")
        return 2
    report = summary(outcome, expect, resource_group, intro, details=False)
    post_comment(github, number, report)
    unexpected = len(outcome["unexpected"])
    status("failure" if unexpected else "success",
           f"FAIL: {unexpected} unexpected change(s)" if unexpected else
           f"PASS: {len(outcome['changes'])} expected change(s), nothing else")
    print(report)
    return 1 if unexpected else 0


# ---------- Local mode ----------
def repository_root() -> Path:
    here = Path(__file__).resolve()
    root = next((p for p in here.parents if (p / ".git").exists()), None)
    if root is None:
        raise ConfigError("run this from a clone of the repository, or pass --pull-request")
    return root


def preview_checkout(args: argparse.Namespace, expect: list[str]) -> int:
    root = repository_root()
    template = (args.template or root / ENTRY).resolve()
    project = project_dir(template)
    shown = template.relative_to(root).as_posix() if template.is_relative_to(root) else str(template)
    try:
        problems = check_templates(root, template)
        if problems:
            print("Refused: this template could read files or the environment while it compiles:\n"
                  + "\n".join(f"  {p}" for p in problems))
            return 1
        resource_group = args.resource_group or os.environ.get("AZURE_RESOURCE_GROUP") \
            or azd_values(project).get("AZURE_RESOURCE_GROUP")
        if not resource_group:
            raise ConfigError("no resource group: pass --resource-group, export AZURE_RESOURCE_GROUP, or run `azd provision` first")
        outcome = preview(template, args.parameters or template.parent / "main.parameters.json", resource_group, expect,
                          args.baseline_deployment, project)
    except CompileError as exc:
        print(f"error: the template did not compile: {mask(str(exc))}", file=sys.stderr)
        return 2
    except (ConfigError, json.JSONDecodeError) as exc:
        print(f"error: {mask(str(exc))}", file=sys.stderr)
        return 2
    report = summary(outcome, expect, resource_group, f"`{shown}` compared with what is deployed now. Nothing was deployed.",
                     details=True)
    print(report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(report + "\n", encoding="utf-8")
    return 1 if outcome["unexpected"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pull-request", type=int, metavar="NUMBER",
                        help="preview this pull request's Bicep in Azure and report on the pull request (needs "
                             "POSTURE_GITHUB_TOKEN, GITHUB_REPOSITORY, and AZURE_RESOURCE_GROUP; the posture-whatif job "
                             "sets them)")
    parser.add_argument("--expect", action="append", metavar="TYPE",
                        help="resource type the change is meant to touch; * matches any characters, so "
                             "Microsoft.Network/private* covers private endpoints and private DNS zones (repeat for "
                             f"several). Default: {', '.join(DEFAULT_EXPECT)}. Any other created, modified, or deleted "
                             "type fails the preview")
    parser.add_argument("--template", type=Path,
                        help=f"local mode: resource-group Bicep template to preview (default: {ENTRY})")
    parser.add_argument("--parameters", type=Path,
                        help="local mode: azd parameters file to resolve (default: main.parameters.json next to the template)")
    parser.add_argument("--resource-group",
                        help="local mode: target resource group (default: AZURE_RESOURCE_GROUP from the environment or azd)")
    parser.add_argument("--baseline-deployment", default="resources", metavar="NAME",
                        help="resource-group deployment whose template is the baseline (default: resources, the module "
                             "name in infra/main.bicep); with no such deployment the raw preview is reported")
    parser.add_argument("--markdown", type=Path, help="local mode: also write the preview as Markdown")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    expect = args.expect or DEFAULT_EXPECT
    if args.pull_request is not None:
        return preview_pull_request(args.pull_request, expect, args.baseline_deployment)
    try:
        return preview_checkout(args, expect)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
