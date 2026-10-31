"""Tests for the posture Function (function/), run offline with fake GitHub and Azure connections.

On a public repository anyone can open a pull request from a fork, name its branch like the remediation's, and comment.
These tests pin who the automation acts for (the gates), and run the three flows end to end: intake (a recommendation
becomes an Issue, a checked edit, a draft pull request, and a preview), preview (a pull request starts the what-if job),
and verify (evidence and the Issue closed once Azure Policy reports the fix compliant). No Azure or GitHub access.

  python -m unittest test_function.py      (from this folder)
"""
from __future__ import annotations

import base64
import re
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "function"))

from posture import auth, checks, flows, messages  # noqa: E402
from posture.config import Settings  # noqa: E402

REPOSITORY = "octo/requesthub"
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
OUTSIDE = ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", None)
RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ai-sdlc-secure"
STORAGE = RG + "/providers/Microsoft.Storage/storageAccounts/stexample"
EDITABLE = "solutions/05-secure-microsoft/infra/resources.bicep"
MODULE = "app/infra/requesthub.bicep"
CONTENT = (HERE / "infra" / "resources.bicep").read_text(encoding="utf-8")
SETTING = "storagePrivateEndpoint: false"
INSIDE = CONTENT[CONTENT.index("    // Without a private endpoint"):CONTENT.index(SETTING) + len(SETTING)]
GOOD = "    // Reach Blob storage through a private endpoint in the app's virtual network.\n    storagePrivateEndpoint: true"
SETTINGS = Settings(
    repository=REPOSITORY, resource_group_id=RG, storage_account_id=STORAGE, assessment_key="cdc78c07",
    policy_definition_name="6edd7eda", policy_assignment_name="requesthub-storage-private-link",
    marker="posture:storage-private-link:rg-ai-sdlc-secure", foundry_project_endpoint="https://foundry.example/api/projects/p",
    agent_name="posture-remediator", editable_path=EDITABLE, module_path=MODULE,
    infra_prefix="solutions/05-secure-microsoft/infra/", whatif_job_id=RG + "/providers/Microsoft.App/jobs/posture-whatif")
ISSUE_MARKER = "<!-- posture:storage-private-link:rg-ai-sdlc-secure -->"
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
INHERITED = {"policyAssignmentName": "Org_Baseline", "policyAssignmentScope": "/providers/Microsoft.Management/managementGroups/root",
             "complianceState": "NonCompliant", "timestamp": "2026-10-31T11:00:00.1234567Z"}


def pull_request(head_repository: str | None = REPOSITORY, association: str | None = "OWNER", ref: str = "fix",
                 number: int = 5, state: str = "open", changed_files: int = 1) -> dict:
    head = {"ref": ref, "sha": "a" * 40, "repo": {"full_name": head_repository} if head_repository else None}
    return {"number": number, "state": state, "head": head, "author_association": association,
            "changed_files": changed_files}


def policy(assignment: str = "requesthub-storage-private-link", state: str = "NonCompliant", scope: str = RG) -> dict:
    return {"policyAssignmentName": assignment, "policyAssignmentScope": scope, "complianceState": state,
            "timestamp": "2026-10-31T11:00:00Z"}


class FakeGitHub:
    """A small stand-in for GitHub's REST API, recording every call."""

    def __init__(self, issues=(), pulls=(), comments=None, statuses=None, files=None):
        self.repository = REPOSITORY
        self.issues = [dict(i) for i in issues]
        self.pulls = {p["number"]: dict(p) for p in pulls}
        self.comments = {k: list(v) for k, v in (comments or {}).items()}
        self.statuses = {k: list(v) for k, v in (statuses or {}).items()}
        self.files = files or {}
        self.contents = {EDITABLE: CONTENT, MODULE: "param storagePrivateEndpoint bool = true"}
        self.calls, self.branches, self.commits = [], [], []
        self.next_number = 100

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path, _ in self.calls if method != "GET"]

    def file(self, path: str, ref: str = "main") -> tuple[str, str]:
        self.calls.append(("GET", f"contents/{path}?ref={ref}", None))
        return self.contents[path], f"sha-of-{path}"

    def call(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        route, query = (path.split("?", 1) + [""])[:2]
        if route == "issues" and method == "GET":
            state = re.search(r"state=(\w+)", query).group(1)
            return [i for i in self.issues if state == "all" or i["state"] == state]
        if route == "issues" and method == "POST":
            self.next_number += 1
            issue = {"number": self.next_number, "state": "open", "author_association": "OWNER", **body}
            self.issues.insert(0, issue)
            return issue
        if match := re.fullmatch(r"issues/(\d+)/comments", route):
            number = int(match[1])
            if method == "GET":
                return self.comments.get(number, [])
            self.comments.setdefault(number, []).append({"body": body["body"], "author_association": "OWNER"})
            return {"id": 1}
        if (match := re.fullmatch(r"issues/(\d+)", route)) and method == "PATCH":
            next(i for i in self.issues if i["number"] == int(match[1])).update(body)
            return {}
        if route == "pulls" and method == "GET":
            return [p for p in self.pulls.values() if p["state"] == "open"]
        if route == "pulls" and method == "POST":
            self.next_number += 1
            pull = pull_request(ref=body["head"], number=self.next_number)
            pull.update(head={"ref": body["head"], "sha": "b" * 40, "repo": {"full_name": REPOSITORY}}, title=body["title"],
                        body=body["body"], draft=body["draft"])
            self.pulls[pull["number"]] = pull
            self.files[pull["number"]] = [{"filename": EDITABLE}]
            return pull
        if (match := re.fullmatch(r"pulls/(\d+)", route)) and method == "GET":
            return self.pulls[int(match[1])]
        if (match := re.fullmatch(r"pulls/(\d+)/files", route)) and method == "GET":
            return self.files.get(int(match[1]), [])
        if (match := re.fullmatch(r"commits/(\w+)/statuses", route)) and method == "GET":
            return self.statuses.get(match[1], [])
        if (match := re.fullmatch(r"statuses/(\w+)", route)) and method == "POST":
            self.statuses.setdefault(match[1], []).insert(0, dict(body))
            return body
        if route == "git/ref/heads/main" and method == "GET":
            return {"object": {"sha": "c" * 40}}
        if route == "git/refs" and method == "POST":
            self.branches.append(body)
            return body
        if route.startswith("contents/") and method == "PUT":
            self.commits.append(body)
            return {"commit": {}}
        raise AssertionError(f"unexpected GitHub call {method} {path}")


class FakeAzure:
    """A stand-in for the Function's Azure calls, recording every one."""

    def __init__(self, statuses=("Unhealthy",), approved=0, states=None, proposal=None, compliant_after=0,
                 job_fails=False):
        self._statuses = list(statuses)
        self.approved, self.job_fails = approved, job_fails
        self.states = states if states is not None else [INHERITED, policy()]
        default = {"decision": "change", "path": EDITABLE, "find": INSIDE, "replace": GOOD,
                   "title": "Use a private endpoint for attachment storage", "summary": "Set it.",
                   "expectedChanges": ["Create Microsoft.Network/privateEndpoints"], "risks": "Check DNS."}
        self.proposals = proposal if isinstance(proposal, list) else [proposal or default]
        self.compliant_after = compliant_after
        self.calls, self.documents, self.jobs = [], [], []

    def assessment(self, storage_account_id, key):
        self.calls.append("assessment")
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return {"properties": {"displayName": "Storage account should use a private link connection",
                               "status": {"code": status, "statusChangeDate": "2026-10-28T09:06:40.1234567Z"},
                               "metadata": {"severity": "Medium", "description": "d", "remediationDescription": "r"}}}

    def storage_account(self, storage_account_id):
        self.calls.append("storage_account")
        connections = [{"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}}] * self.approved
        return {"properties": {"publicNetworkAccess": "Disabled", "privateEndpointConnections": connections}}

    def policy_states(self, resource_group_id, odata_filter):
        self.calls.append("policy_states")
        compliant = self.compliant_after <= 0
        self.compliant_after -= 1
        states = [dict(s, complianceState="Compliant") if compliant else dict(s) for s in self.states]
        if "policyAssignmentName eq" in odata_filter:
            return [s for s in states if s["policyAssignmentName"] == SETTINGS.policy_assignment_name]
        return states

    def start_policy_evaluation(self, resource_group_id):
        self.calls.append("start_policy_evaluation")

    def job_container(self, job_id):
        self.calls.append("job_container")
        if self.job_fails:
            raise flows.HttpError("Azure Resource Manager", 403, "AuthorizationFailed")
        return {"name": "whatif", "image": "mcr.microsoft.com/azure-cli", "command": ["python3"], "env": []}

    def start_job(self, job_id, container, args):
        self.calls.append("start_job")
        self.jobs.append(args)

    def ask_agent(self, endpoint, agent_name, document):
        self.calls.append("ask_agent")
        self.documents.append(document)
        return dict(self.proposals[min(len(self.documents), len(self.proposals)) - 1])


def run_intake(github, azure, status="Unhealthy", triggered_at=NOW, resource=STORAGE, assessment="cdc78c07"):
    event = {"resourceId": resource, "assessment": assessment, "status": status, "triggeredAt": triggered_at.isoformat()}
    return flows.intake(event, SETTINGS, azure, github, now=lambda: NOW, sleep=lambda seconds: None)


class PreviewGate(unittest.TestCase):
    """The preview starts the what-if job, and writes commit statuses, only past this gate."""

    def admits(self, pull: dict) -> bool:
        return checks.outside_pull_request(pull, REPOSITORY) is None

    def test_a_branch_of_this_repository_opened_by_the_owner_a_member_or_a_collaborator(self):
        for association in TRUSTED:
            with self.subTest(association=association):
                self.assertIs(self.admits(pull_request(association=association)), True)
        self.assertIs(self.admits(pull_request("Octo/RequestHub")), True)  # GitHub names are not case-sensitive

    def test_a_fork_never_passes(self):
        for association in (*TRUSTED, *OUTSIDE):
            with self.subTest(association=association):
                self.assertIs(self.admits(pull_request("someone/requesthub", association)), False)
                self.assertIs(self.admits(pull_request(None, association)), False)  # the fork was deleted

    def test_an_outside_author_never_passes_even_from_a_branch_of_this_repository(self):
        for association in OUTSIDE:
            with self.subTest(association=association):
                self.assertIs(self.admits(pull_request(association=association)), False)


class WebhookDelivery(unittest.TestCase):
    """A signed delivery of a fork's or an outside author's pull request is dropped before any call; any other gives
    only its number to the preview, which reads the pull request again."""

    def number(self, payload: dict, event: str = "pull_request"):
        return checks.webhook_number(event, payload, REPOSITORY)[0]

    def delivery(self, pull: dict, action: str = "synchronize") -> dict:
        return {"action": action, "repository": {"full_name": REPOSITORY}, "pull_request": pull}

    def test_this_repositorys_pull_requests_by_trusted_authors(self):
        for association in TRUSTED:
            with self.subTest(association=association):
                self.assertEqual(self.number(self.delivery(pull_request(association=association))), 5)

    def test_a_fork_or_an_outside_author_is_dropped(self):
        for association in (*TRUSTED, *OUTSIDE):
            with self.subTest(association=association):
                self.assertIsNone(self.number(self.delivery(pull_request("someone/requesthub", association), "opened")))
                self.assertIsNone(self.number(self.delivery(pull_request(None, association), "opened")))
        for association in OUTSIDE:
            with self.subTest(association=association):
                self.assertIsNone(self.number(self.delivery(pull_request(association=association), "opened")))

    def test_other_events_and_repositories_are_ignored(self):
        self.assertIsNone(self.number({"zen": "hi"}, "ping"))
        self.assertIsNone(self.number(self.delivery(pull_request()), "push"))
        self.assertIsNone(self.number(dict(self.delivery(pull_request()), repository={"full_name": "someone/else"})))
        self.assertIsNone(self.number(self.delivery(dict(pull_request(), number="5"))))

    def test_only_the_number_goes_further(self):
        # The delivery says this repository and the owner; GitHub's API says a fork: the API wins.
        github, azure = FakeGitHub(pulls=[pull_request("someone/requesthub", "OWNER")]), FakeAzure()
        number = self.number(self.delivery(pull_request()))
        result = flows.preview(number, SETTINGS, azure, github)
        self.assertFalse(result["started"])
        self.assertEqual((github.writes(), azure.calls), ([], []))

    def test_signature(self):
        body = b'{"action": "opened"}'
        good = "sha256=" + __import__("hmac").new(b"s3cret", body, "sha256").hexdigest()
        self.assertTrue(checks.verify_signature("s3cret", body, good))
        self.assertFalse(checks.verify_signature("s3cret", body + b" ", good))
        self.assertFalse(checks.verify_signature("other", body, good))
        self.assertFalse(checks.verify_signature("", body, good))
        self.assertFalse(checks.verify_signature("s3cret", body, None))
        self.assertFalse(checks.verify_signature("s3cret", body, good.replace("sha256=", "sha1=")))


class PreviewFlow(unittest.TestCase):
    def preview(self, pull: dict, statuses=None, files=None, **azure_options):
        github = FakeGitHub(pulls=[pull], statuses={"a" * 40: statuses or []},
                            files={pull["number"]: files if files is not None else [{"filename": EDITABLE}]})
        azure = FakeAzure(**azure_options)
        return flows.preview(pull["number"], SETTINGS, azure, github), github, azure

    def test_everything_that_writes_to_github_or_calls_azure_sits_behind_the_gate(self):
        for pull in (pull_request("someone/requesthub"), pull_request(None), *[pull_request(association=a) for a in OUTSIDE]):
            with self.subTest(pull=pull["head"]["repo"], association=pull["author_association"]):
                result, github, azure = self.preview(pull)
                self.assertFalse(result["started"])
                self.assertEqual(github.writes(), [])
                self.assertEqual([path for _, path, _ in github.calls], ["pulls/5"])  # not even its files
                self.assertEqual(azure.calls, [])

    def test_a_trusted_pull_request_that_changes_infra_starts_the_job(self):
        result, github, azure = self.preview(pull_request())
        self.assertTrue(result["started"])
        self.assertEqual(github.writes(), [("POST", "statuses/" + "a" * 40)])
        self.assertEqual(github.statuses["a" * 40][0]["state"], "pending")
        self.assertEqual(azure.jobs, [["--pull-request", "5"]])

    def test_no_preview_without_an_infra_change_or_when_closed(self):
        for pull, files in ((pull_request(), [{"filename": "README.md"}]), (pull_request(state="closed"), None)):
            result, github, azure = self.preview(pull, files=files)
            self.assertFalse(result["started"])
            self.assertEqual((github.writes(), azure.jobs), ([], []))
        result, _, _ = self.preview(pull_request(changed_files=150), files=[{"filename": "README.md"}])
        self.assertTrue(result["started"])  # too many files to tell from one page

    def test_a_commit_is_previewed_once_unless_its_preview_failed_in_azure(self):
        done = [{"context": "posture/what-if", "state": "success"}, {"context": "other", "state": "error"}]
        result, _, azure = self.preview(pull_request(), statuses=done)
        self.assertFalse(result["started"])
        self.assertEqual(azure.jobs, [])
        errored = [{"context": "posture/what-if", "state": "error"}, {"context": "posture/what-if", "state": "pending"}]
        result, _, azure = self.preview(pull_request(), statuses=errored)
        self.assertTrue(result["started"])

    def test_a_job_that_cannot_start_leaves_an_error_status(self):
        github = FakeGitHub(pulls=[pull_request()], files={5: [{"filename": EDITABLE}]})
        with self.assertRaises(flows.HttpError):
            flows.preview(5, SETTINGS, FakeAzure(job_fails=True), github)
        self.assertEqual([s["state"] for s in github.statuses["a" * 40]], ["error", "pending"])


class IntakeExistingFix(unittest.TestCase):
    """Intake asks the agent for a fix unless an open pull request already is one. A fork can name its branch like the
    remediation's; it must not pass for the fix."""

    def is_fix(self, pull: dict) -> bool:
        return checks.is_fix_for(pull, 12, REPOSITORY)

    def test_the_remediation_branch_of_this_repository(self):
        self.assertIs(self.is_fix(pull_request(ref="posture/issue-12-10310112")), True)

    def test_a_fork_with_the_same_branch_name_is_not_the_fix(self):
        self.assertIs(self.is_fix(pull_request("someone/requesthub", "NONE", "posture/issue-12-10310112")), False)
        self.assertIs(self.is_fix(pull_request(None, "NONE", "posture/issue-12-10310112")), False)

    def test_another_issues_branch_is_not_the_fix(self):
        self.assertIs(self.is_fix(pull_request(ref="posture/issue-120-10310112")), False)


class Markers(unittest.TestCase):
    """A marker counts only on an Issue or a comment by the owner, a member, or a collaborator (the automation's token
    is a person's), because anyone can open an Issue or comment on a public repository."""

    def test_a_marker_from_the_repository_counts(self):
        for text in (checks.VERIFIED, checks.DEFENDER_CONFIRMED):
            for association in TRUSTED:
                with self.subTest(marker=text, association=association):
                    self.assertEqual(len(checks.marker_comments([{"body": f"Evidence\n{text}",
                                                                  "author_association": association}], text)), 1)

    def test_a_marker_from_anyone_else_does_not(self):
        for text in (checks.VERIFIED, checks.DEFENDER_CONFIRMED):
            for association in OUTSIDE:
                with self.subTest(marker=text, association=association):
                    self.assertEqual(checks.marker_comments([{"body": text, "author_association": association}], text), [])
        self.assertEqual(checks.marker_comments([{"body": "Looks good", "author_association": "OWNER"}], checks.VERIFIED), [])

    def test_the_findings_issue_needs_the_full_marker_a_trusted_author_and_no_pull_request(self):
        mine = {"number": 1, "body": f"text\n{ISSUE_MARKER}", "author_association": "OWNER"}
        self.assertEqual(checks.issues_for_finding([mine], SETTINGS.marker), [mine])
        others = [dict(mine, body="<!-- posture:storage-private-link:rg-ai-sdlc-secure2 -->"),
                  dict(mine, author_association="NONE"), dict(mine, pull_request={"url": "x"})]
        self.assertEqual(checks.issues_for_finding(others, SETTINGS.marker), [])


class IntakeFlow(unittest.TestCase):
    def test_another_resource_or_recommendation_is_ignored(self):
        github, azure = FakeGitHub(), FakeAzure()
        for options in ({"resource": STORAGE + "2"}, {"assessment": "other"}):
            self.assertIn("ignored", run_intake(github, azure, **options)["result"])
        self.assertEqual((github.calls, azure.calls), ([], []))

    def test_a_new_finding_becomes_an_issue_a_checked_edit_a_draft_pull_request_and_a_preview(self):
        github, azure = FakeGitHub(), FakeAzure()
        result = run_intake(github, azure)
        self.assertEqual((result["issue"], result["filed"], result["previewStarted"]), (101, True, True))
        issue = github.issues[0]
        self.assertEqual(issue["labels"], ["posture"])
        self.assertIn(ISSUE_MARKER, issue["body"])
        self.assertNotIn("Org_Baseline", issue["body"])
        self.assertIn("`management group assignment` (inherited)", issue["body"])
        self.assertEqual(azure.documents[0]["editableFile"], {"path": EDITABLE, "content": CONTENT})
        self.assertEqual(github.branches[0]["ref"], "refs/heads/posture/issue-101-10311200")
        fixed = base64.b64decode(github.commits[0]["content"]).decode()
        self.assertEqual(fixed, CONTENT.replace(INSIDE, GOOD))
        pull = github.pulls[result["pullRequest"]]
        self.assertTrue(pull["draft"])
        self.assertIn("Remediates #101.", pull["body"])
        self.assertEqual(azure.jobs, [["--pull-request", str(result["pullRequest"])]])
        self.assertIn(f"drafted a fix: #{result['pullRequest']}. The Azure what-if preview runs on it now",
                      github.comments[101][-1]["body"])

    def test_an_open_issue_is_reused_and_an_outsiders_look_alike_is_not(self):
        mine = {"number": 7, "state": "open", "body": ISSUE_MARKER, "author_association": "OWNER"}
        theirs = {"number": 8, "state": "open", "body": ISSUE_MARKER, "author_association": "NONE"}
        result = run_intake(FakeGitHub(issues=[theirs, mine]), FakeAzure())
        self.assertEqual((result["issue"], result["filed"]), (7, False))
        result = run_intake(FakeGitHub(issues=[theirs]), FakeAzure())
        self.assertTrue(result["filed"])

    def test_an_open_fix_is_reported_and_the_agent_not_asked(self):
        mine = {"number": 7, "state": "open", "body": ISSUE_MARKER, "author_association": "OWNER"}
        fix = pull_request(ref="posture/issue-7-10301834", number=9)
        github, azure = FakeGitHub(issues=[mine], pulls=[fix]), FakeAzure()
        result = run_intake(github, azure)
        self.assertEqual(result["pullRequest"], 9)
        self.assertNotIn("ask_agent", azure.calls)
        self.assertEqual(github.comments[7][-1]["body"], messages.existing_fix_comment(9))

    def test_a_forks_branch_named_like_the_fix_does_not_stop_the_agent(self):
        mine = {"number": 7, "state": "open", "body": ISSUE_MARKER, "author_association": "OWNER"}
        fork = pull_request("someone/requesthub", "NONE", "posture/issue-7-10301834", number=9)
        azure = FakeAzure()
        run_intake(FakeGitHub(issues=[mine], pulls=[fork]), azure)
        self.assertIn("ask_agent", azure.calls)

    def test_a_deployed_fix_files_nothing(self):
        github = FakeGitHub()
        self.assertIn("Nothing to file", run_intake(github, FakeAzure(approved=1))["result"])
        self.assertEqual(github.calls, [])

    def test_a_rejected_or_empty_proposal_is_reported_and_nothing_is_written_to_a_branch(self):
        proposals = {"protected": {"find": INSIDE, "replace": GOOD + "\n    // automationRoleDefinitionIds"},
                     "no_change": {"decision": "no_change", "summary": "Nothing safe to change."}}
        for name, change in proposals.items():
            with self.subTest(name):
                github = FakeGitHub()
                azure = FakeAzure(proposal={"decision": "change", "path": EDITABLE, "title": "t", "summary": "s",
                                            "expectedChanges": [], "risks": "r", **change})
                result = run_intake(github, azure)
                self.assertEqual((github.branches, github.commits, azure.jobs), ([], [], []))
                self.assertIn("posture-remediator", github.comments[result["issue"]][-1]["body"])
                if name == "protected":
                    self.assertIn("protected setting", github.comments[result["issue"]][-1]["body"])
                else:
                    self.assertIn("proposes no change", github.comments[result["issue"]][-1]["body"])

    def test_a_preview_that_cannot_start_is_said_on_the_issue(self):
        github = FakeGitHub()
        result = run_intake(github, FakeAzure(job_fails=True))
        self.assertFalse(result["previewStarted"])
        self.assertIn("did not start", github.comments[result["issue"]][-1]["body"])

    def proposal(self, **change) -> dict:
        return {"decision": "change", "path": EDITABLE, "find": INSIDE, "replace": GOOD, "title": "t", "summary": "s",
                "expectedChanges": [], "risks": "r", **change}

    def test_a_refused_answer_goes_back_to_the_agent_with_its_problems(self):
        # Seen live: the agent rewrote the begin marker's line. Its next try, told why, is applied.
        begin = CONTENT.index("    // posture:editable-begin")
        rewrites_marker = self.proposal(find=CONTENT[begin:CONTENT.index(SETTING) + len(SETTING)],
                                        replace="    // posture:editable-begin. Reworded.\n    storagePrivateEndpoint: true")
        github, azure = FakeGitHub(), FakeAzure(proposal=[rewrites_marker, self.proposal()])
        result = run_intake(github, azure)
        self.assertEqual((result["agentAttempts"], result["previewStarted"]), (2, True))
        self.assertNotIn("rejectedProposals", azure.documents[0])
        retry = azure.documents[1]["rejectedProposals"]
        self.assertEqual(retry[0]["find"], rewrites_marker["find"])
        self.assertIn("it changes text outside the lines between the posture:editable markers", retry[0]["problems"])
        self.assertEqual(base64.b64decode(github.commits[0]["content"]).decode(), CONTENT.replace(INSIDE, GOOD))

    def test_three_refused_answers_end_in_a_comment(self):
        unindented = self.proposal(find=INSIDE.replace("    ", ""))
        github, azure = FakeGitHub(), FakeAzure(proposal=[unindented])
        result = run_intake(github, azure)
        self.assertEqual((result["agentAttempts"], azure.calls.count("ask_agent")), (3, 3))
        self.assertEqual((github.branches, azure.jobs), ([], []))
        self.assertEqual(len(azure.documents[2]["rejectedProposals"]), 2)
        self.assertIn("will not apply, in 3 tries. The last one: its search text does not occur exactly once",
                      github.comments[result["issue"]][-1]["body"])

    def test_no_change_is_not_asked_again_and_time_bounds_the_tries(self):
        azure = FakeAzure(proposal=[{"decision": "no_change", "summary": "Nothing safe."}])
        self.assertEqual(run_intake(FakeGitHub(), azure)["agentAttempts"], 1)
        ticks = iter([0, flows.AGENT_BUDGET + 1, flows.AGENT_BUDGET + 2])
        azure = FakeAzure(proposal=[self.proposal(find="not in the file")])
        proposal, problems, attempts = flows._ask_for_an_applicable_edit(azure, SETTINGS, {}, CONTENT,
                                                                         clock=lambda: next(ticks))
        self.assertEqual((attempts, azure.calls.count("ask_agent")), (1, 1))
        self.assertTrue(problems)

    def test_a_healthy_event_ahead_of_azure_asks_to_be_sent_again(self):
        azure = FakeAzure(statuses=("Unhealthy",))
        with self.assertRaises(flows.Retry):
            run_intake(FakeGitHub(), azure, status="Healthy", triggered_at=NOW - timedelta(minutes=2))
        self.assertEqual(azure.calls.count("assessment"), 4)

    def test_after_the_grace_period_intake_acts_on_what_azure_returns(self):
        github = FakeGitHub(issues=[], pulls=[])
        result = run_intake(github, FakeAzure(approved=1), status="Healthy", triggered_at=NOW - timedelta(minutes=11))
        self.assertIn("Nothing to file", result["result"])

    def test_a_healthy_event_seen_by_azure_is_recorded_once(self):
        issue = {"number": 7, "state": "closed", "body": ISSUE_MARKER, "author_association": "OWNER"}
        github = FakeGitHub(issues=[issue])
        run_intake(github, FakeAzure(statuses=("Unhealthy", "Healthy")), status="Healthy")
        self.assertIn(checks.DEFENDER_CONFIRMED, github.comments[7][-1]["body"])
        run_intake(github, FakeAzure(statuses=("Healthy",)), status="Healthy")
        self.assertEqual(len(github.comments[7]), 1)

    def test_an_outsiders_confirmation_marker_does_not_count(self):
        issue = {"number": 7, "state": "closed", "body": ISSUE_MARKER, "author_association": "OWNER"}
        github = FakeGitHub(issues=[issue], comments={7: [{"body": checks.DEFENDER_CONFIRMED, "author_association": "NONE"}]})
        run_intake(github, FakeAzure(statuses=("Healthy",)), status="Healthy")
        self.assertEqual(len(github.comments[7]), 2)


class VerifyFlow(unittest.TestCase):
    ISSUE = {"number": 7, "state": "open", "body": ISSUE_MARKER, "author_association": "OWNER"}

    def verify(self, github, azure):
        return flows.verify(SETTINGS, azure, github, now=lambda: NOW, sleep=lambda seconds: None, polls=3)

    def test_nothing_before_the_fix_is_deployed(self):
        github = FakeGitHub(issues=[self.ISSUE])
        self.assertIn("not fixed yet", self.verify(github, FakeAzure(approved=0))["result"])
        self.assertEqual(github.calls, [])

    def test_a_deployed_fix_gets_the_evidence_and_the_issue_closes(self):
        github, azure = FakeGitHub(issues=[self.ISSUE]), FakeAzure(approved=1)
        result = self.verify(github, azure)
        self.assertEqual((result["result"], result["closed"]), ("verified", True))
        evidence = github.comments[7][-1]["body"]
        self.assertIn(checks.VERIFIED, evidence)
        self.assertIn("1 approved private endpoint ✅", evidence)
        self.assertIn("`management group assignment` (inherited) | Compliant ✅", evidence)
        self.assertNotIn("Org_Baseline", evidence)
        self.assertEqual(github.issues[0]["state"], "closed")
        self.assertNotIn("start_policy_evaluation", azure.calls)
        self.assertEqual((result["evaluationStarted"], result["policyChecks"]), (False, 1))

    def test_stale_policy_results_start_an_evaluation_and_wait_for_it(self):
        azure = FakeAzure(approved=1, compliant_after=2)
        result = self.verify(FakeGitHub(issues=[self.ISSUE]), azure)
        self.assertEqual(result["result"], "verified")
        self.assertEqual(azure.calls.count("start_policy_evaluation"), 1)
        self.assertEqual((result["evaluationStarted"], result["policyChecks"]), (True, 3))

    def test_no_evidence_until_azure_policy_reports_compliant(self):
        github = FakeGitHub(issues=[self.ISSUE])
        result = self.verify(github, FakeAzure(approved=1, compliant_after=99))
        self.assertIn("next run tries again", result["result"])
        self.assertEqual((result["evaluationStarted"], result["policyChecks"]), (True, 4))
        self.assertEqual(github.writes(), [])

    def test_verified_once_unless_reopened_and_only_trusted_markers_count(self):
        closed = dict(self.ISSUE, state="closed")
        github = FakeGitHub(issues=[closed], comments={7: [{"body": checks.VERIFIED, "author_association": "OWNER"}]})
        self.assertEqual(self.verify(github, FakeAzure(approved=1))["result"], "already verified")
        github = FakeGitHub(issues=[self.ISSUE], comments={7: [{"body": checks.VERIFIED, "author_association": "OWNER"}]})
        self.assertEqual(self.verify(github, FakeAzure(approved=1))["result"], "verified")
        github = FakeGitHub(issues=[closed], comments={7: [{"body": checks.VERIFIED, "author_association": "NONE"}]})
        self.assertEqual(self.verify(github, FakeAzure(approved=1))["result"], "verified")


class Caller(unittest.TestCase):
    """Only the Logic App posture-intake's managed identity may call intake."""

    TENANT, CLIENT, PRINCIPAL = "11111111-1111-1111-1111-111111111111", "client-id", "principal-id"

    @classmethod
    def setUpClass(cls):
        try:
            import jwt  # noqa: F401
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            raise unittest.SkipTest("PyJWT[crypto] is not installed")
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, **claims) -> str:
        import jwt
        now = int(time.time())
        payload = {"iss": f"https://sts.windows.net/{self.TENANT}/", "aud": auth.CALLER_AUDIENCE, "iat": now,
                   "exp": now + 600, "oid": self.PRINCIPAL, "appid": self.CLIENT, **claims}
        return "Bearer " + jwt.encode(payload, self.key, algorithm="RS256")

    def check(self, authorization):
        return auth.caller(authorization, self.TENANT, self.CLIENT, self.PRINCIPAL, signing_key=self.key.public_key())

    def test_the_logic_apps_identity_is_accepted(self):
        self.assertEqual(self.check(self.token())["oid"], self.PRINCIPAL)

    def test_anything_else_is_refused(self):
        for claims in ({"oid": "someone-else"}, {"appid": "another-app"}, {"aud": "https://management.azure.com/"},
                       {"iss": "https://sts.windows.net/22222222-2222-2222-2222-222222222222/"},
                       {"exp": int(time.time()) - 60}):
            with self.subTest(claims=claims), self.assertRaises(auth.Unauthorized):
                self.check(self.token(**claims))
        for header in (None, "", "Basic abc", "Bearer not-a-token"):
            with self.subTest(header=header), self.assertRaises(auth.Unauthorized):
                self.check(header)


class Messages(unittest.TestCase):
    def test_model_text_cannot_add_a_marker_and_is_capped(self):
        text = messages.model_text("ok <!-- posture:verified -->" + "x" * 50, 30)
        self.assertNotIn("<!--", text)
        self.assertLessEqual(len(text), 30)
        body = messages.pull_request_body({"summary": "<!-- posture:storage-private-link:rg -->", "risks": "r"}, 7, "a")
        self.assertEqual(body.count("<!--"), 1)  # only the automation's own posture:fix marker
        self.assertIn(messages.FIX_MARKER, body)

    def test_azure_times_with_seven_fractional_digits(self):
        self.assertEqual(messages.utc("2026-10-28T09:06:40.1234567Z"), "2026-10-28 09:06")
        self.assertEqual(messages.utc("2026-10-28T09:06:40Z"), "2026-10-28 09:06")

    def test_settings_name_every_missing_app_setting(self):
        with self.assertRaises(RuntimeError) as raised:
            Settings.from_environment({"GITHUB_REPOSITORY": REPOSITORY})
        self.assertIn("POSTURE_WHATIF_JOB_ID", str(raised.exception))
        self.assertEqual(SETTINGS.resource_group_name, "rg-ai-sdlc-secure")


if __name__ == "__main__":
    unittest.main()
