"""Tests for the backlog publisher's trust boundary: which Issues it treats as its own.

The publisher finds the epic and the tasks it published before by a hidden marker in their body, then updates,
reopens, closes, and links them. Anyone can open an Issue with the `phase:plan` label (this solution's issue form
applies it) and put the same marker in its body, so an Issue counts as the publisher's only when the publisher could
have written it:

- one that the workflow published with its GITHUB_TOKEN, as `github-actions[bot]`, is adopted;
- one that the repository's owner, a member, or a collaborator opened, as a local run does, is adopted;
- one that anyone else opened is ignored: a publish or a reset never updates, reopens, closes, or links it.

They run offline in about a second, against a fake `gh` and synthetic Issues. Where a whole publish runs, the backlog
validator is stubbed: it has its own checks, and these tests are about which Issues the publisher writes to. The live
demo evidence comes from real runs, never from these tests.

Run from the repository root:
  python -m unittest discover -s solutions/01-plan-github/tests -v
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SOLUTION = Path(__file__).resolve().parents[1]
PUBLISHER = SOLUTION / ".github" / "skills" / "backlog-publish" / "publish_backlog.py"
INPUTS = SOLUTION / "inputs"

_spec = importlib.util.spec_from_file_location("publish_backlog", PUBLISHER)
publish_backlog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish_backlog)

REPO = "contoso/plan-demo"
SCENARIO = "assisted-triage-brief"
# Who opened a synthetic Issue: its user, as GitHub returns it, and the author_association GitHub computes for it.
WORKFLOW = {"login": "github-actions[bot]", "type": "Bot", "association": "NONE"}
OWNER = {"login": "plan-owner", "type": "User", "association": "OWNER"}
OUTSIDER = {"login": "outside-reporter", "type": "User", "association": "NONE"}

CRITERION = "Given a new request, When the assistant suggests a route, Then a reviewer confirms it."
BACKLOG = {
    "scenario": SCENARIO,
    "epic": {"id": "EPIC-1", "title": "Synthetic epic", "summary": "Synthetic summary.",
             "acceptanceCriteria": [CRITERION], "sources": ["T03"]},
    "conflicts": [],
    "openQuestions": [],
    "tasks": [{"id": "TASK-1", "title": "Synthetic task", "description": "Synthetic description.",
               "ownerRole": "Backend engineer", "dependsOn": [], "acceptanceCriteria": [CRITERION],
               "sources": ["T03"]}],
}


def marked_issue(number: int, item_id: str, author: dict, state: str = "open") -> dict:
    """A synthetic Issue as GitHub lists it, with the publisher's hidden marker for item_id in its body."""
    return {
        "number": number, "id": 9000 + number, "node_id": f"I_synthetic{number}", "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}", "title": f"Synthetic Issue {number}",
        "body": f"<!-- ai-sdlc-backlog: {SCENARIO}/github/{item_id} -->\nSynthetic text.",
        "labels": [{"name": "phase:plan"}],
        "user": {"login": author["login"], "type": author["type"]},
        "author_association": author["association"],
    }


class FakeGitHub:
    """Stands in for publish_backlog.gh. Lists the seeded Issues newest first, as GitHub does, creates Issues as the
    workflow would, from number 100 up, and records every call with its body."""

    def __init__(self, *issues: dict):
        self.issues = list(issues)
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, path, method="GET", body=None, paginate=False, ok404=False):
        route = path.split("?")[0].removeprefix(f"repos/{REPO}/")
        self.calls.append((method, route, body))
        if (method, route) == ("GET", "labels"):
            return [{"name": name} for name in publish_backlog.LABELS]
        if (method, route) == ("GET", "issues"):
            return list(self.issues)
        if (method, route) == ("POST", "issues"):
            number = 100 + sum(1 for issue in self.issues if issue["number"] >= 100)
            created = {**marked_issue(number, "", WORKFLOW), "title": body["title"], "body": body["body"],
                       "labels": [{"name": name} for name in body["labels"]]}
            self.issues.insert(0, created)
            return created
        if method == "PATCH" and re.fullmatch(r"issues/\d+", route):
            issue = next(i for i in self.issues if i["number"] == int(route.split("/")[1]))
            issue.update({key: value for key, value in body.items() if key != "labels"})
            if "labels" in body:
                issue["labels"] = [{"name": name} for name in body["labels"]]
            return issue
        if re.fullmatch(r"issues/\d+/(sub_issues|dependencies/blocked_by)", route):
            return [] if method == "GET" else {}
        raise AssertionError(f"unexpected gh call: {method} {path}")

    def writes_about(self, issue: dict) -> list[tuple[str, str, dict | None]]:
        """Every write to the Issue, or that names it in its body (a sub-issue or a "blocked by" link)."""
        return [call for call in self.calls if call[0] != "GET" and (
            re.fullmatch(rf"issues/{issue['number']}(/.*)?", call[1])
            or issue["id"] in (call[2] or {}).values())]


def find(*issues: dict) -> tuple[dict[str, int], str]:
    """The publisher's own Issues among the seeded ones, by backlog id, and what it printed on stderr."""
    fake, err = FakeGitHub(*issues), io.StringIO()
    with mock.patch.object(publish_backlog, "gh", fake), redirect_stderr(err):
        found = publish_backlog.existing_issues(REPO, SCENARIO, "github")
    return {item_id: issue["number"] for item_id, issue in found.items()}, err.getvalue()


def run(fake: FakeGitHub, *args: str) -> tuple[int, str, str]:
    """Runs the publisher's command line against the fake, with the synthetic backlog and the real inputs."""
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as folder:
        backlog = Path(folder) / "backlog.json"
        backlog.write_text(json.dumps(BACKLOG), encoding="utf-8")
        inputs = (INPUTS / "stakeholder-transcript.md", INPUTS / "routing-policies.md")
        with mock.patch.object(publish_backlog, "gh", fake), \
                mock.patch.object(publish_backlog.validate_backlog, "find_inputs", return_value=inputs), \
                mock.patch.object(publish_backlog.validate_backlog, "validate", return_value=[]), \
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
                redirect_stdout(out), redirect_stderr(err):
            code = publish_backlog.main([*args, "--backlog", str(backlog), "--track", "github", "--repo", REPO])
    return code, out.getvalue(), err.getvalue()


class ExistingIssuesTests(unittest.TestCase):
    def test_an_outsiders_issue_with_the_marker_is_ignored(self):
        found, note = find(marked_issue(7, "EPIC-1", OUTSIDER))
        self.assertEqual(found, {})
        self.assertIn("#7", note)
        self.assertNotIn(OUTSIDER["login"], note)

    def test_an_issue_the_workflow_published_is_adopted(self):
        found, note = find(marked_issue(12, "EPIC-1", WORKFLOW, state="closed"))
        self.assertEqual(found, {"EPIC-1": 12})
        self.assertEqual(note, "")

    def test_an_issue_from_the_owner_a_member_or_a_collaborator_is_adopted(self):
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                found, note = find(marked_issue(13, "TASK-1", {**OWNER, "association": association}))
                self.assertEqual(found, {"TASK-1": 13})
                self.assertEqual(note, "")

    def test_other_authors_are_ignored(self):
        authors = {
            "another app's bot": {"login": "other-app[bot]", "type": "Bot", "association": "NONE"},
            "the workflow's login on an account that is not a bot": {**WORKFLOW, "type": "User"},
            "a past contributor": {"login": "past-contributor", "type": "User", "association": "CONTRIBUTOR"},
            "a first-time contributor": {"login": "new-contributor", "type": "User",
                                         "association": "FIRST_TIME_CONTRIBUTOR"},
        }
        for name, author in authors.items():
            with self.subTest(author=name):
                found, _ = find(marked_issue(8, "TASK-1", author))
                self.assertEqual(found, {})

    def test_the_publishers_issue_wins_over_an_outsiders_older_issue_with_the_same_marker(self):
        found, _ = find(marked_issue(20, "EPIC-1", WORKFLOW), marked_issue(5, "EPIC-1", OUTSIDER))
        self.assertEqual(found, {"EPIC-1": 20})


class PublishAndResetTests(unittest.TestCase):
    def test_a_publish_creates_its_own_epic_and_never_writes_to_an_outsiders_issue(self):
        outsider = marked_issue(7, "EPIC-1", OUTSIDER)
        fake = FakeGitHub(outsider)
        code, out, err = run(fake, "--json")
        self.assertEqual(code, 0)
        epic = next(r for r in json.loads(out)["results"] if r["id"] == "EPIC-1")
        self.assertEqual(epic["action"], "created")
        self.assertNotEqual(epic["number"], 7)
        self.assertEqual(fake.writes_about(outsider), [])
        self.assertIn("#7", err)

    def test_a_publish_updates_the_issues_it_published_before_without_duplicating_them(self):
        for author in (WORKFLOW, OWNER):
            with self.subTest(author=author["login"]):
                fake = FakeGitHub(marked_issue(13, "TASK-1", author, state="closed"),
                                  marked_issue(12, "EPIC-1", author, state="closed"))
                code, out, err = run(fake, "--json")
                self.assertEqual(code, 0)
                results = {r["id"]: (r["number"], r["action"]) for r in json.loads(out)["results"]}
                self.assertEqual(results, {"EPIC-1": (12, "updated"), "TASK-1": (13, "updated")})
                self.assertNotIn(("POST", "issues"), [call[:2] for call in fake.calls])
                self.assertEqual(err, "")

    def test_a_reset_never_closes_an_outsiders_issue(self):
        outsider = marked_issue(7, "EPIC-1", OUTSIDER)
        fake = FakeGitHub(marked_issue(13, "TASK-1", WORKFLOW), outsider)
        code, out, _ = run(fake, "--close")
        self.assertEqual(code, 0)
        self.assertIn("closed 1 issue(s)", out)
        self.assertEqual(fake.writes_about(outsider), [])
        self.assertIn(("PATCH", "issues/13"), [call[:2] for call in fake.calls])


if __name__ == "__main__":
    unittest.main()
