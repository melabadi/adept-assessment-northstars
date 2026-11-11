"""Tests for 04-test-github's ci-investigation skill: the facts a failed CI run gives its agent.

ci_failure_facts.py runs before the agentic CI failure investigation's agent starts, so the agent explains failures from
facts that a script gathered the same way every time. These tests check that:

- failing tests are read from the logs of .NET (Microsoft Testing Platform), Playwright, and Vitest runs as they look on
  GitHub-hosted runners (timestamps, color codes, noise lines), with their message and their file and line in the
  repository; build errors are read once each; and a failure that is none of these keeps the lines before its error;
- each failing .NET test is marked as added, changed, or unchanged by the pull request, method by method from the merge
  base, and as failing on main or not, from main's latest CI run;
- nothing reaches the agent unless the run is a failed run of an open pull request from a branch of this repository,
  into a base branch it may investigate, by the owner, a member, a collaborator, or Copilot (by its exact bot account),
  with the failed commit still at its head and a job that ran; otherwise the workflow gets a noop, so no agent starts.

They run offline with a fake `gh` and synthetic data, in about a second. Run from the repository root:
  python -m unittest discover -s solutions/04-test-github/tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1] / ".github" / "skills" / "ci-investigation"
sys.path.insert(0, str(SKILL))
import ci_failure_facts as facts_script  # noqa: E402

REPO = "example-org/example-repo"
HEAD = "a" * 40
BASE = "b" * 40
MERGE_BASE = "c" * 40
WORK = "/home/runner/work/example-repo/example-repo/"
TEST_FILE = "app/tests/Example.Tests/DecisionTests.cs"
WHEN = "2026-11-11T10:00:00Z"


def stamped(lines: list[str]) -> str:
    """Log lines as GitHub stores them: a byte-order mark on the first, a timestamp on each."""
    return "\ufeff" + "\n".join(f"2026-11-11T10:00:{n % 60:02d}.1234567Z {line}" for n, line in enumerate(lines)) + "\n"


DOTNET_LOG = stamped([
    "##[group]Run dotnet test --solution app/Example.slnx -c Release --no-build",
    "        Failed executing DbCommand (24ms) [Parameters=[], CommandType='Text', CommandTimeout='30']",
    "\x1b[31mfailed\x1b[m Example.Tests.DecisionTests.Later_decision_returns_conflict \x1b[90m(120ms)\x1b[m",
    f"  from {WORK}app/tests/Example.Tests/bin/Release/net10.0/Example.Tests.dll (net10.0|x64)",
    "\x1b[31m  Assert.Equal() Failure: Values differ",
    "  Expected: Conflict",
    "  Actual:   Created",
    f"\x1b[m\x1b[90m    at Example.Tests.DecisionTests.Later_decision_returns_conflict() in {WORK}{TEST_FILE}:41",
    "    --- End of stack trace from previous location ---",
    "^[[31mfailed^[[m Example.Tests.DecisionTests.Retry_returns_original(persona: \"u-ava\") ^[[90m(1s 20ms)^[[m",
    f"  from {WORK}app/tests/Example.Tests/bin/Release/net10.0/Example.Tests.dll (net10.0|x64)",
    "  Assert.Equal() Failure: Values differ",
    "  Expected: OK",
    "  Actual:   Created",
    f"    at Example.Tests.DecisionTests.Retry_returns_original(String persona) in {WORK}{TEST_FILE}:line 58",
    "failed Example.Tests.SearchTests.Search_is_literal (15ms)",
    f"  from {WORK}app/tests/Example.Tests/bin/Release/net10.0/Example.Tests.dll (net10.0|x64)",
    "  Assert.Single() Failure: The collection contained 2 items",
    f"    at Example.Tests.SearchTests.Search_is_literal() in {WORK}app/tests/Example.Tests/SearchTests.cs:12",
    f"{WORK}app/tests/Example.Tests/bin/Release/net10.0/Example.Tests.dll (net10.0|x64) failed with 3 error(s) (9s 1ms)",
    "\x1b[31mTest run summary: Failed!",
    "\x1b[m  total: 40",
    "\x1b[31m  failed: 3",
    "  succeeded: 37",
    "  skipped: 0",
    "##[error]Process completed with exit code 2.",
])

PLAYWRIGHT_LOG = stamped([
    "  ✘  3 [chromium] › e2e/app.spec.ts:53:3 › Example app › Hugo sees the self-approval message (10.6s)",
    "  1) [chromium] › e2e/app.spec.ts:53:3 › Example app › Hugo sees the self-approval message ",
    "",
    "    Error: expect(locator).toContainText(expected) failed",
    "",
    "    Locator: getByRole('region', { name: 'Decision' })",
    "    Expected substring: \"You can't decide your own request.\"",
    "    Received string:    \"DecisionApproveReject\"",
    "",
    "    Call log:",
    "      - waiting for getByRole('region', { name: 'Decision' })",
    "    > 59 |     await expect(decision).toContainText(\"You can't decide your own request.\");",
    f"        at {WORK}app/web/e2e/app.spec.ts:59:28",
    "  1 failed",
    "##[error]Process completed with exit code 1.",
])

VITEST_LOG = stamped([
    " FAIL  src/lib/format.test.ts > formatDate > uses the user's locale",
    "AssertionError: expected '11/10/2026' to be '10/11/2026' // Object.is equality",
    "",
    "- Expected",
    "+ Received",
    " ❯ src/lib/format.test.ts:12:20",
    "##[error]Process completed with exit code 1.",
])

BUILD_LOG = stamped([
    f"{WORK}app/src/Example.Core/Workflow.cs(88,13): error CS1002: ; expected [{WORK}app/src/Example.Core/Example.Core.csproj]",
    "Build FAILED.",
    f"{WORK}app/src/Example.Core/Workflow.cs(88,13): error CS1002: ; expected [{WORK}app/src/Example.Core/Example.Core.csproj]",
    "##[error]Process completed with exit code 1.",
])

# `tsc -b` writes this format when its output isn't a terminal, as on a runner, with paths from the web folder.
TYPECHECK_LOG = stamped([
    "> example-web@0.0.0 typecheck",
    "> tsc -b",
    "",
    "src/lib/format.ts(12,7): error TS2322: Type 'string' is not assignable to type 'number'.",
    "##[error]Process completed with exit code 1.",
])

SETUP_LOG = stamped([
    "Starting postgres service container",
    "Error response from daemon: failed to create the container: no space left on device",
    "##[error]Failed to initialize container postgres:16",
    "Cleaning up orphan processes",
])


def source(*methods: tuple[str, str]) -> str:
    """A C# test class with the given (name, body) xUnit test methods."""
    parts = ["namespace Example.Tests;", "", "public sealed class DecisionTests", "{"]
    for name, body in methods:
        parts += ["    [Fact]", f"    public async Task {name}()", "    {", f"        {body}", "    }", ""]
    return "\n".join(parts + ["}"]) + "\n"


BASE_SOURCE = source(("Retry_returns_original", "await Decide(1);"), ("Unrelated", "await Noop();"))
HEAD_SOURCE = source(("Later_decision_returns_conflict", "await DecideTwice();"),
                     ("Retry_returns_original", "await Decide(2);"), ("Unrelated", "await Noop();"))
SEARCH_SOURCE = "public sealed class SearchTests\n{\n    [Fact]\n    public void Search_is_literal()\n    {\n        Find(\"%\");\n    }\n}\n"


def job(job_id: int, name: str, *, conclusion: str = "failure", ran: bool = True) -> dict:
    steps = [{"number": 1, "name": "Set up job", "conclusion": "success" if ran else None},
             {"number": 6, "name": "Test", "conclusion": conclusion if ran else None}]
    return {"id": job_id, "name": name, "conclusion": conclusion, "started_at": WHEN if ran else None,
            "html_url": f"https://github.com/{REPO}/actions/runs/1/job/{job_id}", "steps": steps}


class FakeGitHub:
    """Answers the `gh` calls ci_failure_facts.py makes for run 1 of pull request 7, from synthetic data. No network."""

    def __init__(self, **changes):
        self.run = {"id": 1, "run_attempt": 1, "event": "pull_request", "status": "completed", "conclusion": "failure",
                    "head_sha": HEAD, "workflow_id": 99, "name": "CI", "html_url": f"https://github.com/{REPO}/actions/runs/1",
                    "head_repository": {"full_name": REPO}, "repository": {"full_name": REPO},
                    "pull_requests": [{"number": 7}], "created_at": WHEN}
        self.pr = {"number": 7, "state": "open", "html_url": f"https://github.com/{REPO}/pull/7",
                   "author_association": "OWNER", "user": {"login": "maintainer", "type": "User"},
                   "base": {"ref": "lab/test-decisions", "sha": BASE},
                   "head": {"ref": "fix/decisions", "sha": HEAD, "repo": {"full_name": REPO}}}
        self.jobs = [job(11, "API and worker tests")]
        self.logs = {11: DOTNET_LOG}
        self.files = [{"filename": TEST_FILE, "status": "modified", "additions": 9, "deletions": 1,
                       "patch": "@@ -1,3 +1,9 @@\n+    [Fact]"},
                      {"filename": "app/src/Example.Core/Workflow.cs", "status": "modified", "additions": 2,
                       "deletions": 2, "patch": "@@ -80,2 +80,2 @@\n-old\n+new"}]
        self.contents = {(TEST_FILE, MERGE_BASE): BASE_SOURCE, (TEST_FILE, HEAD): HEAD_SOURCE,
                         ("app/tests/Example.Tests/SearchTests.cs", HEAD): SEARCH_SOURCE}
        self.main_run = {"id": 5, "conclusion": "failure", "head_sha": "d" * 40, "created_at": WHEN,
                         "html_url": f"https://github.com/{REPO}/actions/runs/5"}
        self.main_jobs = [job(51, "API and worker tests")]
        self.main_logs = {51: stamped(["failed Example.Tests.SearchTests.Search_is_literal (9ms)",
                                       "  Assert.Single() Failure: The collection contained 2 items"])}
        self.escape_flag = True
        self.calls: list[tuple[str, ...]] = []
        for key, value in changes.items():
            setattr(self, key, value)

    def __call__(self, *args: str, check: bool = True) -> str:
        self.calls.append(args)
        if args and args[0] == "api" and "--allow-escape-sequences" in args and not self.escape_flag:
            raise facts_script.FactsError("gh api: unknown flag: --allow-escape-sequences")
        args = tuple(a for a in args if a != "--allow-escape-sequences")
        endpoint = args[2] if args[:2] == ("api", "--paginate") else args[1] if args[:1] == ("api",) else ""
        lines = lambda items: "".join(json.dumps(item) + "\n" for item in items)  # noqa: E731
        if endpoint == f"repos/{REPO}/actions/runs/1":
            return json.dumps(self.run)
        if endpoint == f"repos/{REPO}/pulls/7":
            return json.dumps(self.pr)
        if endpoint == f"repos/{REPO}/actions/runs/1/attempts/1/jobs?per_page=100":
            return lines(self.jobs)
        if endpoint == f"repos/{REPO}/actions/runs/5/attempts/1/jobs?per_page=100":
            return lines(self.main_jobs)
        if endpoint.startswith(f"repos/{REPO}/actions/jobs/") and endpoint.endswith("/logs"):
            job_id = int(endpoint.split("/")[-2])
            return {**self.logs, **self.main_logs}[job_id]
        if endpoint == f"repos/{REPO}/compare/{BASE}...{HEAD}":
            return MERGE_BASE + "\n"
        if endpoint == f"repos/{REPO}/pulls/7/files?per_page=100":
            return lines(self.files)
        if endpoint == f"repos/{REPO}":
            return json.dumps({"default_branch": "main"})
        if endpoint == f"repos/{REPO}/actions/workflows/99/runs?branch=main&event=push&status=completed&per_page=1":
            return json.dumps({"workflow_runs": [self.main_run] if self.main_run else []})
        if endpoint.startswith(f"repos/{REPO}/contents/"):
            path, ref = endpoint[len(f"repos/{REPO}/contents/"):].split("?ref=")
            return self.contents.get((path, ref), "")
        if endpoint == f"repos/{REPO}/commits/{HEAD}/pulls":
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


def collect(fake: FakeGitHub, *extra: str) -> tuple[int, Path, str]:
    """Run the script for run 1; return its exit code, its output folder, and what it appended to the noop file."""
    folder = Path(tempfile.mkdtemp())
    noop = folder / "safe-outputs.jsonl"
    noop.write_text("", encoding="utf-8")
    out = io.StringIO()
    with mock.patch.object(facts_script, "gh", fake), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = facts_script.main(["--run", "1", "--repo", REPO, "--base", "lab/test-*", "--out", str(folder / "ci"),
                                  "--noop-to", str(noop), *extra])
    return code, folder / "ci", noop.read_text(encoding="utf-8")


def facts_of(folder: Path) -> dict:
    return json.loads((folder / "facts.json").read_text(encoding="utf-8"))


class ParseLogTests(unittest.TestCase):
    def test_reads_dotnet_failures_with_message_file_and_line(self):
        parsed = facts_script.parse_log(DOTNET_LOG)
        tests = parsed["tests"]
        self.assertEqual([t["test"] for t in tests], [
            "Example.Tests.DecisionTests.Later_decision_returns_conflict",
            'Example.Tests.DecisionTests.Retry_returns_original(persona: "u-ava")',
            "Example.Tests.SearchTests.Search_is_literal"])
        self.assertEqual(tests[0]["message"], ["Assert.Equal() Failure: Values differ", "Expected: Conflict",
                                               "Actual:   Created"])
        self.assertEqual((tests[0]["file"], tests[0]["line"]), (TEST_FILE, 41))
        self.assertEqual((tests[1]["file"], tests[1]["line"]), (TEST_FILE, 58), "the classic ':line N' frame")
        self.assertEqual(tests[2]["file"], "app/tests/Example.Tests/SearchTests.cs")
        self.assertEqual(parsed["summary"], {"total": 40, "failed": 3, "succeeded": 37, "skipped": 0})
        self.assertEqual(parsed["errors"], [])
        self.assertEqual(parsed["tail"], [])

    def test_reads_a_playwright_failure_with_its_whole_message(self):
        [test] = facts_script.parse_log(PLAYWRIGHT_LOG)["tests"]
        self.assertEqual(test["kind"], "playwright")
        self.assertEqual(test["test"], "Example app › Hugo sees the self-approval message")
        self.assertEqual((test["file"], test["line"]), ("app/web/e2e/app.spec.ts", 59))
        self.assertEqual(test["message"], [
            "Error: expect(locator).toContainText(expected) failed",
            "Locator: getByRole('region', { name: 'Decision' })",
            "Expected substring: \"You can't decide your own request.\"",
            "Received string:    \"DecisionApproveReject\""])

    def test_reads_a_vitest_failure(self):
        [test] = facts_script.parse_log(VITEST_LOG)["tests"]
        self.assertEqual((test["kind"], test["test"]), ("vitest", "formatDate > uses the user's locale"))
        self.assertEqual((test["file"], test["line"]), ("src/lib/format.test.ts", 12))
        self.assertEqual(test["message"][0], "AssertionError: expected '11/10/2026' to be '10/11/2026' // Object.is equality")

    def test_reads_each_build_error_once(self):
        parsed = facts_script.parse_log(BUILD_LOG)
        self.assertEqual([(e["file"], e["line"], e["code"]) for e in parsed["errors"]],
                         [("app/src/Example.Core/Workflow.cs", 88, "CS1002")])
        self.assertEqual(parsed["errors"][0]["message"], ["; expected"])

    def test_reads_a_typescript_compiler_error(self):
        parsed = facts_script.parse_log(TYPECHECK_LOG)
        self.assertEqual([(e["file"], e["line"], e["code"]) for e in parsed["errors"]], [("src/lib/format.ts", 12, "TS2322")])
        self.assertEqual(parsed["errors"][0]["message"], ["Type 'string' is not assignable to type 'number'."])

    def test_keeps_the_lines_before_the_first_error_when_nothing_else_explains_it(self):
        parsed = facts_script.parse_log(SETUP_LOG)
        self.assertEqual(parsed["tests"], [])
        self.assertEqual(parsed["tail"][-1], "##[error]Failed to initialize container postgres:16")
        self.assertIn("no space left on device", parsed["tail"][-2])
        self.assertNotIn("Cleaning up orphan processes", parsed["tail"])


class CollectTests(unittest.TestCase):
    def test_marks_each_failing_test_as_added_changed_or_unchanged_and_by_its_result_on_main(self):
        code, folder, noop = collect(FakeGitHub())
        self.assertEqual((code, noop), (0, ""))
        facts = facts_of(folder)
        self.assertIsNone(facts["skip"])
        by_test = {f["test"].split("(")[0].rsplit(".", 1)[-1]: f for f in facts["failures"]}
        self.assertEqual(by_test["Later_decision_returns_conflict"]["pull_request_change"], "added")
        self.assertEqual(by_test["Retry_returns_original"]["pull_request_change"], "changed")
        self.assertEqual(by_test["Search_is_literal"]["pull_request_change"], "unchanged",
                         "a test in a file the pull request doesn't change")
        self.assertEqual(by_test["Search_is_literal"]["on_main"], "failed")
        self.assertEqual(by_test["Later_decision_returns_conflict"]["on_main"], "unknown")
        added = by_test["Later_decision_returns_conflict"]
        self.assertEqual(added["file_url"], f"https://github.com/{REPO}/blob/{HEAD}/{TEST_FILE}#L41")
        self.assertEqual(added["log_url"], f"https://github.com/{REPO}/actions/runs/1/job/11#step:6:1")
        self.assertIn("public async Task Later_decision_returns_conflict()", added["source"])
        self.assertEqual(facts["pull_request"]["merge_base"], MERGE_BASE)
        self.assertEqual(facts["main"]["failed_tests"], ["Example.Tests.SearchTests.Search_is_literal"])
        self.assertTrue((folder / "pr.patch").read_text(encoding="utf-8").startswith(f"diff --git a/{TEST_FILE}"))
        self.assertIn("`Later_decision_returns_conflict`", (folder / "facts.md").read_text(encoding="utf-8").replace(
            "Example.Tests.DecisionTests.", ""))
        self.assertTrue((folder / "logs" / "11.txt").exists())

    def test_a_passing_main_marks_every_failure_as_passing_there(self):
        fake = FakeGitHub(main_run={"id": 5, "conclusion": "success", "head_sha": "d" * 40, "created_at": WHEN,
                                    "html_url": f"https://github.com/{REPO}/actions/runs/5"})
        _, folder, _ = collect(fake)
        self.assertEqual({f["on_main"] for f in facts_of(folder)["failures"]}, {"passed"})

    def test_a_build_error_says_whether_the_pull_request_changes_its_file(self):
        _, folder, _ = collect(FakeGitHub(logs={11: BUILD_LOG}))
        [error] = facts_of(folder)["other_failures"]
        self.assertEqual((error["kind"], error["file"], error["line"], error["in_pull_request"]),
                         ("build", "app/src/Example.Core/Workflow.cs", 88, True))

    def test_a_typescript_error_is_matched_to_the_file_the_pull_request_changes(self):
        files = [{"filename": "app/web/src/lib/format.ts", "status": "modified", "patch": "+export const n: number = '1';"}]
        _, folder, _ = collect(FakeGitHub(logs={11: TYPECHECK_LOG}, files=files))
        [error] = facts_of(folder)["other_failures"]
        self.assertEqual((error["kind"], error["file"], error["line"], error["in_pull_request"]),
                         ("build", "app/web/src/lib/format.ts", 12, True))

    def test_a_unit_test_path_is_matched_to_the_file_the_pull_request_changes(self):
        files = [{"filename": "app/web/src/lib/format.test.ts", "status": "added", "patch": "+test"}]
        _, folder, _ = collect(FakeGitHub(logs={11: VITEST_LOG}, files=files))
        [failure] = facts_of(folder)["failures"]
        self.assertEqual((failure["file"], failure["pull_request_change"]), ("app/web/src/lib/format.test.ts", "added"))

    def test_works_with_a_github_cli_that_does_not_know_allow_escape_sequences(self):
        fake = FakeGitHub(escape_flag=False)
        code, folder, _ = collect(fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(facts_of(folder)["failures"]), 3)

    def test_caps_the_failures_it_lists_but_counts_them_all(self):
        many = stamped([f"failed Example.Tests.Bulk.Test_{n} (1ms)\n  Assert.True() Failure" for n in range(35)])
        _, folder, _ = collect(FakeGitHub(logs={11: many}))
        facts = facts_of(folder)
        self.assertEqual((facts["failures_total"], len(facts["failures"])), (35, facts_script.MAX_FAILURES))

    def test_cuts_a_long_diff(self):
        files = [{"filename": TEST_FILE, "status": "modified", "patch": "\n".join(f"+line {n}" for n in range(4000))}]
        _, folder, _ = collect(FakeGitHub(files=files))
        patch = (folder / "pr.patch").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(patch), facts_script.MAX_PATCH_LINES + 1)
        self.assertTrue(facts_of(folder)["patch_cut"])


class SkipTests(unittest.TestCase):
    """Nothing reaches the agent unless the run is one it may investigate: the workflow gets a noop instead."""

    def assert_skipped(self, fake: FakeGitHub, because: str) -> None:
        code, folder, noop = collect(fake)
        self.assertEqual(code, 0)
        reason = facts_of(folder)["skip"]
        self.assertIn(because, reason)
        self.assertEqual(json.loads(noop), {"type": "noop", "message": f"Nothing to investigate: {reason}"})
        self.assertFalse((folder / "facts.md").exists())
        self.assertFalse(any(arg.endswith("/logs") for call in fake.calls for arg in call), "no log is read")

    def test_a_run_from_a_fork(self):
        fake = FakeGitHub()
        fake.run["head_repository"] = {"full_name": "someone/example-repo"}
        self.assert_skipped(fake, "not from a branch of this repository")

    def test_a_pull_request_from_a_fork(self):
        fake = FakeGitHub()
        fake.pr["head"]["repo"] = {"full_name": "someone/example-repo"}
        self.assert_skipped(fake, "comes from a fork")

    def test_a_push_run(self):
        fake = FakeGitHub()
        fake.run["event"] = "push"
        self.assert_skipped(fake, "started by `push`")

    def test_a_run_that_passed(self):
        fake = FakeGitHub()
        fake.run["conclusion"] = "success"
        self.assert_skipped(fake, "not a failure")

    def test_a_closed_pull_request(self):
        fake = FakeGitHub()
        fake.pr["state"] = "closed"
        self.assert_skipped(fake, "is closed")

    def test_a_base_branch_it_may_not_investigate(self):
        fake = FakeGitHub()
        fake.pr["base"]["ref"] = "main"
        self.assert_skipped(fake, "matches no --base pattern")

    def test_an_author_who_is_not_the_owner_a_member_a_collaborator_or_copilot(self):
        for user in ({"login": "someone", "type": "User"}, {"login": "Copilot", "type": "User"},
                     {"login": "dependabot[bot]", "type": "Bot"}):
            with self.subTest(user=user):
                fake = FakeGitHub()
                fake.pr.update(user=user, author_association="NONE")
                self.assert_skipped(fake, "isn't the owner, a member, a collaborator, or Copilot")

    def test_copilot_is_investigated_by_its_exact_bot_account(self):
        fake = FakeGitHub()
        fake.pr.update(user={"login": "Copilot", "type": "Bot"}, author_association="NONE")
        code, folder, noop = collect(fake)
        self.assertEqual((code, noop, facts_of(folder)["skip"]), (0, "", None))

    def test_a_pull_request_whose_head_moved_on(self):
        fake = FakeGitHub()
        fake.pr["head"]["sha"] = "e" * 40
        self.assert_skipped(fake, "has moved on")

    def test_a_run_whose_jobs_never_ran(self):
        self.assert_skipped(FakeGitHub(jobs=[job(11, "API and worker tests", ran=False)]), "no job of the run ran")
        self.assert_skipped(FakeGitHub(jobs=[]), "no job of the run ran")

    def test_a_run_without_a_pull_request(self):
        fake = FakeGitHub()
        fake.run["pull_requests"] = []
        self.assert_skipped(fake, "no open pull request")

    def test_refuses_an_empty_noop_file_rather_than_let_the_agent_start(self):
        fake = FakeGitHub()
        fake.run["event"] = "push"
        err = io.StringIO()
        with mock.patch.object(facts_script, "gh", fake), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = facts_script.main(["--run", "1", "--repo", REPO, "--out", tempfile.mkdtemp(), "--noop-to", ""])
        self.assertEqual(code, 2)
        self.assertIn("--noop-to is empty", err.getvalue())
        self.assertEqual(fake.calls, [], "it stops before reading anything")


if __name__ == "__main__":
    unittest.main()
