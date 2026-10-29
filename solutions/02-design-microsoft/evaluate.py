#!/usr/bin/env python3
"""Run the architecture advisor's evaluation in Microsoft Foundry now (Design phase, Microsoft track).

Foundry runs the evaluation; this script only starts it from this folder's files and reports the result:
  1. Publishes the advisor agents from agent.yaml if their definition changed (otherwise the current versions run).
  2. Registers the five code-based evaluators and the evaluation if their code changed (evaluation.py).
  3. Starts one Foundry evaluation run per operating profile. Foundry sends each labelled case in eval_cases.jsonl to
     that profile's agent, then scores every answer with the evaluators, which embed the gate's own checks.
  4. Waits for the runs (unless --no-wait), then prints each case's result, each evaluator's pass rate, and where to
     open the runs in the Foundry portal (Evaluations > "Architecture advisor · labelled cases").
The same runs start in Azure, without this script, when a change to the standards, agent.yaml, or the cases merges.

Fallback: code-based evaluators are a Foundry preview feature. If they are unavailable, --local asks the same agent
versions through the Responses API and scores each answer on this machine with the same checks (checks.py). Nothing
then appears under Evaluations in Foundry, but every call still shows in the agents' Traces.

Usage
  python evaluate.py
  python evaluate.py --cases E07,E08
  python evaluate.py --no-wait
  python evaluate.py --local

Settings: environment variables, or this folder's azd environment (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT,
SEARCH_ENDPOINT). Your identity needs Foundry User on the Foundry account and read access to the search index.

Exit codes: 0 every case passed (or --no-wait), 1 a case failed, 2 a run could not start, ended in error, or an
evaluator could not grade an answer (Foundry counts such an item as passed; this script does not).
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
from azd_env import credential, setting, utf8_stdout  # noqa: E402

CASES = HERE / "eval_cases.jsonl"
CHECKS = ("citations", "access", "grounding", "abstention", "conflicts")


def case_results(openai, run: dict) -> list[tuple[str, list[str], list[str]]]:
    """(case id, failed checks, checks that could not grade) for every item of a finished run. Computed from each
    evaluator's own result: Foundry's run totals count an item as passed even when one of its evaluators errored."""
    rows = []
    for output in openai.evals.runs.output_items.list(run_id=run["runId"], eval_id=run["evalId"]):
        data = output.model_dump() if hasattr(output, "model_dump") else dict(output)
        item = data.get("datasource_item") or {}
        failed, errored = [], []
        for result in data.get("results") or []:
            name = str(result.get("name", "?")).replace("advisor_", "")
            if (result.get("sample") or {}).get("error"):
                errored.append(name)
            elif not result.get("passed"):
                failed.append(name)
        rows.append((item.get("id", "?"), failed, errored))
    return sorted(rows)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog="Settings come from the environment or from this folder's azd environment.")
    parser.add_argument("--cases", help="Comma-separated case ids to run, for example E07,E08 (default: all ten)")
    parser.add_argument("--no-wait", action="store_true", help="Start the runs and return; read the results in Foundry")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait for the runs (default 900)")
    parser.add_argument("--local", action="store_true",
                        help="Fallback without Foundry evaluations: ask the agents and score the answers here with checks.py")
    args = parser.parse_args(argv)
    utf8_stdout()

    from azure.ai.projects import AIProjectClient

    from advisor_core import agents, evaluation

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in wanted]
    started = time.monotonic()
    try:
        signed_in, search = credential(), setting("SEARCH_ENDPOINT")
        project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=signed_in)
        spec = agents.load_spec((HERE / "agent.yaml").read_text(encoding="utf-8"))
        model = setting("FOUNDRY_MODEL_DEPLOYMENT")
        published = agents.publish(project, spec, model, search)
        if args.local:
            return run_local(project, cases, published, search, signed_in, spec["search"]["index"])
        runs = evaluation.start(project, model, cases, search, signed_in, spec["search"]["index"], published, "evaluate.py")
    except Exception as exc:
        print(f"error: could not start the evaluation: {exc}", file=sys.stderr)
        return 2
    for run in runs:
        print(f"started {run['agent']} on {len(run['cases'])} case(s): {', '.join(run['cases'])}")
    print(f"Foundry portal: Evaluations > \"{evaluation.EVAL_NAME}\"")
    if args.no_wait:
        return 0

    openai = project.get_openai_client()
    pending, results = {r["runId"] for r in runs}, {}
    while pending and time.monotonic() - started < args.timeout:
        time.sleep(15)
        for run in runs:
            if run["runId"] in pending:
                state = evaluation.status(openai, run["evalId"], run["runId"])
                if state["status"] in ("completed", "failed", "canceled"):
                    pending.discard(run["runId"])
                    results[run["runId"]] = state
    if pending:
        print(f"error: {len(pending)} run(s) still running after {args.timeout} s; see Foundry", file=sys.stderr)
        return 2
    passed = total = 0
    errored = False
    for run in runs:
        state = results[run["runId"]]
        rows = case_results(openai, run)
        good = sum(1 for _, failed, errors in rows if not failed and not errors)
        errored |= state["status"] != "completed" or any(errors for _, _, errors in rows)
        passed, total = passed + good, total + len(rows)
        print(f"\n{run['agent']}: {state['status']}, {good}/{len(rows)} cases passed every check")
        rates = [f"{kind} {sum(1 for _, f, e in rows if kind not in f and kind not in e)}/{len(rows)}" for kind in CHECKS]
        print("  " + " · ".join(rates))
        for case_id, failed, errors in rows:
            verdict = "PASS" if not failed and not errors else "FAIL: " + ", ".join(failed) if failed else ""
            if errors:
                verdict = (verdict + "; " if failed else "") + "COULD NOT GRADE: " + ", ".join(errors)
            print(f"  {case_id}  {verdict}")
    print(f"\n{passed}/{total} cases passed in {round(time.monotonic() - started)} s")
    if errored:
        print("error: an evaluator could not grade some answers (see COULD NOT GRADE); run the evaluation again",
              file=sys.stderr)
        return 2
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
