#!/usr/bin/env python3
"""Prove that a change's regression tests catch the defect it fixes (regression-followup skill).

A regression test is only worth keeping if it fails without the fix. This script runs RequestHub's .NET tests twice:

  head    your branch as it is, including uncommitted changes;
  before  the same test files on the base revision's production code: app/src is put back the way it was at the
          merge base with --base, while every test file under app/tests keeps your version.

A test that fails before and passes at head proves the fix. The verdict is one of:

  PROVEN     app/src changed, and at least one test fails before and passes at head
  UNPROVEN   app/src changed, but no test fails before, no test changed, or the tests do not compile against the base
  COVERAGE   only app/tests changed and every test passes (the base code is unchanged, so no defect is demonstrated)
  FAILING    a test fails, or the tests do not build, at head
  NOTHING    nothing changed under app/src or app/tests

Usage
  python .github/skills/regression-followup/prove_regression.py                 # HEAD compared with origin/main
  python .github/skills/regression-followup/prove_regression.py --base main
  python .github/skills/regression-followup/prove_regression.py --class RequestHub.Tests.WorkerTests   # faster
  python .github/skills/regression-followup/prove_regression.py --repo ../pr --base <sha> --summary proof.md

Needs git, the .NET SDK, and PostgreSQL on localhost:5432 (user requesthub, password devpass), like the app's tests.
Set REQUESTHUB_TEST_PG to use another server. The base copy is a temporary git worktree; your working tree is not
modified, except for build output under app/.

Exit codes: 0 PROVEN, COVERAGE, or NOTHING; 1 UNPROVEN or FAILING; 2 setup error (git, .NET SDK, or no test results).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TEST_PROJECT = "app/tests/RequestHub.Tests"
SOURCE_PREFIX = "app/src/"
TEST_PREFIX = "app/tests/"
EXIT_CODES = {"PROVEN": 0, "COVERAGE": 0, "NOTHING": 0, "UNPROVEN": 1, "FAILING": 1}
ICONS = {"PROVEN": "✅", "COVERAGE": "ℹ️", "NOTHING": "➖", "UNPROVEN": "❌", "FAILING": "❌"}


class SetupError(Exception):
    """Tooling failed in a way that says nothing about the tests (git, the .NET SDK, a missing results file)."""


@dataclass
class TestRun:
    label: str
    built: bool
    results: dict[str, str] = field(default_factory=dict)
    log_tail: str = ""

    def count(self, status: str) -> int:
        return sum(1 for value in self.results.values() if value == status)


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = run(["git", *args], repo)
    if check and proc.returncode != 0:
        raise SetupError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def merge_base(repo: Path, base: str) -> str:
    """Merge base of `base` and HEAD. Fetches the base branch, or deepens a shallow clone, when they are missing."""
    if not git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False) and base.startswith("origin/"):
        branch = base.removeprefix("origin/")
        git(repo, "fetch", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", check=False)
    found = git(repo, "merge-base", base, "HEAD", check=False)
    if not found and git(repo, "rev-parse", "--is-shallow-repository", check=False) == "true":
        git(repo, "fetch", "--no-tags", "--unshallow", "origin", check=False)
        found = git(repo, "merge-base", base, "HEAD", check=False)
    if not found:
        raise SetupError(f"no merge base between {base} and HEAD. Fetch {base} first, or pass another --base.")
    return found


def changed_files(repo: Path, base_sha: str) -> list[str]:
    """Files under app/src and app/tests that differ from the merge base, including uncommitted and untracked files."""
    diff = git(repo, "diff", "--name-only", base_sha, "--", SOURCE_PREFIX, TEST_PREFIX).splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "--", SOURCE_PREFIX, TEST_PREFIX).splitlines()
    return sorted({path.strip().replace("\\", "/") for path in diff + untracked if path.strip()})


def run_tests(tree: Path, label: str, classes: list[str], out_dir: Path) -> TestRun:
    """Build the test project in `tree` and run it, reading per-test results from a CTRF (JSON) report."""
    project = tree / TEST_PROJECT
    print(f"[{label}] building {TEST_PROJECT} ...", flush=True)
    build = run(["dotnet", "build", str(project), "-c", "Release", "-nologo", "-v", "q", "--disable-build-servers"], tree)
    if build.returncode != 0:
        errors = [line for line in (build.stdout + build.stderr).splitlines() if ": error " in line]
        return TestRun(label, built=False, log_tail="\n".join(dict.fromkeys(errors)) or tail(build.stdout + build.stderr))

    assembly = next(iter(sorted(project.glob("bin/Release/*/RequestHub.Tests.dll"))), None)
    if assembly is None:
        raise SetupError(f"[{label}] build succeeded but RequestHub.Tests.dll was not found under {project}/bin/Release")
    report = out_dir / f"{label}.ctrf.json"
    report.unlink(missing_ok=True)
    command = ["dotnet", str(assembly), "-noColor", "-noLogo", "-result-ctrf", str(report)]
    for name in classes:
        command += ["-class", name]
    print(f"[{label}] running tests ...", flush=True)
    proc = run(command, tree)
    if not report.exists():
        raise SetupError(f"[{label}] the test run wrote no results (is PostgreSQL running?):\n{tail(proc.stdout + proc.stderr)}")
    tests = json.loads(report.read_text(encoding="utf-8"))["results"]["tests"]
    result = TestRun(label, built=True, results={test["name"]: test["status"] for test in tests}, log_tail=tail(proc.stdout, 15))
    print(f"[{label}] {result.count('passed')} passed, {result.count('failed')} failed, {result.count('skipped')} skipped", flush=True)
    return result


def before_tree(repo: Path, base_sha: str, test_files: list[str], parent: Path) -> Path:
    """A worktree at the merge base with the head versions of the changed test files copied in."""
    tree = parent / "before"
    git(repo, "worktree", "add", "--detach", str(tree), base_sha)
    for relative in test_files:
        source, target = repo / relative, tree / relative
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif target.exists():
            target.unlink()
    return tree


def decide(sources: list[str], tests: list[str], head: TestRun | None, before: TestRun | None) -> tuple[str, str, list[str]]:
    """Return (verdict, explanation, proven test names)."""
    if not sources and not tests:
        return "NOTHING", "No file changed under app/src or app/tests, so there is nothing to prove.", []
    assert head is not None
    if not head.built:
        return "FAILING", "The tests do not build at head.", []
    failed = sorted(name for name, status in head.results.items() if status == "failed")
    if failed:
        return "FAILING", f"{len(failed)} test(s) fail at head: " + ", ".join(f"`{name}`" for name in failed[:5]), []
    if not sources:
        return "COVERAGE", "Only tests changed and they pass. The production code is unchanged, so no defect is demonstrated.", []
    if not tests:
        return "UNPROVEN", "Production code changed but no test changed. Add a test that fails without the change.", []
    assert before is not None
    if not before.built:
        return ("UNPROVEN", "The changed tests do not compile against the base code, so they cannot show the defect. "
                "Test the behavior through APIs that already exist on the base branch.", [])
    proven = sorted(name for name, status in head.results.items() if status == "passed" and before.results.get(name) == "failed")
    if proven:
        return "PROVEN", f"{len(proven)} test(s) fail on the base code and pass with the change.", proven
    return "UNPROVEN", "Every changed test also passes on the base code, so none of them shows the defect the change fixes.", []


def summary(verdict: str, explanation: str, base: str, base_sha: str, head_sha: str, dirty: bool,
            sources: list[str], tests: list[str], head: TestRun | None, before: TestRun | None, proven: list[str]) -> str:
    def files(items: list[str]) -> str:
        return ", ".join(f"`{item}`" for item in items) or "none"

    lines = [f"### Regression proof: {verdict} {ICONS[verdict]}", "", explanation, "",
             f"- Base: `{base_sha[:9]}` (merge base with `{base}`)",
             f"- Head: `{head_sha[:9]}`" + (" plus uncommitted changes" if dirty else ""),
             f"- Production code changed: {files(sources)}",
             f"- Tests changed: {files(tests)}"]
    if before is not None and before.built and head is not None:
        lines += ["", "| Test | Base code (without the change) | Head (with the change) |", "|---|---|---|"]
        lines += [f"| `{name}` | ❌ failed | ✅ passed |" for name in proven] or ["| none | | |"]
    if before is not None and not before.built:
        lines += ["", "Build errors on the base code:", "", "```text", before.log_tail, "```"]
    if head is not None and head.built:
        lines += ["", f"Full run at head: {head.count('passed')} passed, {head.count('failed')} failed, {head.count('skipped')} skipped."]
    elif head is not None:
        lines += ["", "Build errors at head:", "", "```text", head.log_tail, "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="RequestHub checkout to prove; any folder inside it works (default: the current folder)")
    parser.add_argument("--base", default="origin/main",
                        help="branch, tag, or commit the change is compared with; the merge base with HEAD is used (default: origin/main)")
    parser.add_argument("--class", dest="classes", action="append", default=[], metavar="NAME",
                        help="only run this fully qualified test class; repeat for several (default: the whole suite)")
    parser.add_argument("--summary", type=Path,
                        help="append the Markdown summary to this file, for example $GITHUB_STEP_SUMMARY (it is always printed)")
    parser.add_argument("--json", type=Path,
                        help="write machine-readable results here (default: <repo>/out/regression-proof.json)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    head = before = None
    try:
        if not shutil.which("dotnet"):
            raise SetupError("the .NET SDK (dotnet) is not on PATH")
        repo = Path(git(args.repo.resolve(), "rev-parse", "--show-toplevel"))
        out_dir = repo / "out" / "regression-proof"
        out_dir.mkdir(parents=True, exist_ok=True)
        base_sha = merge_base(repo, args.base)
        head_sha = git(repo, "rev-parse", "HEAD")
        dirty = bool(git(repo, "status", "--porcelain", "--", SOURCE_PREFIX, TEST_PREFIX))
        changed = changed_files(repo, base_sha)
        sources = [path for path in changed if path.startswith(SOURCE_PREFIX)]
        tests = [path for path in changed if path.startswith(TEST_PREFIX)]
        print(f"Comparing HEAD {head_sha[:9]} with merge base {base_sha[:9]} ({args.base})")
        print(f"Production files changed: {len(sources)}; test files changed: {len(tests)}", flush=True)

        if sources or tests:
            head = run_tests(repo, "head", args.classes, out_dir)
            head_ok = head.built and head.count("failed") == 0
            if head_ok and sources and tests:
                with tempfile.TemporaryDirectory(prefix="regression-proof-", ignore_cleanup_errors=True) as scratch:
                    tree = before_tree(repo, base_sha, tests, Path(scratch))
                    try:
                        before = run_tests(tree, "before", args.classes, out_dir)
                    finally:
                        git(repo, "worktree", "remove", "--force", str(tree), check=False)
                        git(repo, "worktree", "prune", check=False)
    except SetupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    verdict, explanation, proven = decide(sources, tests, head, before)
    report = summary(verdict, explanation, args.base, base_sha, head_sha, dirty, sources, tests, head, before, proven)
    print()
    print(report)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(report)
    record = {
        "verdict": verdict,
        "explanation": explanation,
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": args.base, "baseSha": base_sha, "headSha": head_sha, "uncommittedChanges": dirty,
        "productionFiles": sources, "testFiles": tests, "provenTests": proven,
        "head": None if head is None else {"built": head.built, "results": head.results},
        "before": None if before is None else {"built": before.built, "results": before.results},
    }
    json_path = args.json or out_dir.parent / "regression-proof.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return EXIT_CODES[verdict]


if __name__ == "__main__":
    sys.exit(main())
