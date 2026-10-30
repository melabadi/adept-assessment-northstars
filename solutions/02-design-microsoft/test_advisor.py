"""Offline tests for the Design · Microsoft solution. No Azure or GitHub access is needed.

They prove the parts that must never depend on the model:
  - the standards parse into index documents, and the evaluation labels agree with what each profile may retrieve;
  - the gate (function/advisor_core/checks.py) rejects invented, out-of-scope, misversioned, or misquoted citations,
    and reads the retrieved standards from every shape Azure reports them in;
  - the code Foundry runs as evaluators is the gate's code, uses the standard library only, and scores items right;
  - the Function's guards: webhook signatures, one run per delivery and per issue, writes only to
    refs/heads/design/advisor-*, only the Logic App identity on the work routes, and a one-time app-manifest setup
    that stores exactly three secrets and answers 409 once connected.
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
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "function"))
from advisor_core import agents, auth, checks, evaluation, github, knowledge, report, setup_flow, standards, webhook  # noqa: E402

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
           "index": "architecture-standards", "scopes": ["all", "small-team"], "workflowRun": "08584000000000000000",
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
        self.assertIn("could not be completed", report.incomplete_markdown("08584"))
        self.assertIn("could not answer", report.unavailable_markdown("08584"))

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
        body = "### Operating profile\n\nsmall-team\n\n### Question\n\nShould triage run in-process?"
        return {"action": "opened", "repository": {"full_name": self.repo, "default_branch": "main"},
                "issue": {"number": 7, "title": "Architecture question", "state": "open", "body": body,
                          "labels": [{"name": "design-advisor"}], **issue}}

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
        labeled = dict(self.payload(), action="labeled", label={"name": "design-advisor"})
        self.assertEqual(webhook.classify("issues", labeled, self.repo)["route"], "advisor")
        for name, event, payload in (
                ("other label", "issues", dict(self.payload(), action="labeled", label={"name": "bug"})),
                ("no label", "issues", self.payload(labels=[])),
                ("closed", "issues", self.payload(state="closed")),
                ("pull request", "issues", self.payload(pull_request={})),
                ("other repo", "issues", dict(self.payload(), repository={"full_name": "octo/other"})),
                ("comment", "issue_comment", self.payload())):
            with self.subTest(name):
                self.assertEqual(webhook.classify(event, payload, self.repo)["route"], "ignore")

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
            return FakeResponse(200, [p for p in self.pulls if p["head"] == params["head"]])
        if method == "POST" and path == "/pulls":
            self.pulls.append({"head": f"octo:{json['head']}", "number": 34, "html_url": "https://github.com/octo/requesthub/pull/34"})
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


class CallerTests(unittest.TestCase):
    """Only the Logic Apps' managed identity may call the Function's work routes."""

    tenant, client_id, principal = "tenant-id", "logic-client-id", "logic-object-id"

    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, **overrides) -> str:
        import jwt
        now = int(time.time())
        claims = {"aud": auth.CALLER_AUDIENCE, "iss": f"https://sts.windows.net/{self.tenant}/", "oid": self.principal,
                  "appid": self.client_id, "iat": now, "nbf": now, "exp": now + 600}
        claims.update(overrides)
        return "Bearer " + jwt.encode(claims, self.key, algorithm="RS256")

    def caller(self, header):
        return auth.caller(header, self.tenant, self.client_id, self.principal, signing_key=self.key.public_key())

    def test_the_logic_app_identity_is_accepted(self):
        self.assertEqual(self.caller(self.token())["oid"], self.principal)

    def test_everyone_else_is_refused(self):
        for name, header in (("no token", None), ("basic", "Basic abc"),
                             ("other identity", self.token(oid="someone-else")),
                             ("other client", self.token(appid="another-app")),
                             ("other audience", self.token(aud="https://management.azure.com/")),
                             ("other tenant", self.token(iss="https://sts.windows.net/other/")),
                             ("expired", self.token(exp=int(time.time()) - 60))):
            with self.subTest(name), self.assertRaises(auth.Unauthorized):
                self.caller(header)


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


class FunctionRouteTests(unittest.TestCase):
    """The Function's routes, with Azure and GitHub replaced by fakes."""

    @classmethod
    def setUpClass(cls):
        import azure.functions as func
        cls.func = func
        with mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "octo/requesthub"}):
            import function_app
        cls.app = function_app
        cls.routes = {f.get_function_name(): f for f in function_app.app.get_functions()}

    def setUp(self):
        self.secrets = {"github-webhook-secret": "s3cret"}
        self.markers, self.started, self.stored = set(), [], {}
        patches = [
            mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "octo/requesthub", "AZURE_TENANT_ID": "t",
                                           "LOGIC_APP_CLIENT_ID": "c", "LOGIC_APP_PRINCIPAL_ID": "p"}),
            mock.patch.object(self.app, "secret", side_effect=lambda name: self.secrets.get(name)),
            mock.patch.object(self.app, "claim", side_effect=self.claim),
            mock.patch.object(self.app, "release", side_effect=lambda *names: self.markers.difference_update(names)),
            mock.patch.object(self.app, "start_workflow", side_effect=lambda name, payload: self.started.append((name, payload))),
            mock.patch.object(self.app, "store_secret", side_effect=lambda name, value: self.stored.__setitem__(name, value)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def claim(self, name, data):
        if name in self.markers:
            return False
        self.markers.add(name)
        return True

    def call(self, name, method="POST", url="https://func.example/api/x", body=b"", headers=None, params=None):
        request = self.func.HttpRequest(method, url, body=body, headers=headers or {}, params=params or {})
        return self.routes[name].get_user_function()(request)

    def deliver(self, payload: dict, delivery: str, event: str = "issues"):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        return self.call("github_webhook", body=body, headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": event,
                                                               "X-GitHub-Delivery": delivery})

    def test_routes_and_their_protection(self):
        levels = {name: next(b for b in f.get_bindings() if b.type == "httpTrigger").auth_level for name, f in self.routes.items()}
        self.assertEqual(levels["github_setup"], self.func.AuthLevel.FUNCTION)
        self.assertEqual(levels["github_status"], self.func.AuthLevel.FUNCTION)
        self.assertEqual(set(self.routes), {"github_webhook", "github_setup", "github_setup_complete", "github_status",
                                            "advisor_check", "repo_write", "standards_sync", "agents_publish",
                                            "evaluations_start"})

    def test_a_redelivery_and_a_second_event_for_the_same_issue_start_one_run(self):
        payload = WebhookTests().payload()
        first = self.deliver(payload, "11111111-1111-1111-1111-111111111111")
        again = self.deliver(payload, "11111111-1111-1111-1111-111111111111")
        labeled = self.deliver(dict(payload, action="labeled", label={"name": "design-advisor"}), "22222222-2222-2222-2222-222222222222")
        self.assertEqual([first.status_code, again.status_code, labeled.status_code], [202, 200, 200])
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0][1], {"issue": 7, "title": "Architecture question", "profile": "small-team",
                                              "question": "Should triage run in-process?"})

    def test_a_bad_signature_is_refused(self):
        response = self.call("github_webhook", body=b"{}", headers={"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "ping",
                                                                    "X-GitHub-Delivery": "33333333-3333-3333-3333-333333333333"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.markers, set())

    def test_a_failed_start_releases_the_markers_for_a_redelivery(self):
        self.app.start_workflow.side_effect = RuntimeError("the Logic App refused the run: HTTP 500")
        response = self.deliver(WebhookTests().payload(), "44444444-4444-4444-4444-444444444444")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.markers, set())

    def test_work_routes_refuse_callers_without_the_logic_app_token(self):
        for name in ("advisor_check", "repo_write", "standards_sync", "agents_publish", "evaluations_start"):
            with self.subTest(name=name):
                self.assertEqual(self.call(name, body=b"{}", headers={"Authorization": "Bearer not-a-jwt"}).status_code, 401)

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

    def test_the_merge_path_refuses_an_unmerged_commit(self):
        unmerged = mock.MagicMock()
        unmerged.on_default_branch.return_value = False
        with mock.patch.object(self.app.auth, "caller", return_value={}), \
                mock.patch.object(self.app, "github_client", return_value=unmerged):
            for name in ("standards_sync", "agents_publish", "evaluations_start"):
                with self.subTest(name=name):
                    response = self.call(name, body=json.dumps({"sha": "b" * 40}).encode())
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("not on the default branch", response.get_body().decode())
        unmerged.read_folder.assert_not_called()


class SecretHandlingTests(unittest.TestCase):
    def test_a_connection_error_never_carries_the_trigger_url(self):
        import requests

        import function_app
        url = "https://prod-1.example.logic.azure.com/workflows/x/triggers/manual/paths/invoke?api-version=1&sig=SECRETSIG"
        with mock.patch.object(function_app, "secret", return_value=url), \
                mock.patch("requests.post", side_effect=requests.ConnectionError(f"Max retries exceeded with url: {url}")):
            with self.assertRaises(RuntimeError) as raised:
                function_app.start_workflow("advisor-workflow-url", {})
        self.assertNotIn("SECRETSIG", str(raised.exception))
        self.assertIn("ConnectionError", str(raised.exception))


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
