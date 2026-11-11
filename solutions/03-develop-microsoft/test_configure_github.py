"""Tests for configure_github.py: which webhook it creates, updates, or deletes, and that the webhook secret never appears
on a command line or in its output.

The GitHub CLI, azd, and the token check are replaced by fakes, so the tests touch no repository and no Azure resource.
Run from the repository root:
  python -m unittest discover -s solutions/03-develop-microsoft -p "test_configure*.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configure_github  # noqa: E402

REPO = "octo/requesthub"
HOST = "func-abc123.azurewebsites.net"
OURS = f"https://{HOST}/api/github/webhook"
OURS_WITH_PORT = f"https://{HOST}:443/api/github/webhook"
OTHER_FUNCTION = "https://func-def456.azurewebsites.net/api/github/webhook"
OTHER_ROUTE = f"https://{HOST}/api/other"
LOGIC_APP = "https://prod-02.centralus.logic.azure.com:443/workflows/def456/triggers/Pull_request_event/paths/invoke?sig=X"
SECRET = "f00d" * 16
VALUES = {"GITHUB_REPOSITORY": REPO, "AZURE_RESOURCE_GROUP": "rg-test", "REVIEWER_FUNCTION_HOST": HOST,
          "REVIEW_LABEL": "review:azure"}


class FakeTools:
    """Answers the commands configure_github runs, and records them."""

    def __init__(self, hooks: list[dict]):
        self.hooks = hooks
        self.calls: list[tuple[tuple[str, ...], str | None]] = []
        self.env_files: list[str] = []

    def run(self, *args: str, stdin: str | None = None) -> str:
        self.calls.append((args, stdin))
        if args[:4] == ("azd", "env", "set", "--file"):
            self.env_files.append(Path(args[4]).read_text(encoding="utf-8"))
            return ""
        if args[:2] in (("gh", "label"), ("azd", "env")):
            return ""
        if args[:2] == ("gh", "api") and args[2].endswith("/hooks?per_page=100"):
            return json.dumps(self.hooks)
        if args[:4] == ("gh", "api", "-X", "POST"):
            return json.dumps({"id": 99, "config": json.loads(stdin)["config"]})
        return "{}"

    def writes(self) -> list[tuple[str, str]]:
        return [(a[3], a[4]) for a, _ in self.calls if a[:3] == ("gh", "api", "-X")]

    def body(self, method: str) -> dict:
        return json.loads(next(stdin for args, stdin in self.calls if args[:4] == ("gh", "api", "-X", method)))


def hook(hook_id: int, url: str, events: list[str] | None = None) -> dict:
    return {"id": hook_id, "active": True, "events": events or ["pull_request"],
            "config": {"url": url, "content_type": "json", "secret": "********"}}


def publish(hooks: list[dict], token: str | None, secret: str | None = SECRET) -> tuple[FakeTools, str]:
    tools = FakeTools(hooks)
    values = dict(VALUES, **({"GITHUB_REVIEW_TOKEN": token} if token else {}), **({"GITHUB_WEBHOOK_SECRET": secret} if secret else {}))
    out = io.StringIO()
    with mock.patch.object(configure_github, "run", tools.run), \
            mock.patch.object(configure_github, "azd_values", lambda: values), \
            mock.patch.object(configure_github, "check_token", lambda repo, tok: "2026-12-01 00:00:00 UTC"), \
            mock.patch.object(configure_github, "check_function", lambda url: None), \
            mock.patch.dict(os.environ, {}, clear=False), contextlib.redirect_stdout(out):
        os.environ.pop("GITHUB_REVIEW_TOKEN", None)
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
        configure_github.publish()
    return tools, out.getvalue()


def prepare(values: dict) -> tuple[FakeTools, str]:
    tools = FakeTools([])
    out = io.StringIO()
    with mock.patch.object(configure_github, "run", tools.run), \
            mock.patch.object(configure_github, "azd_values", lambda: values), contextlib.redirect_stdout(out):
        configure_github.prepare()
    return tools, out.getvalue()


class SameEndpointTests(unittest.TestCase):
    def test_the_port_notation_doesnt_matter(self):
        self.assertTrue(configure_github.same_endpoint(OURS, OURS_WITH_PORT))

    def test_another_function_route_or_solution_is_not_ours(self):
        for url in (OTHER_FUNCTION, OTHER_ROUTE, LOGIC_APP, ""):
            self.assertFalse(configure_github.same_endpoint(url, OURS), url)


class PrepareTests(unittest.TestCase):
    def test_a_missing_secret_is_generated_through_a_file_never_a_command_line(self):
        tools, out = prepare({"GITHUB_REPOSITORY": REPO})
        self.assertEqual(len(tools.env_files), 1)
        name, value = tools.env_files[0].strip().split("=", 1)
        self.assertEqual(name, "GITHUB_WEBHOOK_SECRET")
        self.assertRegex(value, r"^[0-9a-f]{64}$")
        for args, stdin in tools.calls:
            self.assertFalse(any(value in a for a in args), args)
        self.assertNotIn(value, out)
        env_file = next(args[4] for args, _ in tools.calls if args[:4] == ("azd", "env", "set", "--file"))
        self.assertFalse(Path(env_file).exists(), "the temporary file is deleted")

    def test_an_existing_secret_is_kept(self):
        tools, out = prepare({"GITHUB_REPOSITORY": REPO, "GITHUB_WEBHOOK_SECRET": SECRET})
        self.assertEqual(tools.env_files, [])
        self.assertIn("already set", out)


class PublishTests(unittest.TestCase):
    def test_without_a_token_no_webhook_is_created(self):
        tools, out = publish([hook(5, OTHER_FUNCTION)], token=None)
        self.assertEqual(tools.writes(), [])
        self.assertIn("not created", out)

    def test_without_a_token_our_webhook_is_deleted_and_no_other(self):
        tools, out = publish([hook(5, OTHER_FUNCTION), hook(6, LOGIC_APP), hook(7, OURS_WITH_PORT)], token=None)
        self.assertEqual(tools.writes(), [("DELETE", f"repos/{REPO}/hooks/7")])
        self.assertIn("deleted", out)

    def test_without_a_secret_no_webhook_is_created(self):
        tools, out = publish([], token="t", secret=None)
        self.assertEqual(tools.writes(), [])
        self.assertIn("GITHUB_WEBHOOK_SECRET is not set", out)

    def test_with_a_token_the_webhook_is_created_for_signed_pull_request_events_only(self):
        tools, out = publish([hook(5, OTHER_FUNCTION)], token="t")
        self.assertEqual(tools.writes(), [("POST", f"repos/{REPO}/hooks")])
        body = tools.body("POST")
        self.assertEqual(body["events"], ["pull_request"])
        self.assertEqual(body["config"], {"url": OURS, "content_type": "json", "insecure_ssl": "0", "secret": SECRET})
        self.assertIn("(created)", out)

    def test_an_existing_webhook_is_updated_with_the_secret(self):
        tools, out = publish([hook(5, OTHER_FUNCTION), hook(7, OURS, events=["pull_request", "push"])], token="t")
        self.assertEqual(tools.writes(), [("PATCH", f"repos/{REPO}/hooks/7")])
        body = tools.body("PATCH")
        self.assertEqual((body["events"], body["config"]["secret"]), (["pull_request"], SECRET))
        self.assertIn("(updated)", out)

    def test_duplicates_are_deleted(self):
        tools, _ = publish([hook(7, OURS), hook(8, OURS_WITH_PORT)], token="t")
        self.assertEqual(tools.writes(), [("PATCH", f"repos/{REPO}/hooks/7"), ("DELETE", f"repos/{REPO}/hooks/8")])

    def test_the_secret_goes_on_stdin_only_and_is_never_printed(self):
        for hooks in ([], [hook(7, OURS)]):
            tools, out = publish(hooks, token="t")
            for args, _stdin in tools.calls:
                self.assertFalse(any(SECRET in a for a in args), args)
            self.assertNotIn(SECRET, out)
            self.assertNotIn("https://", out)

    def test_the_label_is_created_or_updated_every_time(self):
        tools, _ = publish([], token=None)
        label = [args for args, _ in tools.calls if args[:3] == ("gh", "label", "create")]
        self.assertEqual(len(label), 1)
        self.assertIn("--force", label[0])


class CheckFunctionTests(unittest.TestCase):
    """Before connecting GitHub, the Function must be live and must refuse an unsigned delivery."""

    def answers(self, *codes: int) -> tuple[list[str], str]:
        urls, out = [], io.StringIO()

        def urlopen(request, timeout):
            urls.append(request.full_url)
            self.assertNotIn("X-hub-signature-256", request.headers)
            code = codes[min(len(urls), len(codes)) - 1]
            if code >= 300:
                raise urllib.error.HTTPError(request.full_url, code, "error", {}, None)
            return contextlib.nullcontext(mock.Mock(status=code))

        with mock.patch.object(configure_github.urllib.request, "urlopen", urlopen), \
                mock.patch.object(configure_github.time, "sleep", lambda s: None), contextlib.redirect_stdout(out):
            configure_github.check_function(OURS, attempts=5)
        return urls, out.getvalue()

    def test_it_waits_until_the_function_refuses_an_unsigned_delivery(self):
        urls, out = self.answers(404, 404, 401)
        self.assertEqual(urls, [OURS] * 3)
        self.assertIn("refuses unsigned deliveries", out)

    def test_it_waits_while_the_function_cant_read_its_webhook_secret_yet(self):
        # Right after the first deployment, the Function's role on Key Vault can take minutes to apply; until then it
        # answers 503. A 401 shows it read the secret: it refuses an unsigned delivery only once it has one.
        urls, out = self.answers(503, 503, 401)
        self.assertEqual(len(urls), 3)
        self.assertIn("refuses unsigned deliveries", out)

    def test_a_function_that_accepts_an_unsigned_delivery_stops_the_hook(self):
        with self.assertRaises(SystemExit) as raised:
            self.answers(200)
        self.assertIn("accepted an unsigned delivery", str(raised.exception))

    def test_a_function_that_never_answers_only_warns(self):
        urls, out = self.answers(404)
        self.assertEqual(len(urls), 5)
        self.assertIn("isn't ready yet", out)
        self.assertIn("Key Vault", out)


class RemoveTests(unittest.TestCase):
    def test_only_our_webhook_is_deleted(self):
        tools = FakeTools([hook(5, OTHER_FUNCTION), hook(6, LOGIC_APP), hook(7, OURS_WITH_PORT)])
        out = io.StringIO()
        with mock.patch.object(configure_github, "run", tools.run), \
                mock.patch.object(configure_github, "azd_values", lambda: dict(VALUES)), contextlib.redirect_stdout(out):
            configure_github.remove()
        self.assertEqual(tools.writes(), [("DELETE", f"repos/{REPO}/hooks/7")])
        self.assertNotIn("https://", out.getvalue())


class RunTests(unittest.TestCase):
    def test_a_failing_command_never_echoes_a_url(self):
        with self.assertRaises(SystemExit) as raised:
            configure_github.run(sys.executable, "-c", f"import sys; sys.stderr.write('failed for {OURS}'); sys.exit(1)")
        self.assertNotIn(HOST, str(raised.exception))
        self.assertIn("<url>", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
