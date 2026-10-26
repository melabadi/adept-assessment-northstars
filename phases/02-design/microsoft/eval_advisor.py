#!/usr/bin/env python3
"""Evaluate the Foundry architecture advisor on ten labelled cases (Design phase, Microsoft track).

Each case in eval_cases.jsonl names an operating profile, a question, and expectations:
  expectAnswerable  the advisor must answer (true) or abstain (false, e.g. no standard sets a token budget)
  expectStandards   standards that must be cited (grounding)
  forbidStandards   standards that must NOT be cited (out-of-scope for the profile: negative access test)
  expectConflict    standards that must be reported together as a conflict (contradiction handling)

Every case also runs the advisor's deterministic gates (existing, in-scope, correctly versioned citations).
Results are reported per case; the evaluator is deterministic code, not a model.

Usage
  python phases/02-design/microsoft/eval_advisor.py
  python phases/02-design/microsoft/eval_advisor.py --cases E07,E08 --out out/eval

Exit codes: 0 all cases pass, 1 at least one case failed, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import advisor  # noqa: E402

REPO = advisor.REPO


def evaluate(case: dict, run: dict) -> list[str]:
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
        flagged = any(set(case["expectConflict"]) <= set(advisor.STANDARD_ID.findall(" ".join(c["standards"]))) for c in data["conflicts"])
        if not flagged:
            misses.append(f"did not flag conflict {' vs '.join(case['expectConflict'])}")
    return misses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", help="Comma-separated case ids to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times to measure run-to-run stability (default 1)")
    parser.add_argument("--out", type=Path, default=REPO / "phases/02-design/output/microsoft/eval", help="Output folder")
    args = parser.parse_args(argv)
    advisor.utf8_stdout()

    cases = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    try:
        client = advisor.Advisor()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    print(f"{'Case':<5} {'Profile':<11} {'Result':<6} Response / notes")
    for case in cases:
        for attempt in range(args.repeat):
            try:
                run = client.ask(case["question"], case["profile"])
            except Exception as exc:
                print(f"error: case {case['id']} failed to run: {exc}", file=sys.stderr)
                return 2
            misses = evaluate(case, run)
            results.append({"id": case["id"], "attempt": attempt + 1, "profile": case["profile"], "passed": not misses,
                            "misses": misses, "responseId": run["responseId"], "agent": run["agent"],
                            "toolCalls": run["toolCalls"], "answerable": run["result"]["answerable"]})
            label = case["id"] if args.repeat == 1 else f"{case['id']}.{attempt + 1}"
            print(f"{label:<5} {case['profile']:<11} {'PASS' if not misses else 'FAIL':<6} {run['responseId']}")
            for miss in misses:
                print(f"{'':<24}- {miss}")

    passed = sum(r["passed"] for r in results)
    per_case = {}
    for r in results:
        per_case.setdefault(r["id"], []).append(r["passed"])
    summary = {"cases": len(cases), "runs": len(results), "passed": passed, "repeat": args.repeat,
               "stability": {cid: f"{sum(v)}/{len(v)}" for cid, v in per_case.items()},
               "results": results, "model": client.model,
               "agents": {p: f"{a.name} v{a.version}" for p, a in client.agents.items()}}
    (args.out / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.repeat > 1:
        print("\nPer-case stability: " + ", ".join(f"{cid} {s}" for cid, s in summary["stability"].items()))
    print(f"\n{passed}/{len(results)} runs passed · results: {args.out / 'results.json'}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
