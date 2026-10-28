#!/usr/bin/env python3
"""Preview an infrastructure change with Azure what-if, and fail if it touches anything you did not mean to change.

What this script does
  1. Resolves the azd parameters file (infra/main.parameters.json) the way azd does: ${NAME} and ${NAME=default} come
     from environment variables first, then from the azd environment of the project that owns the template
     (`azd env get-values`, run in the folder that holds azure.yaml). In GitHub Actions the workflow sets them.
  2. Runs an Azure Resource Manager what-if of the resource-group template (infra/resources.bicep) against the resource
     group. Nothing is deployed. It uses --validation-level ProviderNoRbac, so an identity that can read the resources and
     run deployment operations (for example Reader plus Policy Enrollments Contributor) can preview a change it has no
     right to deploy.
  3. Separates the change from what-if noise. Raw what-if output also lists values it cannot compute before deployment
     and defaults that Azure sets, on resources nobody touched. So the script also previews the template that was last
     deployed to the resource group (the `resources` deployment that `azd provision` creates) and reports only the
     differences between the two previews: what this template changes compared with what is running. Without a previous
     deployment it reports the raw changes, minus properties the resource provider ignores.
  4. Exits 1 when a change touches a resource type that matches no --expect pattern, so a remediation pull request cannot
     quietly change something else.

The preview is posted on pull requests, so it never shows what identifies the deployment: GUIDs, and the random token
in resource names (the 13 letters and digits in `st<token>` or `vnet-<token>`), appear as `…`.

Usage
  python .github/skills/infrastructure-remediation/whatif.py
  python .github/skills/infrastructure-remediation/whatif.py --expect Microsoft.Storage/storageAccounts \
      --expect Microsoft.Network/virtualNetworks --expect "Microsoft.Network/private*" --markdown preview.md
  python .github/skills/infrastructure-remediation/whatif.py --template path/to/infra/resources.bicep --resource-group rg-x

The defaults point at this repository's Secure solution (solutions/05-secure-microsoft). Requires the Azure CLI 2.76 or
later, signed in (`az login`, or azure/login in GitHub Actions).

Exit codes: 0 only expected changes (or none), 1 unexpected changes, 2 configuration or Azure error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve()
# Works from the root .github/ mirror and from the solution's own copy.
REPO = next((p for p in HERE.parents if (p / ".git").exists()), HERE.parents[3])
DEFAULT_TEMPLATE = REPO / "solutions/05-secure-microsoft/infra/resources.bicep"
AZ = shutil.which("az") or "az"
PLACEHOLDER = re.compile(r"\$\{(?P<name>[A-Za-z0-9_]+)(?:=(?P<default>[^}]*))?\}")
CHANGES = ("Create", "Delete", "Modify")
NOT_PREVIEWABLE = ("Deploy", "Unsupported")
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
NAME_TOKEN = re.compile(r"(?<![a-z0-9])[a-z0-9]{13}(?![a-z0-9])")


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


def az(*args: str) -> str:
    proc = subprocess.run([AZ, *args, "--only-show-errors"], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise ConfigError(f"az {' '.join(args[:3])} failed: {proc.stderr.strip()[:1500]}")
    return proc.stdout


# ---------- Parameters ----------
def project_dir(template: Path) -> Path | None:
    """The azd project (folder with azure.yaml) that owns the template."""
    return next((p for p in template.resolve().parents if (p / "azure.yaml").exists()), None)


@lru_cache(maxsize=1)
def azd_values(project: Path | None) -> dict[str, str]:
    if project is None or not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=project)
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


def value(name: str, project: Path | None, default: str | None = None) -> str | None:
    found = os.environ.get(name) or azd_values(project).get(name)
    if not found and name == "AZURE_PRINCIPAL_ID":
        found = signed_in_user()  # azd resolves it the same way at provision time and does not save it
    return found or default


def resolve_parameters(path: Path, declared: set[str], project: Path | None) -> dict:
    """azd-style substitution, keeping only the parameters the resource-group template declares."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    def substitute(match: re.Match) -> str:
        resolved = value(match["name"], project, match["default"])
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect", action="append", default=[], metavar="TYPE",
                        help="resource type the change is meant to touch, for example Microsoft.Storage/storageAccounts; "
                             "* matches any characters, so Microsoft.Network/private* covers private endpoints and private "
                             "DNS zones (repeat for several). Any other created, modified, or deleted type fails the preview")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                        help="resource-group Bicep template to preview (default: the Secure solution's infra/resources.bicep)")
    parser.add_argument("--parameters", type=Path,
                        help="azd parameters file to resolve (default: main.parameters.json next to the template)")
    parser.add_argument("--resource-group", help="target resource group (default: AZURE_RESOURCE_GROUP from the environment or azd)")
    parser.add_argument("--baseline-deployment", default="resources", metavar="NAME",
                        help="resource-group deployment whose template is the baseline (default: resources, the module "
                             "name in infra/main.bicep); with no such deployment the raw preview is reported")
    parser.add_argument("--markdown", type=Path, help="also write the preview as Markdown, for a pull request comment")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    template = args.template.resolve()
    project = project_dir(template)
    shown = template.relative_to(REPO).as_posix() if template.is_relative_to(REPO) else str(template)
    try:
        resource_group = args.resource_group or value("AZURE_RESOURCE_GROUP", project)
        if not resource_group:
            raise ConfigError("no resource group: pass --resource-group, export AZURE_RESOURCE_GROUP, or run `azd provision` first")
        compiled = json.loads(az("bicep", "build", "--file", str(template), "--stdout"))
        parameters = resolve_parameters(args.parameters or template.parent / "main.parameters.json",
                                        set(compiled.get("parameters", {})), project)
        baseline = deployed_baseline(resource_group, args.baseline_deployment)
        print(f"what-if: {shown} → {resource_group} (nothing is deployed)"
              + (f", compared with the deployed `{args.baseline_deployment}` template" if baseline else "") + "...", flush=True)
        with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=2) as pool:
            head_job = pool.submit(what_if, resource_group, compiled, parameters, Path(tmp), "head")
            base_job = pool.submit(what_if, resource_group, *baseline, Path(tmp), "base") if baseline else None
            head_result = head_job.result()
            base_result = base_job.result() if base_job else None
    except (ConfigError, json.JSONDecodeError) as exc:
        print(f"error: {mask(str(exc))}", file=sys.stderr)
        return 2

    head = changes_by_resource(head_result)
    base = changes_by_resource(base_result) if base_result else None
    mask.learn([c["id"].rstrip("/").split("/")[-1] for c in [*head.values(), *(base or {}).values()]])
    changes, noise = attributable(head, base)
    for change in changes:
        change["expected"] = any(fnmatch.fnmatchcase(change["type"].lower(), p.lower()) for p in args.expect)
    unexpected = [c for c in changes if not c["expected"]]
    previewless = sorted({resource_type(c["id"]) if c["id"].startswith("/") else computed_type(c["id"])
                          for c in head.values() if c["kind"] in NOT_PREVIEWABLE})

    lines = [f"### Deployment preview (Azure what-if) · `{resource_group}`", "",
             f"`{shown}` compared with what is deployed now. Nothing was deployed.", ""]
    for c in changes:
        lines.append(f"- **{c['kind']}** `{c['type']}` `{c['name']}` {'✅ expected' if c['expected'] else '⚠️ unexpected'}")
        lines += [f"  - {describe(p, v)}" for p, v in sorted(c["leaves"].items())]
    if not changes:
        lines.append("- No resource would be created, modified, or deleted.")
    remaining = left_in_place(head, base)
    if remaining:
        lines.append(f"- No longer in the template, so the deployment leaves them in place (incremental deployments never "
                     f"delete): {', '.join(remaining)}. Remove them yourself if they should go.")
    if noise:
        lines.append(f"- {noise} other resource(s) show differences what-if reports on every run (values it can only compute "
                     "during deployment, defaults Azure sets). " + ("They are identical with and without this change, so "
                     "they are not counted." if base is not None else "Only properties the template sets are counted."))
    if previewless:
        lines.append(f"- Not previewable by what-if: {', '.join(previewless)}.")
    lines += ["", f"**PASS**: every change is an expected resource type ({', '.join(args.expect) or 'none expected'})."
              if not unexpected else f"**FAIL**: {len(unexpected)} unexpected change(s); expected only "
              f"{', '.join(args.expect) or 'no changes'}."]
    report = mask("\n".join(lines))
    print(report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(report + "\n", encoding="utf-8")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
