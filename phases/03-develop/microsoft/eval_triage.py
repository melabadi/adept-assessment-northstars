#!/usr/bin/env python3
"""Evaluate live RequestHub triage on 12 labelled cases (Develop phase, Microsoft track).

Each case goes through the RequestHub API, not straight to the model, so every check covers the whole path:
API authorization -> Foundry agent -> tools executed by the app -> deterministic guards -> stored recommendation.
The evaluator is deterministic code. It reports repeatability instead of assuming the model is deterministic.

Prerequisite: a RequestHub API running with the Foundry provider and development sign-in, for example the local
API from phases/03-develop/README.md, or the API started by the develop-foundry workflow.

Usage
  python phases/03-develop/microsoft/eval_triage.py                       # all cases against http://localhost:5090
  python phases/03-develop/microsoft/eval_triage.py --cases T06,T08 --repeat 3
  python phases/03-develop/microsoft/eval_triage.py --issues              # open or update one GitHub Issue per failing case

Case format (eval_cases.jsonl, one JSON object per line)
  id, kind, title   labels used in the report
  persona           development sign-in persona that asks for triage (u-ben is an IT/FAC reviewer, u-grace FIN/HR)
  request           an existing request id, or
  create            a new request {title, description, category, departmentId} that u-ava submits first
  expect            status        expected HTTP status (default 201)
                    departments   allowed suggested departments
                    priorities    allowed suggested priorities
                    review        expected needsHumanReview
                    cite          policy ids that must be cited
                    question      true if a clarifying question is required
                    rationaleExcludes  text that must not appear in the rationale (data leaks)

Every case also checks that triage changed nothing on the request (no approval through the AI path), that the
agent read the request through its tool, and that it never read another request. Refused calls must leave no
recommendation and no tool calls behind.

Exit codes: 0 every run passed, 1 at least one run failed, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "common"))
from azd_env import REPO, utf8_stdout  # noqa: E402

OBSERVER = "u-dan"  # admin persona used only to read state before and after each case
SUBMITTER = "u-ava"  # requester persona that submits the synthetic requests in `create` cases
ISSUE_LABEL = "triage-eval"


class Api:
    def __init__(self, base: str, timeout: float):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def call(self, method: str, path: str, persona: str, body: dict | None = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        req.add_header("X-RequestHub-User", persona)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                return err.code, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return err.code, raw.decode(errors="replace")

    def get(self, path: str, persona: str = OBSERVER):
        status, body = self.call("GET", path, persona)
        if status != 200:
            raise RuntimeError(f"GET {path} returned HTTP {status}: {body}")
        return body


def snapshot(api: Api, request_id: str) -> dict:
    detail = api.get(f"/api/requests/{request_id}")
    history = api.get(f"/api/requests/{request_id}/history")
    return {
        "state": {k: detail.get(k) for k in ("status", "departmentId", "priority")} | {"decision": detail.get("decision")},
        "lastAuditId": max((e["id"] for e in history), default=0),
    }


def run_case(api: Api, case: dict, provider: str) -> dict:
    expect = case["expect"]
    request_id = case.get("request")
    if "create" in case:
        status, created = api.call("POST", "/api/requests", SUBMITTER, case["create"])
        if status != 201:
            raise RuntimeError(f"{case['id']}: could not create the synthetic request (HTTP {status}: {created})")
        request_id = created["id"]

    before = snapshot(api, request_id)
    status, body = api.call("POST", f"/api/requests/{request_id}/triage-recommendations", case["persona"])
    after = snapshot(api, request_id)
    events = [e for e in api.get(f"/api/requests/{request_id}/history") if e["id"] > before["lastAuditId"]]
    tool_calls = [e["details"] for e in events if e["action"] == "triage.tool_call"]

    misses: list[str] = []
    expected_status = expect.get("status", 201)
    if status != expected_status:
        detail = body.get("detail") if isinstance(body, dict) else body
        misses.append(f"expected HTTP {expected_status}, got {status} ({detail})")
    if after["state"] != before["state"]:
        misses.append(f"triage changed the request: {before['state']} -> {after['state']}")

    rec = body if status == 201 and isinstance(body, dict) else None
    if expected_status != 201:
        if tool_calls or any(e["action"] == "triage.recommended" for e in events):
            misses.append("a refused call still reached the agent or stored a recommendation")
    elif rec:
        cited = [p["policyId"] for p in rec["policyRefs"]]
        if rec["provider"] != provider or rec["isSample"]:
            misses.append(f"expected live provider {provider}, got {rec['provider']} (sample={rec['isSample']})")
        if not str(rec.get("providerTraceId") or "").startswith("resp_"):
            misses.append("no Foundry response id (providerTraceId) recorded")
        if "departments" in expect and rec["suggestedDepartmentId"] not in expect["departments"]:
            misses.append(f"department {rec['suggestedDepartmentId']}, expected one of {expect['departments']}")
        if "priorities" in expect and rec["suggestedPriority"] not in expect["priorities"]:
            misses.append(f"priority {rec['suggestedPriority']}, expected one of {expect['priorities']}")
        if "review" in expect and rec["needsHumanReview"] != expect["review"]:
            misses.append(f"needsHumanReview={rec['needsHumanReview']}, expected {expect['review']}")
        for policy in expect.get("cite", []):
            if policy not in cited:
                misses.append(f"did not cite {policy} (cited {', '.join(cited)})")
        if expect.get("question") and "Question:" not in rec["rationale"]:
            misses.append("no clarifying question")
        for text in expect.get("rationaleExcludes", []):
            if text.lower() in rec["rationale"].lower():
                misses.append(f"rationale contains '{text}' from another request")
        own_reads = [t for t in tool_calls if t.get("tool") == "get_request" and t.get("outcome") == "ok" and t.get("requestId") == request_id]
        foreign = [t for t in tool_calls if t.get("outcome") == "ok" and t.get("requestId") not in (None, request_id)]
        if not own_reads:
            misses.append("the agent did not read the request through get_request")
        if foreign:
            misses.append(f"the agent read another request: {foreign}")

    return {
        "id": case["id"], "kind": case["kind"], "title": case["title"], "persona": case["persona"], "request": request_id,
        "passed": not misses, "misses": misses, "httpStatus": status,
        "department": rec["suggestedDepartmentId"] if rec else None,
        "priority": rec["suggestedPriority"] if rec else None,
        "needsHumanReview": rec["needsHumanReview"] if rec else None,
        "cited": [p["policyId"] for p in rec["policyRefs"]] if rec else [],
        "rationale": rec["rationale"] if rec else None,
        "traceId": rec.get("providerTraceId") if rec else None,
        "toolCalls": tool_calls,
    }


def report_markdown(summary: dict) -> str:
    lines = [
        "## Triage evaluation",
        "",
        f"API `{summary['api']}` · provider `{summary['provider']}` · {summary['passed']}/{summary['runs']} runs passed"
        + (f" · {summary['repeat']} runs per case" if summary["repeat"] > 1 else ""),
        "",
        "| Case | Kind | Result | Department | Review | Cited | Tool calls | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        label = r["id"] if summary["repeat"] == 1 else f"{r['id']}.{r['attempt']}"
        tools = ", ".join(f"{t.get('tool')}:{t.get('outcome')}" for t in r["toolCalls"]) or "none"
        notes = "; ".join(r["misses"]) or r["title"]
        dept = r["department"] or f"HTTP {r['httpStatus']}"
        review = "" if r["needsHumanReview"] is None else ("yes" if r["needsHumanReview"] else "no")
        lines.append(f"| {label} | {r['kind']} | {'PASS' if r['passed'] else 'FAIL'} | {dept} | {review} | {', '.join(r['cited'])} | {tools} | {notes} |")
    if summary["repeat"] > 1:
        lines += ["", "Repeatability: " + ", ".join(f"{cid} {s}" for cid, s in summary["stability"].items())]
    return "\n".join(lines) + "\n"


def gh(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def sync_issues(summary: dict, cases: dict) -> None:
    """One open Issue per failing case (stable title prefix), updated on repeat failures and closed when the case passes again."""
    if not shutil.which("gh"):
        raise RuntimeError("--issues needs the GitHub CLI (gh)")
    gh("label", "create", ISSUE_LABEL, "--color", "D93F0B", "--description", "Failing Foundry triage evaluation case", "--force")
    open_issues = json.loads(gh("issue", "list", "--label", ISSUE_LABEL, "--state", "open", "--limit", "100", "--json", "number,title"))
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    by_case: dict[str, list[dict]] = {}
    for r in summary["results"]:
        by_case.setdefault(r["id"], []).append(r)
    for cid, runs in by_case.items():
        prefix = f"[triage-eval {cid}]"
        existing = next((i for i in open_issues if i["title"].startswith(prefix)), None)
        failed = [r for r in runs if not r["passed"]]
        if not failed:
            if existing:
                gh("issue", "close", str(existing["number"]), "--comment",
                   f"{cid} passed {len(runs)}/{len(runs)} runs{' in ' + run_url if run_url else ''}. Closing.")
                print(f"closed #{existing['number']} ({cid} passes again)")
            continue
        case = cases[cid]
        body = "\n".join([
            f"Triage evaluation case **{cid}** ({case['kind']}): {case['title']}",
            "",
            f"Failed {len(failed)}/{len(runs)} runs{' in ' + run_url if run_url else ''}.",
            "",
            "**Expected**",
            "```json",
            json.dumps(case["expect"], indent=2),
            "```",
            "**Observed**",
            *[f"- run {r['attempt']}: " + "; ".join(r["misses"]) + (f" (response `{r['traceId']}`)" if r["traceId"] else "") for r in failed],
            "",
            f"Rationale of the last failing run: {failed[-1]['rationale'] or 'n/a'}",
            "",
            f"Reproduce: `python phases/03-develop/microsoft/eval_triage.py --cases {cid} --repeat 3`",
            "Fix the agent instructions in `phases/03-develop/microsoft/triage-agent.yaml`, the routing policy data, or the "
            "app guard, then republish and rerun. Do not change the expected result to make the case pass unless the policy changed.",
        ])
        if existing:
            gh("issue", "comment", str(existing["number"]), "--body-file", "-", stdin=body)
            print(f"updated #{existing['number']} ({cid})")
        else:
            url = gh("issue", "create", "--title", f"{prefix} {case['title']}", "--label", ISSUE_LABEL, "--body-file", "-", stdin=body).strip()
            print(f"opened {url} ({cid})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=os.environ.get("REQUESTHUB_API", "http://localhost:5090"), help="RequestHub API base URL (default http://localhost:5090 or REQUESTHUB_API)")
    parser.add_argument("--cases", help="Comma-separated case ids to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times to measure repeatability (default 1)")
    parser.add_argument("--provider", default="foundry-agent", help="Triage provider id the API must report (default foundry-agent)")
    parser.add_argument("--timeout", type=float, default=120, help="Seconds to wait for each API call (default 120)")
    parser.add_argument("--issues", action="store_true", help="Open/update a GitHub Issue per failing case and close Issues for cases that pass again")
    parser.add_argument("--out", type=Path, default=REPO / "phases/03-develop/output/microsoft/eval", help="Output folder")
    args = parser.parse_args(argv)
    utf8_stdout()

    all_cases = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = all_cases
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in all_cases if c["id"] in wanted]
    api = Api(args.api, args.timeout)
    try:
        meta = api.get("/api/meta")
    except Exception as exc:
        print(f"error: cannot reach the RequestHub API at {args.api}: {exc}", file=sys.stderr)
        return 2
    if meta.get("authMode") != "Development":
        print("error: the evaluation switches personas, so it needs an API that uses development sign-in (Auth__Mode=Development).", file=sys.stderr)
        return 2
    if meta.get("triageProvider") != args.provider:
        print(f"error: the API uses triage provider '{meta.get('triageProvider')}', expected '{args.provider}'. "
              "Start it with Triage__Provider=Foundry (see phases/03-develop/README.md).", file=sys.stderr)
        return 2

    results = []
    print(f"{'Case':<6} {'Kind':<16} {'Result':<6} {'Dept':<5} {'Review':<6} Notes")
    for case in cases:
        for attempt in range(args.repeat):
            try:
                result = run_case(api, case, args.provider) | {"attempt": attempt + 1}
            except Exception as exc:
                print(f"error: case {case['id']} could not run: {exc}", file=sys.stderr)
                return 2
            results.append(result)
            label = case["id"] if args.repeat == 1 else f"{case['id']}.{attempt + 1}"
            review = "" if result["needsHumanReview"] is None else ("yes" if result["needsHumanReview"] else "no")
            dept = result["department"] or str(result["httpStatus"])
            print(f"{label:<6} {case['kind']:<16} {'PASS' if result['passed'] else 'FAIL':<6} {dept:<5} {review:<6} {case['title']}")
            for miss in result["misses"]:
                print(f"{'':<42}- {miss}")

    per_case: dict[str, list[bool]] = {}
    for r in results:
        per_case.setdefault(r["id"], []).append(r["passed"])
    passed = sum(r["passed"] for r in results)
    summary = {"api": args.api, "provider": meta["triageProvider"], "appVersion": meta.get("appVersion"), "buildSha": meta.get("buildSha"),
               "cases": len(cases), "runs": len(results), "passed": passed, "repeat": args.repeat,
               "stability": {cid: f"{sum(v)}/{len(v)}" for cid, v in per_case.items()}, "results": results}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    markdown = report_markdown(summary)
    (args.out / "report.md").write_text(markdown, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(markdown)
    if args.repeat > 1:
        print("\nRepeatability: " + ", ".join(f"{cid} {s}" for cid, s in summary["stability"].items()))
    print(f"\n{passed}/{len(results)} runs passed · report: {args.out / 'report.md'}")

    if args.issues:
        try:
            sync_issues(summary, {c["id"]: c for c in all_cases})
        except Exception as exc:
            print(f"error: could not sync GitHub Issues: {exc}", file=sys.stderr)
            return 2
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
