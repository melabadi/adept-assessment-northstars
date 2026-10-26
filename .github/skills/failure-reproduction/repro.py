#!/usr/bin/env python3
"""Reproduce a reported defect against a running RequestHub API before writing the regression test (failure-reproduction skill).

A scenario file turns an Issue's "steps to reproduce" into data: who calls which endpoint, with what body and headers,
and what the correct behavior is. The script runs the steps and compares actual with expected results, so you know the
defect is real (and which expectation it breaks) before you encode it as an automated test.

Scenario format (JSON)
  title       one line
  steps[]     name          what the step does
              as            development sign-in persona (u-ava requester, u-chloe approver, u-dan admin, ...)
              method, path  HTTP call; {name} placeholders use saved values, {run} is unique per run
              body, headers optional JSON body and extra headers (for example Idempotency-Key)
              parallel      send the same call N times at once (double-click and retry races)
              save          {"var": "jsonField"} stores a field of the response for later steps
              expect        status (single call), statusCounts {"201": 1, "409": 7} (parallel call),
                            code (problem "code"), field {"name": "value"} (response field equals),
                            countWhere {"field": "action", "equals": "decision.recorded", "count": 1} (list responses)

Usage
  python .github/skills/failure-reproduction/repro.py phases/04-test/github/repro/duplicate-decision.json
  python .github/skills/failure-reproduction/repro.py phases/04-test/github/repro/whitespace-rejection.json --api http://localhost:5080

Exit codes: 0 every expectation held (not reproduced), 1 defect reproduced, 2 configuration or connection error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def fill(text: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def call(api: str, step: dict, values: dict) -> tuple[int, object]:
    body = fill(json.dumps(step["body"]), values).encode() if "body" in step else None
    req = urllib.request.Request(api.rstrip("/") + fill(step["path"], values), data=body, method=step.get("method", "GET"))
    req.add_header("X-RequestHub-User", step["as"])
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in step.get("headers", {}).items():
        req.add_header(key, fill(value, values))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return err.code, raw.decode(errors="replace")[:200]


def check(step: dict, results: list[tuple[int, object]]) -> tuple[str, list[str]]:
    expect, misses = step.get("expect", {}), []
    statuses = [s for s, _ in results]
    if "statusCounts" in expect:
        actual = {str(s): statuses.count(s) for s in sorted(set(statuses))}
        if actual != {k: v for k, v in expect["statusCounts"].items() if v}:
            misses.append(f"status counts {actual}, expected {expect['statusCounts']}")
        return ", ".join(f"HTTP {k} x{v}" for k, v in actual.items()), misses
    status, body = results[0]
    if "status" in expect and status != expect["status"]:
        misses.append(f"HTTP {status}, expected {expect['status']}")
    if "code" in expect and (not isinstance(body, dict) or body.get("code") != expect["code"]):
        misses.append(f"code {body.get('code') if isinstance(body, dict) else None}, expected {expect['code']}")
    for name, value in expect.get("field", {}).items():
        actual = body.get(name) if isinstance(body, dict) else None
        if actual != value:
            misses.append(f"{name} = {actual!r}, expected {value!r}")
    if "countWhere" in expect:
        rule = expect["countWhere"]
        count = sum(1 for item in (body if isinstance(body, list) else []) if item.get(rule["field"]) == rule["equals"])
        if count != rule["count"]:
            misses.append(f"{count} item(s) with {rule['field']}={rule['equals']}, expected {rule['count']}")
    return f"HTTP {status}", misses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", type=Path, help="Scenario JSON file")
    parser.add_argument("--api", default="http://localhost:5080", help="RequestHub API base URL with development sign-in (default http://localhost:5080)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    values: dict[str, object] = {"run": time.strftime("%Y%m%d%H%M%S")}
    failed = 0
    print(f"Scenario: {scenario['title']}  ({args.api})\n")
    for number, step in enumerate(scenario["steps"], 1):
        count = step.get("parallel", 1)
        try:
            with ThreadPoolExecutor(max_workers=count) as pool:
                results = list(pool.map(lambda _: call(args.api, step, values), range(count)))
        except (urllib.error.URLError, OSError) as exc:
            print(f"error: cannot reach {args.api}: {exc}", file=sys.stderr)
            return 2
        actual, misses = check(step, results)
        for var, field in step.get("save", {}).items():
            if isinstance(results[0][1], dict):
                values[var] = results[0][1].get(field)
        failed += bool(misses)
        print(f"{number:>2}. {'FAIL' if misses else 'ok  '} {step['name']}  ->  {actual}")
        for miss in misses:
            print(f"          {miss}")
    print(f"\nREPRODUCED: {failed} step(s) did not behave as expected." if failed else "\nNot reproduced: every step behaved as expected.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
