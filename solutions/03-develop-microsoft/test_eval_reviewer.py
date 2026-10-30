"""Tests for the evaluation's scoring rules (review_graders.py, and how eval_reviewer.py reports them).

No Azure: the tests score stored results with --reuse --local in a temporary folder.
Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft -p "test_eval*.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_reviewer  # noqa: E402
import review_graders  # noqa: E402

CASES = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
RULE_IDS = ["approval-authority", "authorization-in-workflow", "contract-additive", "tests-with-changes", "synthetic-data"]
TITLES = ["Approval authority is untouched", "Authorization stays in RequestWorkflow", "The API contract changes only additively",
          "Behavior changes come with tests", "Data is synthetic"]


def good_item(case: dict) -> dict:
    """A result that passes every check for this case."""
    rules = [{"id": rid, "title": title, "result": "FAIL" if rid in case["expected_failures"] else "PASS"}
             for rid, title in zip(RULE_IDS, TITLES)]
    failed = sum(r["result"] == "FAIL" for r in rules)
    header = "✅ all 5 passed" if not failed else f"❌ {failed} of 5 failed"
    table = "\n".join(f"| {r['title']} | {'❌ FAIL' if r['result'] == 'FAIL' else '✅ PASS'} | x |" for r in rules)
    words = " ".join(group[0] for group in case["expect_mentions"])
    agent = {"summary": f"The change. {words}", "tests_note": "Tests ran.", "for_the_person": "Decide.",
             "observations": [], "rule_notes": []}
    return {"pr": case["pr"], "kind": case["kind"], "why": case["why"],
            "expected_failures": json.dumps(case["expected_failures"]), "expect_mentions": json.dumps(case["expect_mentions"]),
            "rules": json.dumps(rules), "review": f"**Team rules: {header}.**\n\n{table}\n\n**Commentary from the reviewer agent**",
            "agent": json.dumps(agent), "sandbox": json.dumps({"api": {"status": "passed"}, "web": {"status": "passed"}}),
            "_run": "test", "_status": "Succeeded"}


def run_main(items: list[dict], *args: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        (out / "results.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
        saved, eval_reviewer.OUT = eval_reviewer.OUT, out
        try:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = eval_reviewer.main(["--reuse", "--local", *args])
        finally:
            eval_reviewer.OUT = saved
    return code, stdout.getvalue() + stderr.getvalue()


class GraderTests(unittest.TestCase):
    def test_a_complete_good_result_passes_every_check(self):
        for case in CASES:
            item = good_item(case)
            for name, (fn, _) in review_graders.GRADERS.items():
                self.assertEqual(fn({}, item), 1.0, f"#{case['pr']} {name}")

    def test_missing_or_empty_output_never_passes(self):
        for case in CASES:
            empty = eval_reviewer.missing_result(case, "Failed")
            blank_agent = dict(good_item(case), agent=json.dumps({"summary": " ", "tests_note": "", "for_the_person": "",
                                                                  "observations": [], "rule_notes": []}))
            for name, (fn, _) in review_graders.GRADERS.items():
                self.assertEqual(fn({}, empty), 0.0, f"#{case['pr']} {name} on a missing result")
            for name in ("pr_review_advisory_only", "pr_review_useful_commentary"):
                self.assertEqual(review_graders.GRADERS[name][0]({}, blank_agent), 0.0, f"#{case['pr']} {name} on blank commentary")


class ReportingTests(unittest.TestCase):
    def test_every_case_passing_exits_0(self):
        code, out = run_main([good_item(c) for c in CASES])
        self.assertEqual(code, 0, out)

    def test_a_case_without_a_result_fails(self):
        code, out = run_main([good_item(c) for c in CASES[1:]])
        self.assertEqual(code, 1, out)
        self.assertIn(f"| #{CASES[0]['pr']} |", out)
        self.assertIn("no stored result", out)

    def test_a_check_that_raises_is_could_not_grade_and_exits_2(self):
        broken = [good_item(c) for c in CASES]
        broken[0]["rules"] = "{not json"
        code, out = run_main(broken)
        self.assertEqual(code, 2, out)
        self.assertIn("COULD NOT GRADE", out)

    def test_no_code_is_compiled_or_executed(self):
        for name in ("eval_reviewer.py", "review_graders.py"):
            source = (HERE / name).read_text(encoding="utf-8")
            for word in ("compile(", "exec(", "eval("):
                self.assertNotIn(word, source.replace("re.compile(", ""), f"{word} in {name}")


if __name__ == "__main__":
    unittest.main()
