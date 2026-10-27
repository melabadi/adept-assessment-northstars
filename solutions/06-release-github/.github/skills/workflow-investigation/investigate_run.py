#!/usr/bin/env python3
"""Digest a failed GitHub Actions run so a person or Copilot can explain the failure quickly.

What it does
  1. Reads the run and its jobs with `gh api`.
  2. For every failed job: the failed steps and the log lines around the errors (from `gh run view --log-failed`),
     trimmed so the digest stays short.
  3. Downloads the run's artifacts whose names start with --artifact-prefix and lists the failing tests from any
     JUnit XML reports inside them.
  4. Prints a Markdown digest, or JSON with --json. Read-only: it never re-runs, cancels, approves, or edits anything.

Usage
  python investigate_run.py 1234567890
  python investigate_run.py https://github.com/OWNER/REPO/actions/runs/1234567890 --json out/run-digest.json
  python investigate_run.py --latest-failed --workflow release-github-candidate.yml

Exit codes: 0 digest printed, 2 usage or GitHub error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ERROR_PATTERN = re.compile(r"##\[error\]|\berror\b|\bfail(ed|ure)?\b|exception|assert|refus|mismatch|not found|denied|"
                           r"forbidden|timed? ?out|\bFAIL\b", re.IGNORECASE)
NOISE_PATTERN = re.compile(r"^\s*(warning|info)\b|0 error\(s\)|0 failed|failed: 0|\berrors?=\"0\"", re.IGNORECASE)
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z ?")
ANSI = re.compile(r"(\x1b|\^\[)\[[0-9;]*[A-Za-z]")
# Lines GitHub prints before a step runs: the echoed script (cyan), group markers, the shell, and the step's environment.
PREAMBLE = re.compile(r"^((\x1b|\^\[)\[36;1m|##\[(group|endgroup)\]|shell: |env:\s*$|\s{2}[A-Za-z_][A-Za-z0-9_]*: )")
CONTEXT_BEFORE = 2


class GitHubError(RuntimeError):
    pass


def gh(args: list[str]) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as error:
        raise GitHubError("the GitHub CLI (gh) is not installed or not on PATH") from error
    if proc.returncode != 0:
        raise GitHubError(f"gh {' '.join(args[:3])}: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def gh_json(path: str):
    return json.loads(gh(["api", path, "-H", "Accept: application/vnd.github+json"]) or "null")


def parse_target(value: str | None, repo: str | None) -> tuple[str | None, str | None]:
    if not value:
        return repo, None
    match = re.search(r"github\.com/([^/]+/[^/]+)/actions/runs/(\d+)", value)
    if match:
        return repo or match.group(1), match.group(2)
    if value.isdigit():
        return repo, value
    raise GitHubError(f"expected a run id or a run URL, got {value!r}")


def detect_repo(repo: str | None) -> str:
    if repo:
        return repo
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    return gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def latest_failed(repo: str, workflow: str | None) -> str:
    path = f"repos/{repo}/actions/workflows/{workflow}/runs" if workflow else f"repos/{repo}/actions/runs"
    runs = gh_json(f"{path}?status=failure&per_page=1").get("workflow_runs", [])
    if not runs:
        raise GitHubError(f"no failed runs found{' for ' + workflow if workflow else ''}")
    return str(runs[0]["id"])


def error_excerpts(log: str, max_lines: int) -> dict[str, list[str]]:
    """Group `gh run view --log-failed` output by job and keep error lines with a little context."""
    by_job: dict[str, list[tuple[str, str]]] = {}
    for raw in log.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        job, step, text = parts
        text = TIMESTAMP.sub("", text.lstrip("\ufeff"))
        if PREAMBLE.match(text):
            continue
        by_job.setdefault(job, []).append((step, ANSI.sub("", text).rstrip()))
    excerpts: dict[str, list[str]] = {}
    for job, lines in by_job.items():
        keep: list[int] = []
        for index, (_, text) in enumerate(lines):
            if ERROR_PATTERN.search(text) and not NOISE_PATTERN.search(text):
                keep.extend(range(max(0, index - CONTEXT_BEFORE), index + 1))
        selected, seen, last = [], set(), None
        for index in keep:
            if index in seen:
                continue
            seen.add(index)
            if last is not None and index > last + 1:
                selected.append("…")
            step, text = lines[index]
            selected.append(f"[{step}] {text}"[:400])
            last = index
        if not selected and lines:  # no recognizable error line: show the end of the failed step
            selected = [f"[{step}] {text}"[:400] for step, text in lines[-10:]]
        excerpts[job] = selected[-max_lines:]
    return excerpts


def failing_tests(folder: Path, limit: int = 20) -> list[dict]:
    failures = []
    for report in sorted(folder.rglob("*.xml")):
        try:
            root = ET.parse(report).getroot()
        except ET.ParseError:
            continue
        if root.tag not in ("testsuites", "testsuite"):
            continue
        for case in root.iter("testcase"):
            node = case.find("failure") if case.find("failure") is not None else case.find("error")
            if node is None:
                continue
            message = (node.get("message") or node.text or "").strip().splitlines()
            failures.append({"report": report.name,
                             "test": ".".join(p for p in (case.get("classname"), case.get("name")) if p),
                             "message": message[0][:300] if message else ""})
            if len(failures) >= limit:
                return failures
    return failures


def annotations(repo: str, job_id: int) -> list[str]:
    """Failure annotations of a job: errors, and refusals that happen before any step runs (environment rules)."""
    try:
        items = gh_json(f"repos/{repo}/check-runs/{job_id}/annotations?per_page=50") or []
    except GitHubError:
        return []
    return [a["message"].strip()[:400] for a in items if a.get("annotation_level") == "failure" and a.get("message")]


def investigate(repo: str, run_id: str, artifact_prefix: str, max_lines: int) -> dict:
    run = gh_json(f"repos/{repo}/actions/runs/{run_id}")
    jobs = gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100").get("jobs", [])
    failed_jobs = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out", "cancelled")]
    try:
        excerpts = error_excerpts(gh(["run", "view", run_id, "--repo", repo, "--log-failed"]), max_lines)
    except GitHubError as error:
        excerpts = {"(logs unavailable)": [str(error)]}

    tests: list[dict] = []
    artifacts = gh_json(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100").get("artifacts", [])
    wanted = [a["name"] for a in artifacts if a["name"].startswith(artifact_prefix) and not a.get("expired")]
    if wanted:
        with tempfile.TemporaryDirectory(prefix="run-") as tmp:
            for name in wanted:
                try:
                    gh(["run", "download", run_id, "--repo", repo, "--name", name, "--dir", str(Path(tmp) / name)])
                except GitHubError:
                    continue
            tests = failing_tests(Path(tmp))

    return {
        "run": {key: run.get(key) for key in ("id", "name", "event", "head_branch", "head_sha", "status",
                                              "conclusion", "run_attempt", "html_url", "created_at", "updated_at")}
               | {"actor": (run.get("triggering_actor") or run.get("actor") or {}).get("login")},
        "failed_jobs": [{"name": j["name"], "conclusion": j["conclusion"], "url": j.get("html_url"),
                         "failed_steps": [s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"],
                         "annotations": annotations(repo, j["id"])}
                        for j in failed_jobs],
        "log_excerpts": excerpts,
        "failing_tests": tests,
        "artifacts_read": wanted,
    }


def markdown(digest: dict) -> str:
    run = digest["run"]
    lines = [
        f"## Run {run['id']}: {run['name']}",
        "",
        f"- **Result:** {run['status']}/{run['conclusion']} (attempt {run['run_attempt']}) · [open the run]({run['html_url']})",
        f"- **Trigger:** {run['event']} on `{run['head_branch']}` at `{(run['head_sha'] or '')[:7]}` by @{run['actor']}",
        "",
    ]
    if not digest["failed_jobs"]:
        lines.append("No failed jobs.")
    for job in digest["failed_jobs"]:
        lines.append(f"### Job: {job['name']} ({job['conclusion']})")
        if job["failed_steps"]:
            lines.append("Failed step: " + ", ".join(f"`{s}`" for s in job["failed_steps"]))
        elif not job.get("annotations"):
            lines.append("No step failed: the job was stopped or refused before or between steps.")
        for message in job.get("annotations", []):
            lines.append(f"- Annotation: {message}")
        excerpt = digest["log_excerpts"].get(job["name"], [])
        if excerpt:
            lines += ["", "```text", *excerpt, "```"]
        lines.append("")
    if digest["failing_tests"]:
        lines.append("### Failing tests (from JUnit reports in the run's artifacts)")
        lines += [f"- `{t['test']}` ({t['report']}): {t['message']}" for t in digest["failing_tests"]]
    elif digest["artifacts_read"]:
        lines.append("No failing tests in the reports of: " + ", ".join(digest["artifacts_read"]))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", nargs="?", help="run id or run URL")
    parser.add_argument("--repo", help="OWNER/NAME (default: from the run URL, GITHUB_REPOSITORY, or the current gh repository)")
    parser.add_argument("--latest-failed", action="store_true", help="investigate the most recent failed run instead")
    parser.add_argument("--workflow", help="with --latest-failed: workflow file name, for example release-github-candidate.yml")
    parser.add_argument("--artifact-prefix", default="evidence-",
                        help="download artifacts whose names start with this and read their JUnit reports (default evidence-)")
    parser.add_argument("--max-lines", type=int, default=40, help="maximum log lines kept per failed job (default 40)")
    parser.add_argument("--json", type=Path, help="write the digest as JSON to this file instead of printing Markdown")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        repo, run_id = parse_target(args.run, args.repo)
        repo = detect_repo(repo)
        if args.latest_failed:
            run_id = latest_failed(repo, args.workflow)
        if not run_id:
            parser.error("give a run id or URL, or --latest-failed")
        digest = investigate(repo, run_id, args.artifact_prefix, args.max_lines)
    except GitHubError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(digest, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json}")
    else:
        print(markdown(digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
