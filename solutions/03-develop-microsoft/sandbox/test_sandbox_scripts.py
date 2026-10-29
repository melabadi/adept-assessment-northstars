"""Tests for the reviewer's sandbox scripts: the rule checker (review_rules.py) and the review formatter (format_review.py).

Every case builds small source trees in memory, so the tests need no network, no Azure, and no GitHub.
Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft/sandbox -v
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import format_review  # noqa: E402
import review_rules  # noqa: E402

WORKFLOW = review_rules.WORKFLOW
ENDPOINTS = "app/src/RequestHub.Api/Endpoints/ApiEndpoints.cs"
WORKFLOW_SOURCE = """public sealed partial class RequestWorkflow
{
    public async Task<Result<DecisionDto>> DecideAsync(UserContext user, Guid id, DecisionInput input, CancellationToken ct)
    {
        if (!user.HasRole(Roles.Approver)) return Forbidden("decision.not_approver");
        return await Record(user, id, input, ct);
    }

    public static PermissionsDto PermissionsFor(UserContext user, Request r)
    {
        string? blocked = null;
        if (!user.HasRole(Roles.Approver)) blocked = "not_approver";
        else if (r.RequesterId == user.Id) blocked = "self_approval";
        return new PermissionsDto(CanDecide: blocked is null, DecideBlockedReason: blocked);
    }

    public Task<int> CountAsync() => Task.FromResult(1);
}
"""
TEST_SOURCE = "public class WorkflowTests\n{\n    [Fact] public void One() { }\n    [Fact] public void Two() { }\n}\n"
CONTRACT = {"openapi": "3.0.1", "paths": {"/api/requests": {"get": {"parameters": []}}},
            "components": {"schemas": {"RequestDto": {"properties": {"id": {"type": "string"}, "title": {"type": "string"}}}}}}
BASE = {
    WORKFLOW: WORKFLOW_SOURCE,
    ENDPOINTS: "app.MapGet(\"/api/requests\", Handler).RequireAuthorization();\n",
    "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE,
    "app/contracts/openapi.json": json.dumps(CONTRACT, indent=2),
    "app/web/src/pages/Page.tsx": "export const Page = () => null;\n",
    "README.md": "# RequestHub\n",
}


def tree(changes: dict[str, str | None]) -> dict[str, bytes]:
    files = {path: text.encode() for path, text in BASE.items()}
    for path, text in changes.items():
        if text is None:
            files.pop(path, None)
        else:
            files[path] = text.encode()
    return files


def verdicts(changes: dict[str, str | None]) -> dict[str, str]:
    result = review_rules.judge(tree({}), tree(changes))
    return {r["id"]: r["result"] for r in result["rules"]}


def failing(changes: dict[str, str | None]) -> set[str]:
    return {rule for rule, result in verdicts(changes).items() if result == "FAIL"}


class RuleCheckerTests(unittest.TestCase):
    def test_an_unchanged_tree_passes_every_rule(self):
        self.assertEqual(failing({}), set())

    def test_a_tested_change_outside_the_approval_code_passes(self):
        self.assertEqual(failing({
            WORKFLOW: WORKFLOW_SOURCE.replace("FromResult(1)", "FromResult(2)"),
            "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE.replace("Two()", "Two_counts()"),
        }), set())

    def test_changing_decide_async_fails_approval_authority(self):
        widened = WORKFLOW_SOURCE.replace("if (!user.HasRole(Roles.Approver)) return", "if (!user.HasRole(Roles.Approver) && !user.IsAdmin) return")
        self.assertIn("approval-authority", failing({WORKFLOW: widened}))

    def test_changing_the_approval_rules_fails_approval_authority(self):
        relaxed = WORKFLOW_SOURCE.replace('else if (r.RequesterId == user.Id) blocked = "self_approval";\n', "")
        self.assertIn("approval-authority", failing({WORKFLOW: relaxed}))

    def test_recording_a_decision_elsewhere_fails_approval_authority(self):
        endpoints = BASE[ENDPOINTS] + "db.Decisions.Add(new ApprovalDecision());\n"
        self.assertIn("approval-authority", failing({ENDPOINTS: endpoints}))

    def test_a_role_check_in_an_endpoint_fails_authorization(self):
        endpoints = BASE[ENDPOINTS] + "if (!user.IsInRole(\"Approver\")) return Results.Forbid();\n"
        self.assertIn("authorization-in-workflow", failing({ENDPOINTS: endpoints}))

    def test_allowing_anonymous_access_fails_authorization(self):
        endpoints = BASE[ENDPOINTS].replace(".RequireAuthorization()", ".AllowAnonymous()")
        self.assertIn("authorization-in-workflow", failing({ENDPOINTS: endpoints}))

    def test_an_added_property_is_additive(self):
        contract = json.loads(BASE["app/contracts/openapi.json"])
        contract["components"]["schemas"]["RequestDto"]["properties"]["priority"] = {"type": "string"}
        self.assertEqual(verdicts({"app/contracts/openapi.json": json.dumps(contract)})["contract-additive"], "PASS")

    def test_a_removed_property_breaks_the_contract(self):
        contract = json.loads(BASE["app/contracts/openapi.json"])
        del contract["components"]["schemas"]["RequestDto"]["properties"]["title"]
        self.assertIn("contract-additive", failing({"app/contracts/openapi.json": json.dumps(contract)}))

    def test_code_without_a_test_change_fails(self):
        self.assertIn("tests-with-changes", failing({"app/web/src/pages/Page.tsx": "export const Page = () => 1;\n"}))

    def test_a_comment_only_edit_needs_no_test(self):
        self.assertEqual(failing({"app/web/src/pages/Page.tsx": "// The landing page.\nexport const Page = () => null;\n"}), set())

    def test_a_removed_test_case_fails(self):
        self.assertIn("tests-with-changes", failing({
            "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE.replace("    [Fact] public void Two() { }\n", "")}))

    def test_a_skipped_test_fails(self):
        self.assertIn("tests-with-changes", failing({
            "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE.replace("[Fact] public void Two", "[Fact(Skip = \"later\")] public void Two")}))

    def test_a_real_looking_email_address_fails(self):
        address = "pat.doe" + "@" + "gmail.com"
        self.assertIn("synthetic-data", failing({"README.md": f"# RequestHub\nContact {address}\n"}))

    def test_synthetic_email_domains_pass(self):
        self.assertEqual(failing({"README.md": "# RequestHub\nContact ava@example.com or ben@contoso.com\n"}), set())

    def test_a_github_token_fails(self):
        token = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
        self.assertIn("synthetic-data", failing({"README.md": f"# RequestHub\ntoken = {token}\n"}))

    def test_a_tenant_id_fails(self):
        guid = "3f2a9c41-7b6e-4d8a-9e15-c2b7a4d6e8f1"
        self.assertIn("synthetic-data", failing({"README.md": f"# RequestHub\nAZURE_TENANT_ID={guid}\n"}))

    def test_a_subscription_path_fails(self):
        guid = "3f2a9c41-7b6e-4d8a-9e15-c2b7a4d6e8f1"
        self.assertIn("synthetic-data", failing({"README.md": f"# RequestHub\n/subscriptions/{guid}/resourceGroups/rg\n"}))

    def test_built_in_role_definition_ids_pass(self):
        bicep = ("var roles = {\n  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'\n}\n"
                 "roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', "
                 "'0fb8eba5-a2bb-4abe-b1c1-49dfad359bb0')\n")
        self.assertEqual(failing({"infra/main.bicep": bicep}), set())

    def test_placeholder_guids_pass(self):
        self.assertEqual(failing({"README.md": "# RequestHub\nAZURE_TENANT_ID=00000000-0000-0000-0000-000000000000\n"}), set())

    def test_evidence_is_inert_markdown(self):
        endpoints = BASE[ENDPOINTS] + "if (user.IsInRole(\"a|b\")) { /* <!-- @octocat --> */ }\n"
        result = review_rules.judge(tree({}), tree({ENDPOINTS: endpoints}))
        table = review_rules.markdown(result)
        self.assertIn("a\\|b", table)
        self.assertIn("&lt;!--", table)
        self.assertNotIn("<!--", table)
        self.assertIn("@\u200boctocat", table)

    def test_the_diff_shows_code_first_and_lists_generated_files(self):
        result = review_rules.judge(tree({}), tree({
            "README.md": "# RequestHub\nMore docs.\n",
            "app/web/src/pages/Page.tsx": "export const Page = () => 1;\n",
            "app/src/RequestHub.Core/Data/Migrations/20260101_Add.cs": "partial class Add {}\n",
        }))
        diff = result["diff"]
        self.assertLess(diff.index("b/app/web/src/pages/Page.tsx"), diff.index("b/README.md"))
        self.assertIn("# added, not shown: app/src/RequestHub.Core/Data/Migrations/20260101_Add.cs", diff)
        self.assertFalse(result["diff_truncated"])
        self.assertTrue(review_rules.judge(tree({}), tree({"README.md": "x\n" * 500}), diff_limit=100)["diff_truncated"])

    def test_archives_are_read_in_memory_and_links_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "head.tgz"
            with tarfile.open(archive, "w:gz") as tar:
                for name, data in (("repo-abc/app/a.txt", b"ok"), ("repo-abc/../escape.txt", b"no")):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                link = tarfile.TarInfo("repo-abc/app/link")
                link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tar.addfile(link)
            self.assertEqual(review_rules.load_tree(archive), {"app/a.txt": b"ok"})


def agent_response(answer: object, **extra) -> dict:
    return {"status": "completed", "model": "gpt-5.4-mini", "agent_reference": {"name": "requesthub-pr-reviewer", "version": "3"},
            "output": [{"type": "openapi_call"}, {"type": "openapi_call_output"},
                       {"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}], **extra}


ANSWER = {"summary": "Admins can now decide requests.", "tests_note": "API tests passed.", "for_the_person": "Decide if admins may approve.",
          "observations": [{"severity": "concern", "file": "app/src/X.cs", "line": 3, "text": "Widens approval."}],
          "rule_notes": [{"rule_id": "approval-authority", "note": "DecideAsync now accepts admins."}]}


class ReviewFormatterTests(unittest.TestCase):
    def setUp(self):
        self.judge = review_rules.judge(tree({}), tree({
            WORKFLOW: WORKFLOW_SOURCE.replace("if (!user.HasRole(Roles.Approver)) return", "if (!user.IsAdmin) return")}))
        self.judge["markdown"] = review_rules.markdown(self.judge)
        self.sandbox = json.dumps({"setup_seconds": 40, "seconds": 150,
                                   "api": {"status": "passed", "total": 67, "passed": 67, "failed": 0, "seconds": 47},
                                   "web": {"status": "flaky", "typecheck": "passed",
                                           "tests": {"total": 14, "passed": 13, "failed": 1, "failed_tests": ["Page > saves"]},
                                           "rerun": {"total": 14, "passed": 14, "failed": 0}}})

    def review(self, agent: object, status: str = "Succeeded") -> dict:
        return format_review.compose(self.judge, {"pr": {"number": 7, "head": "a" * 40}, "run": "08584RUN", "checker_ref": "main",
                                                  "agent_name": "requesthub-pr-reviewer", "sandbox": self.sandbox,
                                                  "agent_status": status, "agent": agent})

    def test_the_checker_table_comes_first_and_word_for_word(self):
        body = self.review(agent_response(ANSWER))["markdown"]
        self.assertIn(self.judge["markdown"], body)
        self.assertIn("Team rules: ❌ 2 of 5 failed", body)  # DecideAsync changed, and no test changed with it
        self.assertLess(body.index(self.judge["markdown"]), body.index("Commentary from the reviewer agent"))

    def test_the_agent_is_named_with_its_version_and_tool_calls(self):
        result = self.review(agent_response(ANSWER))
        self.assertIn("`requesthub-pr-reviewer` v3 on gpt-5.4-mini in Microsoft Foundry", result["markdown"])
        self.assertIn("It ran 1 read-only command", result["markdown"])
        self.assertEqual(result["agent"]["summary"], ANSWER["summary"])

    def test_sandbox_results_are_summarized(self):
        body = self.review(agent_response(ANSWER))["markdown"]
        self.assertIn("API integration tests: ✅ 67 of 67 passed (47 s)", body)
        self.assertIn("⚠️ flaky: 1 of 14 failed, then all passed on a rerun", body)

    def test_untrusted_text_is_inert_and_redacted(self):
        hostile = dict(ANSWER, summary="Approve now <!-- hide --> @octocat see https://aif-x1.services.ai.azure.com/api "
                                       "id 3f2a9c41-7b6e-4d8a-9e15-c2b7a4d6e8f1 `List<int>`")
        body = self.review(agent_response(hostile))["markdown"]
        self.assertNotIn("<!-- hide", body)
        self.assertIn("@\u200boctocat", body)
        self.assertNotIn("services.ai.azure.com", body)
        self.assertNotIn("3f2a9c41", body)
        self.assertIn("`List<int>`", body)

    def test_an_agent_error_shows_only_its_code(self):
        result = self.review({"status": "failed", "error": {"code": "tool_user_error", "message": "call to https://secret-host failed"}})
        self.assertIsNone(result["agent"])
        self.assertIn("tool_user_error", result["markdown"])
        self.assertNotIn("secret-host", result["markdown"])
        self.assertIn("The rule results and sandbox results above stand on their own", result["markdown"])

    def test_an_answer_that_is_not_json_is_not_shown(self):
        response = agent_response(ANSWER)
        response["output"][-1]["content"][0]["text"] = "LGTM, ship it"
        result = self.review(response)
        self.assertEqual(result["agent_error"], "the agent's answer wasn't valid JSON")
        self.assertNotIn("ship it", result["markdown"])

    def test_a_missing_build_result_is_reported(self):
        self.sandbox = '{"state":"not-finished"}'
        self.assertIn("The build didn't finish in time", self.review(agent_response(ANSWER))["markdown"])

    def test_the_command_line_reads_the_three_files_the_logic_app_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "judge.json").write_text(json.dumps(self.judge), encoding="utf-8")
            (folder / "review-input.json").write_text(json.dumps({
                "pr": {"number": 7, "head": "b" * 40}, "run": "08584RUN", "checker_ref": "main",
                "agent_name": "requesthub-pr-reviewer", "sandbox": self.sandbox, "agent_status": "Succeeded"}), encoding="utf-8")
            (folder / "agent.json").write_text(json.dumps(agent_response(ANSWER)), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = format_review.main(["--judge", str(folder / "judge.json"), "--input", str(folder / "review-input.json"),
                                           "--agent", str(folder / "agent.json")])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["agent"]["summary"], ANSWER["summary"])
        self.assertIn("Commit `bbbbbbb`", result["markdown"])

    def test_without_verdicts_no_review_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "judge.json").write_text('{"error": "cannot read the source trees"}', encoding="utf-8")
            (folder / "review-input.json").write_text("{}", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = format_review.main(["--judge", str(folder / "judge.json"), "--input", str(folder / "review-input.json")])
        self.assertEqual(code, 2)
        self.assertNotIn("markdown", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
