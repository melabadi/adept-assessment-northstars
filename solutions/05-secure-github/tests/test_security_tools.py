"""Unit tests for evidence reporters and entitlement guards, not live security demo evidence.

Run: python -m unittest discover -s solutions/05-secure-github/tests -v
Fixtures below test parsing only. No fixture result is accepted as a real scanner finding.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import re

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


triage = load("triage", ".github/skills/finding-triage/finding_triage.py")
verify = load("verify", ".github/skills/verified-remediation/verify_remediation.py")
SHA = "a" * 40


class EntitlementTests(unittest.TestCase):
    def test_private_personal_repo_is_blocked_before_commit_lookup(self):
        repository = {"private": True, "owner": {"type": "User"}, "security_and_analysis": None}
        with patch.object(triage, "api", return_value=repository) as api:
            self.assertEqual("BLOCKED", triage.preflight("demo/repo", "lab/secure-test")["status"])
            api.assert_called_once()

    def test_public_and_licensed_organization_are_allowed(self):
        for repository in (
            {"private": False, "owner": {"type": "User"}},
            {"private": True, "owner": {"type": "Organization"},
             "security_and_analysis": {"code_security": {"status": "enabled"}}},
        ):
            with self.subTest(repository=repository), patch.object(
                    triage, "api", side_effect=[repository, {"sha": SHA}]):
                self.assertEqual(SHA, triage.preflight("demo/repo", "lab/secure-test")["scanned_sha"])

    def test_secret_protection_does_not_authorize_codeql(self):
        repository = {"private": True, "owner": {"type": "Organization"},
                      "security_and_analysis": {"secret_scanning": {"status": "enabled"}}}
        forbidden = subprocess.CalledProcessError(1, ["gh"], stderr="gh: Code scanning disabled (HTTP 403)")
        with patch.object(triage, "api", side_effect=[repository, forbidden]):
            self.assertEqual("BLOCKED", triage.preflight("demo/repo", "lab/secure-test")["status"])

    def test_actions_token_can_prove_enabled_service_without_admin_settings(self):
        repository = {"private": True, "owner": {"type": "Organization"}}
        with patch.object(triage, "api", side_effect=[repository, [], {"sha": SHA}]):
            self.assertEqual("PASS", triage.preflight("demo/repo", "lab/secure-test")["status"])

    def test_service_errors_are_not_misreported_as_licensing(self):
        repository = {"private": True, "owner": {"type": "Organization"}}
        server_error = subprocess.CalledProcessError(1, ["gh"], stderr="gh: Server error (HTTP 500)")
        with patch.object(triage, "api", side_effect=[repository, server_error]):
            with self.assertRaises(subprocess.CalledProcessError):
                triage.preflight("demo/repo", "lab/secure-test")

    def test_unrelated_or_unsafe_ref_is_rejected(self):
        for ref in ("main", "--all", "lab/secure-x/../main", "release/latest", "lab/secure-"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                triage.preflight("demo/repo", ref)

    def test_copilot_branch_must_target_lab(self):
        with patch.object(triage, "api", side_effect=[
                {"private": False, "owner": {"type": "User", "login": "demo"}},
                [{"base": {"ref": "main"}, "head": {"repo": {"full_name": "demo/repo"}}}]]):
            with self.assertRaises(ValueError):
                triage.preflight("demo/repo", "copilot/fix")


class SarifTests(unittest.TestCase):
    def document(self, results=None):
        return {"version": "2.1.0", "runs": [{
            "tool": {"driver": {"name": "CodeQL", "version": "test-fixture",
                                "rules": [{"id": triage.RULE}]}},
            "invocations": [{"executionSuccessful": True}],
            "results": results or [],
        }]}

    def finding(self, uri=triage.SOURCE):
        return {"ruleIndex": 0, "message": {"text": "Parser fixture, NOT live evidence"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri}, "region": {"startLine": 49}}}]}

    def summarize(self, document, expect):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.sarif"
            path.write_text(json.dumps(document), encoding="utf-8")
            return triage.summarize(path, expect, SHA)

    def test_present_and_absent_expectations(self):
        document = self.document([self.finding()])
        self.assertEqual("PASS", self.summarize(document, "present")["status"])
        self.assertEqual("FAIL", self.summarize(document, "absent")["status"])
        self.assertEqual("PASS", self.summarize(self.document(), "absent")["status"])
        self.assertEqual("FAIL", self.summarize(self.document(), "present")["status"])

    def test_empty_or_wrong_tool_or_failed_invocation_is_not_a_clean_scan(self):
        documents = [{"version": "2.1.0", "runs": []}, self.document(), self.document(), self.document()]
        documents[1]["runs"][0]["tool"]["driver"]["name"] = "NotCodeQL"
        documents[2]["runs"][0]["invocations"] = [{"executionSuccessful": False}]
        documents[3]["runs"][0].pop("invocations")
        for document in documents:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.summarize(document, "absent")

    def test_file_uri_and_wrong_location(self):
        self.assertEqual("PASS", self.summarize(
            self.document([self.finding("file:///runner/target/" + triage.SOURCE)]), "present")["status"])
        self.assertEqual("FAIL", self.summarize(
            self.document([self.finding("unrelated.cs")]), "present")["status"])

    def test_missing_sarif_is_not_a_clean_scan(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            triage.summarize(Path(folder), "absent", SHA)


class JunitTests(unittest.TestCase):
    def test_absolute_report_path_is_a_dotnet_option_not_a_runner_argument(self):
        command = verify.regression_command(Path.cwd() / "out" / "report")
        self.assertLess(command.index("--results-directory"), command.index("--"))
        self.assertTrue(command[command.index("--project") + 1].endswith(".csproj"))
        self.assertGreater(command.index("--filter-class"), command.index("--"))

    def test_assertions_are_distinguished_from_errors_and_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.xml"
            path.write_text('<testsuites><testsuite><testcase name="Search_treats_SQL_and_wildcards_as_literal_text">'
                            '<failure>assertion</failure></testcase><testcase name="other"><error>infra</error>'
                            '</testcase><testcase name="skip"><skipped /></testcase></testsuite></testsuites>')
            self.assertEqual({"tests": 3, "failures": 1, "errors": 1, "skipped": 1,
                              "literal_search_failures": 1}, verify.report(path))


class ReplayWorkflowTests(unittest.TestCase):
    def test_midnight_eastern_schedule_replays_the_configured_repair(self):
        workflow = (ROOT / ".github/workflows/secure-github-verify.yml").read_text()
        self.assertRegex(workflow, r"schedule:\s*\n\s*- cron: '0 0 \* \* \*'\s*\n\s*timezone: America/New_York")
        self.assertIn("PR: ${{ inputs.pr || vars.SECURE_REPLAY_PR }}", workflow)
        self.assertNotRegex(workflow, r"inputs\.pr \|\| '\d+'", "no pull request number of another repository")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("required: false", workflow)
        self.assertIn("group: secure-github-replay-${{ github.repository }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)

    def test_an_unconfigured_replay_says_what_setup_is_missing(self):
        workflow = (ROOT / ".github/workflows/secure-github-verify.yml").read_text()
        self.assertIn('if [[ -z "$PR" ]]; then', workflow)
        self.assertIn("python solutions/05-secure-github/replay_setup.py", workflow)
        self.assertIn("if: always() && steps.pr.outputs.head != ''", workflow)

    def test_the_lab_boundary_checks_stay(self):
        workflow = (ROOT / ".github/workflows/secure-github-verify.yml").read_text()
        self.assertIn('pr["head"]["repo"]["full_name"] != os.environ["REPO"]', workflow)
        self.assertIn('not pr["base"]["ref"].startswith("lab/secure-")', workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", workflow)

    def test_replay_remains_read_only_and_never_publishes_repo_changes(self):
        workflow = (ROOT / ".github/workflows/secure-github-verify.yml").read_text()
        permissions = re.search(r"^permissions:\n((?:  .*\n)+)", workflow, re.MULTILINE).group(1)
        self.assertEqual(["  contents: read", "  pull-requests: read"], permissions.strip("\n").splitlines())
        self.assertNotRegex(workflow, r": write\b|\bsecrets\.|\bgit push\b|\bgit commit\b|\bgh pr comment\b")


replay = load("replay_setup", "replay_setup.py")
REPO = "octo/requesthub"


def repair_pull(number, *, repo=REPO, author="OWNER", head=None, base=None, state="closed", body=None):
    return {"number": number, "state": state, "author_association": author,
            "body": replay.MARKER if body is None else body,
            "head": {"ref": head or replay.REPAIR, "repo": {"full_name": repo}}, "base": {"ref": base or replay.LAB}}


class FakeTools(replay.Tools):
    """git and gh as dictionaries: pull requests, remote branches, and the repository variable."""

    def __init__(self, pulls=(), branches=(), variable=""):
        super().__init__(REPO, run=None)
        self.pulls = {p["number"]: p for p in pulls}
        self.branches, self.value, self.commits = set(branches), variable, []

    def git(self, *args, cwd=None):
        if args[:2] == ("worktree", "add"):
            (Path(args[-2]) / "app/tests/RequestHub.Tests").mkdir(parents=True)
        if args[0] == "push" and "--delete" in args:
            self.branches -= set(args[args.index("--delete") + 1:])
        elif args[0] == "push":
            self.branches.add(args[-1].removeprefix("HEAD:refs/heads/"))
        elif args[0] == "commit":
            self.commits.append(args[-1])
        elif args[0] == "show":
            return "// regression"
        elif args[0] == "rev-parse":
            return "b" * 40
        return ""

    def api(self, path, method="GET", fields=None):
        if method == "POST":
            number = max(self.pulls, default=300) + 1
            self.pulls[number] = repair_pull(number, state="open", body=fields["body"])
            return self.pulls[number]
        if method == "PATCH":
            self.pulls[int(path.split("/")[1])].update(fields)
            return None
        if path.startswith("pulls?"):
            return sorted(self.pulls.values(), key=lambda p: -p["number"])
        number = int(path.split("/")[1])
        if number not in self.pulls:
            raise RuntimeError("not found")
        return self.pulls[number]

    def variable(self):
        return self.value

    def set_variable(self, value):
        self.value = value

    def delete_variable(self):
        self.value = ""

    def remote_branches(self):
        return self.branches & {replay.BASE, replay.LAB, replay.REPAIR}


class ReplaySetupTests(unittest.TestCase):
    def test_a_fresh_copy_gets_a_closed_reference_repair_and_the_variable(self):
        tools, said = FakeTools(), []
        number = replay.setup(tools, said.append)
        self.assertEqual(tools.value, str(number))
        self.assertEqual(tools.pulls[number]["state"], "closed")
        self.assertEqual(tools.branches, {replay.BASE, replay.LAB, replay.REPAIR})
        self.assertEqual(len(tools.commits), 3)  # the unsafe lab commit, the tests-only commit, the repair
        self.assertTrue(all("[skip ci]" in message for message in tools.commits))
        self.assertIn("regression", tools.commits[1])

    def test_a_second_setup_reuses_the_same_pull_request(self):
        tools = FakeTools([repair_pull(321)], {replay.BASE, replay.LAB, replay.REPAIR}, variable="321")
        self.assertEqual(replay.setup(tools, lambda _: None), 321)
        self.assertEqual(tools.commits, [])
        self.assertEqual(list(tools.pulls), [321])
        lost_variable = FakeTools([repair_pull(321)], {replay.BASE, replay.LAB, replay.REPAIR})
        self.assertEqual(replay.setup(lost_variable, lambda _: None), 321)
        self.assertEqual(lost_variable.value, "321")

    def test_only_this_repositorys_lab_pull_requests_by_trusted_authors_are_found(self):
        for stranger in (repair_pull(5, repo="mallory/requesthub"), repair_pull(5, author="NONE"),
                         repair_pull(5, body="no marker"), repair_pull(5, base="main")):
            self.assertIsNone(replay.find(FakeTools([stranger])))

    def test_adopting_follows_the_workflows_own_boundary(self):
        tools = FakeTools([repair_pull(105, author="NONE", head="copilot/fix-search", body=""),
                           repair_pull(7, repo="mallory/requesthub"), repair_pull(8, base="main")])
        self.assertEqual(replay.adopt(tools, 105, lambda _: None), 105)
        self.assertEqual(tools.value, "105")
        for refused in (7, 8, 999):
            with self.assertRaises(RuntimeError):
                replay.adopt(tools, refused, lambda _: None)

    def test_status_names_what_is_missing(self):
        pull, why = replay.current(FakeTools())
        self.assertIsNone(pull)
        self.assertIn("SECURE_REPLAY_PR", why)
        pull, why = replay.current(FakeTools([repair_pull(8, base="main")], variable="8"))
        self.assertIsNone(pull)
        self.assertIn("lab/secure-", why)

    def test_cleanup_removes_only_what_setup_made(self):
        tools = FakeTools([repair_pull(321, state="open")], {replay.BASE, replay.LAB, replay.REPAIR, "main"}, variable="321")
        replay.cleanup(tools, lambda _: None)
        self.assertEqual(tools.pulls[321]["state"], "closed")
        self.assertEqual(tools.branches, {"main"})
        self.assertEqual(tools.value, "")
        adopted = FakeTools([repair_pull(105, author="NONE", head="copilot/fix-search", body="", state="open")], set(),
                            variable="105")  # a live run's repair, adopted: cleanup unsets the variable, never touches it
        replay.cleanup(adopted, lambda _: None)
        self.assertEqual((adopted.value, adopted.pulls[105]["state"]), ("", "open"))


if __name__ == "__main__":
    unittest.main()
