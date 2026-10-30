"""Tests for configure_github.py: which webhook it creates, updates, or deletes, and that it never prints the trigger URL.

The GitHub CLI, the Azure CLI, azd, and the token check are replaced by fakes, so the tests touch no repository and no
Azure resource. Run from the repository root:
  python -m unittest discover -s solutions/03-develop-microsoft -p "test_configure*.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configure_github  # noqa: E402

REPO = "octo/requesthub"
OURS = "https://prod-01.eastus2.logic.azure.com:443/workflows/abc123/triggers/When_a_pull_request_event_arrives/paths/invoke?api-version=2016-10-01&sp=%2Ftriggers&sv=1.0&sig=NEWSIG"
OURS_OLD_SIG = OURS.replace("NEWSIG", "OLDSIG").replace(":443", "")
OTHER_SOLUTION = "https://prod-02.centralus.logic.azure.com:443/workflows/def456/triggers/Pull_request_event/paths/invoke?sig=X"
VALUES = {"GITHUB_REPOSITORY": REPO, "AZURE_RESOURCE_GROUP": "rg-test", "AZURE_SUBSCRIPTION_ID": "sub",
          "REVIEWER_LOGIC_APP": "logic-pr-reviewer", "REVIEW_LABEL": "review:azure"}


class FakeTools:
    """Answers the commands configure_github runs, and records them."""

    def __init__(self, hooks: list[dict]):
        self.hooks = hooks
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def run(self, *args: str, stdin: str | None = None) -> str:
        self.calls.append((args, stdin))
        if args[1:3] == ("rest", "--method"):
            return OURS
        if args[:2] == ("gh", "label"):
            return ""
        if args[:2] == ("gh", "api") and args[2].endswith("/hooks?per_page=100"):
            return json.dumps(self.hooks)
        if args[:4] == ("gh", "api", "-X", "POST"):
            return json.dumps({"id": 99, "config": json.loads(stdin)["config"]})
        return "{}"

    def writes(self) -> list[tuple[str, str]]:
        return [(a[3], a[4]) for a, _ in self.calls if a[:3] == ("gh", "api", "-X")]


def hook(hook_id: int, url: str, events: list[str] | None = None, active: bool = True) -> dict:
    return {"id": hook_id, "active": active, "events": events or ["pull_request"], "config": {"url": url, "content_type": "json"}}


def publish(hooks: list[dict], token: str | None) -> tuple[FakeTools, str]:
    tools = FakeTools(hooks)
    values = dict(VALUES, **({"GITHUB_REVIEW_TOKEN": token} if token else {}))
    out = io.StringIO()
    with mock.patch.object(configure_github, "run", tools.run), \
            mock.patch.object(configure_github, "azd_values", lambda: values), \
            mock.patch.object(configure_github, "check_token", lambda repo, tok: "2026-12-01 00:00:00 UTC"), \
            mock.patch.dict(os.environ, {}, clear=False), contextlib.redirect_stdout(out):
        os.environ.pop("GITHUB_REVIEW_TOKEN", None)
        configure_github.publish()
    return tools, out.getvalue()


class SameEndpointTests(unittest.TestCase):
    def test_the_signature_and_the_port_notation_dont_matter(self):
        self.assertTrue(configure_github.same_endpoint(OURS, OURS_OLD_SIG))

    def test_another_logic_app_or_trigger_is_not_ours(self):
        self.assertFalse(configure_github.same_endpoint(OTHER_SOLUTION, OURS))
        self.assertFalse(configure_github.same_endpoint(OURS.replace("abc123", "abc124"), OURS))
        self.assertFalse(configure_github.same_endpoint("", OURS))


class PublishTests(unittest.TestCase):
    def test_without_a_token_no_webhook_is_created(self):
        tools, out = publish([hook(5, OTHER_SOLUTION)], token=None)
        self.assertEqual(tools.writes(), [])
        self.assertIn("not created", out)

    def test_without_a_token_our_webhook_is_deleted_and_no_other(self):
        tools, out = publish([hook(5, OTHER_SOLUTION), hook(7, OURS_OLD_SIG)], token=None)
        self.assertEqual(tools.writes(), [("DELETE", f"repos/{REPO}/hooks/7")])
        self.assertIn("deleted", out)

    def test_with_a_token_the_webhook_is_created_for_pull_requests_only(self):
        tools, out = publish([hook(5, OTHER_SOLUTION)], token="t")
        self.assertEqual(tools.writes(), [("POST", f"repos/{REPO}/hooks")])
        body = json.loads(next(stdin for args, stdin in tools.calls if args[:4] == ("gh", "api", "-X", "POST")))
        self.assertEqual(body["events"], ["pull_request"])
        self.assertEqual(body["config"]["url"], OURS)
        self.assertIn("(created)", out)

    def test_the_url_is_passed_on_stdin_only(self):
        tools, _ = publish([hook(7, OURS_OLD_SIG)], token="t")
        for args, _stdin in tools.calls:
            self.assertFalse(any("sig=" in a for a in args), args)

    def test_a_changed_signature_updates_the_webhook(self):
        tools, out = publish([hook(5, OTHER_SOLUTION), hook(7, OURS_OLD_SIG)], token="t")
        self.assertEqual(tools.writes(), [("PATCH", f"repos/{REPO}/hooks/7")])
        self.assertIn("(updated)", out)

    def test_extra_events_are_removed(self):
        tools, _ = publish([hook(7, OURS, events=["pull_request", "push"])], token="t")
        self.assertEqual(tools.writes(), [("PATCH", f"repos/{REPO}/hooks/7")])

    def test_a_matching_webhook_is_left_alone(self):
        tools, out = publish([hook(7, OURS)], token="t")
        self.assertEqual(tools.writes(), [])
        self.assertIn("(unchanged)", out)

    def test_duplicates_are_deleted(self):
        tools, _ = publish([hook(7, OURS), hook(8, OURS_OLD_SIG)], token="t")
        self.assertEqual(tools.writes(), [("DELETE", f"repos/{REPO}/hooks/8")])

    def test_nothing_printed_carries_the_url(self):
        for hooks, token in (([], "t"), ([hook(7, OURS_OLD_SIG)], "t"), ([hook(7, OURS)], None)):
            _, out = publish(hooks, token)
            self.assertNotIn("https://", out)
            self.assertNotIn("sig=", out)

    def test_the_label_is_created_or_updated_every_time(self):
        tools, _ = publish([], token=None)
        label = [args for args, _ in tools.calls if args[:3] == ("gh", "label", "create")]
        self.assertEqual(len(label), 1)
        self.assertIn("--force", label[0])


class RemoveTests(unittest.TestCase):
    def test_only_our_webhook_is_deleted(self):
        tools = FakeTools([hook(5, OTHER_SOLUTION), hook(7, OURS_OLD_SIG)])
        out = io.StringIO()
        with mock.patch.object(configure_github, "run", tools.run), \
                mock.patch.object(configure_github, "azd_values", lambda: dict(VALUES)), contextlib.redirect_stdout(out):
            configure_github.remove()
        self.assertEqual(tools.writes(), [("DELETE", f"repos/{REPO}/hooks/7")])
        self.assertNotIn("sig=", out.getvalue())


class RunTests(unittest.TestCase):
    def test_a_failing_command_never_echoes_a_url(self):
        with self.assertRaises(SystemExit) as raised:
            configure_github.run(sys.executable, "-c", f"import sys; sys.stderr.write('failed for {OURS}'); sys.exit(1)")
        self.assertNotIn("sig=", str(raised.exception))
        self.assertIn("<url>", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
