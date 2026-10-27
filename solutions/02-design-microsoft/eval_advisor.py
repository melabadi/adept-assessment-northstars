#!/usr/bin/env python3
"""Evaluate the Foundry architecture advisor on ten labelled cases (Design phase, Microsoft track).

Each line of eval_cases.jsonl names an operating profile, a question, and what a correct answer looks like:
  expectAnswerable  the advisor must answer (true) or abstain (false; for example no standard sets a token budget)
  expectStandards   standards the answer must cite (grounding)
  forbidStandards   standards the answer must not cite, because the profile may not see them (negative access test)
  expectConflict    standards the answer must report together as a conflict (contradiction handling)
Every run must also pass the advisor's deterministic checks: real, in-scope, correctly versioned citations with
word-for-word excerpts, and a search that returned nothing outside the profile's scope. The evaluator is code, not a
model, and it reports every case individually with the response id of the live call.

Usage
  python solutions/02-design-microsoft/eval_advisor.py
  python solutions/02-design-microsoft/eval_advisor.py --repeat 3              # run-to-run stability
  python solutions/02-design-microsoft/eval_advisor.py --cases E07,E08 --workers 1

Outputs (default out/eval/ next to this script): results.json, every run with its response id, agent version, and
misses; results.md, the same results as a Markdown table (the GitHub workflow shows it in its summary).
Settings: the same as advisor.py (environment variables, or this folder's azd environment).

Exit codes: 0 every run passed, 1 at least one run failed, 2 a run could not reach the service.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import advisor  # noqa: E402

CASES = HERE / "eval_cases.jsonl"


def evaluate(case: dict, run: dict) -> list[str]:
    """What this run got wrong compared with the case's labels, plus any failed deterministic check."""
    data = run["result"]
    misses = list(run["checks"])
    cited = set(advisor.STANDARD_ID.findall(json.dumps({k: data[k] for k in ("constraints", "options", "conflicts")})))
    if data["answerable"] != case["expectAnswerable"]:
        misses.append(f"expected answerable={case['expectAnswerable']}, got {data['answerable']}")
    for standard in case["expectStandards"]:
        if standard not in cited:
            misses.append(f"did not cite {standard}")
    for standard in case["forbidStandards"]:
        if standard in cited:
            misses.append(f"cited out-of-scope {standard}")
    if case["expectConflict"]:
        expected = set(case["expectConflict"])
        if not any(expected <= set(advisor.STANDARD_ID.findall(" ".join(c["standards"]))) for c in data["conflicts"]):
            misses.append(f"did not flag the conflict {' vs '.join(case['expectConflict'])}")
    return misses


def tests(case: dict) -> str:
    """What a case exercises, derived from its labels."""
    kinds = []
    if case["expectStandards"]:
        kinds.append("grounding")
    if case["forbidStandards"]:
        kinds.append("access")
    if case["expectConflict"]:
        kinds.append("conflict")
    if not case["expectAnswerable"]:
        kinds.append("abstention")
    return ", ".join(kinds)


def markdown(summary: dict, cases: dict[str, dict]) -> str:
    agents = ", ".join(f"`{name}`" for name in summary["agents"].values())
    lines = [
        "### Architecture advisor evaluation",
        "",
        f"**{summary['passed']}/{summary['runs']} runs passed** · model `{summary['model']}` · agents {agents} · "
        f"{summary['durationSeconds']} s",
        "",
        "| Case | Profile | Tests | Question | Result | Time | Response |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in summary["results"]:
        label = r["id"] if summary["repeat"] == 1 else f"{r['id']}.{r['attempt']}"
        result = "✅ pass" if r["passed"] else "❌ " + advisor.cell("; ".join(r["misses"]))
        question = advisor.cell(cases[r["id"]]["question"])
        lines.append(f"| {label} | {r['profile']} | {tests(cases[r['id']])} | {question} | {result} | "
                     f"{r.get('durationSeconds', '')} s | `{r.get('responseId', '')}` |")
    if summary["repeat"] > 1:
        lines += ["", "Per-case stability: " + ", ".join(f"{cid} {s}" for cid, s in summary["stability"].items())]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog="Settings: the same as advisor.py (environment variables or this folder's azd environment).")
    parser.add_argument("--cases", help="Comma-separated case ids to run, for example E07,E08 (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times to measure run-to-run stability (default 1)")
    parser.add_argument("--workers", type=int, default=2,
                        help="Cases run in parallel (default 2; more can be throttled by the model deployment's tokens-per-minute limit)")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "eval", help="Output folder (default out/eval/ next to this script)")
    args = parser.parse_args(argv)
    advisor.utf8_stdout()

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in wanted]
    by_id = {c["id"]: c for c in cases}

    started = time.monotonic()
    try:
        client = advisor.Advisor()
        for profile in sorted({c["profile"] for c in cases}):  # publish agents and load the index before running in parallel
            client.agent(profile)
            client.standards(profile)
        client.standards()
    except Exception as exc:
        print(f"error: could not prepare the advisor: {exc}", file=sys.stderr)
        return 2

    jobs = [(case, attempt) for case in cases for attempt in range(1, args.repeat + 1)]
    print(f"running {len(jobs)} run(s) of {len(cases)} case(s) with {max(1, args.workers)} worker(s)")

    def run_one(case: dict, attempt: int) -> dict:
        record = {"id": case["id"], "attempt": attempt, "profile": case["profile"]}
        try:
            run = client.ask(case["question"], case["profile"])
        except Exception as exc:
            return record | {"passed": False, "error": True, "misses": [f"service error: {exc}"]}
        misses = evaluate(case, run)
        return record | {"passed": not misses, "error": False, "misses": misses, "responseId": run["responseId"],
                         "agent": run["agent"], "durationSeconds": run["durationSeconds"], "searchCalls": run["searchCalls"],
                         "retrievedStandards": run["retrievedStandards"], "answerable": run["result"]["answerable"],
                         "cited": sorted(set(advisor.STANDARD_ID.findall(json.dumps(run["result"]["constraints"]))))}

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(run_one, case, attempt) for case, attempt in jobs]
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            label = r["id"] if args.repeat == 1 else f"{r['id']}.{r['attempt']}"
            status = "PASS" if r["passed"] else ("ERROR" if r["error"] else "FAIL")
            line = f"{label:<6} {r['profile']:<11} {status:<5} {r.get('durationSeconds', '-'):>5} s  {r.get('responseId', '')}"
            print("\n".join([line] + [f"{'':<6} - {miss}" for miss in r["misses"]]))

    results.sort(key=lambda r: (r["id"], r["attempt"]))
    per_case: dict[str, list[bool]] = {}
    for r in results:
        per_case.setdefault(r["id"], []).append(r["passed"])
    passed = sum(r["passed"] for r in results)
    summary = {
        "cases": len(cases), "runs": len(results), "passed": passed, "repeat": args.repeat,
        "durationSeconds": round(time.monotonic() - started, 1),
        "model": client.model,
        "agents": {p: f"{a.name} v{a.version}" for p, a in client.agents.items()},
        "stability": {cid: f"{sum(v)}/{len(v)}" for cid, v in per_case.items()},
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "results.md").write_text(markdown(summary, by_id), encoding="utf-8")
    if args.repeat > 1:
        print("\nper-case stability: " + ", ".join(f"{cid} {s}" for cid, s in summary["stability"].items()))
    print(f"\n{passed}/{len(results)} runs passed in {summary['durationSeconds']} s · model {client.model} · "
          f"results: {args.out / 'results.json'}")
    if any(r["error"] for r in results):
        return 2
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
