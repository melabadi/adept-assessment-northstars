"""Tests for the Logic App's workflow (infra/reviewer-workflow.json): the properties the review's trust depends on.

No Azure: the tests read the workflow definition only.
Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft -p "test_reviewer*.py" -v
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

WORKFLOW = json.loads((Path(__file__).resolve().parent / "infra" / "reviewer-workflow.json").read_text(encoding="utf-8"))


def actions(scope: dict, inside: tuple[str, ...] = ()) -> list[tuple[str, tuple[str, ...], dict]]:
    """Every action as (name, the scopes it sits in, definition), through scopes, conditions, and loops."""
    found = []
    for name, action in scope.items():
        found.append((name, inside, action))
        for child in (action.get("actions"), (action.get("else") or {}).get("actions")):
            if child:
                found += actions(child, inside + (name,))
    return found


ALL = actions(WORKFLOW["actions"])
BY_NAME = {name: action for name, _, action in ALL}


def uri(action: dict) -> str:
    inputs = action.get("inputs")
    return str(inputs.get("uri", "")) if isinstance(inputs, dict) else ""


def strings(value: object, path: str = "") -> list[tuple[str, str]]:
    """Every string in a JSON value, with its path."""
    if isinstance(value, dict):
        return [s for key, child in value.items() for s in strings(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [s for i, child in enumerate(value) for s in strings(child, f"{path}[{i}]")]
    return [(path, value)] if isinstance(value, str) else []


class ResultsTravelAsFiles(unittest.TestCase):
    """A session cuts a command's output after 4 KB, so no result may be read from it."""

    def test_only_the_build_status_is_read_from_command_output(self):
        readers = [path for path, text in strings(WORKFLOW["actions"]) if "stdout" in text]
        self.assertEqual(readers, [".Run_the_review.actions.Build_and_test.actions.Run_wait_for_the_build.expression"])

    def test_results_are_downloaded_from_the_sessions(self):
        for compose, download, pool, name in [("Judge_output", "Judge_read_the_verdicts", "judgePool", "judge.json"),
                                              ("Run_results", "Run_get_the_results", "runPool", "summary.json"),
                                              ("Review", "Judge_read_the_review", "judgePool", "review.json")]:
            with self.subTest(compose):
                get = BY_NAME[download]["inputs"]
                self.assertEqual(get["method"], "GET")
                self.assertTrue(get["uri"].startswith(f"@{{parameters('{pool}')}}/files/{name}/content?"), get["uri"])
                self.assertIn(f"body('{download}')?['$content']", BY_NAME[compose]["inputs"])
                self.assertEqual(BY_NAME[compose]["runAfter"], {download: ["Succeeded"]})

    def test_the_sandbox_summary_is_bounded(self):
        self.assertRegex(BY_NAME["Run_results"]["inputs"], r"^@take\(base64ToString\(.*\), 20000\)$")


class TheJudgeRunsFirst(unittest.TestCase):
    def test_pull_request_code_runs_only_after_the_verdicts(self):
        self.assertIn("Rules", BY_NAME["Build_and_test"]["runAfter"])
        self.assertIn("Judge_output", BY_NAME["Rules"]["runAfter"])

    def test_commands_run_in_the_run_pool_only_inside_build_and_test(self):
        for name, inside, action in ALL:
            if "parameters('runPool')" in uri(action) and "/executions?" in uri(action):
                with self.subTest(name):
                    self.assertIn("Build_and_test", inside)

    def test_the_judge_runs_only_the_checker_and_the_formatter(self):
        commands = [action["inputs"]["body"]["shellCommand"] for _, _, action in ALL
                    if "parameters('judgePool')" in uri(action) and "/executions?" in uri(action)]
        self.assertEqual(len(commands), 2)
        for command in commands:
            with self.subTest(command):
                self.assertRegex(command, r"^cd /mnt/data && python3 (review_rules|format_review)\.py ")


class GitHubAccess(unittest.TestCase):
    def test_reviews_are_comments_only(self):
        posts = [(name, action) for name, _, action in ALL
                 if action.get("type") == "Http" and re.search(r"/reviews$", uri(action))]
        self.assertEqual(sorted(name for name, _ in posts), ["Post_a_failure_note", "Post_the_review"])
        for name, action in posts:
            with self.subTest(name):
                self.assertEqual(action["inputs"]["body"]["event"], "COMMENT")

    def test_every_action_that_sends_the_token_hides_its_inputs(self):
        senders = [(name, action) for name, _, action in ALL if "githubToken" in json.dumps(action.get("inputs"))]
        self.assertGreater(len(senders), 3)
        for name, action in senders:
            with self.subTest(name):
                self.assertIn("inputs", action.get("runtimeConfiguration", {}).get("secureData", {}).get("properties", []))

    def test_the_token_never_reaches_a_session(self):
        for name, _, action in ALL:
            if "dynamicsessions.io" in json.dumps(action.get("inputs")):
                with self.subTest(name):
                    self.assertNotIn("githubToken", json.dumps(action["inputs"]))


def used(action: dict) -> set[str]:
    """The actions whose data this action's inputs use."""
    return set(re.findall(r"(?:body|outputs|actions)\('([A-Za-z0-9_]+)'\)", json.dumps(action.get("inputs"))))


class RunHistory(unittest.TestCase):
    def test_the_result_is_visible_in_the_run_history(self):
        # Logic Apps hides the inputs of an action that uses data from an action with secure inputs or outputs, and a
        # Compose's output is its input. eval_reviewer.py reads Result, so Result must use none of that data. To be
        # safe, data from a hidden Compose counts as hidden too.
        hidden = {name for name, _, action in ALL if action.get("runtimeConfiguration", {}).get("secureData")}
        while True:
            more = {name for name, _, action in ALL if action.get("type") == "Compose" and used(action) & hidden} - hidden
            if not more:
                break
            hidden |= more
        self.assertIn("Merge_base", hidden)  # hidden in every run: it uses the merge-base call, which sends the token
        self.assertNotIn("Result", hidden, sorted(used(BY_NAME["Result"]) & hidden))
        for field in ("rules", "review", "agent", "sandbox"):
            self.assertIn(field, BY_NAME["Result"]["inputs"])


if __name__ == "__main__":
    unittest.main()
