"""Replay a bounded security repair on two isolated snapshots and retain real JUnit evidence.

Example: python verify_remediation.py --base FULL_SHA --head FULL_SHA --out out/replay
Requires git, .NET 10 and PostgreSQL. REQUESTHUB_TEST_PG optionally selects the PostgreSQL
server; ApiFixture creates unique test databases. No application deployment is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TEST = "app/tests/RequestHub.Tests/SearchSecurityTests.cs"
WORKFLOW = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"
FILTER = "*SearchSecurityTests"


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, encoding="utf-8").strip()


def report(path: Path) -> dict:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failed = [case for case in cases if case.find("failure") is not None]
    errors = [case for case in cases if case.find("error") is not None]
    skipped = [case for case in cases if case.find("skipped") is not None]
    return {"tests": len(cases), "failures": len(failed), "errors": len(errors), "skipped": len(skipped),
            "literal_search_failures": sum(
                "Search_treats_SQL_and_wildcards_as_literal_text" in case.get("name", "") for case in failed)}


def execute(command: list[str], cwd: Path, log: Path) -> int:
    with log.open("w", encoding="utf-8") as output:
        return subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, timeout=600).returncode


def regression_command(reports: Path) -> list[str]:
    project = Path("app") / "tests" / "RequestHub.Tests" / "RequestHub.Tests.csproj"
    return ["dotnet", "test", "--project", str(project), "-c", "Release", "--no-build",
            "--results-directory", str(reports), "--", "--filter-class", FILTER,
            "--report-xunit-junit", "--report-xunit-junit-filename", "search.junit.xml"]


def verify(base: str, head: str, out: Path) -> dict:
    for sha in (base, head):
        if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
            raise ValueError("Both commits must be immutable full SHAs")
    root = Path(git("rev-parse", "--show-toplevel"))
    git("merge-base", "--is-ancestor", base, head)
    changed = set(git("diff", "--name-only", base, head).splitlines())
    if changed != {TEST, WORKFLOW}:
        raise ValueError(f"Repair must change only workflow source and new regression: {sorted(changed)}")
    before_source = git("show", f"{base}:{WORKFLOW}")
    after_source = git("show", f"{head}:{WORKFLOW}")
    start = "    public async Task<PagedResult<RequestSummaryDto>> ListAsync("
    end = "    public async Task<Result<RequestDetailDto>> GetAsync("
    before_prefix, before_body = before_source.split(start, 1)
    after_prefix, after_body = after_source.split(start, 1)
    if before_prefix != after_prefix or before_body.split(end, 1)[1] != after_body.split(end, 1)[1]:
        raise ValueError("Source changes outside ListAsync are forbidden")
    if git("ls-tree", "--name-only", base, TEST):
        raise ValueError("Base already contains the regression; choose a fresh lab")
    reference = root / "solutions/05-secure-github/regression/SearchSecurityTests.cs"
    expected = reference.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
    if git("show", f"{head}:{TEST}") != expected:
        raise ValueError("Repair changed the supplied regression")
    tests_only = None
    for sha in git("rev-list", "--reverse", f"{base}..{head}").splitlines():
        files = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines())
        if files == {TEST} and not git("diff", base, sha, "--", WORKFLOW):
            if git("show", f"{sha}:{TEST}") == expected:
                tests_only = sha
                break
    if tests_only is None:
        raise ValueError("No tests-only commit before the source repair")
    result = {"status": "FAIL", "base_sha": base, "head_sha": head, "tests_only_sha": tests_only, "checks": {}}
    for label, sha in (("before", tests_only), ("after", head)):
        snapshot = Path(tempfile.mkdtemp(prefix=f"secure-{label}-", dir=out))
        added = False
        try:
            git("worktree", "add", "--detach", str(snapshot), sha)
            added = True
            build = execute(["dotnet", "build", "app/RequestHub.slnx", "-c", "Release"],
                            snapshot, out / f"{label}-build.log")
            if build:
                raise ValueError(f"{label} build failed; see {label}-build.log")
            reports = out / label
            reports.mkdir()
            code = execute(regression_command(reports), snapshot, out / f"{label}-test.log")
            junit_path = reports / "search.junit.xml"
            if not junit_path.is_file():
                raise ValueError(f"{label}: runner exited {code} without JUnit; see {label}-test.log")
            junit = report(junit_path)
            result["checks"][label] = {"exit_code": code, **junit}
            if junit["tests"] != 10 or junit["errors"] or junit["skipped"]:
                raise ValueError(f"{label}: expected exactly 10 executed tests and no errors or skips: {junit}")
            if label == "before" and (code == 0 or junit["literal_search_failures"] == 0):
                raise ValueError("Original defect did not fail a literal-search assertion")
            if label == "after":
                if code or junit["failures"]:
                    raise ValueError("Regression still fails after repair")
                suite = execute(["dotnet", "test", "--solution", "app/RequestHub.slnx", "-c", "Release",
                                 "--no-build"], snapshot, out / "after-full-suite.log")
                result["checks"]["full_suite"] = {"exit_code": suite}
                if suite:
                    raise ValueError("Full app suite failed after repair")
        finally:
            if added:
                git("-c", "core.longpaths=true", "worktree", "remove", "--force", str(snapshot))
            elif snapshot.exists():
                snapshot.rmdir()
    result.update(status="PASS", reason="regression failed before repair, passed after; full app suite passed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Full SHA of the original unsafe lab commit")
    parser.add_argument("--head", required=True, help="Full SHA of the repaired commit")
    parser.add_argument("--out", type=Path, required=True, help="New output directory for logs, JUnit and results")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("--out must be a new directory so prior evidence is never overwritten")
    out.mkdir(parents=True)
    try:
        result = verify(args.base, args.head, out)
    except (ValueError, OSError, subprocess.SubprocessError, ET.ParseError) as error:
        result = {"status": "FAIL", "reason": str(error), "base_sha": args.base, "head_sha": args.head}
    result.update(schema_version="1.0", timestamp_utc=datetime.now(timezone.utc).isoformat())
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['status']}: {result['reason']}")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## Deterministic remediation replay\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
