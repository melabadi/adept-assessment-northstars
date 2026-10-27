"""Offline tests for the deterministic parts of the Design · Microsoft solution. No Azure access is needed.

They check that the standards parse into index documents, that the evaluation labels agree with what each profile may
retrieve, and that the advisor's gates reject invented, out-of-scope, misversioned, or misquoted citations. The model
answers below are hand-written fixtures; the live demo never uses them.

Run from the repository root:
  python -m unittest discover -s solutions/02-design-microsoft -p "test_*.py" -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import advisor  # noqa: E402
import eval_advisor  # noqa: E402
import ingest_standards  # noqa: E402

DOCS, SKIPPED = ingest_standards.load_standards()
BY_ID = {doc["id"]: doc for doc in DOCS}


def visible(profile: str) -> set[str]:
    return {doc["id"] for doc in DOCS if doc["scope"] in ingest_standards.SPEC["profiles"][profile]}


def offline_advisor() -> advisor.Advisor:
    """An Advisor whose index lookups come from the standards folder instead of Azure AI Search."""
    client = object.__new__(advisor.Advisor)
    client._standards = {None: {d["id"]: {"version": d["version"], "text": f"{d['title']}\n{d['content']}"} for d in DOCS}}
    for profile in ingest_standards.SPEC["profiles"]:
        client._standards[profile] = {k: v for k, v in client._standards[None].items() if k in visible(profile)}
    return client


def answer(**overrides) -> dict:
    data = {
        "answerable": True,
        "summary": "Extend the API behind ITriageProvider.",
        "recommendation": "Implement the provider in the existing API.",
        "options": [{"name": "In-process", "description": "", "pros": [], "cons": [], "standards": ["STD-ARCH-001"]}],
        "constraints": [{
            "standardId": "STD-ARCH-001", "version": "1.0", "requirement": "Extend before adding a service.",
            "excerpt": "Prefer extending an existing service behind a stable interface over introducing a new deployable component.",
        }],
        "conflicts": [],
        "unknowns": [],
    }
    data.update(overrides)
    return data


class StandardsTests(unittest.TestCase):
    def test_every_standard_is_indexed_once_with_a_stable_id(self):
        self.assertEqual(len(DOCS), 12)
        self.assertEqual(SKIPPED, [])
        self.assertEqual(len(BY_ID), len(DOCS))
        for doc in DOCS:
            self.assertEqual(doc["url"], f"solutions/02-design-microsoft/standards/{doc['id']}.md")
            self.assertIn(f"(v{doc['version']})", doc["title"])

    def test_profiles_see_their_own_standards_only(self):
        self.assertIn("STD-OPS-001", visible("small-team"))
        self.assertNotIn("STD-OPS-002", visible("small-team"))
        self.assertIn("STD-OPS-002", visible("enterprise"))
        self.assertNotIn("STD-DATA-002", visible("enterprise"))
        self.assertEqual(ingest_standards.scope_filter("small-team"), "scope eq 'all' or scope eq 'small-team'")

    def test_content_hash_is_stable(self):
        again, _ = ingest_standards.load_standards()
        self.assertEqual([d["contentHash"] for d in again], [d["contentHash"] for d in DOCS])


class EvaluationCaseTests(unittest.TestCase):
    """The labels must be answerable from what each profile can retrieve, or the evaluation measures nothing."""

    cases = [json.loads(line) for line in eval_advisor.CASES.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_ten_cases_with_unique_ids(self):
        self.assertEqual(len(self.cases), 10)
        self.assertEqual(len({c["id"] for c in self.cases}), 10)

    def test_labels_match_the_profile_scopes(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                seen = visible(case["profile"])
                self.assertTrue(set(case["expectStandards"]) <= seen, "expected standards must be retrievable")
                self.assertTrue(set(case["expectConflict"]) <= seen, "conflicting standards must be retrievable")
                self.assertFalse(set(case["forbidStandards"]) & seen, "forbidden standards must be out of scope")
                self.assertTrue(set(case["forbidStandards"]) <= set(BY_ID), "forbidden standards must exist")

    def test_suite_covers_every_behaviour(self):
        kinds = {kind for case in self.cases for kind in eval_advisor.tests(case).split(", ")}
        self.assertEqual(kinds, {"grounding", "access", "conflict", "abstention"})


class GateTests(unittest.TestCase):
    def setUp(self):
        self.client = offline_advisor()

    def check(self, data: dict, profile: str = "small-team", retrieved=("STD-ARCH-001",), question: str = "q") -> list[str]:
        return self.client.check(data, profile, question, list(retrieved))

    def test_a_grounded_answer_passes(self):
        self.assertEqual(self.check(answer()), [])

    def test_version_prefix_is_accepted(self):
        data = answer()
        data["constraints"][0]["version"] = "v1.0"
        self.assertEqual(self.check(data), [])

    def test_invented_standard_is_rejected(self):
        data = answer()
        data["constraints"][0]["standardId"] = "STD-SEC-004"
        self.assertTrue(any(p.startswith("citation: STD-SEC-004") for p in self.check(data)))

    def test_out_of_scope_citation_is_rejected(self):
        data = answer(constraints=[{"standardId": "STD-OPS-002", "version": "2.0", "requirement": "Use the gateway.",
                                    "excerpt": "Direct calls from applications to model endpoints are not allowed in production."}])
        self.assertTrue(any(p.startswith("access: STD-OPS-002") for p in self.check(data, "small-team")))
        self.assertEqual(self.check(data, "enterprise", retrieved=["STD-OPS-002"]), [])

    def test_out_of_scope_retrieval_is_rejected(self):
        problems = self.check(answer(), retrieved=["STD-ARCH-001", "STD-DATA-001"])
        self.assertTrue(any("search returned STD-DATA-001" in p for p in problems))

    def test_wrong_version_is_rejected(self):
        data = answer()
        data["constraints"][0]["version"] = "2.0"
        self.assertTrue(any(p.startswith("version: STD-ARCH-001") for p in self.check(data)))

    def test_paraphrased_excerpt_is_rejected(self):
        data = answer()
        data["constraints"][0]["excerpt"] = "Always extend existing services instead of creating new ones."
        self.assertTrue(any(p.startswith("excerpt:") for p in self.check(data)))

    def test_excerpt_tolerates_punctuation_and_ellipsis(self):
        source = BY_ID["STD-SEC-002"]["content"]
        self.assertTrue(advisor.excerpt_found("“Attachments and personal data must not be sent”", source))
        self.assertTrue(advisor.excerpt_found("Send AI services only the fields ... Attachments and personal data", source))
        self.assertFalse(advisor.excerpt_found("Personal data may be sent when encrypted.", source))
        self.assertFalse(advisor.excerpt_found("...", source))

    def test_search_markers_are_removed_from_every_text(self):
        raw = {"summary": "Stay in the API.【5:0†source】【5:4†source】", "unknowns": ["Scaling needs【5:1†source】"],
               "constraints": [{"excerpt": "Prefer extending an existing service【3:2†source】"}], "answerable": True}
        clean = advisor.strip_markers(raw)
        self.assertEqual(clean["summary"], "Stay in the API.")
        self.assertEqual(clean["unknowns"], ["Scaling needs"])
        self.assertEqual(clean["constraints"][0]["excerpt"], "Prefer extending an existing service")
        self.assertIs(clean["answerable"], True)

    def test_mentions_in_free_text_are_checked_unless_the_question_named_them(self):
        data = answer(unknowns=["Does STD-OPS-002 apply?"])
        self.assertTrue(any("STD-OPS-002 in the answer text" in p for p in self.check(data)))
        self.assertEqual(self.check(data, question="Does STD-OPS-002 apply to a small team?"), [])

    def test_abstention_must_be_clean(self):
        abstained = answer(answerable=False, constraints=[], options=[], recommendation=None, unknowns=["No budget standard."])
        self.assertEqual(self.check(abstained, retrieved=[]), [])
        self.assertIn("abstention: answerable is false but a recommendation was given",
                      self.check(dict(abstained, recommendation="Spend 500 a month."), retrieved=[]))
        self.assertIn("abstention: answerable is false but unknowns is empty",
                      self.check(dict(abstained, unknowns=[]), retrieved=[]))

    def test_an_answer_must_cite_a_standard(self):
        self.assertIn("grounding: an answer must cite at least one standard", self.check(answer(constraints=[], options=[])))


class EvaluatorTests(unittest.TestCase):
    def test_conflict_and_scope_expectations(self):
        case = {"expectAnswerable": True, "expectStandards": ["STD-OBS-002", "STD-SEC-002"], "forbidStandards": ["STD-OPS-002"],
                "expectConflict": ["STD-OBS-002", "STD-SEC-002"]}
        flagged = {"checks": [], "result": answer(
            constraints=[{"standardId": s, "version": BY_ID[s]["version"], "requirement": "", "excerpt": ""} for s in ("STD-OBS-002", "STD-SEC-002")],
            conflicts=[{"standards": ["STD-OBS-002 v1.0", "STD-SEC-002 v1.1"], "description": "log vs do not persist"}])}
        self.assertEqual(eval_advisor.evaluate(case, flagged), [])
        missed = {"checks": [], "result": dict(flagged["result"], conflicts=[])}
        self.assertEqual(eval_advisor.evaluate(case, missed), ["did not flag the conflict STD-OBS-002 vs STD-SEC-002"])


if __name__ == "__main__":
    unittest.main()
