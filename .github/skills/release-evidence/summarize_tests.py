#!/usr/bin/env python3
"""Summarize JUnit XML test reports into release evidence, and refuse a release when tests failed.

What it does
  1. Reads one JUnit XML report per test suite. xUnit (dotnet test), Vitest, Playwright, and smoke_test.py all
     write JUnit, so one parser covers the whole release.
  2. Counts tests, passes, failures, errors, and skips per suite from the <testcase> elements themselves, so a
     report header cannot overstate the result. Records each report's SHA-256.
  3. Writes test-summary.json and prints a Markdown table for the job summary.
  4. Exits 1 when a report is missing or unreadable, when a suite ran no tests, or when any test failed or errored.
     The release candidate workflow runs this gate before it drafts a release.

Usage
  python summarize_tests.py --suite api=evidence/api-tests.junit.xml --suite web=evidence/web-tests.junit.xml \
      --out evidence/test-summary.json
  python summarize_tests.py --suite smoke=out/smoke-tests.junit.xml          # print the table only

Exit codes: 0 every suite passed, 1 the gate failed, 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "release-github/test-summary@1"
MAX_FAILING = 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seconds(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


def parse_junit(path: Path) -> dict:
    """Count the outcome of every <testcase> in a JUnit XML file (root <testsuites> or <testsuite>)."""
    root = ET.parse(path).getroot()
    if root.tag not in ("testsuites", "testsuite"):
        raise ValueError(f"root element is <{root.tag}>, expected <testsuites> or <testsuite>")
    cases = list(root.iter("testcase"))
    failed = errors = skipped = 0
    failing: list[dict] = []
    for case in cases:
        failure = case.find("failure")
        error = case.find("error")
        if failure is not None or error is not None:
            node = failure if failure is not None else error
            if failure is not None:
                failed += 1
            else:
                errors += 1
            if len(failing) < MAX_FAILING:
                name = ".".join(part for part in (case.get("classname"), case.get("name")) if part)
                message = (node.get("message") or node.text or "").strip().splitlines()
                failing.append({"test": name, "message": message[0][:300] if message else ""})
        elif case.find("skipped") is not None:
            skipped += 1
    if root.get("time"):
        duration = _seconds(root.get("time"))
    else:
        duration = sum(_seconds(suite.get("time")) for suite in root.iter("testsuite"))
    total = len(cases)
    return {
        "tests": total,
        "passed": total - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "duration_seconds": round(duration, 3),
        "failing": failing,
    }


def summarize(suites: list[tuple[str, Path]]) -> dict:
    """Build the test summary and the gate decision for (name, report path) pairs."""
    results, reasons = [], []
    for name, path in suites:
        entry: dict = {"name": name, "report": path.name}
        if not path.is_file():
            entry["error"] = "report not found"
            reasons.append(f"{name}: report {path.name} not found")
        else:
            try:
                entry.update(parse_junit(path))
                entry["sha256"] = sha256_file(path)
            except (ET.ParseError, ValueError) as exc:
                entry["error"] = f"unreadable report: {exc}"
                reasons.append(f"{name}: unreadable report ({exc})")
        if "error" not in entry:
            if entry["tests"] - entry["skipped"] == 0:
                reasons.append(f"{name}: no tests ran")
            if entry["failed"] or entry["errors"]:
                reasons.append(f"{name}: {entry['failed']} failed, {entry['errors']} errors")
        results.append(entry)
    totals = {key: sum(s.get(key, 0) for s in results) for key in ("tests", "passed", "failed", "errors", "skipped")}
    return {"schema": SCHEMA, "suites": results, "totals": totals, "gate": {"passed": not reasons, "reasons": reasons}}


def markdown(summary: dict) -> str:
    lines = [
        "| Suite | Tests | Passed | Failed | Errors | Skipped | Duration |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in summary["suites"]:
        if "error" in s:
            lines.append(f"| {s['name']} | {s['error']} | | | | | |")
        else:
            lines.append(
                f"| {s['name']} | {s['tests']} | {s['passed']} | {s['failed']} | {s['errors']} | {s['skipped']} "
                f"| {s['duration_seconds']:.1f} s |"
            )
    gate = summary["gate"]
    lines.append("")
    lines.append("**Gate: passed.** Every suite ran tests and none failed." if gate["passed"]
                 else "**Gate: failed.** " + "; ".join(gate["reasons"]))
    for s in summary["suites"]:
        for failure in s.get("failing", []):
            lines.append(f"- `{s['name']}` {failure['test']}: {failure['message']}")
    return "\n".join(lines)


def parse_suite(value: str) -> tuple[str, Path]:
    name, sep, path = value.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=PATH, got {value!r}")
    return name.strip(), Path(path.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", action="append", type=parse_suite, required=True, metavar="NAME=PATH",
                        help="a suite name and its JUnit XML report; repeat for every suite (order is kept)")
    parser.add_argument("--out", type=Path, help="also write the summary as JSON to this file")
    args = parser.parse_args(argv)

    summary = summarize(args.suite)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(markdown(summary))
    return 0 if summary["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
