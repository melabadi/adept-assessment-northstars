"""Tests for the code-based evaluators in ../evaluators, run the way Foundry runs them: setup_foundry.py first fills in
the citable ids from inputs/. The fixture sample-brief.json is a brief the Foundry agent wrote; it passed all four gates.

    python -m unittest discover -s solutions/01-plan-microsoft/tests -v
"""
import copy
import json
import sys
import unittest
from pathlib import Path

SOLUTION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOLUTION))
import setup_foundry  # noqa: E402  (standard library only at import time)

GATES = ("structure", "citations", "testable_criteria", "injection_ignored")


def score(stem: str, brief: dict) -> float:
    namespace: dict = {}
    exec(setup_foundry.evaluator_code(SOLUTION / "evaluators" / f"{stem}.py", setup_foundry.source_ids()), namespace)
    return namespace["grade"]({}, {"response": json.dumps(brief)})


class EvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads((Path(__file__).parent / "sample-brief.json").read_text(encoding="utf-8"))

    def variant(self) -> dict:
        return copy.deepcopy(self.sample)

    def test_the_sample_brief_passes_every_gate(self):
        for stem in GATES:
            with self.subTest(gate=stem):
                self.assertEqual(score(stem, self.sample), 1.0)

    def test_an_uncited_requirement_fails_citations(self):
        brief = self.variant()
        brief["brief"]["requirements"][-1]["sources"] = []
        self.assertEqual(score("citations", brief), 0.0)

    def test_uncited_tasks_fail_citations(self):
        brief = self.variant()
        for task in brief["tasks"]:
            task["sources"] = []
        self.assertEqual(score("citations", brief), 0.0)

    def test_every_kind_of_item_must_cite(self):
        paths = [("brief", "problem"), ("brief", "goals", 0), ("brief", "requirements", 0), ("brief", "outOfScope", 0),
                 ("brief", "successMeasures", 0), ("epic",), ("tasks", 0), ("openQuestions", 0), ("conflicts", 0),
                 ("decisions", 0)]
        for path in paths:
            with self.subTest(item="/".join(map(str, path))):
                brief = self.variant()
                node = brief
                for key in path:
                    node = node[key]
                node["sources"] = []
                self.assertEqual(score("citations", brief), 0.0)

    def test_a_missing_sources_list_fails_citations(self):
        brief = self.variant()
        del brief["epic"]["sources"]
        self.assertEqual(score("citations", brief), 0.0)

    def test_an_invented_citation_lowers_the_score(self):
        brief = self.variant()
        brief["brief"]["requirements"][0]["sources"].append("T99")
        self.assertGreater(score("citations", brief), 0.0)
        self.assertLess(score("citations", brief), 1.0)


if __name__ == "__main__":
    unittest.main()
