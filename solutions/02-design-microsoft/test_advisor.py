"""Offline tests for the Design · Microsoft solution. No Azure or GitHub access is needed.

They prove the parts that must never depend on the model:
  - the standards parse into index documents, and the evaluation labels agree with what each profile may retrieve;
  - the gate (function/advisor_core/checks.py) rejects invented, out-of-scope, misversioned, or misquoted citations,
    and reads the retrieved standards from every shape Azure reports them in;
  - the code Foundry runs as evaluators is the gate's code, uses the standard library only, and scores items right;
  - the advisor run and the standards run (function/advisor_core/runs.py): nothing reaches GitHub before the gate
    passed, a rejected answer gets only its failed checks, the advisor is never silent when Foundry or a GitHub step
    fails, and only a commit on the default branch is re-indexed, published, and evaluated, step by step;
  - the Function's guards: webhook signatures, Issues only from the owner, members, and collaborators, one run per
    delivery and per issue (a run that couldn't finish may be retried), writes only to refs/heads/design/advisor-*,
    two queues as the only way to start work, and a one-time app-manifest setup that stores exactly three secrets and
    answers 409 once connected.
The answers and payloads below are hand-written fixtures; the live demo never uses them.

Run from this folder (azd runs them before every deploy):
  python -m unittest -v test_advisor
"""
from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import io
import json
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "function"))
from advisor_core import agents, checks, evaluation, foundry, github, knowledge, report, runs, setup_flow, standards, webhook  # noqa: E402

SPEC = agents.load_spec((HERE / "agent.yaml").read_text(encoding="utf-8"))
FILES = {path.name: path.read_text(encoding="utf-8") for path in (HERE / "standards").glob("STD-*.md")}
DOCS, SKIPPED = standards.parse(FILES, SPEC)
BY_ID = {doc["id"]: doc for doc in DOCS}
EVERY = {d["id"]: {"version": d["version"], "text": f"{d['title']}\n{d['content']}"} for d in DOCS}
CASES = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def visible(profile: str) -> list[str]:
    return sorted(d["id"] for d in DOCS if d["scope"] in SPEC["profiles"][profile])


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


def gate(data: dict, profile: str = "small-team", retrieved=("STD-ARCH-001",), question: str = "q") -> list[str]:
    return checks.check(data, question, list(retrieved), EVERY, visible(profile), profile)


def iq_output(*ids: str) -> str:
    """A Foundry IQ knowledge_base_retrieve result, as the Responses API reports it in an mcp_call item."""
    return json.dumps({"documents": [{"id": f"0000000{i}-ref", "content": json.dumps(
        {"id": sid, "title": f"{sid} · Title (v1.0)", "content": "text"})} for i, sid in enumerate(ids)]})


class StandardsTests(unittest.TestCase):
    def test_every_standard_is_indexed_once_with_a_stable_id(self):
        self.assertEqual(len(DOCS), 12)
        self.assertEqual(SKIPPED, [])
        for doc in DOCS:
            self.assertEqual(doc["url"], f"solutions/02-design-microsoft/standards/{doc['id']}.md")
            self.assertIn(f"(v{doc['version']})", doc["title"])

    def test_profiles_see_their_own_standards_only(self):
        self.assertIn("STD-OPS-001", visible("small-team"))
        self.assertNotIn("STD-OPS-002", visible("small-team"))
        self.assertIn("STD-OPS-002", visible("enterprise"))
        self.assertNotIn("STD-DATA-002", visible("enterprise"))
        self.assertEqual(standards.scope_filter(SPEC, "small-team"), "scope eq 'all' or scope eq 'small-team'")

    def test_content_hash_is_stable(self):
        again, _ = standards.parse(FILES, SPEC)
        self.assertEqual([d["contentHash"] for d in again], [d["contentHash"] for d in DOCS])

    def test_malformed_standards_stop_the_sync(self):
        good = FILES["STD-AI-001.md"]
        for name, text in (("STD-AI-001.md", "# no front matter"),
                           ("STD-AI-009.md", good),
                           ("STD-AI-001.md", good.replace("scope: all", "scope: everyone"))):
            with self.subTest(name=name), self.assertRaises(standards.StandardsError):
                standards.parse({name: text}, SPEC)

    def test_unapproved_standards_are_left_out(self):
        docs, skipped = standards.parse({"STD-AI-001.md": FILES["STD-AI-001.md"].replace("status: approved", "status: draft")}, SPEC)
        self.assertEqual((docs, skipped), ([], ["STD-AI-001.md (status draft)"]))

    def test_the_sync_summary_names_what_sets_each_profile_apart(self):
        result = {"index": "architecture-standards", "approved": 12, "new": [], "changed": [], "removed": [], "failed": [],
                  "unchanged": 12, "documents": 12, "visible": {p: visible(p) for p in SPEC["profiles"]}}
        lines = standards.summary_lines(result)
        self.assertIn("only this profile sees STD-DATA-002, STD-OPS-001", lines[1])
        self.assertIn("only this profile sees STD-AI-002, STD-DATA-001, STD-OPS-002", lines[2])

    def test_each_profile_gets_a_knowledge_base_with_its_filter(self):
        source, base = knowledge.definitions(SPEC, "enterprise", "architecture-standards")
        self.assertEqual(source["searchIndexParameters"]["baseFilter"], "scope eq 'all' or scope eq 'enterprise'")
        self.assertEqual(base["knowledgeSources"], [{"name": "standards-enterprise"}])
        self.assertEqual(base["retrievalReasoningEffort"], {"kind": "minimal"})
        self.assertEqual(knowledge.connection_name("enterprise"), "standards-kb-enterprise")


class EvaluationCaseTests(unittest.TestCase):
    """The labels must be answerable from what each profile can retrieve, or the evaluation measures nothing."""

    def test_ten_cases_with_unique_ids(self):
        self.assertEqual(len(CASES), 10)
        self.assertEqual(len({c["id"] for c in CASES}), 10)

    def test_labels_match_the_profile_scopes(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                seen = set(visible(case["profile"]))
                self.assertTrue(set(case["expectStandards"]) <= seen, "expected standards must be retrievable")
                self.assertTrue(set(case["expectConflict"]) <= seen, "conflicting standards must be retrievable")
                self.assertFalse(set(case["forbidStandards"]) & seen, "forbidden standards must be out of scope")
                self.assertTrue(set(case["forbidStandards"]) <= set(BY_ID), "forbidden standards must exist")

    def test_suite_covers_every_behaviour(self):
        self.assertTrue(any(c["forbidStandards"] for c in CASES))
        self.assertTrue(any(c["expectConflict"] for c in CASES))
        self.assertTrue(any(not c["expectAnswerable"] for c in CASES))
        self.assertEqual({c["profile"] for c in CASES}, set(SPEC["profiles"]))


class GateTests(unittest.TestCase):
    def test_a_grounded_answer_passes(self):
        self.assertEqual(gate(answer()), [])

    def test_version_prefix_is_accepted(self):
        data = answer()
        data["constraints"][0]["version"] = "v1.0"
        self.assertEqual(gate(data), [])

    def test_invented_standard_is_rejected(self):
        data = answer()
        data["constraints"][0]["standardId"] = "STD-SEC-004"
        self.assertTrue(any(p.startswith("citation: STD-SEC-004") for p in gate(data)))

    def test_out_of_scope_citation_is_rejected(self):
        data = answer(constraints=[{"standardId": "STD-OPS-002", "version": "2.0", "requirement": "Use the gateway.",
                                    "excerpt": "Direct calls from applications to model endpoints are not allowed in production."}])
        self.assertTrue(any(p.startswith("access: STD-OPS-002") for p in gate(data, "small-team")))
        self.assertEqual(gate(data, "enterprise", retrieved=["STD-OPS-002"]), [])

    def test_out_of_scope_retrieval_is_rejected(self):
        problems = gate(answer(), retrieved=["STD-ARCH-001", "STD-DATA-001"])
        self.assertTrue(any("knowledge base returned STD-DATA-001" in p for p in problems))

    def test_wrong_version_is_rejected(self):
        data = answer()
        data["constraints"][0]["version"] = "2.0"
        self.assertTrue(any(p.startswith("version: STD-ARCH-001") for p in gate(data)))

    def test_paraphrased_excerpt_is_rejected(self):
        data = answer()
        data["constraints"][0]["excerpt"] = "Always extend existing services instead of creating new ones."
        self.assertTrue(any(p.startswith("excerpt:") for p in gate(data)))

    def test_excerpt_tolerates_punctuation_and_ellipsis(self):
        source = BY_ID["STD-SEC-002"]["content"]
        self.assertTrue(checks.excerpt_found("“Attachments and personal data must not be sent”", source))
        self.assertTrue(checks.excerpt_found(
            "Send AI services only the fields the use case needs ... Attachments and personal data must not be sent",
            source))
        self.assertFalse(checks.excerpt_found("Personal data may be sent when encrypted.", source))
        self.assertFalse(checks.excerpt_found("...", source))

    def test_excerpt_fragments_and_partial_words_are_rejected(self):
        source = BY_ID["STD-SEC-002"]["content"]
        self.assertFalse(checks.excerpt_found("e", source))
        self.assertFalse(checks.excerpt_found("personal data ... be sent", source))  # the source says "must not be sent"
        self.assertFalse(checks.excerpt_found("Attachments and persona data must not be sent", source))  # whole words only
        self.assertFalse(checks.excerpt_found(  # parts out of the source's order
            "Attachments and personal data must not be sent ... Send AI services only the fields the use case needs",
            source))

    def test_a_short_excerpt_passes_only_as_a_whole_sentence(self):
        source = "Keep it short. Every decision is recorded in an architecture decision record."
        self.assertTrue(checks.excerpt_found("Keep it short.", source))
        self.assertFalse(checks.excerpt_found("Keep it", source))
        self.assertFalse(checks.excerpt_found("decision is recorded", source))

    def test_a_quote_may_shorten_a_standard_but_never_skip_a_negation(self):
        sec1, sec2, ops1 = (BY_ID[s]["content"] for s in ("STD-SEC-001", "STD-SEC-002", "STD-OPS-001"))
        self.assertFalse(checks.excerpt_found(  # between two parts: the standard says "must not be stored"
            "API keys, connection-string secrets, and shared keys ... be stored in configuration or code", sec1))
        self.assertFalse(checks.excerpt_found(  # before the first part, in its clause: "Do not persist"
            "persist raw prompts or completions that contain free text entered by users", sec2))
        self.assertFalse(checks.excerpt_found(  # "Avoid" turns a requirement around too
            "gateways, queues, or clusters unless an existing platform team operates them", ops1))
        self.assertFalse(checks.excerpt_found(  # a contraction is a negation
            "store API keys in configuration files on any server", "Don't store API keys in configuration files on any server."))
        self.assertTrue(checks.excerpt_found(  # the whole sentence keeps its negation
            "API keys, connection-string secrets, and shared keys must not be stored in configuration or code.", sec1))
        self.assertTrue(checks.excerpt_found(  # the clause after a semicolon starts afresh
            "persist only structured results and identifiers", sec2))
        self.assertTrue(checks.excerpt_found(  # a repeated phrase is placed where it skips no negation
            "Review the plan with the team ... and then publish the decision record",
            "Review the plan with the team, not alone. Review the plan with the team and then publish the decision record."))

    def test_the_gate_rejects_a_quote_that_leaves_out_a_negation(self):
        for standard, excerpt, requirement in (
                ("STD-SEC-001", "API keys, connection-string secrets, and shared keys ... be stored in configuration or code",
                 "Store API keys and shared keys in configuration."),
                ("STD-SEC-002", "persist raw prompts or completions that contain free text entered by users",
                 "Persist the raw prompts so they can be audited.")):
            data = answer(constraints=[{"standardId": standard, "version": EVERY[standard]["version"],
                                        "requirement": requirement, "excerpt": excerpt}])
            problems = gate(data, retrieved=[standard])
            self.assertEqual(len(problems), 1, problems)
            self.assertTrue(problems[0].startswith(f"excerpt: the quote attributed to {standard} leaves out a negation"))

    def test_citation_markers_are_removed_from_every_text(self):
        raw = {"summary": "Stay in the API.【5:0†source】", "unknowns": ["Scaling needs【5:1†source】"], "answerable": True}
        clean = checks.strip_markers(raw)
        self.assertEqual((clean["summary"], clean["unknowns"]), ("Stay in the API.", ["Scaling needs"]))

    def test_mentions_in_free_text_are_checked_unless_the_question_named_them(self):
        data = answer(unknowns=["Does STD-OPS-002 apply?"])
        self.assertTrue(any("STD-OPS-002 in the answer text" in p for p in gate(data)))
        self.assertEqual(gate(data, question="Does STD-OPS-002 apply to a small team?"), [])

    def test_abstention_must_be_clean(self):
        abstained = answer(answerable=False, constraints=[], options=[], recommendation=None, unknowns=["No budget standard."])
        self.assertEqual(gate(abstained, retrieved=[]), [])
        self.assertIn("abstention: answerable is false but a recommendation was given",
                      gate(dict(abstained, recommendation="Spend 500 a month."), retrieved=[]))
        self.assertIn("abstention: answerable is false but unknowns is empty", gate(dict(abstained, unknowns=[]), retrieved=[]))

    def test_an_answer_must_cite_a_standard(self):
        self.assertIn("grounding: an answer must cite at least one standard", gate(answer(constraints=[], options=[])))


class ResponseParsingTests(unittest.TestCase):
    def test_retrieval_is_read_from_a_foundry_iq_response(self):
        response = {"output": [{"type": "mcp_list_tools", "tools": []},
                               {"type": "mcp_call", "name": "knowledge_base_retrieve", "output": iq_output("STD-SEC-002", "STD-OBS-002")},
                               {"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer())}]}]}
        self.assertEqual(checks.retrieved_ids(response["output"]), ["STD-OBS-002", "STD-SEC-002"])
        self.assertEqual(checks.parse_answer(checks.answer_text(response))["recommendation"], answer()["recommendation"])

    def test_retrieval_is_read_from_the_search_tool_and_from_evaluation_items(self):
        search_tool = [{"type": "azure_ai_search_call_output", "output": json.dumps({"documents": [{"id": "STD-API-001"}]})}]
        evaluation_items = [{"role": "tool", "content": json.dumps([{"type": "tool_result", "tool_result": iq_output("STD-AI-001")}])}]
        self.assertEqual(checks.retrieved_ids(search_tool), ["STD-API-001"])
        self.assertEqual(checks.retrieved_ids(evaluation_items), ["STD-AI-001"])

    def test_citations_in_the_answer_are_not_counted_as_retrievals(self):
        message = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer())}]}]
        self.assertEqual(checks.retrieved_ids(message), [])

    def test_a_non_json_answer_is_rejected(self):
        with self.assertRaises(ValueError):
            checks.parse_answer("I think you should use a gateway.")


class EvaluatorTests(unittest.TestCase):
    """Foundry runs evaluation.evaluator_code(kind) in a sandbox: it must be the gate's code and stand alone."""

    @staticmethod
    def grade(kind: str, item: dict) -> float:
        scope: dict = {}
        exec(compile(evaluation.evaluator_code(kind), f"advisor_{kind}", "exec"), scope)  # noqa: S102 - our own code
        return scope["grade"]({}, item)

    @staticmethod
    def item(case_id: str, data: dict, retrieved: tuple[str, ...]) -> dict:
        case = next(c for c in CASES if c["id"] == case_id)
        row = evaluation.items([case], EVERY, visible(case["profile"]))[0]["item"]
        row["sample"] = {"output_text": json.dumps(data),
                         "output_items": [{"type": "tool_result", "tool_result": iq_output(*retrieved)}]}
        return row

    def test_evaluator_code_runs_in_the_grader_sandbox(self):
        """Foundry runs the evaluators as Python graders: standard library only, and no compile(), eval(), exec(),
        open(), or __import__() anywhere, not even re.compile()."""
        code = evaluation.evaluator_code("citations")
        tree = ast.parse(code)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertLessEqual(imported, {"json", "re"})
        called = {node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                  for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(called & {"compile", "eval", "exec", "open", "__import__", "globals", "locals", "vars", "input"})
        self.assertLess(len(code.encode()), 256 * 1024)

    def test_a_correct_conflict_answer_passes_every_evaluator(self):
        data = answer(constraints=[
            {"standardId": "STD-OBS-002", "version": "1.0", "requirement": "Log prompts.",
             "excerpt": "log the full prompt and completion of every AI call for 30 days"},
            {"standardId": "STD-SEC-002", "version": "1.1", "requirement": "Do not persist raw prompts.",
             "excerpt": "Send AI services only the fields the use case needs."}],
            options=[], conflicts=[{"standards": ["STD-OBS-002", "STD-SEC-002"], "description": "log vs do not persist"}])
        row = self.item("E07", data, ("STD-OBS-002", "STD-SEC-002"))
        self.assertEqual({kind: self.grade(kind, row) for kind in evaluation.EVALUATORS}, dict.fromkeys(evaluation.EVALUATORS, 1.0))

    def test_each_evaluator_fails_on_its_own_mistake(self):
        missed_conflict = self.item("E07", answer(constraints=[{"standardId": "STD-OBS-002", "version": "1.0", "requirement": "",
                                                                 "excerpt": "log the full prompt and completion of every AI call"}],
                                                  options=[]), ("STD-OBS-002",))
        self.assertEqual(self.grade("conflicts", missed_conflict), 0.0)
        self.assertEqual(self.grade("grounding", missed_conflict), 0.0)  # STD-SEC-002 not cited
        self.assertEqual(self.grade("citations", missed_conflict), 1.0)
        leaked = self.item("E01", answer(), ("STD-ARCH-001", "STD-OPS-002"))
        self.assertEqual(self.grade("access", leaked), 0.0)
        invented = answer()
        invented["constraints"][0]["excerpt"] = "Microservices are always preferred."
        self.assertEqual(self.grade("citations", self.item("E01", invented, ("STD-ARCH-001",))), 0.0)
        turned_around = answer(constraints=[{"standardId": "STD-SEC-001", "version": "2.0", "requirement": "Store keys in config.",
                                             "excerpt": "API keys, connection-string secrets, and shared keys ... be stored "
                                                        "in configuration or code"}])
        self.assertEqual(self.grade("citations", self.item("E01", turned_around, ("STD-SEC-001",))), 0.0)
        not_abstained = self.item("E08", answer(), ("STD-ARCH-001",))
        self.assertEqual(self.grade("abstention", not_abstained), 0.0)

    def test_a_missing_answer_fails_instead_of_erroring(self):
        row = self.item("E01", answer(), ("STD-ARCH-001",))
        row["sample"] = {"output_text": "", "output_items": []}
        self.assertEqual(self.grade("citations", row), 0.0)


class ReportTests(unittest.TestCase):
    sample = {"issue": 12, "question": "Where should the triage provider run?", "profile": "small-team",
           "startedAt": "2026-01-01T00:00:00+00:00", "durationSeconds": 12.5, "responseId": "resp_example",
           "agent": {"name": "architecture-advisor-small-team", "version": "3"}, "model": "gpt-5.4-mini",
           "knowledgeCalls": 2, "retrievedStandards": ["STD-ARCH-001", "STD-OPS-001"], "checks": [],
           "index": "architecture-standards", "scopes": ["all", "small-team"], "runId": "3f2a9c1b7d4e",
           "result": answer()}

    def test_adr_metadata_is_a_list_and_keeps_the_timestamp_apart(self):
        draft = report.adr_markdown(self.sample)
        self.assertNotIn("| | |", draft)
        self.assertIn("- **Status:** Proposed.", draft)
        self.assertIn("- **Issue:** #12", draft)
        evidence = next(line for line in draft.splitlines() if line.startswith("- **Evidence:**"))
        self.assertIn("at 2026-01-01T00:00:00+00:00.", evidence)
        self.assertTrue(evidence.endswith("retrieved STD-ARCH-001, STD-OPS-001."))

    def test_comment_links_the_adr_draft_or_explains_why_there_is_none(self):
        self.assertIn("**ADR draft: #34.**", report.comment_markdown(self.sample, 34))
        failed = dict(self.sample, checks=["excerpt: the quote attributed to STD-ARCH-001 is not in the standard"])
        text = report.comment_markdown(failed)
        self.assertIn("❌ The deterministic checks rejected this answer", text)
        self.assertIn("no ADR draft was proposed", text)

    def test_a_rejected_answer_never_reaches_github(self):
        rejected = answer(recommendation="Email @octocat and see https://evil.example for the real policy.",
                          constraints=[{"standardId": "STD-SEC-009", "version": "1.0", "excerpt": "Invented rule.",
                                        "requirement": "Send everything to the vendor @octocat."}])
        problems = ["citation: STD-SEC-009 in constraints does not exist in the standards index (invented)",
                    'excerpt: the quote attributed to STD-ARCH-001 is not in the standard: "see @octocat ``` [x](https://evil.example)"']
        text = report.comment_markdown(dict(self.sample, result=rejected, checks=problems))
        self.assertNotIn(rejected["recommendation"], text)
        self.assertNotIn("Send everything to the vendor", text)
        body = text.split("```text\n", 1)[1].split("\n```", 1)[0]  # the problems sit in one code block
        self.assertIn("STD-SEC-009", body)
        self.assertNotIn("```", body)
        outside = text.replace(body, "")
        self.assertNotIn("@octocat", outside)
        self.assertNotIn("https://evil.example", outside)

    def test_mentions_in_an_accepted_answer_notify_nobody(self):
        noisy = answer(recommendation="Ask @octocat to review.", unknowns=["Whether @team-a owns it"])
        text = report.comment_markdown(dict(self.sample, result=noisy), 34)
        self.assertIn("`@octocat`", text)
        self.assertIn("`@team-a`", text)
        self.assertNotIn(" @octocat", text.replace("`@octocat`", ""))
        # GitHub also mentions after an underscore or a non-ASCII letter; an e-mail address mentions nobody.
        self.assertEqual(report.quiet("_@octocat_ é@octocat"), "_`@octocat`_ é`@octocat`")
        self.assertEqual(report.quiet("user@example.com"), "user@example.com")

    def test_a_failed_github_step_still_answers_the_issue(self):
        incomplete, unavailable = report.incomplete_markdown("3f2a9c1b7d4e"), report.unavailable_markdown("3f2a9c1b7d4e")
        self.assertIn("could not be completed", incomplete)
        self.assertIn("could not answer", unavailable)
        for text in (incomplete, unavailable):  # how to ask again, and where the details are
            self.assertIn("removes the `design-advisor` label and adds it back", text)
            self.assertIn("advisor run `3f2a9c1b7d4e`", text)

    def test_the_evidence_names_the_advisor_run(self):
        self.assertIn("advisor run `3f2a9c1b7d4e`", report.comment_markdown(self.sample, 34))
        self.assertIn("advisor run `3f2a9c1b7d4e`", report.pull_request_text(self.sample, "x")[1])
        self.assertNotIn("Logic App", report.comment_markdown(self.sample, 34) + report.pull_request_text(self.sample, "x")[1])

    def test_pull_request_closes_the_issue(self):
        title, body = report.pull_request_text(self.sample, github.adr_path_for(12))
        self.assertEqual(title, "Design: ADR draft for #12 (Foundry advisor)")
        self.assertTrue(body.startswith("Closes #12."))

    def test_nothing_names_an_azure_host(self):
        text = " ".join([report.adr_markdown(self.sample), report.comment_markdown(self.sample, 34),
                         *report.pull_request_text(self.sample, "x"), report.unavailable_markdown("08584")])
        for host in ("azure.com", "windows.net", "azurewebsites", "services.ai"):
            self.assertNotIn(host, text)


class WebhookTests(unittest.TestCase):
    repo = "octo/requesthub"

    def payload(self, **issue) -> dict:
        """The issues.labeled event GitHub sends when the design-advisor label is added, at creation or later."""
        body = "### Operating profile\n\nsmall-team\n\n### Question\n\nShould triage run in-process?"
        return {"action": "labeled", "label": {"name": "design-advisor"},
                "repository": {"full_name": self.repo, "default_branch": "main"},
                "issue": {"number": 7, "title": "Architecture question", "state": "open", "body": body,
                          "labels": [{"name": "design-advisor"}], "author_association": "OWNER", **issue}}

    def opened(self, **issue) -> dict:
        """The issues.opened event that comes with the labeled event for an Issue filed with the label."""
        event = self.payload(**issue)
        del event["label"]
        return dict(event, action="opened")

    def test_signature(self):
        body = b'{"zen": "Keep it logically awesome."}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(webhook.verify_signature("s3cret", body, good))
        self.assertFalse(webhook.verify_signature("s3cret", body + b" ", good))
        self.assertFalse(webhook.verify_signature("s3cret", body, None))
        self.assertFalse(webhook.verify_signature("", body, good))

    def test_issue_form(self):
        self.assertEqual(webhook.parse_issue_form(self.payload()["issue"]["body"]), ("small-team", "Should triage run in-process?"))
        self.assertEqual(webhook.parse_issue_form("### Operating profile\n\nadmin\n\n### Question\n\nQ?"), ("enterprise", "Q?"))

    def test_routes(self):
        asked = webhook.classify("issues", self.payload(), self.repo)
        self.assertEqual((asked["route"], asked["issue"], asked["profile"]), ("advisor", 7, "small-team"))
        for name, event, payload in (
                ("opened: the labeled event that comes with it starts the run", "issues", self.opened()),
                ("other label", "issues", dict(self.payload(), label={"name": "bug"})),
                ("label removed", "issues", dict(self.payload(), action="unlabeled")),
                ("closed", "issues", self.payload(state="closed")),
                ("pull request", "issues", self.payload(pull_request={})),
                ("other repo", "issues", dict(self.payload(), repository={"full_name": "octo/other"})),
                ("comment", "issue_comment", self.payload())):
            with self.subTest(name):
                self.assertEqual(webhook.classify(event, payload, self.repo)["route"], "ignore")

    def test_only_the_owner_members_and_collaborators_start_the_advisor(self):
        # On a public repository anyone can use the issue form, which applies the label for them: the author decides.
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                payload = self.payload(author_association=association)
                self.assertEqual(webhook.classify("issues", payload, self.repo)["route"], "advisor")
        for association in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", "NONE", "", None, "owner"):
            with self.subTest(association=association):
                decision = webhook.classify("issues", self.payload(author_association=association), self.repo)
                self.assertEqual(decision["route"], "ignore")
                self.assertIn("outside contributor", decision["reason"])
        missing = self.payload()
        del missing["issue"]["author_association"]
        self.assertEqual(webhook.classify("issues", missing, self.repo)["route"], "ignore")

    def test_push_routes_only_merged_standards(self):
        push = {"ref": "refs/heads/main", "after": "a" * 40, "repository": {"full_name": self.repo, "default_branch": "main"},
                "commits": [{"modified": ["solutions/02-design-microsoft/standards/STD-AI-001.md"]}]}
        self.assertEqual(webhook.classify("push", push, self.repo)["route"], "standards")
        self.assertEqual(webhook.classify("push", dict(push, ref="refs/heads/feature"), self.repo)["route"], "ignore")
        self.assertEqual(webhook.classify("push", dict(push, commits=[{"modified": ["README.md"]}]), self.repo)["route"], "ignore")


class FakeResponse:
    def __init__(self, status: int, data=None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeSession:
    """Records requests and answers like GitHub would for a repository with a main branch."""

    def __init__(self):
        self.calls, self.refs, self.files, self.pulls = [], {"main": "base-sha"}, {}, []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.split("/repos/octo/requesthub", 1)[1]
        self.calls.append((method, path, json))
        if method == "GET" and path == "":
            return FakeResponse(200, {"default_branch": "main"})
        if method == "GET" and path.startswith("/git/ref/heads/"):
            name = path[len("/git/ref/heads/"):]
            return FakeResponse(200, {"object": {"sha": self.refs[name]}}) if name in self.refs else FakeResponse(404)
        if method == "POST" and path == "/git/refs":
            self.refs[json["ref"][len("refs/heads/"):]] = json["sha"]
            return FakeResponse(201, {"object": {"sha": json["sha"]}})
        if method == "GET" and path.startswith("/contents/"):
            key = (path[len("/contents/"):], params["ref"])
            return FakeResponse(200, {"sha": "file-sha"}) if key in self.files else FakeResponse(404)
        if method == "PUT" and path.startswith("/contents/"):
            self.files[(path[len("/contents/"):], json["branch"])] = json["content"]
            return FakeResponse(201, {"commit": {"sha": "commit-sha"}})
        if method == "GET" and path == "/pulls":
            return FakeResponse(200, [p for p in self.pulls if p["head"]["label"] == params["head"]])
        if method == "POST" and path == "/pulls":
            self.pulls.append({"head": {"label": f"octo:{json['head']}", "repo": {"full_name": "octo/requesthub"}},
                               "number": 34 + len(self.pulls), "html_url": "https://github.com/octo/requesthub/pull/34"})
            return FakeResponse(201, self.pulls[-1])
        if method == "POST" and path.endswith("/comments"):
            return FakeResponse(201, {"id": 1, "html_url": "https://github.com/octo/requesthub/issues/7#issuecomment-1"})
        if method == "GET" and path.startswith("/compare/"):
            return FakeResponse(200, {"status": "behind" if path.endswith("a" * 40) else "ahead"})
        return FakeResponse(403, {"message": "forbidden"})


class GitHubGuardTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.client = github.GitHub("octo/requesthub", lambda: "ghs_test_token", session=self.session)

    def test_only_advisor_refs_are_writable(self):
        github.assert_writable_ref("refs/heads/design/advisor-issue-12")
        for ref in ("refs/heads/main", "refs/heads/design/advisor-../main", "refs/tags/design/advisor-1",
                    "refs/heads/design/advisor-", "refs/heads/design/advisors-1"):
            with self.subTest(ref=ref), self.assertRaises(github.GuardError):
                github.assert_writable_ref(ref)

    def test_the_adr_flow_writes_only_to_its_branch_and_folder(self):
        self.client.ensure_branch(12)
        put = self.client.put_adr(12, "# ADR", "Design: ADR draft for #12")
        pull = self.client.open_pull_request(12, "t", "b")
        self.client.comment(7, "answer")
        self.assertEqual(self.session.refs["design/advisor-issue-12"], "base-sha")
        self.assertEqual(put["path"], "solutions/02-design-microsoft/adr/issue-12.md")
        self.assertEqual(pull["number"], 34)
        writes = [(m, p) for m, p, _ in self.session.calls if m != "GET"]
        self.assertEqual(writes, [("POST", "/git/refs"), ("PUT", "/contents/solutions/02-design-microsoft/adr/issue-12.md"),
                                  ("POST", "/pulls"), ("POST", "/issues/7/comments")])

    def test_a_second_run_reuses_the_branch_and_the_pull_request(self):
        for _ in range(2):
            self.client.ensure_branch(12)
            self.client.put_adr(12, "# ADR", "m")
            self.client.open_pull_request(12, "t", "b")
        self.assertEqual(sum(1 for m, p, _ in self.session.calls if (m, p) == ("POST", "/git/refs")), 1)
        self.assertEqual(sum(1 for m, p, _ in self.session.calls if (m, p) == ("POST", "/pulls")), 1)

    def test_a_pull_request_from_a_fork_is_never_reused(self):
        # Only a branch in this repository counts: only writers and the app can push one.
        self.session.pulls.append({"head": {"label": "octo:design/advisor-issue-12", "repo": {"full_name": "outsider/requesthub"}},
                                   "number": 99, "html_url": "https://github.com/octo/requesthub/pull/99"})
        pull = self.client.open_pull_request(12, "t", "b")
        self.assertTrue(pull["created"])
        self.assertNotEqual(pull["number"], 99)
        self.assertFalse(github.same_repository({"head": {"repo": None}}, "octo/requesthub"))
        self.assertTrue(github.same_repository({"head": {"repo": {"full_name": "Octo/RequestHub"}}}, "octo/requesthub"))

    def test_any_other_write_is_refused_before_a_request_is_sent(self):
        for method, path, body in (("PUT", "/contents/README.md", {"branch": "design/advisor-issue-1"}),
                                   ("PUT", "/contents/solutions/02-design-microsoft/adr/x.md", {"branch": "main"}),
                                   ("POST", "/git/refs", {"ref": "refs/heads/main", "sha": "x"}),
                                   ("POST", "/pulls", {"head": "main", "base": "release"}),
                                   ("PUT", "/pulls/34/merge", {}),
                                   ("PATCH", "/git/refs/heads/main", {"sha": "x"}),
                                   ("DELETE", "/git/refs/heads/main", {})):
            with self.subTest(method=method, path=path), self.assertRaises(github.GuardError):
                self.client._write(method, path, body)
        self.assertEqual(self.session.calls, [])

    def test_errors_never_carry_the_token(self):
        with self.assertRaises(github.GitHubError) as raised:
            self.client._request("GET", "/actions/secrets")
        self.assertNotIn("ghs_test_token", str(raised.exception))

    def test_only_merged_commits_are_on_the_default_branch(self):
        self.assertTrue(self.client.on_default_branch("a" * 40))
        self.assertFalse(self.client.on_default_branch("b" * 40))

    def test_app_jwt_is_short_lived_and_names_the_app(self):
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        claims = jwt.decode(github.app_jwt("123", pem), key.public_key(), algorithms=["RS256"])
        self.assertEqual(claims["iss"], "123")
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)


def foundry_response(data=None, retrieved=("STD-ARCH-001",), status="completed", agent="architecture-advisor-small-team",
                     version="2") -> dict:
    """A Responses API result as Foundry returns it for the advisor: one Foundry IQ call, then the JSON answer."""
    return {"id": "resp_test", "status": status, "model": "gpt-5.4-mini", "created_at": 1_700_000_000,
            "completed_at": 1_700_000_012, "agent_reference": {"type": "agent_reference", "name": agent, "version": version},
            "usage": {"input_tokens": 900, "output_tokens": 700},
            "output": [{"type": "mcp_call", "name": "knowledge_base_retrieve", "output": iq_output(*retrieved)},
                       {"type": "message", "content": [{"type": "output_text", "text": json.dumps(data or answer())}]}]}


def scope_of(name: str, version: str) -> tuple[str, str]:
    """What an agent version records when it is published: its profile and its knowledge tool's scope filter."""
    profile = name.split("architecture-advisor-", 1)[1]
    return profile, standards.scope_filter(SPEC, profile)


def snapshot(search_filter: str | None) -> dict:
    """The index: every standard, or those a profile's scope filter returns."""
    if search_filter is None:
        return EVERY
    return {key: EVERY[key] for key in visible("small-team" if "small-team" in search_filter else "enterprise")}


def check_with_fakes(response: dict, job: dict) -> dict:
    return runs.check_answer(response, job, scope_of=scope_of, snapshot=snapshot, index="architecture-standards")


class FoundryTests(unittest.TestCase):
    """advisor_core/foundry.py asks the agent the way the Logic App did: by name, through the Responses API."""

    class Session:
        def __init__(self, *answers):
            self.answers, self.calls = list(answers), []

        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append((url, json, headers))
            reply = self.answers.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    def ask(self, *answers):
        self.session, self.slept = self.Session(*answers), []
        return foundry.ask("https://aif.example/api/projects/design/", "architecture-advisor-small-team", "Q?",
                           lambda: "token-SECRET", session=self.session, sleep=self.slept.append)

    def test_the_agent_is_asked_by_name_through_the_responses_api(self):
        self.assertEqual(self.ask(FakeResponse(200, {"id": "resp_1"})), {"id": "resp_1"})
        url, body, headers = self.session.calls[0]
        self.assertEqual(url, "https://aif.example/api/projects/design/openai/v1/responses")
        self.assertEqual(body["agent_reference"], {"type": "agent_reference", "name": "architecture-advisor-small-team"})
        self.assertEqual((body["input"], body["max_output_tokens"]), ("Q?", 8000))
        self.assertEqual(headers["Authorization"], "Bearer token-SECRET")

    def test_throttling_is_retried_and_a_refusal_is_not(self):
        self.assertEqual(self.ask(FakeResponse(429, {}), FakeResponse(503, {}), FakeResponse(200, {"id": "r"}))["id"], "r")
        self.assertEqual(self.slept, [10, 20])
        with self.assertRaises(foundry.FoundryError) as refused:
            self.ask(FakeResponse(400, {}))
        self.assertEqual(len(self.session.calls), 1)
        self.assertIn("HTTP 400", str(refused.exception))

    def test_errors_never_carry_the_url_or_the_token(self):
        import requests
        failure = requests.ConnectionError("Max retries exceeded with url: https://aif.example/api/x (token-SECRET)")
        with self.assertRaises(foundry.FoundryError) as raised:
            self.ask(failure, failure, failure)
        self.assertIn("ConnectionError", str(raised.exception))
        for secret in ("aif.example", "token-SECRET"):
            self.assertNotIn(secret, str(raised.exception))
        self.assertEqual(runs.describe(ConnectionError("https://stsecret.queue.example")), "ConnectionError")


class CheckAnswerTests(unittest.TestCase):
    """runs.check_answer: the gate's run record, built from Foundry's response and the index."""
    job = {"id": "3f2a9c1b7d4e", "issue": 12, "profile": "small-team", "question": "Should triage run in-process?"}

    def test_a_grounded_answer_passes_with_its_evidence(self):
        run = check_with_fakes(foundry_response(), self.job)
        self.assertEqual(run["checks"], [])
        self.assertEqual((run["runId"], run["agent"]["version"], run["knowledgeCalls"], run["retrievedStandards"],
                          run["scopes"], run["durationSeconds"]),
                         ("3f2a9c1b7d4e", "2", 1, ["STD-ARCH-001"], ["all", "small-team"], 12))

    def test_an_answer_from_another_profiles_agent_is_rejected(self):
        run = check_with_fakes(foundry_response(agent="architecture-advisor-enterprise"), self.job)
        self.assertTrue(any("serves the 'enterprise' profile" in problem for problem in run["checks"]))

    def test_an_unknown_agent_an_unfinished_answer_or_a_non_json_answer_is_rejected(self):
        def unknown(name, version):
            raise KeyError(version)
        run = runs.check_answer(foundry_response(), self.job, scope_of=unknown, snapshot=snapshot, index="i")
        self.assertTrue(any(problem.startswith("access: could not read the scope") for problem in run["checks"]))
        run = check_with_fakes(foundry_response(status="incomplete"), self.job)
        self.assertTrue(any(problem.startswith("response:") for problem in run["checks"]))
        broken = foundry_response()
        broken["output"][-1]["content"][0]["text"] = "not json"
        run = check_with_fakes(broken, self.job)
        self.assertTrue(any(problem.startswith("format:") for problem in run["checks"]))
        self.assertFalse(run["result"]["answerable"])


class FakeGitHub:
    """The guarded client's four writes, recorded. fail_on names the write that fails, as GitHub would fail it."""

    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def _do(self, name, *args):
        self.calls.append((name, *args))
        if name == self.fail_on:
            raise github.GitHubError(502, f"{name}: Bad Gateway")

    def ensure_branch(self, issue):
        self._do("branch", issue)
        return {"branch": github.branch_for(issue), "sha": "base-sha", "created": True}

    def put_adr(self, issue, content, message):
        self._do("commit", issue, content)
        return {"path": github.adr_path_for(issue), "branch": github.branch_for(issue), "commit": "abc1234def", "created": True}

    def open_pull_request(self, issue, title, body):
        self._do("pull", issue, body)
        return {"number": 34, "url": "https://github.com/octo/requesthub/pull/34", "created": True}

    def comment(self, issue, body):
        self._do("comment", issue, body)
        return {"id": 1}


class AdvisorRunTests(unittest.TestCase):
    """runs.advise, the advisor Logic App's steps as Python: ask, check, then GitHub, or one comment that says why not."""
    job = {"id": "3f2a9c1b7d4e", "issue": 12, "title": "Architecture question", "profile": "small-team",
           "question": "Should triage run in-process?"}

    def advise(self, ask=None, client=None, check=None) -> dict:
        self.client, self.lines = client or FakeGitHub(), []
        tools = runs.AdvisorTools(ask=ask or (lambda question, profile: foundry_response()), check=check or check_with_fakes,
                                  github=lambda: self.client)
        return runs.advise(dict(self.job), tools, self.lines.append)

    def steps(self) -> list[str]:
        return [call[0] for call in self.client.calls]

    def comments(self) -> list[str]:
        return [call[2] for call in self.client.calls if call[0] == "comment"]

    def test_a_checked_answer_becomes_an_adr_draft_a_pull_request_and_a_comment(self):
        result = self.advise()
        self.assertEqual((result["state"], result["pullRequest"]), ("answered", 34))
        self.assertEqual(self.steps(), ["branch", "commit", "pull", "comment"])
        self.assertIn("**ADR draft: #34.**", self.comments()[0])
        self.assertIn("advisor run `3f2a9c1b7d4e`", self.comments()[0])
        self.assertTrue(all(line.startswith("advisor run 3f2a9c1b7d4e: #12 ") for line in self.lines))
        self.assertTrue(any("the gate passed the answer" in line for line in self.lines))

    def test_a_rejected_answer_gets_only_its_failed_checks(self):
        invented = answer()
        invented["constraints"][0]["standardId"] = "STD-SEC-009"
        result = self.advise(ask=lambda question, profile: foundry_response(invented))
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(self.steps(), ["comment"])
        self.assertIn("❌ The deterministic checks rejected this answer", self.comments()[0])
        self.assertNotIn(invented["recommendation"], self.comments()[0])

    def test_the_advisor_is_never_silent_when_foundry_or_the_index_is_down(self):
        def foundry_down(question, profile):
            raise foundry.FoundryError("Foundry didn't answer after 3 attempts: HTTP 503")

        def index_down(response, job):
            raise ConnectionError("https://srch-secret.search.example unreachable")

        for name, kwargs in (("Foundry", {"ask": foundry_down}), ("the index", {"check": index_down})):
            with self.subTest(name):
                result = self.advise(**kwargs)
                self.assertEqual(result["state"], "unavailable")
                self.assertEqual(self.steps(), ["comment"])  # no branch, no draft, no pull request
                self.assertIn("could not answer", self.comments()[0])
                self.assertNotIn("srch-secret", "\n".join(self.lines + self.comments()))

    def test_a_failed_github_step_after_the_gate_says_so_on_the_issue(self):
        result = self.advise(client=FakeGitHub(fail_on="pull"))
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(self.steps(), ["branch", "commit", "pull", "comment"])
        self.assertIn("could not be completed", self.comments()[0])
        self.assertTrue(any("a GitHub step failed: GitHub returned HTTP 502" in line for line in self.lines))

    def test_a_github_outage_is_logged_and_never_raises(self):
        result = self.advise(client=FakeGitHub(fail_on="comment"), ask=lambda question, profile: foundry_response(status="failed"))
        self.assertEqual(result["state"], "incomplete")
        self.assertTrue(any("couldn't comment that the ADR draft is incomplete" in line for line in self.lines))

    def test_the_log_never_holds_the_question_or_the_answer(self):
        self.advise()
        text = "\n".join(self.lines)
        self.assertNotIn(self.job["question"], text)
        self.assertNotIn(answer()["recommendation"], text)


class FakeRepository:
    """The guarded client's reads at one commit, for the standards run."""

    def __init__(self, merged=True, agent_yaml=True):
        self.merged, self.agent_yaml, self.reads = merged, agent_yaml, []

    def on_default_branch(self, sha):
        return self.merged

    def default_branch(self):
        return "main"

    def read_text(self, path, ref):
        self.reads.append(path)
        if path.endswith("agent.yaml"):
            return (HERE / "agent.yaml").read_text(encoding="utf-8") if self.agent_yaml else None
        return (HERE / "eval_cases.jsonl").read_text(encoding="utf-8") if path.endswith("eval_cases.jsonl") else None

    def read_folder(self, folder, ref):
        self.reads.append(folder)
        return dict(FILES)


class StandardsRunTests(unittest.TestCase):
    """runs.publish_standards, the standards Logic App's steps as Python: merged only, then re-index, publish, evaluate."""
    sha = "a" * 40

    def publish(self, repository=None, reindex=None) -> dict:
        self.repository, self.steps, self.lines = repository or FakeRepository(), [], []

        def default_reindex(docs, spec):
            self.steps.append(("re-index", len(docs)))
            return {"index": "architecture-standards", "approved": len(docs), "new": [], "changed": ["STD-API-001 v1.0"],
                    "removed": [], "failed": []}

        def publish_agents(spec):
            self.steps.append(("publish",))
            return {profile: {"name": f"architecture-advisor-{profile}", "version": "2", "reused": True}
                    for profile in spec["profiles"]}

        def evaluate(spec, cases, published, label):
            self.steps.append(("evaluate", len(cases), label))
            return [{"cases": [case["id"] for case in cases if case["profile"] == profile]} for profile in published]

        tools = runs.StandardsTools(github=lambda: self.repository, reindex=reindex or default_reindex,
                                    publish=publish_agents, evaluate=evaluate)
        job = {"id": "5b7e1d0c9a2f", "sha": self.sha, "files": ["solutions/02-design-microsoft/standards/STD-API-001.md"]}
        return runs.publish_standards(job, tools, self.lines.append)

    def test_a_merged_change_is_reindexed_published_and_evaluated_in_order(self):
        result = self.publish()
        self.assertEqual(result["state"], "done")
        self.assertEqual(self.steps, [("re-index", len(DOCS)), ("publish",), ("evaluate", len(CASES), "commit aaaaaaa")])
        self.assertTrue(all(line.startswith("standards run 5b7e1d0c9a2f: ") for line in self.lines))
        self.assertTrue(any("1 changed" in line for line in self.lines))
        self.assertTrue(any("(reused)" in line for line in self.lines))

    def test_an_unmerged_commit_is_refused_before_anything_is_read(self):
        result = self.publish(FakeRepository(merged=False))
        self.assertEqual((result["state"], result["step"]), ("stopped", "check the commit"))
        self.assertEqual((self.repository.reads, self.steps), ([], []))
        self.assertIn("only merged changes are published", self.lines[-1])
        for sha in ("main", "a" * 39, "A" * 40, ""):
            with self.subTest(sha=sha), self.assertRaises(runs.StepError):
                runs.merged_commit(FakeRepository(), sha)

    def test_a_failed_step_stops_the_ones_after_it(self):
        def index_down(docs, spec):
            raise ConnectionError("https://srch-secret.search.example unreachable")

        result = self.publish(reindex=index_down)
        self.assertEqual((result["state"], result["step"]), ("stopped", "re-index the standards"))
        self.assertEqual(self.steps, [])  # never published nor evaluated from a partly indexed commit
        self.assertNotIn("srch-secret", self.lines[-1])
        result = self.publish(FakeRepository(agent_yaml=False))
        self.assertEqual((result["state"], result["step"]), ("stopped", "read the commit"))
        self.assertEqual(self.steps, [])

    def test_a_partly_indexed_commit_is_never_published(self):
        def some_refused(docs, spec):
            self.steps.append(("re-index", len(docs)))
            return {"index": "architecture-standards", "approved": len(docs), "new": [], "changed": [], "removed": [],
                    "failed": ["STD-API-001"]}

        result = self.publish(reindex=some_refused)
        self.assertEqual((result["state"], result["step"]), ("stopped", "re-index the standards"))
        self.assertEqual(self.steps, [("re-index", len(DOCS))])  # neither published nor evaluated
        self.assertIn("1 standard(s) were not indexed: STD-API-001", self.lines[-1])

class SetupFlowTests(unittest.TestCase):
    def test_the_manifest_asks_only_for_what_the_advisor_uses(self):
        app = setup_flow.manifest("octo/requesthub", "https://func.example", "AI-SDLC design advisor")
        self.assertFalse(app["public"])
        self.assertEqual(app["default_permissions"], {"contents": "write", "issues": "write", "pull_requests": "write",
                                                      "metadata": "read"})
        self.assertEqual(app["default_events"], ["issues", "push"])
        self.assertEqual(app["hook_attributes"]["url"], "https://func.example/api/github/webhook")
        self.assertEqual(app["redirect_url"], "https://func.example/api/github/setup/complete")

    def test_the_setup_page_posts_the_manifest_to_github(self):
        app = setup_flow.manifest("octo/requesthub", "https://func.example", 'name "with" <tags>')
        _, html_user = setup_flow.setup_page("octo/requesthub", False, "st4te", app)
        _, html_org = setup_flow.setup_page("octo/requesthub", True, "st4te", app)
        self.assertIn('action="https://github.com/settings/apps/new?state=st4te"', html_user)
        self.assertIn("https://github.com/organizations/octo/settings/apps/new?state=st4te", html_org)
        self.assertNotIn("<tags>", html_user)


class FakeMarkers:
    """The Function's marker blobs, in memory: claim creates once, swap replaces only a marker nobody changed."""

    def __init__(self):
        self.blobs, self.version = {}, 0

    def put(self, name, data):
        self.version += 1
        self.blobs[name] = (json.loads(json.dumps(data)), f"etag-{self.version}")

    def claim(self, name, data):
        if name in self.blobs:
            return False
        self.put(name, data)
        return True

    def read(self, name):
        return self.blobs.get(name, (None, None))

    def swap(self, name, data, etag):
        if name not in self.blobs or self.blobs[name][1] != etag:
            return False
        self.put(name, data)
        return True

    def release(self, *names):
        for name in names:
            self.blobs.pop(name, None)


class FunctionRouteTests(unittest.TestCase):
    """The Function's routes and queue functions, with Azure and GitHub replaced by fakes."""

    @classmethod
    def setUpClass(cls):
        import azure.functions as func
        cls.func = func
        with mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "octo/requesthub"}):
            import function_app
        cls.app = function_app
        cls.functions = {f.get_function_name(): f for f in function_app.app.get_functions()}

    def setUp(self):
        self.secrets = {"github-webhook-secret": "s3cret"}
        self.markers, self.queued, self.stored = FakeMarkers(), [], {}
        patches = [
            mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "octo/requesthub"}),
            mock.patch.object(self.app, "secret", side_effect=lambda name: self.secrets.get(name)),
            mock.patch.object(self.app, "claim", side_effect=self.markers.claim),
            mock.patch.object(self.app, "release", side_effect=self.markers.release),
            mock.patch.object(self.app, "read_marker", side_effect=self.markers.read),
            mock.patch.object(self.app, "swap_marker", side_effect=self.markers.swap),
            mock.patch.object(self.app, "enqueue", side_effect=lambda queue, message: self.queued.append((queue, message))),
            mock.patch.object(self.app, "store_secret", side_effect=lambda name, value: self.stored.__setitem__(name, value)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def call(self, name, method="POST", url="https://func.example/api/x", body=b"", headers=None, params=None):
        request = self.func.HttpRequest(method, url, body=body, headers=headers or {}, params=params or {})
        return self.functions[name].get_user_function()(request)

    def deliver(self, payload: dict, delivery: str | None = None, event: str = "issues"):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        return self.call("github_webhook", body=body, headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": event,
                                                               "X-GitHub-Delivery": delivery or str(uuid.uuid4())})

    def run_queue(self, name, data):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        return self.functions[name].get_user_function()(self.func.QueueMessage(body=body))

    def test_routes_queues_and_their_protection(self):
        triggers = {name: f.get_bindings()[0] for name, f in self.functions.items()}
        http = {name: binding.auth_level for name, binding in triggers.items() if binding.type == "httpTrigger"}
        self.assertEqual(http, {"github_webhook": self.func.AuthLevel.ANONYMOUS,  # GitHub's signature
                                "github_setup_complete": self.func.AuthLevel.ANONYMOUS,  # the one-time state
                                "github_setup": self.func.AuthLevel.FUNCTION, "github_status": self.func.AuthLevel.FUNCTION})
        queues = {name: (binding.queue_name, binding.connection) for name, binding in triggers.items()
                  if binding.type == "queueTrigger"}
        self.assertEqual(queues, {"advise": ("advisor-runs", "AzureWebJobsStorage"),
                                  "publish_standards": ("standards-runs", "AzureWebJobsStorage")})
        self.assertEqual(set(http) | set(queues), set(triggers))  # no other way in

    def test_a_redelivery_and_a_second_event_for_the_same_issue_start_one_run(self):
        events = WebhookTests()
        opened = self.deliver(events.opened())  # filed with the label: GitHub sends opened, then labeled
        first = self.deliver(events.payload(), "11111111-1111-1111-1111-111111111111")
        again = self.deliver(events.payload(), "11111111-1111-1111-1111-111111111111")
        relabeled = self.deliver(events.payload())
        self.assertEqual([opened.status_code, first.status_code, again.status_code, relabeled.status_code],
                         [200, 202, 200, 200])
        self.assertEqual(len(self.queued), 1)
        queue, message = self.queued[0]
        self.assertEqual(queue, "advisor-runs")
        self.assertEqual({key: message[key] for key in ("issue", "title", "profile", "question")},
                         {"issue": 7, "title": "Architecture question", "profile": "small-team",
                          "question": "Should triage run in-process?"})
        self.assertRegex(message["id"], r"^[0-9a-f]{12}$")
        self.assertIn(message["id"], json.loads(first.get_body())["result"])
        self.assertEqual(self.markers.read("issues/7.json")[0]["state"], "queued")

    def test_an_issue_from_an_outside_contributor_starts_nothing(self):
        events = WebhookTests()
        opened = self.deliver(events.opened(author_association="NONE"))
        labeled = self.deliver(events.payload(author_association="NONE"))
        self.assertEqual([opened.status_code, labeled.status_code], [200, 200])
        self.assertEqual(json.loads(opened.get_body())["result"], "ignored")
        self.assertIn("outside contributor", json.loads(labeled.get_body())["reason"])
        self.assertEqual(self.queued, [])
        self.assertIsNone(self.markers.read("issues/7.json")[0])

    def test_a_bad_signature_is_refused(self):
        response = self.call("github_webhook", body=b"{}", headers={"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "ping",
                                                                    "X-GitHub-Delivery": "33333333-3333-3333-3333-333333333333"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.markers.blobs, {})

    def test_a_failed_queue_write_releases_the_markers_for_a_redelivery(self):
        self.app.enqueue.side_effect = RuntimeError("https://stsecret.queue.example refused the message")
        with self.assertLogs("advisor", level="ERROR") as logs:
            response = self.deliver(WebhookTests().payload(), "44444444-4444-4444-4444-444444444444")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.markers.blobs, {})
        self.assertNotIn("stsecret", "\n".join(logs.output))

    def test_a_push_that_changes_the_standards_queues_a_standards_run(self):
        push = {"ref": "refs/heads/main", "after": "a" * 40, "repository": {"full_name": "octo/requesthub", "default_branch": "main"},
                "commits": [{"modified": ["solutions/02-design-microsoft/standards/STD-AI-001.md"]}]}
        response = self.deliver(push, event="push")
        self.assertEqual(response.status_code, 202)
        queue, message = self.queued[0]
        self.assertEqual((queue, message["sha"], message["files"]),
                         ("standards-runs", "a" * 40, ["solutions/02-design-microsoft/standards/STD-AI-001.md"]))

    def test_a_maintainer_retries_only_a_run_that_could_not_finish(self):
        labeled = dict(WebhookTests().payload(), action="labeled", label={"name": "design-advisor"})
        for state, since, retried in (("unavailable", 0, True), ("incomplete", 0, True), ("answered", 0, False),
                                      ("rejected", 0, False), ("running", 0, False), ("queued", 0, False),
                                      ("running", 16 * 60, True), (None, 0, False)):
            with self.subTest(state=state, since=since):
                self.markers.blobs.clear()
                self.queued.clear()
                old = {"run": "aaaaaaaaaaaa", "since": time.time() - since} | ({"state": state} if state else {})
                self.markers.put("issues/7.json", old)
                response = self.deliver(labeled)
                self.assertEqual(len(self.queued), 1 if retried else 0)
                marker = self.markers.read("issues/7.json")[0]
                self.assertEqual(marker["run"], self.queued[0][1]["id"] if retried else "aaaaaaaaaaaa")
                self.assertEqual(response.status_code, 202 if retried else 200)

    def test_the_advisor_run_records_its_state_and_yields_to_a_newer_run(self):
        job = {"id": "3f2a9c1b7d4e", "issue": 7, "title": "t", "profile": "small-team", "question": "Should triage run in-process?"}
        self.markers.put("issues/7.json", {"state": "queued", "run": "3f2a9c1b7d4e", "since": time.time()})
        with mock.patch.object(self.app.runs, "advise", return_value={"state": "answered"}) as advise, \
                mock.patch.object(self.app, "advisor_tools"):
            self.run_queue("advise", job)
            self.assertEqual(self.markers.read("issues/7.json")[0]["state"], "answered")
            self.assertEqual(advise.call_count, 1)
            self.run_queue("advise", job)  # a second copy of the same message: the issue isn't waiting for it
            self.assertEqual(advise.call_count, 1)
            self.markers.put("issues/7.json", {"state": "queued", "run": "999999999999", "since": time.time()})
            self.run_queue("advise", job)  # a newer run took the issue over: this one asks nothing
            self.assertEqual(advise.call_count, 1)
            self.assertEqual(self.markers.read("issues/7.json")[0]["run"], "999999999999")

    def test_only_a_run_the_webhook_queued_asks_the_agent(self):
        job = {"id": "3f2a9c1b7d4e", "issue": 8, "title": "t", "profile": "small-team", "question": "Should triage run in-process?"}
        with mock.patch.object(self.app.runs, "advise", return_value={"state": "answered"}) as advise, \
                mock.patch.object(self.app, "advisor_tools"):
            self.run_queue("advise", job)  # well formed, but no marker: the webhook never queued it
            self.assertIsNone(self.markers.read("issues/8.json")[0])
            self.app.read_marker.side_effect = ConnectionError("https://stsecret.blob.example unreachable")
            with self.assertLogs("advisor", level="ERROR") as logs:
                self.run_queue("advise", job)  # the marker can't be read: no proof the webhook queued it
            self.assertNotIn("stsecret", "\n".join(logs.output))
        advise.assert_not_called()

    def test_the_queues_drop_messages_the_webhook_did_not_write(self):
        with mock.patch.object(self.app.runs, "advise") as advise, \
                mock.patch.object(self.app.runs, "publish_standards") as publish, \
                self.assertLogs("advisor", level="ERROR"):
            for message in ({"id": "nope", "issue": 7, "profile": "small-team", "question": "q"},
                            {"id": "3f2a9c1b7d4e", "issue": 7, "profile": "admin", "question": "q"},
                            {"id": "3f2a9c1b7d4e", "issue": 0, "profile": "small-team", "question": "q"},
                            {"id": "3f2a9c1b7d4e", "issue": 7, "profile": "small-team", "question": "  "},
                            b"not json"):
                self.run_queue("advise", message)
            self.run_queue("publish_standards", {"sha": "a" * 40})
        advise.assert_not_called()
        publish.assert_not_called()
    def test_setup_stores_three_secrets_once_and_then_answers_409(self):
        blob = mock.MagicMock()
        blob.download_blob.return_value.readall.return_value = json.dumps({"state": "st4te", "created": time.time()}).encode()
        container = mock.MagicMock()
        container.get_blob_client.return_value = blob
        conversion = FakeResponse(201, {"id": 123, "slug": "ai-sdlc-design-advisor", "pem": "-----BEGIN-----",
                                        "webhook_secret": "w", "client_id": "Iv1.x", "client_secret": "never-stored"})
        with mock.patch.object(self.app, "state_container", return_value=container), \
                mock.patch("requests.post", return_value=conversion) as post:
            self.secrets.pop("github-webhook-secret")
            bad = self.call("github_setup_complete", method="GET", params={"state": "wrong", "code": "abcdef123456"})
            self.assertEqual(bad.status_code, 400)
            post.assert_not_called()
            blob.delete_blob.assert_called_once()  # a wrong state still burns the stored one: it works once
            done = self.call("github_setup_complete", method="GET", params={"state": "st4te", "code": "abcdef123456"})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(set(self.stored), {"github-app-id", "github-app-private-key", "github-webhook-secret"})
        self.assertNotIn("never-stored", self.stored.values())
        self.assertIn("ai-sdlc-design-advisor/installations/new", done.get_body().decode())
        self.secrets.update(self.stored)
        again = self.call("github_setup_complete", method="GET", params={"state": "st4te", "code": "abcdef123456"})
        self.assertEqual(again.status_code, 409)

    def test_a_connection_error_during_setup_never_logs_the_code(self):
        import requests
        blob = mock.MagicMock()
        blob.download_blob.return_value.readall.return_value = json.dumps({"state": "st4te", "created": time.time()}).encode()
        container = mock.MagicMock()
        container.get_blob_client.return_value = blob
        failure = requests.ConnectionError("Max retries exceeded with url: /app-manifests/codeSECRET1234/conversions")
        with mock.patch.object(self.app, "state_container", return_value=container), \
                mock.patch("requests.post", side_effect=failure), self.assertLogs("advisor", level="WARNING") as logs:
            response = self.call("github_setup_complete", method="GET", params={"state": "st4te", "code": "codeSECRET1234"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("codeSECRET1234", "\n".join(logs.output) + response.get_body().decode())
        self.assertEqual(self.stored, {})

    def test_empty_github_secrets_mean_not_connected(self):
        # Azure Resource Manager can't delete a Key Vault secret, and the vault is closed to the internet, so the README
        # disconnects GitHub by setting the GitHub secrets to empty values.
        self.secrets.update({"github-app-id": "", "github-app-private-key": "", "github-webhook-secret": "", "github-token": ""})
        status = json.loads(self.call("github_status", method="GET").get_body())
        self.assertEqual((status["connected"], status["webhookSecret"]), (False, False))
        self.assertEqual(self.deliver(WebhookTests().payload()).status_code, 503)
        self.assertFalse(self.app.connected())
        with self.assertRaises(self.app.NotConnected):
            self.app.github_client()


class ScriptErrorTests(unittest.TestCase):
    """setup_azure.py and evaluate.py print errors without the subscription, a resource, a host, or a key."""

    def test_errors_never_print_the_subscription_a_host_or_a_key(self):
        import requests
        sys.path.insert(0, str(HERE))
        from azd_env import describe_error

        path = "/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg-x/providers/Microsoft.Web/sites/func-abc123"
        outage = requests.ConnectionError(f"HTTPSConnectionPool(host='management.azure.com', port=443): Max retries "
                                          f"exceeded with url: {path}?api-version=2024-04-01&code=KEY123")
        refused = requests.HTTPError(f"403 Client Error: Forbidden for url: https://management.azure.com{path}",
                                     response=FakeResponse(403))
        sdk = RuntimeError("Failed to resolve 'srch-abc123.search.windows.net' for https://aif-abc123.services.ai.azure.com"
                           f"/api/projects/design (tenant 00000000-1111-2222-3333-444444444444, {path})")
        texts = [describe_error(exc) for exc in (outage, refused, sdk)]
        self.assertTrue(texts[0].startswith("ConnectionError: the request didn't complete"))
        self.assertEqual(texts[1], "HTTPError: HTTP 403")
        self.assertIn("Failed to resolve '<host>'", texts[2])
        for secret in ("00000000-1111", "func-abc123", "srch-abc123", "aif-abc123", "KEY123", "management.azure.com"):
            self.assertNotIn(secret, "\n".join(texts))


class EvaluateScriptTests(unittest.TestCase):
    """evaluate.py decides PASS from each item's own results, never from Foundry's run totals."""
    ALL = dict.fromkeys(checks.CHECK_KINDS, True)

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HERE))
        import evaluate
        cls.evaluate = evaluate

    @staticmethod
    def output(case_id, agent_failed=False, **results):
        """One output item; a result of None is an evaluator that errored."""
        item = mock.MagicMock()
        item.model_dump.return_value = {
            "datasource_item": {"id": case_id},
            "sample": {"error": {"code": "agent_error"} if agent_failed else None},
            "results": [{"name": f"advisor_{kind}", "passed": passed is True,
                         "sample": {"error": {"message": "An error occurred during grading"}} if passed is None else {}}
                        for kind, passed in results.items()]}
        return item

    @staticmethod
    def started_run(*outputs, cases):
        openai = mock.MagicMock()
        openai.evals.runs.output_items.list.return_value = list(outputs)
        return openai, {"runId": "r", "evalId": "e", "agent": "architecture-advisor-small-team v2", "cases": cases}

    def test_an_evaluator_that_could_not_grade_is_not_a_pass(self):
        openai, run = self.started_run(self.output("E02", **dict(self.ALL, citations=None)),
                               self.output("E04", **dict(self.ALL, access=False)), self.output("E06", **self.ALL),
                               cases=["E02", "E04", "E06"])
        self.assertEqual(self.evaluate.case_results(openai, run),
                         [("E02", [], ["citations"]), ("E04", ["access"], []), ("E06", [], [])])

    def test_an_answer_without_every_result_is_not_a_pass(self):
        openai, run = self.started_run(self.output("E03", agent_failed=True),  # the agent call failed: no results
                               self.output("E05", citations=True),  # 1 of 5 results
                               cases=["E03", "E05", "E09"])  # and no item at all for E09
        rows = {case_id: (failed, errors) for case_id, failed, errors in self.evaluate.case_results(openai, run)}
        self.assertEqual(rows["E03"], ([], [self.evaluate.NO_ANSWER, *checks.CHECK_KINDS]))
        self.assertEqual(rows["E05"], ([], ["access", "grounding", "abstention", "conflicts"]))
        self.assertEqual(rows["E09"], ([], [self.evaluate.NO_ITEM, *checks.CHECK_KINDS]))

    def test_only_a_fully_graded_run_can_exit_0(self):
        graded = [self.output(case_id, **self.ALL) for case_id in ("E01", "E02")]
        openai, run = self.started_run(*graded, cases=["E01", "E02"])
        completed = {"status": "completed", "errored": 0}

        def exit_code(runs, state):
            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                return self.evaluate.summarize(openai, runs, {"r": state}, time.monotonic())

        self.assertEqual(exit_code([run], completed), 0)
        self.assertEqual(exit_code([run], dict(completed, errored=1)), 2)  # Foundry counts an item in error
        self.assertEqual(exit_code([run], dict(completed, status="failed")), 2)
        self.assertEqual(exit_code([dict(run, cases=["E01"])], completed), 2)  # more results than cases
        openai.evals.runs.output_items.list.return_value = [graded[0], self.output("E02", agent_failed=True)]
        self.assertEqual(exit_code([run], completed), 2)
        openai.evals.runs.output_items.list.return_value = [graded[0], self.output("E02", **dict(self.ALL, access=False))]
        self.assertEqual(exit_code([run], completed), 1)


if __name__ == "__main__":
    unittest.main()
