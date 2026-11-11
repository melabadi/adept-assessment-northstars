#!/usr/bin/env python3
"""Collect the facts of a pull request's failed CI run, before anyone explains it (ci-investigation skill).

The agentic workflow "Test · GitHub · agentic CI failure investigation" runs this script before its agent starts, so the
agent works from facts gathered the same way every time: which tests failed, with which message, in which file and
line, whether the pull request adds or changes each of them, and whether main's latest CI run fails them too. The agent
then sorts each failure into one of three classes and writes one comment; SKILL.md says how. A person can run it too,
to see what the agent sees.

It reads GitHub with the GitHub CLI and changes nothing. It investigates only a failed run of a pull request from a
branch of this repository, never a fork's, into a base branch that matches --base, whose author is the repository's
owner, a member, a collaborator, or Copilot, and whose head is still the commit that failed. Anything else is skipped,
and facts.json says why.

It writes, in --out:
  facts.json   the run, the pull request, each failing test (its message, file and line, links to the log and the file,
               whether the pull request adds or changes it, whether it also fails on main), the build and other
               failures, and main's latest CI result
  facts.md     the same facts as Markdown, for the agent and for a person
  pr.patch     the pull request's diff, at most 3,000 lines
  logs/        each failed job's log around its failures, at most 400 lines per job

Usage
  python .github/skills/ci-investigation/ci_failure_facts.py --run 42759314093
  python .github/skills/ci-investigation/ci_failure_facts.py --run 42759314093 --base 'lab/test-*' --out out/ci
  python .github/skills/ci-investigation/ci_failure_facts.py --run 42759314093 --noop-to "$GH_AW_SAFE_OUTPUTS"

Needs the GitHub CLI, signed in with read access to the repository's pull requests, contents, and Actions runs
(GH_TOKEN in a workflow). Test methods are found with review-evidence's prove_fix.py (xUnit [Fact] and [Theory]).

Exit codes: 0 facts written, or nothing to investigate (facts.json "skip" says why); 2 configuration or GitHub CLI
error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "review-evidence"))
import prove_fix  # noqa: E402  (test_methods: the xUnit test methods of a C# file and their text)

TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
COPILOT = "Copilot"  # the cloud agent opens its pull requests as this bot
MAX_FAILURES = 30
MAX_MESSAGE_LINES = 12
MAX_LINE = 300
MAX_SOURCE_LINES = 120
MAX_PATCH_LINES = 3000
MAX_LOG_LINES = 400
TAIL_LINES = 80
BLOCK_LINES = 60

TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")
WORKSPACE = re.compile(r"^.*?/home/runner/work/[^/]+/[^/]+/")  # GitHub-hosted runners check out into work/<repo>/<repo>/
DOTNET_FAILED = re.compile(r"^failed (?P<name>\S.*?) \((?P<duration>\d[^()]*)\)\s*$")
DOTNET_FRAME = re.compile(r"^\s+at (?P<frame>.+?)(?: in (?P<path>\S.*?):(?:line )?(?P<line>\d+))?\s*$")
DOTNET_FROM = re.compile(r"^\s*from \S+\.dll \(")  # Microsoft Testing Platform names the test assembly first
SUMMARY = re.compile(r"^\s*(?P<key>total|failed|succeeded|skipped): (?P<value>\d+)\s*$")
BUILD_ERROR = re.compile(r"(?P<path>[^\s(:]+\.(?:cs|tsx?|jsx?|csproj|props|targets))\((?P<line>\d+),(?P<col>\d+)\): "
                         r"error (?P<code>[A-Z]+\d+): (?P<message>.+?)(?: \[[^\]]*\])?\s*$")
PLAYWRIGHT_FAILED = re.compile(r"^\s+\d+\) \[(?P<project>[^\]]+)\] › (?P<file>[^:\s]+):(?P<line>\d+):\d+ › (?P<title>.+?)\s*$")
VITEST_FAILED = re.compile(r"^\s*(?:FAIL|×|✗)\s+(?P<file>\S+\.(?:test|spec)\.[cm]?[jt]sx?)\s+>\s+(?P<title>.+?)\s*$")
JS_FRAME = re.compile(r"(?:\bat |❯ )\(?(?P<path>[^\s()]+\.(?:test|spec)\.[cm]?[jt]sx?):(?P<line>\d+):\d+\)?")
JS_ERROR = re.compile(r"^\s*(?:Error|AssertionError|TypeError|ReferenceError)\b")
JS_CODE = re.compile(r"^\s*(?:>?\s*\d+ \||at |❯ |Call log:)")
GH_ERROR = re.compile(r"^##\[error\]")


class FactsError(Exception):
    """A configuration or GitHub CLI problem (exit code 2)."""


def gh(*args: str, check: bool = True) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except FileNotFoundError as exc:
        raise FactsError("the GitHub CLI (gh) is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise FactsError(f"gh {' '.join(args[:2])} did not answer within 5 minutes") from exc
    if check and proc.returncode != 0:
        raise FactsError(f"gh {' '.join(args[:2])}: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout if proc.returncode == 0 else ""


def api(endpoint: str) -> dict:
    return json.loads(gh("api", endpoint) or "null") or {}


def api_list(endpoint: str, jq: str = ".[]") -> list[dict]:
    """Every item of a paginated REST list, one compact JSON object per line. `jq` selects the items, for example
    ".jobs[]" for an endpoint that wraps its list in an object."""
    out = gh("api", "--paginate", endpoint, "--jq", jq)
    return [json.loads(line) for line in out.split("\n") if line.strip()]


def job_log(repo: str, job_id: int) -> str:
    """A job's raw log. Recent GitHub CLIs refuse to print terminal escape sequences unless told to; older ones don't know
    the flag."""
    try:
        return gh("api", "--allow-escape-sequences", f"repos/{repo}/actions/jobs/{job_id}/logs")
    except FactsError as exc:
        if "allow-escape-sequences" not in str(exc):
            raise
        return gh("api", f"repos/{repo}/actions/jobs/{job_id}/logs")


def file_at(repo: str, path: str, sha: str, cache: dict) -> str:
    """A file's text at a commit, or "" when it doesn't exist there."""
    key = (path, sha)
    if key not in cache:
        cache[key] = gh("api", f"repos/{repo}/contents/{quote(path)}?ref={sha}", "-H", "Accept: application/vnd.github.raw",
                        check=False)
    return cache[key]


def clean(line: str) -> str:
    """A log line without its timestamp, byte-order mark, or color codes."""
    return ANSI.sub("", TIMESTAMP.sub("", line.rstrip("\r")))


def relative(path: str) -> str:
    """A path in the runner's checkout, relative to the repository's root."""
    return WORKSPACE.sub("", path.strip()).lstrip("/") if path else ""


def clip(text: str, limit: int = MAX_LINE) -> str:
    text = text.rstrip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def split_test(name: str) -> tuple[str, str]:
    """Namespace.Class.Method(arguments) -> (Class, Method)."""
    parts = name.split("(", 1)[0].split(".")
    return (parts[-2] if len(parts) > 1 else "", parts[-1])


def in_changed(path: str, changed: dict[str, dict]) -> str:
    """The path of a file the pull request changes that `path` names: the same path, or one that ends with it (type-check
    and unit-test tools print paths relative to their project folder). "" when the pull request doesn't change it."""
    if not path:
        return ""
    if path in changed:
        return path
    return next((p for p in changed if p.endswith("/" + path)), "")


def parse_log(text: str) -> dict:
    """The failures in a job's log: .NET test failures (Microsoft Testing Platform), build and type-check errors,
    Playwright and Vitest failures, the .NET test summary, and the lines before the first error when nothing else
    explains the failure. Every list is in log order and has no duplicates."""
    lines = [clean(line) for line in text.splitlines()]
    tests: list[dict] = []
    errors: list[dict] = []
    summary: dict[str, int] = {}
    seen: set = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        dotnet = DOTNET_FAILED.match(line)
        js = PLAYWRIGHT_FAILED.match(line) or VITEST_FAILED.match(line)
        if dotnet:
            block, message, frames = [line], [], []
            j = i + 1
            while j < len(lines) and j - i < BLOCK_LINES and not DOTNET_FAILED.match(lines[j]):
                frame = DOTNET_FRAME.match(lines[j])
                if frame:
                    frames.append(frame)
                elif frames and lines[j].strip() and not lines[j][:1].isspace():
                    break
                elif not frames and lines[j].strip() and not DOTNET_FROM.match(lines[j]):
                    message.append(lines[j].strip())
                block.append(lines[j])
                j += 1
            name = dotnet.group("name")
            method = split_test(name)[1]
            at = next((f for f in frames if f.group("path") and f".{method}(" in f.group("frame")),
                      next((f for f in frames if f.group("path")), None))
            if ("dotnet", name) not in seen:
                seen.add(("dotnet", name))
                tests.append({"kind": "dotnet", "test": name, "message": message[:MAX_MESSAGE_LINES],
                              "file": relative(at.group("path")) if at else "",
                              "line": int(at.group("line")) if at else 0, "excerpt": block})
            i = j
            continue
        if js:
            kind = "playwright" if PLAYWRIGHT_FAILED.match(line) else "vitest"
            block, message, location, collecting = [line], [], None, False
            j = i + 1
            while j < len(lines) and j - i < BLOCK_LINES and not PLAYWRIGHT_FAILED.match(lines[j]) \
                    and not VITEST_FAILED.match(lines[j]):
                current = lines[j]
                if not message and JS_ERROR.match(current):
                    collecting = True
                elif collecting and JS_CODE.match(current):
                    collecting = False  # the error ends where the call log, the code frame, or the stack begins
                if collecting and current.strip() and len(message) < MAX_MESSAGE_LINES:
                    message.append(current.strip())
                location = location or JS_FRAME.search(current)
                block.append(current)
                j += 1
            title = js.group("title")
            key = (kind, js.group("file"), title)
            if key not in seen:
                seen.add(key)
                listed_line = int(js.group("line")) if "line" in js.groupdict() else 0
                tests.append({"kind": kind, "test": title, "message": message,
                              "file": relative(location.group("path")) if location else js.group("file"),
                              "line": int(location.group("line")) if location else listed_line, "excerpt": block})
            i = j
            continue
        build = BUILD_ERROR.search(line)
        if build:
            key = ("build", relative(build.group("path")), build.group("line"), build.group("code"))
            if key not in seen:
                seen.add(key)
                errors.append({"kind": "build", "file": relative(build.group("path")), "line": int(build.group("line")),
                               "code": build.group("code"), "message": [clip(build.group("message"))], "excerpt": [line]})
        total = SUMMARY.match(line)
        if total:
            summary[total.group("key")] = int(total.group("value"))
        i += 1
    tail: list[str] = []
    if not tests and not errors:
        end = next((n for n, line in enumerate(lines) if GH_ERROR.match(line)), len(lines))
        tail = [line for line in lines[max(0, end - TAIL_LINES):end + 1] if line.strip()]
    return {"tests": tests, "errors": errors, "summary": summary, "tail": tail}


def failed_jobs(repo: str, run: dict) -> list[dict]:
    """The jobs of the run's latest attempt that failed or timed out, with their first failed step, and whether they ran
    at all (a run that was never approved has jobs that never started)."""
    jobs = api_list(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run.get('run_attempt') or 1}/jobs?per_page=100",
                    ".jobs[]")
    failed = []
    for job in jobs:
        if job.get("conclusion") not in ("failure", "timed_out"):
            continue
        steps = job.get("steps") or []
        step = next((s for s in steps if s.get("conclusion") in ("failure", "timed_out")), None)
        failed.append({"id": job["id"], "name": job.get("name") or "?", "conclusion": job["conclusion"],
                       "url": job.get("html_url") or "", "step": (step or {}).get("name") or "",
                       "step_number": (step or {}).get("number") or 0,
                       "ran": bool(job.get("started_at")) and any(s.get("conclusion") not in (None, "skipped") for s in steps)})
    return failed


def log_url(job: dict) -> str:
    """The job's log, opened at its first failed step."""
    return f"{job['url']}#step:{job['step_number']}:1" if job["url"] and job["step_number"] else job["url"]


def main_ci(repo: str, run: dict, branch: str) -> dict:
    """The latest completed push run of the same workflow on the default branch, and what failed in it."""
    runs = api(f"repos/{repo}/actions/workflows/{run['workflow_id']}/runs?branch={quote(branch)}&event=push"
               f"&status=completed&per_page=1").get("workflow_runs") or []
    result = {"branch": branch, "run_id": 0, "conclusion": "none", "url": "", "head_sha": "", "created_at": "",
              "failed_tests": [], "build_errors": []}
    if not runs:
        return result
    latest = runs[0]
    result.update(run_id=latest["id"], conclusion=latest.get("conclusion") or "?", url=latest.get("html_url") or "",
                  head_sha=latest.get("head_sha") or "", created_at=latest.get("created_at") or "")
    if latest.get("conclusion") == "failure":
        for job in failed_jobs(repo, latest)[:5]:
            parsed = parse_log(job_log(repo, job["id"]))
            result["failed_tests"] += [t["test"] for t in parsed["tests"]]
            result["build_errors"] += [f"{e['file']}:{e['line']} {e['code']}" for e in parsed["errors"]]
    return result


def on_main(test: str, main: dict) -> str:
    """Whether the same test fails in main's latest CI run: failed, passed, or unknown."""
    if main["conclusion"] == "success":
        return "passed"
    if test in main["failed_tests"]:
        return "failed"
    return "unknown"


def change_of(failure: dict, changed: dict[str, dict], repo: str, merge_base: str, head: str, cache: dict) -> tuple[str, str]:
    """Whether the pull request adds, changes, or leaves as it is the failing test, and the test's source at the head.

    .NET tests are compared method by method (prove_fix.test_methods), from the merge base to the head. Browser and unit
    tests are compared by file: "added" when the pull request adds the file, "file-changed" when it changes it."""
    if failure["kind"] != "dotnet":
        status = changed.get(in_changed(failure["file"], changed), {}).get("status")
        return ("added" if status == "added" else "file-changed" if status else "unchanged"), ""
    method = split_test(failure["test"])[1]
    candidates = [failure["file"]] if failure["file"] else []
    candidates += [p for p in changed if p.endswith(".cs") and prove_fix.TEST_FILE.search(p) and p not in candidates]
    for path in candidates:
        methods = prove_fix.test_methods(file_at(repo, path, head, cache))
        if method not in methods:
            continue
        source = "\n".join(methods[method].splitlines()[:MAX_SOURCE_LINES])
        if path not in changed:
            return "unchanged", source
        before = prove_fix.test_methods(file_at(repo, changed[path].get("previous_filename") or path, merge_base, cache))
        if method not in before:
            return "added", source
        return ("changed" if before[method] != methods[method] else "unchanged"), source
    return "unknown", ""


def write_patch(files: list[dict], out: Path) -> bool:
    """The pull request's diff, from GitHub's per-file patches; True when it had to be cut."""
    lines: list[str] = []
    for f in files:
        lines.append(f"diff --git a/{f.get('previous_filename') or f['filename']} b/{f['filename']}  ({f.get('status')})")
        lines += (f.get("patch") or "(no patch: a binary or very large file)").splitlines()
    cut = len(lines) > MAX_PATCH_LINES
    out.write_text("\n".join(lines[:MAX_PATCH_LINES] + (["… (cut at 3,000 lines)"] if cut else [])) + "\n", encoding="utf-8")
    return cut


def where(item: dict) -> str:
    return prove_fix.code(f"{item['file']}:{item['line']}") if item.get("file") else "unknown"


def render(facts: dict) -> str:
    """facts.json as Markdown. Everything quoted from the run or the pull request stays in a code block or a code span:
    the agent reads it as data."""
    run, pr, main = facts["run"], facts["pull_request"], facts["main"]
    code = prove_fix.code
    on_main_line = f"`{main['conclusion']}`" + (f" on `{main['head_sha'][:9]}`, {main['url']}" if main["url"] else "")
    files = ", ".join(f"{code(f['path'])} ({f['status']})" for f in facts["changed_files"][:40])
    out = [f"# Facts: CI run {run['id']} (attempt {run['attempt']}) on pull request {pr['number']}", "",
           f"- Run: {run['url']}, conclusion `{run['conclusion']}`, head `{run['head_sha'][:9]}`",
           f"- Pull request {pr['number']}: {code(pr['head'])} into {code(pr['base'])}, by {code(pr['author'])} "
           f"({pr['author_association']}), merge base `{pr['merge_base'][:9]}`",
           f"- Main's latest CI: {on_main_line}",
           f"- Failing on main: {', '.join(code(t) for t in main['failed_tests'][:20]) or 'nothing listed'}",
           f"- Files the pull request changes ({len(facts['changed_files'])}): {files}", "",
           f"## Failing tests ({facts['failures_total']}, {len(facts['failures'])} listed)", ""]
    for n, f in enumerate(facts["failures"], 1):
        link = f", {f['file_url']}" if f["file_url"] else ""
        out += [f"### {n}. {code(f['test'], 200)}", "",
                f"- Kind: {f['kind']}; job {code(f['job'])}; log: {f['log_url']}",
                f"- Where: {where(f)}{link}",
                f"- Pull request change: `{f['pull_request_change']}`",
                f"- On main: `{f['on_main']}`", "- Message:", "", "```text", *f["message"], "```", ""]
        if f["source"]:
            out += ["- Test source at the head:", "", "```", f["source"], "```", ""]
    out += [f"## Build and other failures ({len(facts['other_failures'])})", ""]
    for n, f in enumerate(facts["other_failures"], 1):
        changed = f"; in a file the pull request changes: `{f['in_pull_request']}`" if f.get("file") else ""
        at = f" at {where(f)}" if f.get("file") else ""
        out += [f"### {n}. {f['kind']} in job {code(f['job'])}{at}", "", f"- Log: {f['log_url']}{changed}", "",
                "```text", *f["message"], "```", ""]
    out += ["Excerpts of each failed job's log are in `logs/`, and the pull request's diff is in `pr.patch`."]
    return "\n".join(out) + "\n"


def skip(out: Path, reason: str, noop_to: str | None, facts: dict | None = None) -> int:
    """Nothing to investigate: say why in facts.json and, for the workflow, in a gh-aw noop, so its agent doesn't start."""
    (out / "facts.json").write_text(json.dumps({**(facts or {}), "skip": reason}, indent=2) + "\n", encoding="utf-8")
    print(f"Nothing to investigate: {reason}")
    if noop_to:
        with open(noop_to, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "noop", "message": f"Nothing to investigate: {reason}"}) + "\n")
    return 0


def collect(repo: str, run_id: int, bases: list[str], out: Path, noop_to: str | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if (run.get("head_repository") or {}).get("full_name") != repo:
        return skip(out, "the run is not from a branch of this repository", noop_to)
    if run.get("event") != "pull_request":
        return skip(out, f"the run was started by `{run.get('event')}`, not by a pull request", noop_to)
    if run.get("status") != "completed" or run.get("conclusion") != "failure":
        return skip(out, f"the run's conclusion is `{run.get('conclusion') or run.get('status')}`, not a failure", noop_to)
    numbers = [p["number"] for p in run.get("pull_requests") or []]
    if not numbers:
        numbers = [p["number"] for p in api_list(f"repos/{repo}/commits/{run['head_sha']}/pulls")
                   if p.get("state") == "open"]
    if not numbers:
        return skip(out, "no open pull request has this run's commit as its head", noop_to)
    pr = api(f"repos/{repo}/pulls/{numbers[0]}")
    user = pr.get("user") or {}
    facts = {"repository": repo,
             "run": {"id": run["id"], "attempt": run.get("run_attempt") or 1, "url": run.get("html_url") or "",
                     "head_sha": run["head_sha"], "conclusion": run["conclusion"], "workflow": run.get("name") or "",
                     "created_at": run.get("created_at") or ""},
             "pull_request": {"number": pr["number"], "url": pr.get("html_url") or "", "base": pr["base"]["ref"],
                              "head": pr["head"]["ref"], "author": user.get("login") or "?",
                              "author_association": pr.get("author_association") or "NONE", "merge_base": ""}}
    if pr.get("state") != "open":
        return skip(out, f"pull request {pr['number']} is {pr.get('state')}", noop_to, facts)
    if (pr["head"].get("repo") or {}).get("full_name") != repo:
        return skip(out, f"pull request {pr['number']} comes from a fork", noop_to, facts)
    if not any(fnmatch.fnmatchcase(pr["base"]["ref"], pattern) for pattern in bases):
        return skip(out, f"pull request {pr['number']} goes into `{pr['base']['ref']}`, which matches no --base pattern",
                    noop_to, facts)
    copilot = user.get("login") == COPILOT and user.get("type") == "Bot"
    if pr.get("author_association") not in TRUSTED and not copilot:
        return skip(out, f"pull request {pr['number']} was opened by someone who isn't the owner, a member, a "
                         "collaborator, or Copilot", noop_to, facts)
    if pr["head"]["sha"] != run["head_sha"]:
        return skip(out, f"pull request {pr['number']} has moved on to `{pr['head']['sha'][:9]}`; its own CI run is "
                         "investigated if it fails", noop_to, facts)
    jobs = [job for job in failed_jobs(repo, run) if job["ran"]]
    if not jobs:
        return skip(out, "no job of the run ran: its workflows were never approved, or it was cancelled", noop_to, facts)

    merge_base = gh("api", f"repos/{repo}/compare/{pr['base']['sha']}...{run['head_sha']}", "--jq",
                    ".merge_base_commit.sha").strip()
    facts["pull_request"]["merge_base"] = merge_base
    files = api_list(f"repos/{repo}/pulls/{pr['number']}/files?per_page=100")
    changed = {f["filename"]: f for f in files}
    default_branch = (run.get("repository") or {}).get("default_branch") or api(f"repos/{repo}").get("default_branch") or "main"
    main = main_ci(repo, run, default_branch)
    cache: dict = {}
    failures, others, total = [], [], 0
    (out / "logs").mkdir(exist_ok=True)
    for job in jobs:
        parsed = parse_log(job_log(repo, job["id"]))
        excerpt: list[str] = []
        for test in parsed["tests"]:
            total += 1
            excerpt += [f"== {test['test']}", *test["excerpt"], ""]
            if len(failures) >= MAX_FAILURES:
                continue
            change, source = change_of(test, changed, repo, merge_base, run["head_sha"], cache)
            path = in_changed(test["file"], changed) or test["file"]
            failures.append({"job": job["name"], "kind": test["kind"], "test": test["test"],
                             "message": [clip(m) for m in test["message"]], "file": path, "line": test["line"],
                             "file_url": f"https://github.com/{repo}/blob/{run['head_sha']}/{quote(path)}#L{test['line']}"
                             if path and test["line"] else "",
                             "log_url": log_url(job), "pull_request_change": change,
                             "on_main": on_main(test["test"], main), "source": source})
        for error in parsed["errors"]:
            excerpt += [f"== {error['code']} {error['file']}:{error['line']}", *error["excerpt"], ""]
            path = in_changed(error["file"], changed)
            others.append({"job": job["name"], "kind": "build", "file": path or error["file"], "line": error["line"],
                           "message": [f"{error['code']}: {m}" for m in error["message"]], "log_url": log_url(job),
                           "in_pull_request": bool(path)})
        if parsed["tail"]:
            excerpt += [f"== the lines before the first error of step {job['step']!r}", *parsed["tail"]]
            others.append({"job": job["name"], "kind": "other", "step": job["step"], "log_url": log_url(job),
                           "message": [clip(line) for line in parsed["tail"][-MAX_MESSAGE_LINES:]]})
        (out / "logs" / f"{job['id']}.txt").write_text("\n".join(excerpt[:MAX_LOG_LINES]) + "\n", encoding="utf-8")
    facts.update({"jobs": [{"id": job["id"], "name": job["name"], "conclusion": job["conclusion"], "step": job["step"],
                            "log_url": log_url(job)} for job in jobs],
                  "changed_files": [{"path": f["filename"], "status": f.get("status"), "additions": f.get("additions", 0),
                                     "deletions": f.get("deletions", 0)} for f in files],
                  "failures_total": total, "failures": failures, "other_failures": others, "main": main,
                  "patch_cut": write_patch(files, out / "pr.patch"), "skip": None})
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    (out / "facts.md").write_text(render(facts), encoding="utf-8")
    print(f"Wrote {out / 'facts.json'}: {total} failing test(s) and {len(others)} other failure(s) in {len(jobs)} job(s) "
          f"of run {run['id']}, pull request {pr['number']}; main's latest CI: {main['conclusion']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect the facts of a pull request's failed CI run: the failing tests, their messages and "
                    "locations, whether the pull request adds or changes each one, and main's latest CI result.",
        epilog="Exit codes: 0 facts written, or nothing to investigate (facts.json says why); 2 configuration or GitHub "
               "CLI error.")
    parser.add_argument("--run", type=int, required=True, help="id of the failed CI workflow run")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                        help="repository as owner/name (default: $GITHUB_REPOSITORY, else the current repository)")
    parser.add_argument("--base", action="append", default=None, metavar="PATTERN",
                        help="base branches to investigate, as a glob such as 'lab/test-*' or main; repeat it for more "
                             "(default: any base branch)")
    parser.add_argument("--out", type=Path, default=Path("out/ci-investigation"),
                        help="folder for facts.json, facts.md, pr.patch, and logs/ (default out/ci-investigation)")
    parser.add_argument("--noop-to", metavar="FILE",
                        help="when there is nothing to investigate, append a gh-aw noop entry with the reason to FILE "
                             "(the workflow passes $GH_AW_SAFE_OUTPUTS, so its agent doesn't start)")
    args = parser.parse_args(argv)
    if args.noop_to is not None and not args.noop_to.strip():
        print("error: --noop-to is empty: the workflow did not pass the path of its safe-outputs file", file=sys.stderr)
        return 2
    try:
        repo = args.repo or json.loads(gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        return collect(repo, args.run, args.base or ["*"], args.out, args.noop_to)
    except (FactsError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
