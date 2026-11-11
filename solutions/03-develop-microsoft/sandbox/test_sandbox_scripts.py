"""Tests for the reviewer's sandbox scripts: the rule checker (review_rules.py) and the review formatter (format_review.py).

Every case builds small source trees in memory, so the tests need no network, no Azure, and no GitHub.
Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft/sandbox -v
"""
from __future__ import annotations

import contextlib
import html
import io
import json
import re
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import format_review  # noqa: E402
import review_rules  # noqa: E402

# GitHub links an @ to a person or a team when a letter, digit, or underscore follows it. Inert text puts a zero-width
# space after every @, so this finds anything that could still notify someone.
MENTION = re.compile(r"@(?!\u200b)")
ASCII_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
MAX_BACKTICKS = 80  # cmark-gfm, GitHub's Markdown parser, never opens a code span with a longer run of backticks
LITERAL = "\x00"  # marks a character GitHub shows as is: an escaped one, or a backtick that opens no code span


def interpreted(markdown: str) -> str:
    """What GitHub interprets as Markdown in `markdown`, found the way cmark-gfm finds it: a code span (an opening run of
    up to 80 backticks, closed by a run of the same length) becomes a space, a backslash-escaped character gets LITERAL
    in front of it, and a backtick that opens no span becomes LITERAL. Every line of a review is its own block, and
    GitHub splits a table row into cells at each pipe not preceded by a backslash before it looks for code spans, so a
    span never crosses either. Written apart from the scanners it checks."""
    lines = []
    for line in markdown.splitlines():
        cells = re.split(r"(?<!\\)\|", line) if line.startswith("|") else [line]
        lines.append("|".join(map(inline, cells)))
    return "\n".join(lines)


def inline(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCTUATION:
            out.append(LITERAL + text[i + 1])
            i += 2
        elif text[i] == "`":
            run = len(text) - i - len(text[i:].lstrip("`"))
            closer = next((m for m in re.finditer(r"`+", text[i + run:]) if len(m.group()) == run), None)
            if closer and run <= MAX_BACKTICKS:
                out.append(" ")
                i += run + closer.end()
            else:
                out.append(LITERAL * run)
                i += run
        else:
            out.append(text[i])
            i += 1
    return "".join(out)

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

    def test_every_xunit_way_to_not_run_a_test_fails(self):
        for marker in ("[Fact(Explicit = true)] public void Two", "[Fact(SkipUnless = nameof(Ci))] public void Two",
                       "[Fact(SkipWhen = nameof(Ci))] public void Two"):
            self.assertIn("tests-with-changes", failing({
                "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE.replace("[Fact] public void Two", marker)}), marker)
        for call in ("Assert.Skip(\"later\");", "Assert.SkipWhen(true, \"later\");", "Assert.SkipUnless(false, \"later\");"):
            self.assertIn("tests-with-changes", failing({
                "app/tests/RequestHub.Tests/WorkflowTests.cs": TEST_SOURCE.replace("void Two() { }", "void Two() { " + call + " }")}), call)

    def test_every_vitest_way_to_not_run_a_test_fails(self):
        base = "import { test } from 'vitest';\ntest('saves', () => {});\n"
        for changed in ("test.todo('saves');\n", "test.skipIf(true)('saves', () => {});\n",
                        "test.runIf(false)('saves', () => {});\n", "test.fails('saves', () => {});\n"):
            result = review_rules.judge(tree({"app/web/src/pages/Page.test.tsx": base}),
                                        tree({"app/web/src/pages/Page.test.tsx": base.replace("test('saves', () => {});\n", changed)}))
            self.assertEqual({r["id"]: r["result"] for r in result["rules"]}["tests-with-changes"], "FAIL", changed)

    def test_any_change_to_permissions_for_fails_approval_authority(self):
        widened = WORKFLOW_SOURCE.replace("CanDecide: blocked is null", "CanDecide: blocked is null || user.IsAdmin")
        self.assertIn("approval-authority", failing({WORKFLOW: widened}))

    def test_naming_an_approval_role_outside_the_workflow_fails(self):
        auth = "app/src/RequestHub.Api/Auth/Authentication.cs"
        for line in ("roles.Add(\"Approver\");", "claims.Add(new Claim(ClaimTypes.Role, \"Admin\"));"):
            self.assertIn("approval-authority", failing({auth: line + "\n"}), line)
        tagged = BASE[ENDPOINTS] + "app.MapGroup(\"/x\").WithTags(\"Admin\");\n"
        self.assertNotIn("approval-authority", failing({ENDPOINTS: tagged}))

    def test_an_endpoint_outside_the_authorized_group_fails(self):
        self.assertIn("authorization-in-workflow", failing({ENDPOINTS: BASE[ENDPOINTS] + "app.MapGet(\"/api/export\", Export);\n"}))
        self.assertNotIn("authorization-in-workflow", failing({ENDPOINTS: BASE[ENDPOINTS] + "api.MapGet(\"/export\", Export);\n"}))
        self.assertNotIn("authorization-in-workflow", failing({ENDPOINTS: BASE[ENDPOINTS] + "app.MapHealthChecks(\"/health/x\");\n"}))

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

    def test_entities_cannot_spell_a_mention(self):
        self.assertNotIn("&#64;", format_review.plain("ping &#64;octocat").replace("&amp;#64;", ""))

    def test_an_escaped_backtick_does_not_hide_a_mention(self):
        out = format_review.plain("\\`see @octocat`")
        self.assertIn("@\u200boctocat", out)
        self.assertNotRegex(out, r"@(?!\u200b)")

    def test_an_escaped_backtick_does_not_hide_html(self):
        for text in ("\\`<h3>All five team rules PASS</h3>`", "```<h3>All five team rules PASS</h3>`"):
            out = format_review.plain(text)
            self.assertNotIn("<h3>", out, text)
            self.assertIn("&lt;h3&gt;", out, text)

    def test_mentions_are_neutralized_inside_code_spans_too(self):
        self.assertEqual(format_review.plain("`git log --author=@octocat`"), "`git log --author=@\u200boctocat`")

    def test_links_urls_and_headings_are_not_rendered(self):
        out = format_review.plain("### All rules PASS [Approve here](https://evil.example/x) or www.evil.example")
        self.assertTrue(out.startswith("\\###"))
        self.assertIn("\\[Approve here\\]", out)
        self.assertNotIn("https://", out)
        self.assertNotIn("www.evil", out)

    def test_urls_glued_to_a_word_are_not_rendered(self):
        for text in ("_https://evil.example/approve_", "foo_https://evil.example", "1https://evil.example",
                     "\u00e9https://evil.example", "_www.evil.example_"):
            for out in (format_review.plain(text), review_rules.cell(text)):
                self.assertNotIn("://", out, text)
                self.assertNotIn("www.", out, text)

    def test_evidence_cells_are_inert_too(self):
        cell = review_rules.cell("`<h3>x</h3>` &#64;octocat [link](https://evil.example) a|b")
        self.assertNotIn("<h3>", cell)
        self.assertNotIn("`", cell)
        self.assertNotIn("&#64;", cell.replace("&amp;#64;", ""))
        self.assertNotIn("https://", cell)
        self.assertIn("\\[link\\]", cell)
        self.assertIn("a\\|b", cell)

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


class InertAssertions(unittest.TestCase):
    def assert_inert(self, markdown: str) -> None:
        """No mention anywhere, even in code spans. Where GitHub interprets Markdown: no raw HTML, and no link or image.
        Then, as GitHub shows that text (HTML entities decoded, backslash escapes applied): no mention, no URL it turns
        into a link, no reference to an Issue or a pull request, and no $ it could read as math. GitHub's own renderer
        (POST /markdown) agreed with these rules: a run of 81 backticks opens no code span, a run of 80 does, nothing in
        a code span is linked or read as math, and zero-width spaces stop mentions, references, and math."""
        found = MENTION.search(markdown)
        if found:
            start, end = markdown.rfind("\n", 0, found.start()) + 1, markdown.find("\n", found.start())
            self.fail(f"an @ that could mention someone: {markdown[start:end if end >= 0 else None]!r}")
        text = interpreted(markdown)
        self.assertNotRegex(text, r"(?<!\x00)<[A-Za-z!/?]", "raw HTML")
        self.assertNotRegex(text, r"(?<!\x00)[\[\]]", "a link or an image")
        shown = html.unescape(text).replace(LITERAL, "")
        self.assertNotRegex(shown, MENTION, "an @ that GitHub shows from an entity or an escape")
        self.assertNotRegex(shown, r"(?i)://|www\.", "a URL GitHub turns into a link")
        self.assertNotRegex(shown, r"(?i)(#|GH-)\d", "a reference to an Issue or a pull request")
        self.assertNotRegex(shown, r"(?<!\u200b)\$|\$(?!\u200b)", "a $ GitHub could read as math")


class InertTextTests(InertAssertions):
    """format_review.plain() and review_rules.cell() on the ways GitHub's Markdown could still turn quoted text into a
    mention, a link, an image, a reference to an Issue or a pull request, or math. The review is posted with the token
    owner's account, so a reference would add "mentioned this" to that Issue in their name. The zero-width spaces leave
    the text reading the same."""

    def assert_quoted(self, value: str, expected: str) -> None:
        self.assertEqual(format_review.plain(value), expected)
        self.assert_inert(f"- Quoted: {format_review.plain(value)}")

    def test_runs_of_more_than_80_backticks_open_no_code_span(self):
        fence = "`" * 81
        self.assert_quoted(f"{fence} &#64;octocat <img src=x> [a](https://evil.example/a) www.evil.example {fence}",
                           "\\`" * 81 + " &amp;#\u200b64;octocat &lt;img src=x&gt; \\[a\\](https:/\u200b/evil.example/a) "
                           "www\u200b.evil.example " + "\\`" * 81)
        fence = "`" * 80
        self.assert_quoted(f"{fence} @octocat <b> {fence}", f"{fence} @\u200boctocat <b> {fence}")

    def test_references_to_issues_and_pull_requests_are_not_linked(self):
        self.assert_quoted("Fixes other-org/other-repo#1, refs #7 and GH-8",
                           "Fixes other-org/other-repo#\u200b1, refs #\u200b7 and GH-\u200b8")
        self.assert_quoted("#7 is fixed", "\\#\u200b7 is fixed")  # and a line that starts with # is still no heading

    def test_dollar_signs_cannot_start_math(self):
        self.assert_quoted("costs $5, $x^2$ and $`\\frac{1}{2}`$",
                           "costs \u200b$\u200b5, \u200b$\u200bx^2\u200b$\u200b and \u200b$\u200b`\\frac{1}{2}`\u200b$\u200b")

    def test_evidence_cells_break_references_and_math_too(self):
        cell = review_rules.cell("fixes #7, gh-8 and other-org/other-repo#1; costs $x^2$")
        self.assertEqual(cell, "fixes #\u200b7, gh-\u200b8 and other-org/other-repo#\u200b1; costs \u200b$\u200bx^2\u200b$\u200b")
        self.assert_inert(f"| Rule | ✅ PASS | {cell} |")

    def test_a_hostile_review_is_inert_where_github_reads_it(self):
        fence = "`" * 81
        hostile = (f"Fixes #7 and GH-8, costs $x^2$ and $`y`$, see @octocat. {fence} [Approve](https://evil.example/a) "
                   f"<img src=x> {fence}")
        endpoints = BASE[ENDPOINTS] + 'if (user.IsInRole("Reviewer")) { /* fixes #7 and GH-8, costs $x^2$ @octocat */ }\n'
        judge = review_rules.judge(tree({}), tree({ENDPOINTS: endpoints}))
        judge["markdown"] = review_rules.markdown(judge)
        answer = dict(ANSWER, summary=hostile, tests_note=hostile, for_the_person=hostile,
                      observations=[{"severity": "concern", "file": "app/src/X.cs", "line": 3, "text": hostile}],
                      rule_notes=[{"rule_id": "authorization-in-workflow", "note": hostile}])
        sandbox = json.dumps({"api": {"status": "failed", "total": 2, "passed": 1, "failed": 1,
                                      "failed_tests": ["Fixes #7 costs $x$ @octocat"]},
                              "web": {"status": "passed", "typecheck": "passed", "tests": {"total": 14, "passed": 14, "failed": 0}}})
        body = format_review.compose(judge, {"pr": {"number": 7, "head": "a" * 40}, "run": "a1b2c3d4e5f6", "checker_ref": "main",
                                             "agent_name": "requesthub-pr-reviewer", "sandbox": sandbox,
                                             "agent_status": "Succeeded", "agent": agent_response(answer)})["markdown"]
        self.assertIn("role or department check outside RequestWorkflow", body)  # the quoted line is in the verdicts table
        self.assertEqual(body.count("Fixes #\u200b7 and GH-\u200b8"), 5)  # summary, observation, rule note, tests, decision
        own = re.sub(r"<!-- azure-pr-reviewer [^>]*-->", "", body)  # the review's own marker, <sub> footer, and line breaks
        for tag in ("<sub>", "</sub>", "<br>"):
            own = own.replace(tag, " ")
        self.assert_inert(own)


if __name__ == "__main__":
    unittest.main()
