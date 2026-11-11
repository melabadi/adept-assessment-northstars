#!/usr/bin/env python3
"""Run the architecture advisor's evaluation in Microsoft Foundry now (Design phase, Microsoft track).

Foundry runs the evaluation; this script only starts it from this folder's files and reports the result:
  1. Publishes the advisor agents from agent.yaml if their definition changed (otherwise the current versions run).
  2. Registers the five code-based evaluators and the evaluation if their code changed (evaluation.py).
  3. Starts one Foundry evaluation run per operating profile. Foundry sends each labelled case in eval_cases.jsonl to
     that profile's agent, then scores every answer with the evaluators, which embed the gate's own checks.
  4. Waits for the runs (unless --no-wait). Foundry's preview grader sometimes fails to score one evaluator of a run;
     such a run is started again for its profile, so the agent answers again, up to --attempts runs. A run with a
     failed case is never started again: a failed case is a result. Then prints each case's result, each evaluator's
     pass rate, and where to open the runs in the Foundry portal (Evaluations > "Architecture advisor · labelled cases").
     The summary keeps the first attempt apart from any retry: how many cases passed, failed, and could not be graded
     the first time, which runs were started again and why, and the result of the last run of each profile.
The same runs start in Azure, without this script, when a change to the standards, agent.yaml, or the cases merges.

Held-out cases: --held-out asks the agents the questions in eval_heldout.jsonl instead. They were labelled before any
answer to them was seen and were never used to tune the checks, so they show how the checks do on questions they
weren't written for.

Grader checks: --check-graders grades the fixed answers in grader_checks.jsonl, a right and a wrong answer to every
labelled question that quote the same evidence and differ only in their conclusion, on this machine with checks.py
and in Foundry with the registered evaluators (Evaluations > "Architecture advisor · grader checks"). It shows that the
checks tell the two apart, and that Foundry grades exactly as checks.py does. No agent is asked.

Fallback: code-based evaluators are a Foundry preview feature. If they are unavailable, --local asks the same agent
versions through the Responses API and scores each answer on this machine with the same checks (checks.py). Nothing
then appears under Evaluations in Foundry, but every call still shows in the agents' Traces. With --check-graders,
--local grades the fixed answers on this machine only.

Usage
  python evaluate.py
  python evaluate.py --cases E07,E08
  python evaluate.py --held-out
  python evaluate.py --check-graders
  python evaluate.py --no-wait
  python evaluate.py --attempts 1
  python evaluate.py --local

Settings: environment variables, or this folder's azd environment (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT,
SEARCH_ENDPOINT). Your identity needs Foundry User on the Foundry account and read access to the search index.

Exit codes: 0 every case passed (or --no-wait), 1 a case failed, 2 a run could not start or ended in error, or an
answer was not graded in the last run of its profile: an evaluator errored or returned no result, the agent call
failed, or a case has no result. Foundry's run totals count some of these as passed; this script does not.
With --check-graders: 0 every answer was graded as labelled (or as its recorded known miss) and Foundry graded it as
checks.py did, 1 a grade differs from its label or Foundry's grade differs from checks.py's, 2 Foundry could not grade.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "function"))
from azd_env import credential, describe_error, setting, utf8_stdout  # noqa: E402

CASES = HERE / "eval_cases.jsonl"
HELD_OUT = HERE / "eval_heldout.jsonl"
GRADER_CHECKS = HERE / "grader_checks.jsonl"
CHECKS = ("citations", "access", "grounding", "abstention", "conflicts")
NO_ANSWER = "no answer to grade (the agent call failed)"
NO_ITEM = "no result for this case"


def case_results(openai, run: dict) -> list[tuple[str, list[str], list[str]]]:
    """(case id, failed checks, what could not be graded) for every case of a finished run.

    Computed from each item's own results, because Foundry's run totals count an item as passed even when one of its
    evaluators errored. A check is ungraded when its evaluator errored or returned no result; every check of a case is
    ungraded when the agent call failed (the item's sample has an error) or the run has no item for the case."""
    rows = []
    for output in openai.evals.runs.output_items.list(run_id=run["runId"], eval_id=run["evalId"]):
        data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
        failed, errored, graded = [], [], set()
        for result in data.get("results") or []:
            name = str(result.get("name", "?")).replace("advisor_", "")
            if (result.get("sample") or {}).get("error"):
                errored.append(name)
            else:
                graded.add(name)
                if not result.get("passed"):
                    failed.append(name)
        if (data.get("sample") or {}).get("error"):
            failed, errored = [], [NO_ANSWER, *CHECKS]
        else:
            errored += [kind for kind in CHECKS if kind not in graded and kind not in errored]
        rows.append(((data.get("datasource_item") or {}).get("id", "?"), failed, errored))
    seen = {case_id for case_id, _, _ in rows}
    rows += [(case_id, [], [NO_ITEM, *CHECKS]) for case_id in run["cases"] if case_id not in seen]
    return sorted(rows)


def ungraded(run: dict, state: dict, rows: list) -> list[str]:
    """Why a finished run's answers were not all graded (rows from case_results); empty when every case has every
    check's result."""
    reasons = []
    if state["status"] != "completed":
        reasons.append(f"the run ended {state['status']}")
    if state["errored"] > 0:
        reasons.append(f"Foundry reports {state['errored']} item(s) in error")
    if len(rows) != len(run["cases"]):
        reasons.append(f"{len(rows)} results for {len(run['cases'])} cases")
    if any(errors for _, _, errors in rows):
        reasons.append("some answers could not be graded (COULD NOT GRADE)")
    return reasons


def wait(openai, runs: list[dict], restart, attempts: int, timeout: int, poll: float = 15) -> tuple[list, dict, list, list]:
    """Wait for the runs. A finished run that Foundry could not grade (ungraded) is started again for its profile with
    restart(run), which returns the new run, until that profile has had `attempts` runs. A run with a failed case is
    final even when another answer was not graded: a failed case is a result, and asking again could hide it.
    Returns (the last run of each profile, in the order given; their states; the runs still running after `timeout`
    seconds; every finished run in order, as {profile, agent, attempt, rows, reasons}, first attempts included)."""
    from advisor_core import evaluation

    pending = [dict(run, attempt=1, deadline=time.monotonic() + timeout) for run in runs]
    last, states, late, history = {}, {}, [], []
    while pending:
        time.sleep(poll)
        for run in list(pending):
            state = evaluation.status(openai, run["evalId"], run["runId"])
            if state["status"] not in ("completed", "failed", "canceled"):
                if time.monotonic() > run["deadline"]:
                    pending.remove(run)
                    late.append(run)
                continue
            pending.remove(run)
            rows = case_results(openai, run)
            reasons = ungraded(run, state, rows)
            history.append({"profile": run["profile"], "agent": run["agent"], "attempt": run["attempt"], "rows": rows,
                            "reasons": reasons})
            if reasons and run["attempt"] < attempts and not any(failed for _, failed, _ in rows):
                missing = [kind for kind in CHECKS if any(kind in errors for _, _, errors in rows)]
                detail = ", ".join(missing) or "; ".join(reasons)
                print(f"{run['agent']}: Foundry could not grade run {run['attempt']} ({detail}); "
                      f"starting run {run['attempt'] + 1} of up to {attempts}", flush=True)
                try:
                    pending.append(dict(restart(run), attempt=run["attempt"] + 1, deadline=time.monotonic() + timeout))
                    continue
                except Exception as exc:  # report the run that could not be graded instead
                    print(f"error: could not start {run['agent']} again: {describe_error(exc)}", file=sys.stderr)
            last[run["profile"]], states[run["runId"]] = run, state
    return [last[run["profile"]] for run in runs if run["profile"] in last], states, late, history


def tally(rows: list) -> tuple[int, int, int]:
    """(passed, failed, could not be graded) among a run's cases. A case with a failed check counts as failed even
    when another of its checks was not graded."""
    passed = sum(1 for _, failed, errors in rows if not failed and not errors)
    failed = sum(1 for _, failed, _ in rows if failed)
    return passed, failed, len(rows) - passed - failed


def attempts_report(history: list) -> list[str]:
    """The first attempt, the retries, and what could not be graded, kept apart: a retry asks the agent again, so its
    answers are new, and never replace what the first attempt showed."""
    first = [entry for entry in history if entry["attempt"] == 1]
    passed, failed, ungraded_count = (sum(values) for values in zip(*(tally(e["rows"]) for e in first))) if first else (0, 0, 0)
    lines = [f"First attempt: {passed} passed, {failed} failed, {ungraded_count} could not be graded "
             f"(of {sum(len(e['rows']) for e in first)} cases)"]
    for entry in first:
        missing = sorted({case_id for case_id, failed_checks, errors in entry["rows"] if errors and not failed_checks})
        if missing:
            lines.append(f"  {entry['agent']}: could not be graded: {', '.join(missing)}")
    retries = [entry for entry in history if entry["attempt"] > 1]
    if not retries:
        lines.append("Retries: none")
    for entry in retries:
        p, f, u = tally(entry["rows"])
        lines.append(f"Retry: {entry['agent']} run {entry['attempt']}, started because Foundry could not grade run "
                     f"{entry['attempt'] - 1}; the agent answered again: {p} passed, {f} failed, {u} could not be graded")
    return lines


def summarize(openai, runs: list[dict], results: dict, started: float, history: list | None = None) -> int:
    """Print each run's cases and each evaluator's pass rate, then the first attempt and any retries apart. Returns the
    exit code (see the module docstring), from the last run of each profile."""
    passed = total = 0
    problems = []
    for run in runs:
        state = results[run["runId"]]
        rows = case_results(openai, run)
        good = sum(1 for _, failed, errors in rows if not failed and not errors)
        passed, total = passed + good, total + len(rows)
        print(f"\n{run['agent']}: {state['status']}, {good}/{len(rows)} cases passed every check")
        rates = [f"{kind} {sum(1 for _, f, e in rows if kind not in f and kind not in e)}/{len(rows)}" for kind in CHECKS]
        print("  " + " · ".join(rates))
        for case_id, failed, errors in rows:
            verdict = [f"FAIL: {', '.join(failed)}"] if failed else []
            if errors:
                verdict.append("COULD NOT GRADE: " + ", ".join([e for e in errors if e not in CHECKS] or errors))
            print(f"  {case_id}  {'; '.join(verdict) or 'PASS'}")
        problems += [f"{run['agent']}: {reason}" for reason in ungraded(run, state, rows)]
    if history:
        print("\n" + "\n".join(attempts_report(history)))
    print(f"\n{'Last run of each profile: ' if history else ''}{passed}/{total} cases passed in "
          f"{round(time.monotonic() - started)} s")
    sys.stdout.flush()  # the errors follow the results, also when both streams go to one pipe
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        print("error: not every answer was graded; open the runs in Foundry, then run the evaluation again", file=sys.stderr)
        return 2
    return 0 if passed == total else 1


def run_local(project, cases: list[dict], published: dict, search: str, signed_in, index: str) -> int:
    """The fallback: ask each case's agent version, then score the answer here with the evaluators' own checks."""
    from advisor_core import checks, evaluation, standards

    openai = project.get_openai_client()
    every = standards.snapshot(search, signed_in, index)
    passed = 0
    for case in cases:
        agent = published[case["profile"]]
        started = time.monotonic()
        response = openai.responses.create(input=case["question"], max_output_tokens=8000, extra_body={
            "agent_reference": {"type": "agent_reference", "name": agent["name"], "version": agent["version"]}}).model_dump()
        item = evaluation.items([case], every, list(standards.snapshot(search, signed_in, index, agent["scopeFilter"])))[0]["item"]
        item["sample"] = {"output_text": checks.answer_text(response), "output_items": response.get("output")}
        try:
            failed = [kind for kind in checks.CHECK_KINDS if not checks.verdict(checks.evaluate_item(item), kind)]
        except ValueError as exc:  # not the agent's JSON answer
            failed = [f"format ({exc})"]
        passed += not failed
        print(f"{case['id']}  {case['profile']:<11} {'PASS' if not failed else 'FAIL: ' + ', '.join(failed)}  "
              f"{round(time.monotonic() - started, 1)} s  {agent['name']} v{agent['version']}")
    print(f"\n{passed}/{len(cases)} cases passed (scored locally with checks.py)")
    return 0 if passed == len(cases) else 1


def fixed_results(openai, run: dict) -> dict[str, dict[str, bool | None]]:
    """Each fixed answer's grade per check in a finished Foundry run: True, False, or None when the evaluator errored
    or returned nothing. A jsonl run reports the item's fields flattened ("item.id")."""
    graded = {}
    for output in openai.evals.runs.output_items.list(run_id=run["runId"], eval_id=run["evalId"]):
        data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
        source = data.get("datasource_item") or {}
        answer_id = source.get("id") or source.get("item.id") or (source.get("item") or {}).get("id") or "?"
        results = {str(r.get("name", "?")).replace("advisor_", ""): r for r in data.get("results") or []}
        graded[answer_id] = {kind: None if kind not in results or (results[kind].get("sample") or {}).get("error")
                             or results[kind].get("passed") is None else bool(results[kind]["passed"]) for kind in CHECKS}
    return graded


def check_graders(project, model: str, spec: dict, search: str, signed_in, local_only: bool, timeout: int,
                  attempts: int) -> int:
    """Grade grader_checks.jsonl's fixed answers with checks.py here and, unless local_only, with the registered
    evaluators in Foundry, then compare both with the labels. The answers are fixed, so when Foundry's preview grader
    can't grade a check, the same answers are graded again, up to `attempts` runs, and each check keeps the first grade
    Foundry gave it. See the module docstring for the exit codes."""
    from advisor_core import checks, evaluation, standards

    rows = [json.loads(line) for line in GRADER_CHECKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = {c["id"]: c for path in (CASES, HELD_OUT)
             for c in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}
    index = spec["search"]["index"]
    every = standards.snapshot(search, signed_in, index)
    permitted = {profile: list(standards.snapshot(search, signed_in, index, standards.scope_filter(spec, profile)))
                 for profile in spec["profiles"]}
    built = evaluation.fixed_answer_items(rows, cases, every, permitted)
    local = {b["item"]["id"]: {kind: checks.verdict(checks.evaluate_item(b["item"]), kind) for kind in CHECKS} for b in built}
    foundry = None
    if not local_only:
        foundry = {row["id"]: dict.fromkeys(CHECKS) for row in rows}
        openai = project.get_openai_client()
        print(f"Foundry portal: Evaluations > \"{evaluation.GRADER_EVAL_NAME}\"", flush=True)
        for attempt in range(1, attempts + 1):
            run = evaluation.start_grader_checks(project, model, built, f"evaluate.py --check-graders, run {attempt}")
            print(f"  run {attempt}: grading {len(built)} fixed answers ...", flush=True)
            deadline = time.monotonic() + timeout
            while evaluation.status(openai, run["evalId"], run["runId"])["status"] not in ("completed", "failed", "canceled"):
                if time.monotonic() > deadline:
                    print(f"error: the Foundry run is still running after {timeout} s; see Foundry", file=sys.stderr)
                    return 2
                time.sleep(10)
            for answer_id, grades in fixed_results(openai, run).items():
                for kind, grade in grades.items():
                    if answer_id in foundry and foundry[answer_id][kind] is None:
                        foundry[answer_id][kind] = grade
            missing = sorted({kind for grades in foundry.values() for kind, grade in grades.items() if grade is None})
            if not missing:
                break
            print(f"  run {attempt}: Foundry could not grade {', '.join(missing)} on some answers"
                  + ("; grading the same answers again" if attempt < attempts else ""), flush=True)
    print(f"\n{'Answer':<11} {'Split':<9} " + " ".join(f"{kind:<10}" for kind in CHECKS) + "  Foundry")
    wrong, differs, ungraded_ids = [], [], []
    for row in rows:
        mine = local[row["id"]]
        known = row.get("knownMiss", "").split(":")[0]
        cells = []
        for kind in CHECKS:
            mark = "" if mine[kind] == row["expect"][kind] else "*" if kind == known else "!"
            cells.append(f"{('pass' if mine[kind] else 'FAIL') + mark:<10}")
            if mark == "!" or (kind == known and not mark):
                wrong.append(f"{row['id']} {kind}")
        theirs = (foundry or {}).get(row["id"], dict.fromkeys(CHECKS)) if foundry is not None else None
        if theirs is None:
            column = "-"
        elif any(theirs[kind] is None for kind in CHECKS):
            column = "COULD NOT GRADE: " + ", ".join(kind for kind in CHECKS if theirs[kind] is None)
            ungraded_ids.append(row["id"])
        elif theirs != mine:
            column = "differs: " + ", ".join(kind for kind in CHECKS if theirs[kind] != mine[kind])
            differs.append(row["id"])
        else:
            column = "same"
        print(f"{row['id']:<11} {row['split']:<9} " + " ".join(cells) + f"  {column}")
    print("\n* a known miss of the checks, recorded in grader_checks.jsonl:")
    for row in rows:
        if row.get("knownMiss"):
            print(f"  {row['id']}: {row['knownMiss']}")
    for split in ("paired", "held-out"):
        mine = [row for row in rows if row["split"] == split]
        right = sum(1 for row in mine if local[row["id"]] == row["expect"])
        print(f"{split}: {right}/{len(mine)} answers graded as labelled on every check"
              + ("" if foundry is None else f"; Foundry graded {sum(1 for row in mine if foundry.get(row['id']) == local[row['id']])}"
                                            f"/{len(mine)} exactly as checks.py did"))
    sys.stdout.flush()
    if wrong:
        print(f"error: graded differently from the labels: {', '.join(wrong)}", file=sys.stderr)
    if differs:
        print(f"error: Foundry graded differently from checks.py: {', '.join(differs)}", file=sys.stderr)
    if ungraded_ids:
        print(f"error: Foundry could not grade {', '.join(ungraded_ids)}; run --check-graders again", file=sys.stderr)
        return 2
    return 1 if wrong or differs else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog="Settings come from the environment or from this folder's azd environment.")
    parser.add_argument("--cases", help="Comma-separated case ids to run, for example E07,E08 (default: all ten)")
    parser.add_argument("--held-out", action="store_true",
                        help="Ask the questions in eval_heldout.jsonl instead: labelled, never used to tune the checks")
    parser.add_argument("--check-graders", action="store_true",
                        help="Grade the fixed right and wrong answers in grader_checks.jsonl here and in Foundry; no agent "
                             "is asked")
    parser.add_argument("--no-wait", action="store_true", help="Start the runs and return; read the results in Foundry")
    parser.add_argument("--attempts", type=int, default=3,
                        help="Runs per profile at most: a run Foundry could not grade is started again, and the agent "
                             "answers again (default 3; 1 never starts a run again). A run with a failed case is final")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait for each run (default 900)")
    parser.add_argument("--local", action="store_true",
                        help="Fallback without Foundry evaluations: ask the agents and score the answers here with "
                             "checks.py (with --check-graders: grade the fixed answers here only)")
    args = parser.parse_args(argv)
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    utf8_stdout()

    from azure.ai.projects import AIProjectClient

    from advisor_core import agents, evaluation

    cases = [json.loads(line) for line in (HELD_OUT if args.held_out else CASES).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in wanted]
    label = "evaluate.py, held-out" if args.held_out else "evaluate.py"
    started = time.monotonic()
    try:
        signed_in, search = credential(), setting("SEARCH_ENDPOINT")
        project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=signed_in)
        spec = agents.load_spec((HERE / "agent.yaml").read_text(encoding="utf-8"))
        model = setting("FOUNDRY_MODEL_DEPLOYMENT")
        if args.check_graders:
            return check_graders(project, model, spec, search, signed_in, args.local, args.timeout, args.attempts)
        published = agents.publish(project, spec, model, search)
        if args.local:
            return run_local(project, cases, published, search, signed_in, spec["search"]["index"])
        runs = evaluation.start(project, model, cases, search, signed_in, spec["search"]["index"], published, label)
    except Exception as exc:
        print(f"error: could not start the evaluation: {describe_error(exc)}", file=sys.stderr)
        return 2
    for run in runs:
        print(f"started {run['agent']} on {len(run['cases'])} case(s): {', '.join(run['cases'])}")
    print(f"Foundry portal: Evaluations > \"{evaluation.EVAL_NAME}\"")
    if args.no_wait:
        return 0

    def restart(run: dict) -> dict:
        """The same profile's cases against the same agent version, as a new run."""
        again = [case for case in cases if case["id"] in run["cases"]]
        return evaluation.start(project, model, again, search, signed_in, spec["search"]["index"], published,
                                f"{label}, run {run['attempt'] + 1}")[0]

    openai = project.get_openai_client()
    final, results, late, history = wait(openai, runs, restart, args.attempts, args.timeout)
    if late:
        print(f"error: {len(late)} run(s) still running after {args.timeout} s; see Foundry", file=sys.stderr)
        return 2
    return summarize(openai, final, results, started, history)


if __name__ == "__main__":
    sys.exit(main())
