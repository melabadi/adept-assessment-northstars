#!/usr/bin/env python3
"""Smoke-test a running RequestHub release: the deployment check of the release candidate workflow.

The candidate workflow starts the API and worker container images it just pushed (by digest) on the runner, then runs
this script against them. It proves the exact images being released start, run the business flow, keep the human
approval rule, and were built from the commit being released.

Checks (each becomes one test case in the JUnit report)
  api_ready                 GET /health/ready answers 200 (waits up to --timeout seconds for startup and migrations).
  build_matches_commit      GET /api/meta reports the expected build SHA (--expect-sha) and contract requesthub.v1.
  submit_request            Ava (requester) submits a request.
  triage_is_advisory        Ben (reviewer) asks for a triage recommendation; the request stays undecided.
  self_approval_refused     Hugo (requester and approver) cannot approve his own request (403 decision.self_approval).
  approver_decides          Chloé (approver) approves Ava's request.
  history_records_decision  The audit history shows Chloé's decision.
  worker_ready              The worker's GET /health/ready answers 200 (only with --worker).
  notifications_delivered   The worker drains the notification backlog with no failures (only with --worker).

It uses the development persona header (X-RequestHub-User), so the API must run with ASPNETCORE_ENVIRONMENT=Development.
Standard library only.

Usage
  python smoke_test.py --api http://localhost:8080 --worker http://localhost:8081 --expect-sha <commit> \
      --junit evidence/smoke-tests.junit.xml --json evidence/smoke-results.json

Exit codes: 0 every check passed, 1 a check failed, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

CONTRACT = "requesthub.v1"


class CheckFailed(Exception):
    pass


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, persona: str | None = None, body: dict | None = None,
             idempotency_key: str | None = None) -> tuple[int, object]:
        headers = {"Accept": "application/json"}
        data = None
        if persona:
            headers["X-RequestHub-User"] = persona
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw.decode(errors="replace")[:500]


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def wait_ready(api: Api, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            status, body = api.call("GET", "/health/ready")
            if status == 200:
                return "ready"
            last = f"HTTP {status}: {body}"
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
        time.sleep(2)
    raise CheckFailed(f"{api.base}/health/ready not ready after {timeout:.0f}s ({last})")


def run_checks(args: argparse.Namespace) -> tuple[list[dict], dict]:
    api = Api(args.api)
    worker = Api(args.worker) if args.worker else None
    state: dict = {}
    run_id = uuid.uuid4().hex[:8]

    def api_ready() -> str:
        return wait_ready(api, args.timeout)

    def build_matches_commit() -> str:
        status, meta = api.call("GET", "/api/meta")
        expect(status == 200 and isinstance(meta, dict), f"GET /api/meta returned HTTP {status}")
        state["meta"] = meta
        expect(meta.get("contractVersion") == CONTRACT, f"contract is {meta.get('contractVersion')!r}, expected {CONTRACT}")
        if args.expect_sha:
            expect(meta.get("buildSha") == args.expect_sha,
                   f"image reports build SHA {meta.get('buildSha')!r}, expected {args.expect_sha}")
        return f"build {meta.get('buildSha')}, {meta.get('appVersion')}, contract {meta.get('contractVersion')}"

    def submit_request() -> str:
        status, created = api.call("POST", "/api/requests", "u-ava", {
            "title": f"Smoke test docking station {run_id}",
            "description": "Release smoke test: a synthetic request submitted against the release images.",
            "category": "equipment",
            "departmentId": "IT",
            "priority": "Normal",
        }, idempotency_key=f"smoke-{run_id}")
        expect(status == 201 and isinstance(created, dict), f"POST /api/requests returned HTTP {status}: {created}")
        state["request"] = created["id"]
        return f"{created['id']} submitted by u-ava, status {created.get('status')}"

    def triage_is_advisory() -> str:
        rid = state["request"]
        status, rec = api.call("POST", f"/api/requests/{rid}/triage-recommendations", "u-ben")
        expect(status == 201 and isinstance(rec, dict), f"triage returned HTTP {status}: {rec}")
        status, detail = api.call("GET", f"/api/requests/{rid}", "u-ben")
        expect(status == 200 and isinstance(detail, dict), f"GET request returned HTTP {status}")
        expect(detail.get("decision") is None and detail.get("status") not in ("Approved", "Rejected"),
               f"the recommendation changed the decision: status {detail.get('status')}")
        return f"recommended {rec.get('suggestedDepartmentId')} ({rec.get('provider')}); request still {detail.get('status')}"

    def self_approval_refused() -> str:
        status, created = api.call("POST", "/api/requests", "u-hugo", {
            "title": f"Smoke test self-approval {run_id}",
            "description": "Release smoke test: the requester tries to approve their own request.",
            "category": "equipment",
            "departmentId": "IT",
        })
        expect(status == 201 and isinstance(created, dict), f"u-hugo could not submit a request: HTTP {status}")
        status, problem = api.call("POST", f"/api/requests/{created['id']}/decisions", "u-hugo", {"outcome": "Approved"})
        code = problem.get("code") if isinstance(problem, dict) else None
        expect(status == 403 and code == "decision.self_approval",
               f"self-approval returned HTTP {status} {code!r}, expected 403 decision.self_approval")
        return f"{created['id']}: u-hugo refused with 403 decision.self_approval"

    def approver_decides() -> str:
        rid = state["request"]
        status, decision = api.call("POST", f"/api/requests/{rid}/decisions", "u-chloe",
                                    {"outcome": "Approved", "comment": "Release smoke test"})
        expect(status == 201 and isinstance(decision, dict), f"decision returned HTTP {status}: {decision}")
        decided_by = (decision.get("decidedBy") or {}).get("id")
        expect(decided_by == "u-chloe", f"decision recorded for {decided_by!r}, expected u-chloe")
        return f"{rid} approved by u-chloe"

    def history_records_decision() -> str:
        rid = state["request"]
        status, history = api.call("GET", f"/api/requests/{rid}/history", "u-ava")
        expect(status == 200 and isinstance(history, list), f"history returned HTTP {status}")
        actions = [(e.get("action"), (e.get("actor") or {}).get("id")) for e in history]
        expect(("decision.recorded", "u-chloe") in actions, f"no decision.recorded by u-chloe in {actions}")
        return f"{len(history)} audit events, including decision.recorded by u-chloe"

    def worker_ready() -> str:
        return wait_ready(worker, args.timeout)

    def notifications_delivered() -> str:
        deadline = time.monotonic() + args.timeout
        backlog: object = None
        while time.monotonic() < deadline:
            status, backlog = api.call("GET", "/api/admin/notifications/backlog", "u-dan")
            expect(status == 200 and isinstance(backlog, dict), f"backlog returned HTTP {status}: {backlog}")
            if backlog.get("pending") == 0:
                expect(backlog.get("failed") == 0, f"{backlog.get('failed')} notifications failed")
                return "backlog drained: 0 pending, 0 failed"
            time.sleep(2)
        raise CheckFailed(f"backlog not drained after {args.timeout:.0f}s: {backlog}")

    checks = [api_ready, build_matches_commit, submit_request, triage_is_advisory, self_approval_refused,
              approver_decides, history_records_decision]
    if worker:
        checks += [worker_ready, notifications_delivered]

    results = []
    for check in checks:
        started = time.monotonic()
        name = check.__name__
        if name in ("triage_is_advisory", "approver_decides", "history_records_decision") and "request" not in state:
            results.append({"name": name, "status": "skipped", "detail": "no request was submitted", "seconds": 0.0})
            print(f"SKIP  {name}: no request was submitted", flush=True)
            continue
        try:
            detail, status = check(), "passed"
        except CheckFailed as error:
            detail, status = str(error), "failed"
        except (urllib.error.URLError, OSError, KeyError, TypeError) as error:
            detail, status = f"{type(error).__name__}: {error}", "failed"
        results.append({"name": name, "status": status, "detail": detail, "seconds": round(time.monotonic() - started, 3)})
        print(f"{'PASS' if status == 'passed' else 'FAIL'}  {name}: {detail}", flush=True)
        if name == "api_ready" and status == "failed":
            break
    return results, state


def write_junit(results: list[dict], path: Path) -> None:
    failures = sum(r["status"] == "failed" for r in results)
    skipped = sum(r["status"] == "skipped" for r in results)
    total_time = sum(r["seconds"] for r in results)
    suites = ET.Element("testsuites", name="smoke", tests=str(len(results)), failures=str(failures), errors="0",
                        skipped=str(skipped), time=f"{total_time:.3f}")
    suite = ET.SubElement(suites, "testsuite", name="RequestHub release smoke test", tests=str(len(results)),
                          failures=str(failures), errors="0", skipped=str(skipped), time=f"{total_time:.3f}",
                          timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    for result in results:
        case = ET.SubElement(suite, "testcase", classname="smoke", name=result["name"], time=f"{result['seconds']:.3f}")
        if result["status"] == "failed":
            ET.SubElement(case, "failure", message=result["detail"][:300]).text = result["detail"]
        elif result["status"] == "skipped":
            ET.SubElement(case, "skipped", message=result["detail"])
        else:
            ET.SubElement(case, "system-out").text = result["detail"]
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True, help="base URL of the running API, for example http://localhost:8080")
    parser.add_argument("--worker", help="base URL of the running worker; adds the worker checks")
    parser.add_argument("--expect-sha", help="commit SHA the API image must report in /api/meta (its BUILD_SHA)")
    parser.add_argument("--timeout", type=float, default=120, help="seconds to wait for readiness and the backlog (default 120)")
    parser.add_argument("--junit", type=Path, help="write a JUnit XML report to this file")
    parser.add_argument("--json", type=Path, help="write the check results and metadata as JSON to this file")
    args = parser.parse_args(argv)

    results, state = run_checks(args)
    if args.junit:
        write_junit(results, args.junit)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "schema": "release-github/smoke@1",
            "api": args.api,
            "worker": args.worker,
            "expected_sha": args.expect_sha,
            "meta": state.get("meta"),
            "request": state.get("request"),
            "checks": results,
        }, indent=2) + "\n", encoding="utf-8")
    failed = [r for r in results if r["status"] == "failed"]
    print(f"\n{len(results) - len(failed)}/{len(results)} smoke checks passed" if not failed
          else f"\n{len(failed)} of {len(results)} smoke checks failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
