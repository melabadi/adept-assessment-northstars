#!/usr/bin/env python3
"""Prove a test-first fix: its regression tests fail before the fix and pass after it (review-evidence skill).

A test-first fix starts with a commit that only adds or changes tests, followed by the fix. This script finds that
tests-only commit between the base and the head of a pull request, works out which xUnit test methods it added or
changed, and runs exactly those tests twice, each time in a clean temporary git worktree:

  1. at the tests-only commit  at least one must FAIL: the tests detect the defect
  2. at the head               all of them must PASS: the fix works

Both test outputs (console log and CTRF JSON report) are kept in --out, named after their commit, next to proof.json and
proof.md. The workflow "Test · GitHub · prove the fix test-first" runs this script on fix pull requests, and a reviewer
can run it locally. It proves the order of the evidence, not the quality of the tests: a person still reads them.

Usage
  python .github/skills/review-evidence/prove_fix.py --pr 42
      a pull request (needs the GitHub CLI); fetches its base branch and head
  python .github/skills/review-evidence/prove_fix.py --base origin/lab/test-duplicate-decision --head HEAD
      local commits, for example after fixing a defect with Copilot CLI
  python .github/skills/review-evidence/prove_fix.py --pr 42 --filter "*Decision*"
      choose the test methods yourself instead of taking the ones the tests-only commit changed

Needs git, the .NET SDK, and PostgreSQL on localhost:5432 (or the server connection string in REQUESTHUB_TEST_PG).
Only .NET tests under app/tests/ are selected; browser tests in the tests-only commit are reported, not run.

Exit codes: 0 proven, 1 not proven, 2 configuration, git, or GitHub CLI error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOLUTION = "app/RequestHub.slnx"
DOTNET_TESTS = "app/tests/"
TEST_FILE = re.compile(r"^(app/tests/|app/web/e2e/)|\.(test|spec)\.tsx?$")
TEST_ATTRIBUTE = re.compile(r"^\s*\[(?:Fact|Theory)\b")
METHOD = re.compile(r"\b(?:Task|ValueTask|void)\s+(\w+)\s*\(")
CLASS = re.compile(r"\bclass\s+(\w+)")


class ProofError(Exception):
    """A configuration, git, or GitHub CLI problem (exit code 2)."""


def run(*args: str, cwd: Path = REPO) -> str:
    proc = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ProofError(f"{' '.join(args[:3])}: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def show(rev: str, path: str) -> str:
    """A file's contents at a revision, or an empty string when the file does not exist there."""
    proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.stdout if proc.returncode == 0 else ""


def fetch_pr(number: int) -> tuple[str, str]:
    """Fetch a pull request's base branch and head; return (base ref, head SHA)."""
    pr = json.loads(run("gh", "pr", "view", str(number), "--json", "baseRefName,headRefOid"))
    run("git", "fetch", "--quiet", "--no-tags", "origin", pr["baseRefName"], f"+refs/pull/{number}/head:refs/remotes/origin/pr/{number}")
    return f"origin/{pr['baseRefName']}", pr["headRefOid"]


def history(base: str, head: str) -> list[dict]:
    """Commits from base (exclusive) to head, oldest first, with the files each one changes."""
    commits = []
    for sha in run("git", "rev-list", "--reverse", "--no-merges", f"{base}..{head}").split():
        files = [f for f in run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha).split("\0") if f]
        commits.append({"sha": sha, "title": run("git", "log", "-1", "--format=%s", sha).strip(), "files": files})
    return commits


def tests_only_commit(commits: list[dict]) -> dict | None:
    """The last commit of the leading run of tests-only commits. Empty commits (such as "Initial plan") are skipped."""
    found = None
    for commit in commits:
        if not commit["files"]:
            continue
        if not all(TEST_FILE.search(path) for path in commit["files"]):
            break
        found = commit
    return found


def test_methods(source: str) -> dict[str, str]:
    """Map each xUnit test method to its text, from its [Fact] or [Theory] attribute to the next test."""
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if TEST_ATTRIBUTE.match(line)]
    methods: dict[str, str] = {}
    for n, start in enumerate(starts):
        block = lines[start:starts[n + 1] if n + 1 < len(starts) else len(lines)]
        name = next((m.group(1) for line in block if not line.lstrip().startswith("[") and (m := METHOD.search(line))), None)
        if name:
            methods[name] = "\n".join(line.rstrip() for line in block).strip()
    return methods


def changed_tests(base: str, commit: str) -> tuple[list[str], list[str], list[str]]:
    """Test methods added or changed between base and commit, the classes in those files, and other test files."""
    paths = [p for p in run("git", "diff", "--name-only", "-z", base, commit, "--").split("\0") if TEST_FILE.search(p)]
    names: set[str] = set()
    classes: set[str] = set()
    for path in (p for p in paths if p.startswith(DOTNET_TESTS) and p.endswith(".cs")):
        source = show(commit, path)
        before = test_methods(show(base, path))
        names |= {name for name, text in test_methods(source).items() if before.get(name) != text}
        classes |= set(CLASS.findall(source))
    others = [p for p in paths if not p.startswith(DOTNET_TESTS)]
    return sorted(names), sorted(classes), others


def run_tests(sha: str, filters: list[str], out: Path, label: str) -> dict:
    """Run the selected tests in a temporary worktree at `sha`; keep the console log and the CTRF report in `out`."""
    log, report = out / f"{label}-{sha[:9]}.log", out / f"{label}-{sha[:9]}.ctrf.json"
    report.unlink(missing_ok=True)
    print(f"Running {len(filters) // 2} test filter(s) at {sha[:9]} ({label}) ...", flush=True)
    with tempfile.TemporaryDirectory(prefix="proof-", ignore_cleanup_errors=True) as tmp:
        tree = Path(tmp) / "tree"
        run("git", "worktree", "add", "--quiet", "--detach", str(tree), sha)
        try:
            proc = subprocess.run(
                ["dotnet", "test", "--solution", SOLUTION, *filters, "--results-directory", str(out.resolve()),
                 "--report-xunit-ctrf", "--report-xunit-ctrf-filename", report.name],
                cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise ProofError("dotnet is not installed or not on PATH") from exc
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, capture_output=True)
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    result = {"sha": sha, "log": log.name, "report": None, "total": 0, "passed": 0, "failed": 0, "failedTests": []}
    if report.exists():
        tests = json.loads(report.read_text(encoding="utf-8"))["results"]["tests"]
        failed = [t for t in tests if t.get("status") == "failed"]
        result.update(report=report.name, total=len(tests), failed=len(failed),
                      passed=sum(1 for t in tests if t.get("status") == "passed"),
                      failedTests=[{"name": t.get("name", "?"), "message": summary_of(t.get("message"))} for t in failed])
    return result


def summary_of(message: str | None) -> str:
    """The first lines of an assertion message on one line, for example "Expected: Conflict · Actual: Created"."""
    lines = [" ".join(line.split())[:90] for line in (message or "").strip().splitlines() if line.strip()]
    return " · ".join(lines[:3])


def short_name(test: str) -> str:
    """RequestHub.Tests.SomeTests.Method(arg: 1) -> Method(arg: 1)"""
    method, paren, arguments = test.partition("(")
    return method.rsplit(".", 1)[-1] + paren + arguments


def outcome(result: dict) -> str:
    if not result["total"]:
        return "⚠️ did not run (build error? see the log)"
    if result["failed"]:
        return f"❌ {result['failed']} of {result['total']} failed"
    return f"✅ {result['total']} of {result['total']} passed"


def render(proof: dict, heading: str = "### Regression tests at known commits") -> str:
    lines = [heading, ""]
    runs = proof["runs"]
    if runs:
        tests_only, head = proof["testsOnly"], runs["head"]
        lines += ["| Commit | What it contains | Selected tests | Expected |", "|---|---|---|---|",
                  f"| `{tests_only['sha'][:9]}` | tests only: {tests_only['title']} | {outcome(runs['testsOnly'])} | must fail: proves the defect |",
                  f"| `{head['sha'][:9]}` | head: {proof['headTitle']} | {outcome(head)} | must pass: proves the fix |", ""]
    icon = "✅ Proven" if proof["verdict"] == "proven" else "❌ Not proven"
    lines += [f"**{icon}:** {proof['reason']}", ""]
    if proof["tests"]:
        lines += [f"Selected tests ({proof['selection']}): " + ", ".join(f"`{t}`" for t in proof["tests"]), ""]
    if runs and runs["testsOnly"]["failedTests"]:
        failures = sorted(runs["testsOnly"]["failedTests"], key=lambda t: t["name"])
        lines += ["Failures at the tests-only commit (the reported defect, in the tests' words):", ""]
        lines += [f"- `{short_name(t['name'])}`: {t['message'] or 'failed'}" for t in failures[:12]]
        lines.append("")
    if proof["otherTests"]:
        lines += ["Not run by this check (run them by hand): " + ", ".join(f"`{p}`" for p in proof["otherTests"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def prove(base: str, head: str, out: Path, test_filter: str | None = None) -> dict:
    """Build the proof for base..head and write proof.json, proof.md, and both test outputs to `out`."""
    out.mkdir(parents=True, exist_ok=True)
    head_sha = run("git", "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    merge_base = run("git", "merge-base", base, head_sha).strip()
    commits = history(merge_base, head_sha)
    tests_commit = tests_only_commit(commits)
    proof = {"verdict": "not proven", "reason": "", "base": merge_base, "head": head_sha,
             "headTitle": run("git", "log", "-1", "--format=%s", head_sha).strip(),
             "testsOnly": {k: tests_commit[k] for k in ("sha", "title")} if tests_commit else None,
             "commits": [{k: c[k] for k in ("sha", "title")} for c in commits],
             "tests": [], "selection": "", "otherTests": [], "runs": {}}

    if tests_commit is None:
        proof["reason"] = "no tests-only commit before the fix. Commit the failing tests on their own first, then the fix."
    else:
        names, classes, proof["otherTests"] = changed_tests(merge_base, tests_commit["sha"])
        if test_filter:
            proof["tests"], proof["selection"], filters = [test_filter], "--filter", ["--filter-method", test_filter]
        elif names:
            proof["tests"], proof["selection"] = names, "added or changed by the tests-only commit"
            filters = [arg for name in names for arg in ("--filter-method", f"*.{name}")]
        else:
            proof["tests"], proof["selection"] = classes, "classes the tests-only commit changed"
            filters = [arg for name in classes for arg in ("--filter-class", f"*.{name}")]
        if not filters:
            proof["reason"] = f"the tests-only commit changes no .NET test under {DOTNET_TESTS}, so this check has nothing to run."
        else:
            before = run_tests(tests_commit["sha"], filters, out, "tests-only")
            after = before if tests_commit["sha"] == head_sha else run_tests(head_sha, filters, out, "head")
            proof["runs"] = {"testsOnly": before, "head": after}
            if not before["total"]:
                proof["reason"] = "the selected tests did not run at the tests-only commit (build error? see the log)."
            elif not before["failed"]:
                proof["reason"] = "the new tests pass without the fix, so they do not detect the defect."
            elif not after["total"]:
                proof["reason"] = "the selected tests did not run at the head (build error? see the log)."
            elif after["failed"]:
                proof["reason"] = f"{after['failed']} of {after['total']} selected tests still fail at the head."
            else:
                proof["verdict"] = "proven"
                proof["reason"] = (f"{before['failed']} of {before['total']} selected tests fail at the tests-only commit "
                                   f"`{before['sha'][:9]}`, and all {after['total']} pass at the head `{after['sha'][:9]}`.")

    (out / "proof.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "proof.md").write_text(render(proof), encoding="utf-8")
    return proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="Pull request number; fetches its base branch and head with the GitHub CLI")
    target.add_argument("--base", help="Base branch or commit the fix starts from, for example origin/lab/test-duplicate-decision")
    parser.add_argument("--head", default="HEAD", help="Last commit of the fix when using --base (default HEAD)")
    parser.add_argument("--filter", help='Test method filter to run instead of the detected tests, for example "*Decision*"')
    parser.add_argument("--out", type=Path, default=Path("out/regression-proof"),
                        help="Folder for proof.json, proof.md, and both test outputs (default out/regression-proof)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        base, head = fetch_pr(args.pr) if args.pr else (args.base, args.head)
        proof = prove(base, head, args.out, args.filter)
    except ProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print()
    print(render(proof))
    print(f"Proof and both test outputs: {args.out}")
    return 0 if proof["verdict"] == "proven" else 1


if __name__ == "__main__":
    sys.exit(main())
