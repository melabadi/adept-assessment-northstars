"""Tests for the evaluation's scoring rules (review_graders.py, and how eval_reviewer.py reports them).

No Azure: the tests score stored results with --reuse --local in a temporary folder.
Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft -p "test_eval*.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_reviewer  # noqa: E402
import review_graders  # noqa: E402

CASES = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
GRADER_CHECKS = [json.loads(line) for line in (HERE / "grader_checks.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
RULE_IDS = ["approval-authority", "authorization-in-workflow", "contract-additive", "tests-with-changes", "synthetic-data"]
TITLES = ["Approval authority is untouched", "Authorization stays in RequestWorkflow", "The API contract changes only additively",
          "Behavior changes come with tests", "Data is synthetic"]


def good_item(case: dict) -> dict:
    """A result that passes every check for this case: each labelled finding stated where it is, as a concern."""
    rules = [{"id": rid, "title": title, "result": "FAIL" if rid in case["expected_failures"] else "PASS"}
             for rid, title in zip(RULE_IDS, TITLES)]
    failed = sum(r["result"] == "FAIL" for r in rules)
    header = "✅ all 5 passed" if not failed else f"❌ {failed} of 5 failed"
    table = "\n".join(f"| {r['title']} | {'❌ FAIL' if r['result'] == 'FAIL' else '✅ PASS'} | x |" for r in rules)
    observations = [{"severity": "concern", "file": finding["file"], "line": 1,
                     "text": f"Here: {finding['states'][0].replace('*', '')}."} for finding in case["expect_findings"]]
    agent = {"summary": "The change.", "tests_note": "Tests ran.", "for_the_person": "Decide.",
             "observations": observations, "rule_notes": []}
    return {"pr": case["example"], "id": case["id"], "kind": case["kind"], "why": case["why"],
            "expected_failures": json.dumps(case["expected_failures"]), "expect_findings": json.dumps(case["expect_findings"]),
            "rules": json.dumps(rules), "review": f"**Team rules: {header}.**\n\n{table}\n\n**Commentary from the reviewer agent**",
            "agent": json.dumps(agent), "sandbox": json.dumps({"api": {"status": "passed"}, "web": {"status": "passed"}}),
            "_run": "test", "_status": "Succeeded"}


def run_main(items: list[dict], *args: str) -> tuple[int, str, str]:
    """Runs eval_reviewer.main on these stored results. Returns the exit code, what it printed, and report.md."""
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
        report = (out / "report.md").read_text(encoding="utf-8") if (out / "report.md").exists() else ""
    return code, stdout.getvalue() + stderr.getvalue(), report


class GraderTests(unittest.TestCase):
    def test_a_complete_good_result_passes_every_check(self):
        for case in CASES:
            item = good_item(case)
            for name, (fn, _) in review_graders.GRADERS.items():
                self.assertEqual(fn({}, item), 1.0, f"{case['id']} {name}")

    def test_missing_or_empty_output_never_passes(self):
        for case in CASES:
            empty = eval_reviewer.missing_result(case, "Failed")
            blank_agent = dict(good_item(case), agent=json.dumps({"summary": " ", "tests_note": "", "for_the_person": "",
                                                                  "observations": [], "rule_notes": []}))
            for name, (fn, _) in review_graders.GRADERS.items():
                self.assertEqual(fn({}, empty), 0.0, f"{case['id']} {name} on a missing result")
            for name in ("pr_review_advisory_only", "pr_review_useful_commentary"):
                self.assertEqual(review_graders.GRADERS[name][0]({}, blank_agent), 0.0, f"{case['id']} {name} on blank commentary")

    def test_a_denial_that_names_the_problem_earns_no_commentary_credit(self):
        """#99, as reported: "There is no SQL injection here." mentions injection, yet concludes the opposite."""
        case = next(c for c in CASES if c["id"] == "sql-concatenation")
        denial = dict(good_item(case), agent=json.dumps({
            "summary": "ListAsync now searches with FromSqlRaw.", "tests_note": "One search test failed.",
            "for_the_person": "Look at the failing search test.", "rule_notes": [],
            "observations": [{"severity": "info", "file": "app/src/RequestHub.Core/Services/RequestWorkflow.cs", "line": 48,
                              "text": "There is no SQL injection here."}]}))
        self.assertLess(review_graders.grade_useful_commentary({}, denial), 1.0)

    def test_every_flagged_or_known_bad_case_labels_a_finding_with_a_file(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(bool(case["expect_findings"]), case["kind"] != "known-good")
                for finding in case["expect_findings"]:
                    self.assertTrue(finding["states"] and finding["file"].startswith("app/"))
                    for claim in finding["states"]:
                        self.assertFalse(set(claim.replace("*", "").split()) & {"not", "no", "never", "without", "cannot"},
                                         f"{claim!r}: claims are positive statements")

    def test_paired_reviews_share_their_words_and_evidence(self):
        """Each right review has a wrong twin that points at the same file and line and differs in what it concludes."""
        by_id = {row["id"]: row for row in GRADER_CHECKS}
        for row in GRADER_CHECKS:
            if not row["id"].endswith("/right"):
                continue
            with self.subTest(review=row["id"]):
                twin = by_id[row["id"].replace("/right", "/wrong")]
                where = lambda r: [(o["file"], o["line"]) for o in json.loads(r["item"]["agent"])["observations"]]  # noqa: E731
                self.assertEqual(where(row), where(twin))
                self.assertTrue(all(row["expect"].values()))
                self.assertFalse(twin["expect"]["pr_review_useful_commentary"])
        self.assertTrue(any(row["split"] == "held-out" for row in GRADER_CHECKS))

    def test_every_grader_check_is_graded_as_labelled(self):
        """grader_checks.jsonl: right reviews pass every check; wrong ones fail only the commentary check. A wrong review
        that points at the right place earns the evidence half (0.5), never the whole."""
        for row in GRADER_CHECKS:
            with self.subTest(review=row["id"]):
                graded = {name: fn({}, row["item"]) for name, (fn, _) in review_graders.GRADERS.items()}
                self.assertEqual({name: score >= 1 for name, score in graded.items()}, row["expect"])
                if not row["expect"]["pr_review_useful_commentary"] and row["item"]["kind"] != "known-good":
                    self.assertEqual(graded["pr_review_useful_commentary"], 0.5)


class ReportingTests(unittest.TestCase):
    def test_every_case_passing_exits_0(self):
        code, out, _ = run_main([good_item(c) for c in CASES])
        self.assertEqual(code, 0, out)

    def test_a_case_without_a_result_fails(self):
        code, out, report = run_main([good_item(c) for c in CASES[1:]])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, rf"(?m)^{CASES[0]['id']} +#0 +{CASES[0]['kind']} +FAIL +FAIL")
        self.assertIn("no stored result", out)
        self.assertIn(f"| {CASES[0]['id']} | #0 |", report)

    def test_the_terminal_table_lines_up_and_report_md_stays_markdown(self):
        code, out, report = run_main([good_item(c) for c in CASES])
        lines = out.splitlines()
        header = next(line for line in lines if line.startswith("Case "))
        columns = [m.start() for m in re.finditer(r"(?<=  )\S", header)]
        rows = [line for line in lines if re.match(r"[a-z-]+ +#\d+ ", line)] + [next(line for line in lines if line.startswith("Passed"))]
        self.assertEqual(len(rows), len(CASES) + 1)
        for row in rows:
            for column in columns[2:-1]:  # every check's column, between Kind and Dry run
                self.assertEqual(row[column - 1], " ", row)
                self.assertNotEqual(row[column], " ", row)
        self.assertNotIn("|", out)
        for name, (_, title) in review_graders.GRADERS.items():
            self.assertRegex(out, rf"(?m)^{name.removeprefix('pr_review_')} +{re.escape(title)}$")
        self.assertIn("| Case | PR | Kind |", report)

    def test_a_check_that_raises_is_could_not_grade_and_exits_2(self):
        broken = [good_item(c) for c in CASES]
        broken[0]["rules"] = "{not json"
        code, out, _ = run_main(broken)
        self.assertEqual(code, 2, out)
        self.assertIn("COULD NOT GRADE", out)

    def test_the_grader_check_runs_here_without_azure(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = eval_reviewer.main(["--check-graders", "--local"])
        printed = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(code, 0, printed)
        self.assertIn("sql-concatenation/reported", printed)
        self.assertRegex(printed, r"paired: (\d+)/\1 reviews graded as labelled")
        self.assertRegex(printed, r"held-out: (\d+)/\1 reviews graded as labelled")

    def test_no_code_is_compiled_or_executed(self):
        for name in ("eval_reviewer.py", "review_graders.py"):
            source = (HERE / name).read_text(encoding="utf-8")
            for word in ("compile(", "exec(", "eval("):
                self.assertNotIn(word, source.replace("re.compile(", ""), f"{word} in {name}")


class FoundryRunTests(unittest.TestCase):
    """What eval_reviewer.py makes of a finished Foundry evaluation run."""
    items = eval_reviewer.score([good_item(c) for c in CASES])

    def run_with(self, passed: dict[str, int] | None = None, failed: dict[str, int] | None = None, drop: str = "",
                 errored: int = 0, total: int | None = None):
        from types import SimpleNamespace
        n = len(self.items)
        criteria = [SimpleNamespace(testing_criteria=name, passed=(passed or {}).get(name, n), failed=(failed or {}).get(name, 0))
                    for name in review_graders.GRADERS if name != drop]
        counts = SimpleNamespace(total=n if total is None else total, errored=errored, passed=n - errored, failed=0)
        return SimpleNamespace(status="completed", result_counts=counts, per_testing_criteria_results=criteria)

    def test_a_complete_run_that_agrees_is_trusted(self):
        self.assertIsNone(eval_reviewer.foundry_verdict(self.run_with(), self.items))

    def test_a_check_foundry_could_not_grade_is_could_not_grade(self):
        # Seen live: every item of one check said "An error occurred during grading", yet the run counted 10 passed
        # and 0 errored, and the check itself passed 0 and failed 0.
        problem = eval_reviewer.foundry_verdict(self.run_with(passed={"pr_review_rule_verdicts": 0}), self.items)
        self.assertIn("COULD NOT GRADE", problem)
        self.assertIn(f"pr_review_rule_verdicts on 0 of {len(self.items)}", problem)

    def test_two_gradings_of_the_same_results_complete_each_other(self):
        # Seen live: the first grading lost every item of rule_verdicts, the second every item of useful_commentary.
        graded: dict = {}
        first = eval_reviewer.foundry_verdict(self.run_with(passed={"pr_review_rule_verdicts": 0}), self.items, graded)
        self.assertIn("COULD NOT GRADE", first)
        self.assertIsNone(eval_reviewer.foundry_verdict(self.run_with(passed={"pr_review_useful_commentary": 0}),
                                                        self.items, graded))
        # Both gradings missing the same check still can't be trusted.
        graded = {}
        eval_reviewer.foundry_verdict(self.run_with(passed={"pr_review_rule_verdicts": 0}), self.items, graded)
        self.assertIn("COULD NOT GRADE", eval_reviewer.foundry_verdict(
            self.run_with(passed={"pr_review_rule_verdicts": 0}), self.items, graded))

    def test_a_check_missing_from_the_run_is_could_not_grade(self):
        problem = eval_reviewer.foundry_verdict(self.run_with(drop="pr_review_sandbox_ran"), self.items)
        self.assertIn("COULD NOT GRADE", problem)
        self.assertIn("pr_review_sandbox_ran", problem)

    def test_errored_items_or_too_few_results_are_not_trusted(self):
        self.assertIn("COULD NOT GRADE 2 of", eval_reviewer.foundry_verdict(self.run_with(errored=2), self.items))
        self.assertIn("results for", eval_reviewer.foundry_verdict(self.run_with(total=9), self.items))

    def test_a_run_that_disagrees_with_the_local_scores_is_not_trusted(self):
        n = len(self.items)
        problem = eval_reviewer.foundry_verdict(
            self.run_with(passed={"pr_review_useful_commentary": n - 1}, failed={"pr_review_useful_commentary": 1}), self.items)
        self.assertIn("differ from the local ones", problem)

    def test_only_a_grading_failure_is_graded_again(self):
        n = len(self.items)
        self.assertTrue(eval_reviewer.grade_again(eval_reviewer.foundry_verdict(
            self.run_with(passed={"pr_review_verdicts_verbatim": 0}), self.items)))
        self.assertTrue(eval_reviewer.grade_again(eval_reviewer.foundry_verdict(self.run_with(errored=1), self.items)))
        self.assertFalse(eval_reviewer.grade_again(None))
        self.assertFalse(eval_reviewer.grade_again(eval_reviewer.foundry_verdict(
            self.run_with(passed={"pr_review_useful_commentary": n - 1}, failed={"pr_review_useful_commentary": 1}), self.items)))
        self.assertFalse(eval_reviewer.grade_again(eval_reviewer.foundry_verdict(self.run_with(total=n - 1), self.items)))


if __name__ == "__main__":
    unittest.main()
