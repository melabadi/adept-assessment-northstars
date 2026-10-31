"""Tests for the posture Logic Apps (infra/logic/*.json): what decides whether they act on a pull request or a comment.

On a public repository anyone can open a pull request from a fork, name its branch like the remediation's, and comment.
These tests evaluate the expressions that decide, against GitHub API objects shaped like the real ones, with a small
evaluator for the few workflow-language functions they use. No Azure or GitHub access.

  python -m unittest test_logic_apps.py      (from this folder)
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

LOGIC = Path(__file__).resolve().parent / "infra" / "logic"
REPOSITORY = "octo/requesthub"
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
OUTSIDE = ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", None)


def definition(name: str) -> dict:
    template = json.loads((LOGIC / f"{name}.json").read_text(encoding="utf-8"))
    return next(r for r in template["resources"] if r["type"] == "Microsoft.Logic/workflows")["properties"]["definition"]


def actions(scope: dict, inside: tuple[str, ...] = ()) -> list[tuple[str, tuple[str, ...], dict]]:
    """Every action as (name, the actions it sits in, definition), through scopes, conditions, switches, and loops."""
    found = []
    for name, action in scope.items():
        found.append((name, inside, action))
        children = [action.get("actions"), (action.get("else") or {}).get("actions"),
                    (action.get("default") or {}).get("actions"),
                    *[case.get("actions") for case in (action.get("cases") or {}).values()]]
        for child in children:
            if child:
                found += actions(child, inside + (name,))
    return found


def find(workflow: dict, name: str) -> dict:
    return next(action for found, _, action in actions(workflow["actions"]) if found == name)


TOKEN = re.compile(r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<number>-?\d+)|(?P<name>[A-Za-z_]\w*)|(?P<punct>\?\[|[()\[\],]))")
FUNCTIONS = {
    "and": lambda *a: all(a), "or": lambda *a: any(a), "not": lambda a: not a, "equals": lambda a, b: a == b,
    "toLower": lambda a: str(a).lower(), "coalesce": lambda *a: next((x for x in a if x is not None), None),
    "contains": lambda collection, value: value in collection, "createArray": lambda *a: list(a),
    "startsWith": lambda a, b: str(a).lower().startswith(str(b).lower()),  # not case-sensitive, like Logic Apps
    "concat": lambda *a: "".join(str(x) for x in a), "string": str, "length": len, "greater": lambda a, b: a > b,
}


def evaluate(expression: str, **context) -> object:
    """Evaluate one '@...' expression. context: body={action: output}, parameters={}, variables={}, item=<object>."""
    assert expression.startswith("@") and not expression.startswith("@{"), expression
    text, tokens, position = expression[1:].strip(), [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            raise ValueError(f"cannot read {text[position:position + 20]!r}")
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        position = match.end()
    tokens.reverse()

    def take(expected: str | None = None) -> str:
        kind, value = tokens.pop()
        if expected is not None and value != expected:
            raise ValueError(f"expected {expected}, found {value}")
        return value

    def peek(value: str) -> bool:
        return bool(tokens) and tokens[-1][1] == value

    def value() -> object:
        kind, text = tokens[-1]
        take()
        if kind == "string":
            result = text[1:-1].replace("''", "'")
        elif kind == "number":
            result = int(text)
        elif kind == "name" and text in ("null", "true", "false") and not peek("("):
            result = {"null": None, "true": True, "false": False}[text]
        elif kind == "name":
            take("(")
            args = [] if peek(")") else [value()]
            while peek(","):
                take(",")
                args.append(value())
            take(")")
            if text in ("body", "parameters", "variables"):
                result = context[text][args[0]]
            elif text in ("item", "triggerBody"):
                result = context[text]
            else:
                result = FUNCTIONS[text](*args)
        else:
            raise ValueError(f"unexpected {text}")
        while peek("?[") or peek("["):
            safe = take() == "?["
            key = value()
            take("]")
            if result is None and not safe:
                raise KeyError(key)
            result = result.get(key) if isinstance(result, dict) else None
        return result

    result = value()
    if tokens:
        raise ValueError(f"left over: {tokens}")
    return result


def pull_request(head_repository: str | None = REPOSITORY, association: str | None = "OWNER", ref: str = "fix") -> dict:
    head = {"ref": ref, "sha": "a" * 40, "repo": {"full_name": head_repository} if head_repository else None}
    return {"number": 5, "state": "open", "head": head, "author_association": association}


class PreviewGate(unittest.TestCase):
    """posture-preview starts the what-if job, and writes commit statuses, only past this gate."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = definition("preview")
        cls.gate = find(cls.workflow, "Is_from_this_repository_and_a_trusted_author")

    def admits(self, pull: dict) -> bool:
        return evaluate(self.gate["expression"], body={"Get_pull_request": pull}, parameters={"repository": REPOSITORY})

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

    def test_everything_that_writes_to_github_or_calls_azure_sits_behind_the_gate(self):
        for name, inside, action in actions(self.workflow["actions"]):
            if action.get("type") == "Http" and name != "Get_pull_request":
                with self.subTest(name):
                    self.assertIn("Is_from_this_repository_and_a_trusted_author", inside)
        self.assertEqual(self.gate["runAfter"], {"Get_pull_request": ["Succeeded"]})
        self.assertEqual({a["type"] for a in self.gate["else"]["actions"].values()}, {"Compose"})

    def test_only_the_pull_request_number_is_taken_from_the_event(self):
        events = [name for name, _, action in actions(self.workflow["actions"]) if "triggerBody()" in json.dumps(action)]
        self.assertEqual(events, ["Pull_request_number"])


class PreviewTrigger(unittest.TestCase):
    """A fork's pull request events start no run at all. The payload is not signed, so this only saves runs; the gate
    inside reads the pull request again (PreviewGate)."""

    @classmethod
    def setUpClass(cls):
        trigger = definition("preview")["triggers"]["Pull_request_event"]
        cls.conditions = [condition["expression"] for condition in trigger["conditions"]]

    def fires(self, body: dict) -> bool:
        return all(evaluate(c, triggerBody=body, parameters={"repository": REPOSITORY}) for c in self.conditions)

    def test_the_intake_call_and_this_repositorys_pull_requests_start_a_run(self):
        self.assertIs(self.fires({"number": 5}), True)
        for association in TRUSTED:
            with self.subTest(association=association):
                self.assertIs(self.fires({"action": "synchronize", "pull_request": pull_request(association=association)}), True)

    def test_a_fork_or_an_outside_author_starts_no_run(self):
        for association in (*TRUSTED, *OUTSIDE):
            with self.subTest(association=association):
                self.assertIs(self.fires({"action": "opened", "pull_request": pull_request("someone/requesthub", association)}), False)
                self.assertIs(self.fires({"action": "opened", "pull_request": pull_request(None, association)}), False)
        for association in OUTSIDE:
            with self.subTest(association=association):
                self.assertIs(self.fires({"action": "opened", "pull_request": pull_request(association=association)}), False)


class IntakeExistingFix(unittest.TestCase):
    """posture-intake asks the agent for a fix unless an open pull request already is one. A fork can name its branch
    like the remediation's; it must not pass for the fix."""

    @classmethod
    def setUpClass(cls):
        cls.where = find(definition("intake"), "Fixes_for_this_issue")["inputs"]["where"]

    def is_fix(self, pull: dict) -> bool:
        return evaluate(self.where, item=pull, variables={"issueNumber": 12}, parameters={"repository": REPOSITORY})

    def test_the_remediation_branch_of_this_repository(self):
        self.assertIs(self.is_fix(pull_request(ref="posture/issue-12-10310112")), True)

    def test_a_fork_with_the_same_branch_name_is_not_the_fix(self):
        self.assertIs(self.is_fix(pull_request("someone/requesthub", "NONE", "posture/issue-12-10310112")), False)
        self.assertIs(self.is_fix(pull_request(None, "NONE", "posture/issue-12-10310112")), False)

    def test_another_issues_branch_is_not_the_fix(self):
        self.assertIs(self.is_fix(pull_request(ref="posture/issue-120-10310112")), False)


class MarkerComments(unittest.TestCase):
    """The Logic Apps post a marker comment once; a marker counts only from the owner, a member, or a collaborator (the
    Logic Apps' token is a person's), because anyone can comment on a public repository."""

    @classmethod
    def setUpClass(cls):
        cls.filters = {"posture:defender-confirmed": find(definition("intake"), "Confirmations")["inputs"]["where"],
                       "posture:verified": find(definition("verify"), "Verifications")["inputs"]["where"]}

    def counts(self, marker: str, association: str | None, body: str | None = None) -> bool:
        comment = {"body": body if body is not None else f"Evidence\n<!-- {marker} -->", "author_association": association}
        return evaluate(self.filters[marker], item=comment)

    def test_a_marker_from_the_repository_counts(self):
        for marker in self.filters:
            for association in TRUSTED:
                with self.subTest(marker=marker, association=association):
                    self.assertIs(self.counts(marker, association), True)

    def test_a_marker_from_anyone_else_does_not(self):
        for marker in self.filters:
            for association in OUTSIDE:
                with self.subTest(marker=marker, association=association):
                    self.assertIs(self.counts(marker, association), False)

    def test_a_comment_without_the_marker_does_not(self):
        for marker in self.filters:
            with self.subTest(marker=marker):
                self.assertIs(self.counts(marker, "OWNER", "Looks good"), False)


class Evaluator(unittest.TestCase):
    def test_safe_navigation_and_literals(self):
        self.assertIsNone(evaluate("@body('a')?['b']?['c']", body={"a": None}))
        self.assertEqual(evaluate("@coalesce(null, 'x')"), "x")
        self.assertIs(evaluate("@equals(item()?['n'], null)", item={}), True)
        self.assertEqual(evaluate("@concat('it''s ', string(1))"), "it's 1")
        with self.assertRaises(KeyError):
            evaluate("@body('a')['b']", body={"a": None})


if __name__ == "__main__":
    unittest.main()
