#!/usr/bin/env python3
"""Release evidence for RequestHub on GitHub: preflight, assemble, verify, and approve a release candidate.

Subcommands
  preflight  Before anything is built: checks the version, that the run is on main, that the version is new, and
             reads the release-github environment's protection rules, which decide who can approve. In GitHub Actions
             it writes step outputs (tag, previous_tag, image_prefix, approval_mode) and a job summary.
  assemble   After the tests and images: writes release-manifest.json (commit, image digests, test results, and the
             SHA-256 of every evidence file), SHA256SUMS, and the notes for the draft release.
  verify     Checks a draft or published release: release state, manifest, checksums, test results recounted from
             the reports, commit on main, the candidate run, image digests in the registry, the git tag, and the
             approval record. Read-only; anyone with access to the repository can run it.
  approve    Used by the approval workflow: runs every verify check, checks the approver, then writes
             approval-record.json and the final release notes. It never publishes; the workflow does that with gh.

It calls the GitHub CLI (gh api), so it uses your gh login locally and GH_TOKEN in GitHub Actions.
Standard library only (Python 3.12+).

Usage
  python release_evidence.py preflight --version 1.0.0
  python release_evidence.py assemble --evidence evidence --out release --notes release-notes.md --tag demo-v1.0.0 \
      --commit <sha> --run-id <id> --requested-by <login>
  python release_evidence.py verify --tag demo-v1.0.0
  python release_evidence.py approve --tag demo-v1.0.0 --approver <login> --run-id <id> --workdir release \
      --notes release-notes.md

Run a subcommand with --help for all of its options.
Exit codes: 0 success, 1 a check failed, 2 usage or GitHub error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from summarize_tests import parse_junit, sha256_file  # noqa: E402

TAG_PREFIX = "demo-v"
TAG_RE = re.compile(r"^demo-v(\d+)\.(\d+)\.(\d+)$")
ENVIRONMENT = "release-github"
CANDIDATE_WORKFLOW = ".github/workflows/release-github-candidate.yml"
SOLUTION_PATH = "solutions/06-release-github"
AI_MARKER = "<!-- release-github:ai-summary -->"
MANIFEST = "release-manifest.json"
SUMS = "SHA256SUMS"
APPROVAL = "approval-record.json"
TEST_SUMMARY = "test-summary.json"
WHATS_CHANGED = "whats-changed.md"
SMOKE_RESULTS = "smoke-results.json"
SERVICES = ("api", "worker")
APPROVER_ROLES = ("admin", "maintain")
# key: (label, what ran, report file name)
SUITES = {
    "api": ("API and worker", "xUnit integration tests on PostgreSQL, including the API contract check", "api-tests.junit.xml"),
    "web": ("Web UI", "Vitest unit tests (after the TypeScript check)", "web-tests.junit.xml"),
    "smoke": ("Smoke test on the release images",
              "The pushed API and worker images on the runner: build SHA, submit, triage, decision, history, "
              "self-approval refused, notifications delivered", "smoke-tests.junit.xml"),
    "browser": ("Browser tests on the release image", "Playwright end-to-end tests against the pushed API image",
                "browser-tests.junit.xml"),
}
OCI_ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class GitHubError(RuntimeError):
    pass


class UsageError(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    status: str  # PASS, FAIL, SKIP
    detail: str

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


# --------------------------------------------------------------------------------------------------- GitHub helpers

def gh(args: list[str], binary: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=not binary,
                              encoding=None if binary else "utf-8")
    except FileNotFoundError as error:
        raise GitHubError("the GitHub CLI (gh) is not installed or not on PATH") from error


def api(path: str, ok404: bool = False, paginate: bool = False):
    """GET a GitHub REST path with `gh api` and return parsed JSON (pages are flattened)."""
    args = ["api", path, "-H", "Accept: application/vnd.github+json"]
    if paginate:
        args += ["--paginate", "--slurp"]
    proc = gh(args)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        if ok404 and "404" in message:
            return None
        raise GitHubError(f"gh api {path}: {message}")
    data = json.loads(proc.stdout) if proc.stdout.strip() else None
    if paginate and isinstance(data, list):
        flat = []
        for page in data:
            flat.extend(page if isinstance(page, list) else [page])
        return flat
    return data


def detect_repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    proc = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if proc.returncode != 0:
        raise UsageError("cannot detect the repository; pass --repo OWNER/NAME")
    return proc.stdout.strip()


def server_url() -> str:
    return os.environ.get("GITHUB_SERVER_URL", "https://github.com")


def find_release(repo: str, tag: str) -> dict | None:
    """Find a release by tag, including drafts (the tag endpoint never returns drafts)."""
    for release in api(f"repos/{repo}/releases?per_page=100", paginate=True) or []:
        if release.get("tag_name") == tag:
            return release
    return None


def download_assets(repo: str, release: dict, folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for asset in release.get("assets", []):
        proc = gh(["api", f"repos/{repo}/releases/assets/{asset['id']}", "-H", "Accept: application/octet-stream"],
                  binary=True)
        if proc.returncode != 0:
            raise GitHubError(f"cannot download {asset['name']}: {proc.stderr.decode(errors='replace').strip()}")
        (folder / asset["name"]).write_bytes(proc.stdout)
        names.append(asset["name"])
    return names


def describe_environment(repo: str, name: str = ENVIRONMENT) -> dict | None:
    """Summarize an environment's protection: deployment branches, required reviewers, wait timer."""
    env = api(f"repos/{repo}/environments/{name}", ok404=True)
    if env is None:
        return None
    reviewers: list[str] = []
    prevent_self_review = None
    wait_timer = 0
    for rule in env.get("protection_rules") or []:
        if rule.get("type") == "required_reviewers":
            for entry in rule.get("reviewers") or []:
                reviewer = entry.get("reviewer") or {}
                reviewers.append(reviewer.get("login") or reviewer.get("slug") or reviewer.get("name") or "?")
            prevent_self_review = rule.get("prevent_self_review")
        elif rule.get("type") == "wait_timer":
            wait_timer = rule.get("wait_timer") or 0
    policy = env.get("deployment_branch_policy")
    if policy is None:
        branches = None
    elif policy.get("protected_branches"):
        branches = ["protected branches"]
    else:
        listing = api(f"repos/{repo}/environments/{name}/deployment-branch-policies?per_page=100") or {}
        branches = [p["name"] + (" (tag)" if p.get("type") == "tag" else "") for p in listing.get("branch_policies", [])]
    return {
        "name": name,
        "url": env.get("html_url"),
        "deployment_branches": branches,
        "required_reviewers": reviewers,
        "prevent_self_review": prevent_self_review,
        "wait_timer_minutes": wait_timer,
    }


def approval_mode(env: dict) -> str:
    if env["required_reviewers"]:
        text = f"a required reviewer of the `{env['name']}` environment ({', '.join('@' + r for r in env['required_reviewers'])})"
        if env.get("prevent_self_review"):
            text += ", who cannot be the person who started the approval"
        return text
    return "the person who runs the approval workflow (an admin or maintainer)"


def environment_text(env: dict) -> str:
    branches = env.get("deployment_branches")
    parts = [f"deployments from {', '.join(f'`{b}`' for b in branches)} only" if branches else "any branch can deploy"]
    if env.get("required_reviewers"):
        parts.append("required reviewers " + ", ".join("@" + r for r in env["required_reviewers"])
                     + (" (self-review prevented)" if env.get("prevent_self_review") else ""))
    else:
        parts.append("no required reviewers")
    if env.get("wait_timer_minutes"):
        parts.append(f"wait timer {env['wait_timer_minutes']} min")
    return "; ".join(parts)


# --------------------------------------------------------------------------------------------------- small helpers

def version_key(tag: str) -> tuple[int, int, int] | None:
    match = TAG_RE.match(tag or "")
    return tuple(int(part) for part in match.groups()) if match else None


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_outputs(values: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def checks_table(checks: list[Check]) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚪"}
    lines = ["| | Check | Result |", "| --- | --- | --- |"]
    lines += [f"| {icon.get(c.status, '')} | {c.name} | {c.detail} |" for c in checks]
    return "\n".join(lines)


def print_checks(title: str, checks: list[Check]) -> None:
    print(title)
    for check in checks:
        print(f"  {check.status:<4}  {check.name}: {check.detail}")
    counts = {status: sum(c.status == status for c in checks) for status in ("PASS", "SKIP", "FAIL")}
    print(f"{counts['PASS']} passed, {counts['SKIP']} skipped, {counts['FAIL']} failed")


def read_sums(path: Path) -> dict[str, str]:
    sums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, _, name = line.strip().partition("  ")
            sums[name.lstrip("*")] = digest.lower()
    return sums


def short(sha: str) -> str:
    return sha[:7]


# --------------------------------------------------------------------------------------------------- preflight

def cmd_preflight(args: argparse.Namespace) -> int:
    repo = detect_repo(args.repo)
    checks: list[Check] = []
    version = args.version.strip()
    if version.startswith(TAG_PREFIX):
        version = version[len(TAG_PREFIX):]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise UsageError(f"version must look like 1.0.0, got {args.version!r}")
    tag = TAG_PREFIX + version
    checks.append(Check("version", "PASS", f"`{tag}` (demo releases are always tagged {TAG_PREFIX}X.Y.Z)"))

    ref = args.ref if args.ref is not None else os.environ.get("GITHUB_REF", "")
    if not ref:
        checks.append(Check("built from main", "SKIP", "not running in GitHub Actions"))
    elif ref == "refs/heads/main":
        checks.append(Check("built from main", "PASS", "this run is on `main`"))
    else:
        checks.append(Check("built from main", "FAIL", f"release candidates are built from `main`; this run is on `{ref}`"))

    releases = api(f"repos/{repo}/releases?per_page=100", paginate=True) or []
    published = [r for r in releases if not r.get("draft") and version_key(r.get("tag_name"))]
    latest = max(published, key=lambda r: version_key(r["tag_name"]), default=None)
    previous_tag = latest["tag_name"] if latest else ""
    if any(r["tag_name"] == tag for r in published):
        checks.append(Check("new version", "FAIL", f"`{tag}` is already released; choose a higher version or reset the demo"))
    elif latest and version_key(tag) <= version_key(previous_tag):
        checks.append(Check("new version", "FAIL", f"`{tag}` must be higher than the latest demo release `{previous_tag}`"))
    else:
        tag_ref = api(f"repos/{repo}/git/ref/tags/{tag}", ok404=True)
        if tag_ref is not None:
            checks.append(Check("new version", "FAIL", f"tag `{tag}` exists without a release; delete it or choose another version"))
        else:
            replaced = " (an earlier draft of this version will be replaced)" if any(
                r.get("draft") and r.get("tag_name") == tag for r in releases) else ""
            checks.append(Check("new version", "PASS",
                                f"previous demo release: `{previous_tag}`{replaced}" if previous_tag
                                else f"first demo release{replaced}"))

    env = describe_environment(repo, args.environment)
    mode = ""
    if env is None:
        checks.append(Check("environment", "FAIL",
                            f"environment `{args.environment}` not found; create it as described in {SOLUTION_PATH}/README.md (Set up)"))
    else:
        branches = env["deployment_branches"]
        if not branches:
            checks.append(Check("environment", "FAIL",
                                f"`{args.environment}` lets any branch deploy; restrict it to `main` (see the README's Set up)"))
        else:
            checks.append(Check("environment", "PASS", f"`{args.environment}`: {environment_text(env)}"))
        mode = approval_mode(env)
        if env["required_reviewers"]:
            checks.append(Check("approver", "PASS", f"approval comes from {mode}"))
        else:
            checks.append(Check("approver", "PASS",
                                f"approval comes from {mode}. Required reviewers on environments need a public "
                                "repository on GitHub Free, Pro, and Team, or GitHub Enterprise for private ones"))

    owner = repo.split("/")[0].lower()
    outputs = {"tag": tag, "version": version, "previous_tag": previous_tag,
               "image_prefix": f"ghcr.io/{owner}", "approval_mode": mode}
    write_outputs(outputs)
    write_summary(f"### Preflight for `{tag}`\n\n{checks_table(checks)}\n")
    print_checks(f"Preflight for {tag} in {repo}", checks)
    return 1 if any(c.status == "FAIL" for c in checks) else 0


# --------------------------------------------------------------------------------------------------- assemble

def file_kind(name: str) -> str:
    if name.endswith(".junit.xml"):
        return "test-report"
    if name.endswith(".spdx.json"):
        return "sbom"
    return {MANIFEST: "manifest", TEST_SUMMARY: "test-summary", SMOKE_RESULTS: "smoke-results",
            WHATS_CHANGED: "release-notes-source"}.get(name, "evidence")


def cmd_assemble(args: argparse.Namespace) -> int:
    evidence, out = args.evidence, args.out
    repo = detect_repo(args.repo)
    problems: list[str] = []

    summary_path = evidence / TEST_SUMMARY
    if not summary_path.is_file():
        raise UsageError(f"{summary_path} not found; run summarize_tests.py first")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    suites = {s["name"]: s for s in summary.get("suites", [])}
    missing = [key for key in SUITES if key not in suites]
    if missing:
        problems.append(f"test suites missing from {TEST_SUMMARY}: {', '.join(missing)}")
    if not summary.get("gate", {}).get("passed"):
        problems.append("the test gate did not pass: " + "; ".join(summary.get("gate", {}).get("reasons", [])))

    images = []
    for service in SERVICES:
        path = evidence / f"image-{service}.json"
        if not path.is_file():
            problems.append(f"{path.name} not found (the image job did not finish)")
            continue
        image = json.loads(path.read_text(encoding="utf-8"))
        if image.get("build_sha") != args.commit:
            problems.append(f"{service} image was built from {image.get('build_sha')}, not {args.commit}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image.get("digest", "")):
            problems.append(f"{service} image digest is missing or malformed: {image.get('digest')!r}")
        images.append(image)

    if problems:
        print("Cannot assemble the release:", *problems, sep="\n  - ")
        return 1

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    names = [spec[2] for spec in SUITES.values()] + [TEST_SUMMARY]
    names += [image["sbom"] for image in images if image.get("sbom")]
    for optional in (SMOKE_RESULTS, WHATS_CHANGED):
        if (evidence / optional).is_file():
            names.append(optional)
    for name in names:
        source = evidence / name
        if not source.is_file():
            print(f"Cannot assemble the release: evidence file {name} not found in {evidence}")
            return 1
        shutil.copy2(source, out / name)

    files = [{"name": name, "kind": file_kind(name), "bytes": (out / name).stat().st_size,
              "sha256": sha256_file(out / name)} for name in sorted(names)]
    server = server_url()
    run_url = f"{server}/{repo}/actions/runs/{args.run_id}" + (f"/attempts/{args.run_attempt}" if args.run_attempt else "")
    manifest = {
        "schema": "release-github/manifest@1",
        "product": "RequestHub",
        "demo": True,
        "tag": args.tag,
        "version": args.tag[len(TAG_PREFIX):] if args.tag.startswith(TAG_PREFIX) else args.tag,
        "repository": repo,
        "commit": args.commit,
        "ref": args.ref,
        "previous_tag": args.previous_tag or None,
        "requested_by": args.requested_by,
        "created_at": now_utc(),
        "approval_mode": args.approval_mode or None,
        "candidate_run": {"id": int(args.run_id), "attempt": int(args.run_attempt or 1), "url": run_url,
                          "workflow": CANDIDATE_WORKFLOW},
        "images": [{key: image.get(key) for key in ("service", "name", "tag", "digest", "build_sha", "sbom")}
                   for image in images],
        "tests": {"suites": [{key: suites[k].get(key) for key in
                              ("name", "report", "sha256", "tests", "passed", "failed", "errors", "skipped", "duration_seconds")}
                             for k in SUITES],
                  "totals": summary.get("totals"), "gate": "passed"},
        "files": files,
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sums = sorted([(f["sha256"], f["name"]) for f in files] + [(sha256_file(out / MANIFEST), MANIFEST)],
                  key=lambda item: item[1])
    (out / SUMS).write_text("".join(f"{digest}  {name}\n" for digest, name in sums), encoding="utf-8")

    whats_changed = (out / WHATS_CHANGED).read_text(encoding="utf-8") if (out / WHATS_CHANGED).is_file() else ""
    args.notes.parent.mkdir(parents=True, exist_ok=True)
    args.notes.write_text(render_notes(manifest, whats_changed) + f"\n\n{AI_MARKER}\n", encoding="utf-8")
    print(f"Assembled {args.tag}: {len(files) + 2} release assets in {out}, notes in {args.notes}")
    return 0


# --------------------------------------------------------------------------------------------------- notes

def render_notes(manifest: dict, whats_changed: str, approval: dict | None = None) -> str:
    repo, commit, tag = manifest["repository"], manifest["commit"], manifest["tag"]
    server = server_url()
    run = manifest["candidate_run"]
    lines = [
        "> [!NOTE]",
        f"> Demo release of RequestHub, produced by the [Release evidence on GitHub]({server}/{repo}/tree/main/{SOLUTION_PATH}) "
        "demo. It is not a product release.",
        "",
        f"**Commit** [`{short(commit)}`]({server}/{repo}/commit/{commit}) on `main` · "
        f"**Candidate run** [#{run['id']}]({run['url']}) · **Requested by** @{manifest['requested_by']}",
        "",
        "## Release evidence",
        "",
        "| Container image | Digest |",
        "| --- | --- |",
    ]
    for image in manifest["images"]:
        lines.append(f"| `{image['name']}:{image['tag']}` | `{image['digest']}` |")
    lines += ["", "| Suite | What ran | Tests | Passed | Failed | Skipped |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for suite in manifest["tests"]["suites"]:
        label, what, _ = SUITES.get(suite["name"], (suite["name"], "", ""))
        lines.append(f"| {label} | {what} | {suite['tests']} | {suite['passed']} | {suite['failed'] + suite['errors']} "
                     f"| {suite['skipped']} |")
    lines += [
        "",
        f"Every file attached to this release is listed with its SHA-256 in `{SUMS}`. `{MANIFEST}` ties the files to "
        "the commit and the image digests. Check them yourself with "
        f"`python .github/skills/release-evidence/release_evidence.py verify --tag {tag}`.",
        "",
        "## Approval",
        "",
    ]
    if approval is None:
        mode = manifest.get("approval_mode") or "a person"
        lines.append(f"⏳ **Waiting for approval** by {mode}: run **Release · GitHub · approve and publish** with "
                     f"tag `{tag}`.")
    else:
        when = approval["approved_at"].replace("T", " ").replace("Z", " UTC")
        lines.append(f"✅ **Approved by @{approval['approved_by']}** on {when} "
                     f"([approval run]({approval['approval_run']['url']})).")
        if approval.get("comment"):
            lines += ["", f"> {approval['comment']}"]
        env = approval["environment"]
        reviews = approval["environment"].get("reviews") or []
        passed = sum(c["status"] == "PASS" for c in approval["checks"])
        lines += [
            "",
            "| | |",
            "| --- | --- |",
            f"| Approver | @{approval['approved_by']} ({approval['approver_role']} on the repository) |",
            f"| Requested by | @{approval['requested_by']}" + (" (same person)" if approval["self_approval"] else "") + " |",
            f"| Environment | [`{env['name']}`]({env.get('url') or server}): {environment_text(env)} |",
            f"| Environment reviews | " + (", ".join(f"@{r['user']} {r['state']}" for r in reviews) if reviews
                                          else "none configured") + " |",
            f"| Evidence checks | {passed} of {len(approval['checks'])} passed when approved |",
            f"| Approval record | `{APPROVAL}` (manifest SHA-256 `{approval['manifest_sha256'][:16]}…`) |",
        ]
    lines += ["", "## What's changed", ""]
    body = whats_changed.strip()
    body = re.sub(r"^## What's Changed\s*\n", "", body)
    lines.append(body or "_No pull requests were merged since the previous demo release._")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------- verify

def registry_check(image: dict, user: str | None, token: str | None) -> tuple[bool, str]:
    """HEAD the manifest by digest in the registry (GitHub Container Registry token exchange)."""
    name = image["name"]
    host, _, repository = name.partition("/")
    auth = base64.b64encode(f"{user or 'token'}:{token}".encode()).decode()
    token_url = f"https://{host}/token?service={host}&scope=repository:{repository}:pull"
    try:
        with urllib.request.urlopen(urllib.request.Request(token_url, headers={"Authorization": f"Basic {auth}"}),
                                    timeout=30) as response:
            bearer = json.loads(response.read())["token"]
        request = urllib.request.Request(f"https://{host}/v2/{repository}/manifests/{image['digest']}", method="HEAD",
                                         headers={"Authorization": f"Bearer {bearer}", "Accept": OCI_ACCEPT})
        with urllib.request.urlopen(request, timeout=30) as response:
            served = response.headers.get("Docker-Content-Digest", image["digest"])
    except urllib.error.HTTPError as error:
        return False, f"{name}@{image['digest'][:19]}…: registry answered HTTP {error.code}"
    except (urllib.error.URLError, OSError, KeyError, ValueError) as error:
        return False, f"{name}: {error}"
    if served != image["digest"]:
        return False, f"{name}: registry served {served}, manifest records {image['digest']}"
    return True, f"`{name}@{image['digest'][:19]}…` exists"


def verify_release(repo: str, tag: str, folder: Path, release: dict, expect: str, require_images: bool,
                   registry_user: str | None, registry_token: str | None) -> tuple[list[Check], dict | None]:
    checks: list[Check] = []
    state = "draft" if release.get("draft") else "published"
    if expect != "any" and state != expect:
        checks.append(Check("release", "FAIL", f"`{tag}` is {state}, expected {expect}"))
    else:
        checks.append(Check("release", "PASS", f"`{tag}` is {state}"))

    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        checks.append(Check("manifest", "FAIL", f"{MANIFEST} is not attached to the release"))
        return checks, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as error:
        checks.append(Check("manifest", "FAIL", f"{MANIFEST} is not valid JSON: {error}"))
        return checks, None
    if manifest.get("schema") != "release-github/manifest@1" or manifest.get("tag") != tag or manifest.get("repository") != repo:
        checks.append(Check("manifest", "FAIL", f"{MANIFEST} describes {manifest.get('repository')} "
                                                  f"{manifest.get('tag')}, not {repo} {tag}"))
        return checks, manifest
    commit = manifest["commit"]
    checks.append(Check("manifest", "PASS", f"commit `{short(commit)}`, {len(manifest.get('files', []))} evidence files, "
                                            f"{len(manifest.get('images', []))} images"))

    # Checksums: every asset is listed and matches; the manifest agrees.
    sums_path = folder / SUMS
    if not sums_path.is_file():
        checks.append(Check("checksums", "FAIL", f"{SUMS} is not attached to the release"))
    else:
        sums = read_sums(sums_path)
        present = {p.name for p in folder.iterdir() if p.is_file()} - {SUMS, APPROVAL}
        problems = []
        for name in sorted(present - set(sums)):
            problems.append(f"{name} is not listed in {SUMS}")
        for name, digest in sorted(sums.items()):
            if not (folder / name).is_file():
                problems.append(f"{name} is missing")
            elif sha256_file(folder / name) != digest:
                problems.append(f"{name} changed after the candidate run (SHA-256 mismatch)")
        for entry in manifest.get("files", []):
            if sums.get(entry["name"]) != entry["sha256"]:
                problems.append(f"{entry['name']}: {MANIFEST} and {SUMS} disagree")
        checks.append(Check("checksums", "FAIL", "; ".join(problems)) if problems
                      else Check("checksums", "PASS", f"{len(sums)} files match {SUMS}"))

    # Tests: recount every report and compare with the manifest.
    problems, counts = [], []
    by_name = {s["name"]: s for s in manifest.get("tests", {}).get("suites", [])}
    for key, (label, _, report) in SUITES.items():
        recorded = by_name.get(key)
        if not recorded:
            problems.append(f"{label}: not in the manifest")
            continue
        path = folder / report
        if not path.is_file():
            problems.append(f"{label}: {report} is missing")
            continue
        actual = parse_junit(path)
        for field in ("tests", "passed", "failed", "errors", "skipped"):
            if actual[field] != recorded.get(field):
                problems.append(f"{label}: report has {field}={actual[field]}, manifest says {recorded.get(field)}")
        if actual["failed"] or actual["errors"]:
            problems.append(f"{label}: {actual['failed']} failed, {actual['errors']} errors")
        if actual["tests"] - actual["skipped"] == 0:
            problems.append(f"{label}: no tests ran")
        counts.append(f"{key} {actual['passed']}/{actual['tests']}")
    checks.append(Check("tests", "FAIL", "; ".join(problems)) if problems
                  else Check("tests", "PASS", "no failures: " + ", ".join(counts)))

    # The commit is on main.
    compare = api(f"repos/{repo}/compare/{commit}...main", ok404=True)
    if compare is None:
        checks.append(Check("commit on main", "FAIL", f"commit {commit} not found"))
    elif compare.get("status") in ("identical", "ahead"):
        checks.append(Check("commit on main", "PASS", f"`{short(commit)}` is on `main`"
                                                      + (f" ({compare.get('ahead_by')} commits behind its tip)" if compare.get('ahead_by') else "")))
    else:
        checks.append(Check("commit on main", "FAIL", f"`{short(commit)}` is not an ancestor of main ({compare.get('status')})"))

    # The candidate run that produced the evidence.
    run_info = manifest.get("candidate_run") or {}
    run = api(f"repos/{repo}/actions/runs/{run_info.get('id')}", ok404=True) if run_info.get("id") else None
    if run is None:
        checks.append(Check("candidate run", "FAIL", f"run {run_info.get('id')} not found"))
    else:
        problems = []
        if run.get("path") != CANDIDATE_WORKFLOW:
            problems.append(f"run comes from {run.get('path')}, not {CANDIDATE_WORKFLOW}")
        if run.get("head_sha") != commit:
            problems.append(f"run built {run.get('head_sha')}, manifest says {commit}")
        if run.get("head_branch") != "main":
            problems.append(f"run is on {run.get('head_branch')}, not main")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            problems.append(f"run is {run.get('status')}/{run.get('conclusion')}, expected completed/success")
        checks.append(Check("candidate run", "FAIL", "; ".join(problems)) if problems
                      else Check("candidate run", "PASS", f"[run {run['id']}]({run['html_url']}) succeeded on `main`"))

    # Images exist in the registry with the recorded digests.
    if not registry_token:
        checks.append(Check("images", "FAIL" if require_images else "SKIP",
                            "no registry token (set GHCR_TOKEN to a token that can read packages)"))
    else:
        results = [registry_check(image, registry_user, registry_token) for image in manifest.get("images", [])]
        bad = [detail for ok, detail in results if not ok]
        if len(results) != len(SERVICES):
            bad.append(f"expected {len(SERVICES)} images, manifest lists {len(results)}")
        checks.append(Check("images", "FAIL", "; ".join(bad)) if bad
                      else Check("images", "PASS", "; ".join(detail for _, detail in results)))

    # The git tag (published) or the draft's target.
    if state == "published":
        ref = api(f"repos/{repo}/git/ref/tags/{tag}", ok404=True)
        target = (ref or {}).get("object", {})
        if target.get("type") == "tag":
            target = (api(f"repos/{repo}/git/tags/{target['sha']}") or {}).get("object", {})
        if target.get("sha") == commit:
            checks.append(Check("git tag", "PASS", f"`{tag}` points to `{short(commit)}`"))
        else:
            checks.append(Check("git tag", "FAIL", f"`{tag}` points to {target.get('sha')}, not {commit}"))
    elif release.get("target_commitish") == commit:
        checks.append(Check("git tag", "PASS", f"the draft will tag `{short(commit)}` when published"))
    else:
        checks.append(Check("git tag", "FAIL", f"the draft targets {release.get('target_commitish')}, not {commit}"))

    # The approval record.
    approval_path = folder / APPROVAL
    if approval_path.is_file():
        record = json.loads(approval_path.read_text(encoding="utf-8"))
        problems = []
        if record.get("manifest_sha256") != sha256_file(manifest_path):
            problems.append("it approves a different manifest")
        if record.get("tag") != tag or record.get("commit") != commit:
            problems.append(f"it approves {record.get('tag')} at {record.get('commit')}")
        if record.get("decision") != "approved":
            problems.append(f"decision is {record.get('decision')!r}")
        checks.append(Check("approval record", "FAIL", "; ".join(problems)) if problems
                      else Check("approval record", "PASS", f"approved by @{record.get('approved_by')} at {record.get('approved_at')}"))
    elif state == "published":
        checks.append(Check("approval record", "FAIL", f"published without {APPROVAL}"))
    else:
        checks.append(Check("approval record", "SKIP", "not approved yet"))
    return checks, manifest


def registry_credentials(args: argparse.Namespace) -> tuple[str | None, str | None]:
    token = os.environ.get(args.registry_token_env) if args.registry_token_env else None
    return args.registry_user or os.environ.get("GITHUB_ACTOR"), token


def load_release(args: argparse.Namespace, repo: str) -> tuple[dict, Path]:
    if not TAG_RE.match(args.tag):
        raise UsageError(f"tag must look like {TAG_PREFIX}1.0.0, got {args.tag!r}")
    release = find_release(repo, args.tag)
    if release is None:
        raise UsageError(f"no release (draft or published) with tag {args.tag} in {repo}; "
                         "draft releases are only visible to people and tokens that can write to the repository")
    folder = args.workdir or Path(tempfile.mkdtemp(prefix="release-"))
    if folder.exists():
        shutil.rmtree(folder)
    download_assets(repo, release, folder)
    return release, folder


def cmd_verify(args: argparse.Namespace) -> int:
    repo = detect_repo(args.repo)
    release, folder = load_release(args, repo)
    user, token = registry_credentials(args)
    checks, _ = verify_release(repo, args.tag, folder, release, args.expect, args.require_images, user, token)
    write_summary(f"### Verify `{args.tag}`\n\n{checks_table(checks)}\n")
    print_checks(f"Verify {args.tag} in {repo} (assets in {folder})", checks)
    if args.json:
        args.json.write_text(json.dumps([c.as_dict() for c in checks], indent=2) + "\n", encoding="utf-8")
    return 1 if any(c.status == "FAIL" for c in checks) else 0


# --------------------------------------------------------------------------------------------------- approve

def cmd_approve(args: argparse.Namespace) -> int:
    repo = detect_repo(args.repo)
    release, folder = load_release(args, repo)
    user, token = registry_credentials(args)
    checks, manifest = verify_release(repo, args.tag, folder, release, "draft", True, user, token)
    checks = [c for c in checks if c.name != "approval record" or c.status != "SKIP"]

    approver = args.approver
    role = "none"
    if approver.endswith("[bot]") or approver.lower() in ("copilot", "github-actions"):
        checks.append(Check("approver", "FAIL", f"@{approver} is an automation account; only a person can approve"))
    else:
        permission = api(f"repos/{repo}/collaborators/{approver}/permission", ok404=True) or {}
        role = permission.get("role_name") or permission.get("permission") or "none"
        if role in APPROVER_ROLES:
            checks.append(Check("approver", "PASS", f"@{approver} is {role} on the repository"))
        else:
            checks.append(Check("approver", "FAIL", f"@{approver} is {role}; approving needs {' or '.join(APPROVER_ROLES)}"))
    requested_by = (manifest or {}).get("requested_by")
    self_approval = bool(requested_by) and requested_by.lower() == approver.lower()
    if self_approval and args.prevent_self_approval:
        checks.append(Check("separation of duties", "FAIL",
                            f"@{approver} requested this release and cannot approve it (RELEASE_GITHUB_PREVENT_SELF_APPROVAL)"))
    elif self_approval:
        checks.append(Check("separation of duties", "PASS",
                            f"@{approver} also requested the release; allowed because self-approval is not prevented"))
    else:
        checks.append(Check("separation of duties", "PASS", f"requested by @{requested_by}, approved by @{approver}"))

    env = describe_environment(repo, args.environment)
    if env is None:
        checks.append(Check("environment", "FAIL", f"environment `{args.environment}` not found"))
    reviews = []
    if args.run_id and env is not None:
        for entry in api(f"repos/{repo}/actions/runs/{args.run_id}/approvals") or []:
            reviews.append({"user": (entry.get("user") or {}).get("login"), "state": entry.get("state"),
                            "comment": entry.get("comment"),
                            "environments": [e.get("name") for e in entry.get("environments") or []]})
        if env["required_reviewers"] and not any(r["state"] == "approved" for r in reviews):
            checks.append(Check("environment review", "FAIL",
                                f"`{args.environment}` requires a reviewer, but this run has no approved review"))

    write_summary(f"### Approval checks for `{args.tag}`\n\n{checks_table(checks)}\n")
    print_checks(f"Approval checks for {args.tag} by @{approver}", checks)
    if any(c.status == "FAIL" for c in checks) or manifest is None or env is None:
        print("Not approved: fix the failed checks, or build a new candidate.")
        return 1

    server = server_url()
    run_url = f"{server}/{repo}/actions/runs/{args.run_id}" if args.run_id else None
    record = {
        "schema": "release-github/approval@1",
        "decision": "approved",
        "tag": args.tag,
        "commit": manifest["commit"],
        "manifest_sha256": sha256_file(folder / MANIFEST),
        "approved_by": approver,
        "approver_role": role,
        "requested_by": requested_by,
        "self_approval": self_approval,
        "comment": (args.comment or "").strip() or None,
        "approved_at": now_utc(),
        "approval_run": {"id": int(args.run_id) if args.run_id else None, "url": run_url},
        "environment": {**env, "reviews": reviews},
        "checks": [c.as_dict() for c in checks],
    }
    (folder / APPROVAL).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    body = release.get("body") or ""
    ai_section = body.split(AI_MARKER, 1)[1].strip() if AI_MARKER in body else ""
    whats_changed = (folder / WHATS_CHANGED).read_text(encoding="utf-8") if (folder / WHATS_CHANGED).is_file() else ""
    notes = render_notes(manifest, whats_changed, record) + f"\n\n{AI_MARKER}\n"
    if ai_section:
        notes += f"\n{ai_section}\n"
    args.notes.parent.mkdir(parents=True, exist_ok=True)
    args.notes.write_text(notes, encoding="utf-8")
    write_outputs({"approval_record": str(folder / APPROVAL), "notes": str(args.notes), "commit": manifest["commit"]})
    print(f"Approval recorded in {folder / APPROVAL}; final notes in {args.notes}"
          + (" (AI summary kept)" if ai_section else " (no AI summary on the draft)"))
    return 0


# --------------------------------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", help="OWNER/NAME (default: GITHUB_REPOSITORY, then the current gh repository)")

    p = sub.add_parser("preflight", help="check that a release candidate can start")
    common(p)
    p.add_argument("--version", required=True, help="version to release, for example 1.0.0 (tag demo-v1.0.0)")
    p.add_argument("--ref", help="git ref of the run (default: GITHUB_REF; empty locally, which skips the main check)")
    p.add_argument("--environment", default=ENVIRONMENT, help=f"environment that gates publishing (default {ENVIRONMENT})")

    p = sub.add_parser("assemble", help="write the release manifest, checksums, and draft notes")
    common(p)
    p.add_argument("--evidence", type=Path, required=True,
                   help="folder with the test reports, test-summary.json, image-*.json, SBOMs, and whats-changed.md")
    p.add_argument("--out", type=Path, required=True, help="folder for the release assets (emptied first)")
    p.add_argument("--notes", type=Path, required=True, help="file for the draft release notes (not an asset)")
    p.add_argument("--tag", required=True, help="release tag, for example demo-v1.0.0")
    p.add_argument("--commit", required=True, help="commit SHA the candidate was built from")
    p.add_argument("--ref", default="refs/heads/main", help="git ref of the candidate run (default refs/heads/main)")
    p.add_argument("--previous-tag", default="", help="previous demo release tag, if any")
    p.add_argument("--run-id", required=True, help="GitHub Actions run id of the candidate workflow")
    p.add_argument("--run-attempt", default="1", help="run attempt (default 1)")
    p.add_argument("--requested-by", required=True, help="login of the person who started the candidate")
    p.add_argument("--approval-mode", default="", help="who approves, as reported by preflight (shown in the notes)")

    for name, text in (("verify", "check a draft or published release"),
                       ("approve", "verify a draft, check the approver, and write the approval record and notes")):
        p = sub.add_parser(name, help=text)
        common(p)
        p.add_argument("--tag", required=True, help="release tag, for example demo-v1.0.0")
        p.add_argument("--workdir", type=Path, help="folder to download the release assets into (emptied first; default: a temp folder)")
        p.add_argument("--registry-user", help="registry user for the image check (default: GITHUB_ACTOR)")
        p.add_argument("--registry-token-env", default="GHCR_TOKEN",
                       help="environment variable holding a token that can read the images (default GHCR_TOKEN)")
        if name == "verify":
            p.add_argument("--expect", choices=("draft", "published", "any"), default="any",
                           help="required release state (default any)")
            p.add_argument("--require-images", action="store_true",
                           help="fail instead of skipping the image check when no registry token is set")
            p.add_argument("--json", type=Path, help="also write the check results as JSON to this file")
        else:
            p.add_argument("--approver", required=True, help="login of the person approving (the workflow's triggering actor)")
            p.add_argument("--comment", default="", help="approval note to record")
            p.add_argument("--run-id", default="", help="run id of the approval workflow (links the record, reads environment reviews)")
            p.add_argument("--environment", default=ENVIRONMENT, help=f"environment that gates publishing (default {ENVIRONMENT})")
            p.add_argument("--prevent-self-approval", action="store_true",
                           help="refuse when the approver also requested the release")
            p.add_argument("--notes", type=Path, required=True, help="file for the final release notes")

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        return {"preflight": cmd_preflight, "assemble": cmd_assemble, "verify": cmd_verify,
                "approve": cmd_approve}[args.command](args)
    except (GitHubError, UsageError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
