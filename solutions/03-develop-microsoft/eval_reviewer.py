#!/usr/bin/env python3
"""Evaluate the Azure pull request reviewer on labelled pull requests (Develop phase, Microsoft track).

What this script does:
  1. Reads eval_cases.jsonl: labelled changes to RequestHub, each known-good, flagged (a good change that a rule rightly
     flags for a person), or known-bad, with the rules that should fail and the findings the commentary must state: what
     the problem is, and the file where it is. Each came from a pull request of the original repository (its number is
     the case's "example"), and is recreated as a closed pull request in your repository by --setup (eval_prs.py), which
     keeps their numbers and reuses them.
  2. Runs the deployed reviewer on each one in dry-run mode: it posts {"pr": <number>} to the Function's dry-runs route,
     which queues a review that does everything a real review does (rule checker, sandbox build and tests, agent,
     review formatter) but posts nothing to GitHub. The script polls the route until the review's result is ready.
  3. Scores every result on this machine with the five checks in review_graders.py.
  4. Registers the same checks in Microsoft Foundry as code-based evaluators (preview) and runs a Foundry evaluation over
     the same results, so they appear in the project's Evaluation view. Foundry sometimes fails every item of one check
     ("An error occurred during grading"); such a run is graded once more. --local skips this step; the local scores in
     step 3 are the fallback. The report keeps Foundry's first grading apart from the one it repeated.

Grader checks: --check-graders grades the fixed reviews in grader_checks.jsonl instead, without any dry run: a right and
a wrong commentary for labelled cases, and for held-out changes the checks were never tuned on, that use the same words
and point at the same file and line, and differ only in what they conclude. It scores them here and, unless --local,
with the evaluators in Foundry, and shows that both tell the two apart and agree with each other.

The dry-runs route needs the Function's key, so the script reads it from Azure Resource Manager each time, sends it in a
header, and never prints or saves it. Results go to out/eval/ (results.jsonl and report.md), which git ignores.

Configuration: this solution's azd environment (after `azd up`) or environment variables: AZURE_SUBSCRIPTION_ID,
AZURE_RESOURCE_GROUP, REVIEWER_FUNCTION_APP, REVIEWER_FUNCTION_HOST, FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT,
GITHUB_REPOSITORY, and REVIEWER_EVAL_PRS (written by --setup). You need Contributor (or Website Contributor) on the
resource group, to read the Function's key, and the Foundry User role on the Foundry account; `azd up` gives you both as
the person who runs it. --setup and --cleanup use your git and GitHub CLI. The Function needs GITHUB_REVIEW_TOKEN, as for
a real review.

Usage
  python eval_reviewer.py --setup                  # once per repository: create the evaluation's pull requests, or reuse them
  python eval_reviewer.py                          # every case: dry runs, local scores, then a Foundry evaluation
  python eval_reviewer.py --cases admins-decide    # only these cases (ids from eval_cases.jsonl)
  python eval_reviewer.py --reuse                  # score the results of the last dry runs again, without new runs
  python eval_reviewer.py --local                  # skip the Foundry evaluation
  python eval_reviewer.py --check-graders          # grade the fixed right and wrong reviews in grader_checks.jsonl
  python eval_reviewer.py --parallel 5             # dry runs at a time (default 4; each uses two of the pools' ten sessions)
  python eval_reviewer.py --show-url               # also print the Foundry report link (it contains resource ids)
  python eval_reviewer.py --cleanup                # close the evaluation's pull requests and delete their branches

Exit codes: 0 every check passed for every case; 1 at least one check failed (a case without a result fails every
check); 2 configuration or service error, the evaluation's pull requests not set up, a check that COULD NOT GRADE, or a
Foundry evaluation that is incomplete, has errored items, has a check that didn't grade every item (even when graded once
more), or disagrees with the local scores. With --check-graders: 0 every fixed review was graded as labelled here and
Foundry graded it the same way; 1 a grade differs from its label or Foundry's differs from the local one; 2 Foundry could
not grade. With --setup or --cleanup: 0 done, 2 git or GitHub refused a step.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import setting, utf8_stdout  # noqa: E402
from review_graders import GRADERS  # noqa: E402
import eval_prs  # noqa: E402

OUT = HERE / "out" / "eval"
ARM = "https://management.azure.com"
WEB_API = "api-version=2024-04-01"
FINISHED = {"done": "Succeeded", "skipped": "Skipped", "failed": "Failed"}
EVAL_NAME = "Azure pull request reviewer: labelled pull requests"
# Custom evaluators are a preview feature of Foundry: their calls must opt in.
PREVIEW = {"Foundry-Features": "Evaluations=V1Preview"}
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "pr": {"type": "integer"}, "id": {"type": "string"}, "kind": {"type": "string"}, "why": {"type": "string"},
        "expected_failures": {"type": "string"}, "expect_findings": {"type": "string"}, "rules": {"type": "string"},
        "review": {"type": "string"}, "agent": {"type": "string"}, "sandbox": {"type": "string"},
    },
    "required": ["pr", "kind", "expected_failures", "expect_findings", "rules", "review", "agent", "sandbox"],
}


class Reviewer:
    """The deployed Function's dry-runs route, called with the Function's key, which Azure Resource Manager hands to
    the caller's Azure CLI or developer sign-in. The key lives only in this object and in a request header."""

    def __init__(self, credential: DefaultAzureCredential):
        self.credential = credential
        self.base = f"https://{setting('REVIEWER_FUNCTION_HOST')}/api/dry-runs"
        self._key: str | None = None

    def call(self, method: str, url: str, body: object = None, headers: dict | None = None) -> tuple[int, object]:
        request = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
                return response.status, json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, json.loads(data)
            except ValueError:
                return exc.code, None

    def key(self) -> str:
        if self._key is None:
            site = (f"{ARM}/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
                    f"/providers/Microsoft.Web/sites/{setting('REVIEWER_FUNCTION_APP')}")
            token = self.credential.get_token(f"{ARM}/.default").token
            status, keys = self.call("POST", f"{site}/host/default/listKeys?{WEB_API}", headers={"Authorization": f"Bearer {token}"})
            key = ((keys or {}).get("functionKeys") or {}).get("default") if isinstance(keys, dict) else None
            if status != 200 or not key:
                raise RuntimeError(f"couldn't read the Function's key (HTTP {status})")
            self._key = key
        return self._key

    def start_dry_run(self, pr: int) -> str:
        """Queue one dry run and return its id."""
        status, answer = self.call("POST", self.base, {"pr": pr}, {"x-functions-key": self.key()})
        if status != 202 or not isinstance(answer, dict) or not answer.get("id"):
            raise RuntimeError(f"the Function didn't queue a dry run of #{pr} (HTTP {status})")
        return str(answer["id"])

    def wait(self, review_id: str, timeout: int = 2700) -> dict:
        """The dry run's final state: {"state": "done" | "skipped" | "failed", ...}, or {"state": "TimedOut"}."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(15)
            status, answer = self.call("GET", f"{self.base}/{review_id}", headers={"x-functions-key": self.key()})
            if status == 200 and isinstance(answer, dict) and answer.get("state") in FINISHED:
                return answer
            if status not in (200, 404):  # 404: the review hasn't saved its state yet
                raise RuntimeError(f"the Function didn't return dry run {review_id} (HTTP {status})")
        return {"state": "TimedOut"}


def review_case(reviewer: Reviewer, case: dict, pr: int) -> dict:
    """Dry-run the reviewer on the case's pull request in this repository (pr, from eval_prs) and keep its result."""
    started = time.time()
    try:
        review_id = reviewer.start_dry_run(pr)
        result = reviewer.wait(review_id)
        state = FINISHED.get(result.get("state"), str(result.get("state")))
        if state == "Failed":
            state = f"Failed at {result.get('step')}: {result.get('error')}"
        result = result if result.get("state") == "done" else {}
    except (RuntimeError, OSError) as exc:
        review_id, state, result = None, f"error: {exc}", {}
    print(f"  {case['id']:<22} #{pr:<5} {state:<10} {int(time.time() - started):>4} s", flush=True)
    return {
        "pr": pr, "id": case["id"], "kind": case["kind"], "why": case["why"],
        "expected_failures": json.dumps(case["expected_failures"]), "expect_findings": json.dumps(case["expect_findings"]),
        "rules": json.dumps(result.get("rules") or []), "review": result.get("review") or "",
        "agent": json.dumps(result.get("agent")), "sandbox": result.get("sandbox") or "",
        "_run": review_id, "_status": state,
    }


def missing_result(case: dict, status: str, pr: int = 0) -> dict:
    """A labelled case without a reviewer result: every check scores it 0, so it can never pass."""
    return {"pr": pr, "id": case["id"], "kind": case["kind"], "why": case["why"],
            "expected_failures": json.dumps(case["expected_failures"]), "expect_findings": json.dumps(case["expect_findings"]),
            "rules": "[]", "review": "", "agent": "null", "sandbox": "", "_run": None, "_status": status}


def score(items: list[dict]) -> list[dict]:
    """Scores every item with every check. A check that raises is recorded as None: COULD NOT GRADE, never a pass."""
    for item in items:
        item["_scores"] = {}
        for name, (fn, _) in GRADERS.items():
            try:
                item["_scores"][name] = round(float(fn({}, item)), 3)
            except Exception as exc:  # report it; don't let one bad item stop the others
                item["_scores"][name] = None
                item.setdefault("_errors", []).append(f"{name}: {type(exc).__name__}")
    return items


def report(items: list[dict]) -> str:
    """The scores as a Markdown table, for out/eval/report.md."""
    names = list(GRADERS)
    lines = ["| Case | PR | Kind | " + " | ".join(GRADERS[n][1] for n in names) + " | Dry run |",
             "| --- | --- | --- | " + " | ".join("---" for _ in names) + " | --- |"]
    for item in items:
        cells = ["⚠️ COULD NOT GRADE" if item["_scores"][n] is None else "✅" if item["_scores"][n] >= 1
                 else f"❌ {item['_scores'][n]:.2f}" for n in names]
        lines.append(f"| {item.get('id', '')} | #{item['pr']} | {item['kind']} | " + " | ".join(cells) + f" | {item['_status']} |")
    passed = [sum(1 for i in items if (i["_scores"][n] or 0) >= 1) for n in names]
    lines.append("| **Passed** | | | " + " | ".join(f"**{p}/{len(items)}**" for p in passed) + " | |")
    return "\n".join(lines)


def terminal_report(items: list[dict]) -> str:
    """The same scores as a plain-text table that lines up in a terminal. The columns are the checks' names in Foundry,
    without their pr_review_ prefix, and a legend below gives each check's title."""
    names = list(GRADERS)
    short = [n.removeprefix("pr_review_") for n in names]

    def cell(score: float | None) -> str:
        return "COULD NOT GRADE" if score is None else "pass" if score >= 1 else "FAIL" if score <= 0 else f"FAIL {score:.2f}"

    rows = [["Case", "PR", "Kind", *short, "Dry run"]]
    rows += [[str(i.get("id", "")), f"#{i['pr']}", str(i["kind"]), *(cell(i["_scores"][n]) for n in names), str(i["_status"])]
             for i in items]
    passed = [sum(1 for i in items if (i["_scores"][n] or 0) >= 1) for n in names]
    rows.append(["Passed", "", "", *(f"{p}/{len(items)}" for p in passed), ""])
    widths = [max(len(row[c]) for row in rows) for c in range(len(rows[0]))]
    lines = ["  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip() for row in rows]
    legend = [f"{s.ljust(max(map(len, short)))}  {GRADERS[n][1]}" for s, n in zip(short, names)]
    return "\n".join(lines + [""] + legend)


def grader_source(fn) -> str:
    import inspect
    return re.sub(r"^def \w+\(", "def grade(", inspect.getsource(fn), count=1)


def foundry_setup() -> tuple:
    """Register the checks as code-based evaluators (a new version only when a check's code changed) and return
    (OpenAI client, evaluation). A new evaluator version gets a new evaluation, so a run is never scored by an older
    version of a check."""
    from azure.ai.projects import AIProjectClient

    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    criteria, registered = [], False
    for name, (fn, title) in GRADERS.items():
        code = grader_source(fn)
        try:
            versions = list(project.evaluators.list_versions(name=name, headers=PREVIEW))
        except Exception:  # the first run: the evaluator doesn't exist yet
            versions = []
        current = next((v for v in versions if (v.get("definition") or {}).get("code_text") == code), None)
        if current is None:
            current = project.evaluators.create_version(name=name, headers=PREVIEW, evaluator_version={
                "name": name, "display_name": title, "categories": ["quality"],
                "description": (fn.__doc__ or title).strip(),
                "definition": {
                    "type": "code", "code_text": code,
                    "init_parameters": {"type": "object", "required": ["deployment_name", "pass_threshold"],
                                        "properties": {"deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"}}},
                    "metrics": {"result": {"type": "continuous", "desirable_direction": "increase", "min_value": 0.0, "max_value": 1.0}},
                    "data_schema": {"type": "object", "required": ["item"], "properties": {"item": ITEM_SCHEMA}},
                }})
            registered = True
            print(f"  registered evaluator {name} v{current.get('version')}")
        criteria.append({"type": "azure_ai_evaluator", "name": name, "evaluator_name": name,
                         "initialization_parameters": {"deployment_name": model, "pass_threshold": 1.0}})
    client = project.get_openai_client()
    existing = None if registered else next((e for e in client.evals.list(limit=100) if e.name == EVAL_NAME
                                             and sorted(c.name for c in e.testing_criteria) == sorted(GRADERS)), None)
    evaluation = existing or client.evals.create(
        name=EVAL_NAME, data_source_config={"type": "custom", "item_schema": ITEM_SCHEMA, "include_sample_schema": False},
        testing_criteria=criteria)
    return client, evaluation


def foundry_grade(client, evaluation, items: list[dict], name: str):
    """One Foundry run over these items (their fields, without the script's own "_" keys), once it finished."""
    content = [{"item": {k: v for k, v in item.items() if not k.startswith("_")}} for item in items]
    run = client.evals.runs.create(eval_id=evaluation.id, name=name,
                                   data_source={"type": "jsonl", "source": {"type": "file_content", "content": content}})
    print(f"  Foundry evaluation run started: {run.name}")
    while run.status not in ("completed", "failed", "canceled"):
        time.sleep(10)
        run = client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
    print(f"  Foundry evaluation run {run.status}.")
    for result in run.per_testing_criteria_results or []:
        print(f"    {result.testing_criteria:<40} passed {result.passed}, failed {result.failed}")
    return run


def foundry_evaluation(items: list[dict], show_url: bool) -> str | None:
    """Register the checks as code-based evaluators, then evaluate the same items in Foundry. Returns None when Foundry's
    results are complete and agree with the local scores, otherwise why they can't be trusted."""
    client, evaluation = foundry_setup()
    versions = sorted({m.group(1) for i in items for m in [re.search(r"`requesthub-pr-reviewer` v(\d+)", i["review"])] if m})
    graded: dict = {}
    for attempt in (1, 2):
        run = foundry_grade(client, evaluation, items,
                            f"{len(items)} labelled pull request{'s' if len(items) != 1 else ''} · agent "
                            f"v{', v'.join(versions) or '?'} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
        problem = foundry_verdict(run, items, graded)
        if attempt == 2 or not grade_again(problem):
            break
        print(f"  First grading: {problem}. Grading the same results in Foundry once more; a check graded on every item "
              "in either grading counts.")
    if not problem and attempt == 2:
        print("  Across the two gradings, Foundry graded every check on every item, and its pass counts match the local ones.")
    if show_url and run.report_url:
        print(f"  Report: {run.report_url}")
    else:
        print(f"  See it in the Foundry portal: your project > Evaluation > \"{EVAL_NAME}\".")
    return problem


def grade_again(problem: str | None) -> bool:
    """Foundry's code-based evaluators sometimes fail every item of one check ("An error occurred during grading"),
    a different check each time. Such a run is graded once more; a run that disagrees with the local scores isn't."""
    return bool(problem) and problem.startswith("COULD NOT GRADE")


def foundry_verdict(run, items: list[dict], graded_before: dict | None = None) -> str | None:
    """None when a finished Foundry run graded every item with every check and agrees with the local scores,
    otherwise why it can't be trusted. graded_before ({check: items passed}, updated in place) carries the checks an
    earlier grading of the same results graded on every item: the results and the code are the same, so a check graded
    in either grading counts."""
    counts = run.result_counts
    if run.status != "completed":
        return f"the run ended {run.status}"
    if counts is None or counts.total != len(items):
        return f"it returned {getattr(counts, 'total', 0)} results for {len(items)} pull requests"
    if counts.errored:
        return f"COULD NOT GRADE {counts.errored} of {len(items)} items"
    # An item can count as passed while one of its checks errored ("An error occurred during grading"): that check
    # then neither passes nor fails it. Every check must have graded every item.
    graded = {r.testing_criteria: (r.passed or 0) + (r.failed or 0) for r in run.per_testing_criteria_results or []}
    known = graded_before if graded_before is not None else {}
    for result in run.per_testing_criteria_results or []:
        if graded.get(result.testing_criteria) == len(items):
            known.setdefault(result.testing_criteria, result.passed)
    short = [f"{name} on {graded.get(name, 0)} of {len(items)}" for name in GRADERS if name not in known]
    if short:
        return f"COULD NOT GRADE: Foundry graded {', '.join(short)} items"
    local = {n: sum(1 for i in items if (i["_scores"][n] or 0) >= 1) for n in GRADERS}
    foundry = {n: known[n] for n in GRADERS}
    if any(foundry.get(n) != local[n] for n in GRADERS):
        return f"its pass counts {foundry} differ from the local ones {local}"
    return None


def fixed_grades(client, evaluation, run) -> dict[str, dict[str, bool | None]]:
    """Each fixed review's grade per check in a finished run: True, False, or None when Foundry couldn't grade it. A
    jsonl run reports the item's fields flattened ("item.check")."""
    graded = {}
    for output in client.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id):
        data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
        source = data.get("datasource_item") or {}
        check = source.get("check") or source.get("item.check") or (source.get("item") or {}).get("check") or "?"
        results = {r.get("name"): r for r in data.get("results") or []}
        graded[check] = {name: None if name not in results or (results[name].get("sample") or {}).get("error")
                         or results[name].get("passed") is None else bool(results[name]["passed"]) for name in GRADERS}
    return graded


def check_graders(local_only: bool) -> int:
    """Grade grader_checks.jsonl's fixed reviews here and, unless local_only, in Foundry; compare both with the labels.
    The reviews are fixed, so when Foundry can't grade a check the same reviews are graded once more."""
    rows = [json.loads(line) for line in (HERE / "grader_checks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    items = score([dict(row["item"]) for row in rows])
    local = {item["check"]: {name: (item["_scores"][name] or 0) >= 1 for name in GRADERS} for item in items}
    foundry = None
    if not local_only:
        client, evaluation = foundry_setup()
        foundry = {row["id"]: dict.fromkeys(GRADERS) for row in rows}
        for attempt in (1, 2):
            run = foundry_grade(client, evaluation, items, f"{len(items)} fixed reviews (grader checks) · run {attempt} · "
                                                           f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
            for check, grades in fixed_grades(client, evaluation, run).items():
                for name, grade in grades.items():
                    if check in foundry and foundry[check][name] is None:
                        foundry[check][name] = grade
            if all(grade is not None for grades in foundry.values() for grade in grades.values()):
                break
            print("  Foundry couldn't grade some checks; grading the same reviews once more.")
    short = {name: name.removeprefix("pr_review_") for name in GRADERS}
    width = max(len("Review"), *(len(row["id"]) for row in rows)) + 2
    print(f"\n{'Review':<{width}} {'Split':<9} " + " ".join(f"{s:<18}" for s in short.values()) + " Foundry")
    wrong, differs, ungraded = [], [], []
    for row in rows:
        mine = local[row["id"]]
        cells = [f"{('pass' if mine[n] else 'FAIL') + ('' if mine[n] == row['expect'][n] else '!'):<18}" for n in GRADERS]
        wrong += [f"{row['id']} {short[n]}" for n in GRADERS if mine[n] != row["expect"][n]]
        if foundry is None:
            column = "-"
        elif any(grade is None for grade in foundry[row["id"]].values()):
            column = "COULD NOT GRADE"
            ungraded.append(row["id"])
        elif foundry[row["id"]] != mine:
            column = "differs: " + ", ".join(short[n] for n in GRADERS if foundry[row["id"]][n] != mine[n])
            differs.append(row["id"])
        else:
            column = "same"
        print(f"{row['id']:<{width}} {row['split']:<9} " + " ".join(cells) + f" {column}")
    for split in ("paired", "held-out"):
        mine = [row for row in rows if row["split"] == split]
        right = sum(1 for row in mine if local[row["id"]] == row["expect"])
        same = "" if foundry is None else f"; Foundry graded {sum(1 for r in mine if foundry[r['id']] == local[r['id']])}" \
                                         f"/{len(mine)} the same way"
        print(f"{split}: {right}/{len(mine)} reviews graded as labelled{same}")
    sys.stdout.flush()
    if wrong:
        print(f"error: graded differently from the labels: {', '.join(wrong)}", file=sys.stderr)
    if differs:
        print(f"error: Foundry graded differently from the local checks: {', '.join(differs)}", file=sys.stderr)
    if ungraded:
        print(f"error: Foundry could not grade {', '.join(ungraded)}; run --check-graders again", file=sys.stderr)
        return 2
    return 1 if wrong or differs else 0


def save_pulls(value: str) -> None:
    """Keep the evaluation's pull request numbers in this solution's azd environment (REVIEWER_EVAL_PRS)."""
    import shutil
    import subprocess

    if shutil.which("azd") and subprocess.run(["azd", "env", "set", eval_prs.SETTING, value], cwd=HERE,
                                              capture_output=True).returncode == 0:
        return
    print(f"  azd isn't set up here: to keep these numbers, set {eval_prs.SETTING}={value or '(empty)'} in your environment.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setup", action="store_true",
                        help="Create the evaluation's pull requests in GITHUB_REPOSITORY, or reuse the ones made before")
    parser.add_argument("--cleanup", action="store_true", help="Close the evaluation's pull requests and delete their branches")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="Evaluate only these cases (ids from eval_cases.jsonl)")
    parser.add_argument("--reuse", action="store_true", help="Score out/eval/results.jsonl again instead of running the reviewer")
    parser.add_argument("--local", action="store_true", help="Score locally only; skip the Foundry evaluation")
    parser.add_argument("--check-graders", action="store_true",
                        help="Grade the fixed right and wrong reviews in grader_checks.jsonl (no dry runs), here and in Foundry")
    parser.add_argument("--parallel", type=int, default=4, help="Dry runs at a time (default 4)")
    parser.add_argument("--show-url", action="store_true", help="Print the Foundry report link (it contains resource ids)")
    args = parser.parse_args(argv)
    utf8_stdout()
    if args.check_graders:
        try:
            return check_graders(args.local)
        except Exception as exc:  # preview service: say what failed without its message, which can name resources
            print(f"error: the Foundry grader check didn't run ({type(exc).__name__})", file=sys.stderr)
            return 2
    cases = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.cases:
        unknown = set(args.cases) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case id(s): {', '.join(sorted(unknown))}; see eval_cases.jsonl")
        cases = [c for c in cases if c["id"] in args.cases]
    OUT.mkdir(parents=True, exist_ok=True)
    results = OUT / "results.jsonl"
    if args.reuse:
        stored = {i.get("id"): i for i in (json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip())}
        items = [stored.get(c["id"]) or missing_result(c, "no stored result") for c in cases]
    else:
        repository = setting("GITHUB_REPOSITORY")
        github, kept = eval_prs.GitHub(repository), eval_prs.stored(setting(eval_prs.SETTING, "{}"), repository)
        try:
            if args.setup or args.cleanup:
                print(f"{'Setting up' if args.setup else 'Removing'} the evaluation's pull requests in {repository}:")
                action = eval_prs.setup if args.setup else eval_prs.cleanup
                action(cases, github, eval_prs.Git(repository), kept, save_pulls)
                return 0
            pulls = eval_prs.require(cases, github, kept)
        except eval_prs.SetupMissing as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"Dry-running the reviewer on {len(cases)} labelled cases in {repository}, {args.parallel} at a time:")
        reviewer = Reviewer(DefaultAzureCredential())
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            items = list(pool.map(lambda case: review_case(reviewer, case, pulls[case["id"]]), cases))
        results.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    if not cases or len(items) != len(cases):
        print(f"error: {len(items)} results for {len(cases)} labelled cases", file=sys.stderr)
        return 2
    items = score(items)
    (OUT / "report.md").write_text(f"# Azure pull request reviewer: labelled pull requests\n\n{report(items)}\n", encoding="utf-8")
    print("\n" + terminal_report(items) + "\n")
    ungraded = [f"{i.get('id')} ({', '.join(i['_errors'])})" for i in items if i.get("_errors")]
    if ungraded:
        print(f"error: COULD NOT GRADE {', '.join(ungraded)}", file=sys.stderr)
        return 2
    if not args.local:
        try:
            problem = foundry_evaluation(items, args.show_url)
        except Exception as exc:  # preview service: keep the local scores, explain, and fail clearly
            problem = f"it didn't run ({type(exc).__name__}: {str(exc)[:300]})"
        if problem:
            print(f"error: the Foundry evaluation can't be trusted: {problem}. The local scores above stand; run with "
                  "--reuse to grade the same results in Foundry again, or --local to skip Foundry.", file=sys.stderr)
            return 2
    return 0 if all(s is not None and s >= 1 for i in items for s in i["_scores"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
