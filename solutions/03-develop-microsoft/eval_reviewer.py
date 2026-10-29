#!/usr/bin/env python3
"""Evaluate the Azure pull request reviewer on labelled pull requests (Develop phase, Microsoft track).

What this script does:
  1. Reads eval_cases.jsonl: real pull requests of this repository, each labelled known-good, flagged (a good change that
     a rule rightly flags for a person), or known-bad, with the rules that should fail and what the commentary should
     mention.
  2. Runs the deployed reviewer on each one in dry-run mode: it posts {"dryRun": true, "pr": <number>} to the Logic App's
     trigger. The Logic App does everything it does for a real review (rule checker, sandbox build and tests, agent,
     review formatter) but posts nothing to GitHub. The script reads each run's Result step from the run history.
  3. Scores every result on this machine with the five checks in review_graders.py.
  4. Registers the same checks in Microsoft Foundry as code-based evaluators (preview) and runs a Foundry evaluation over
     the same results, so they appear in the project's Evaluation view. --local skips this step; the local scores in
     step 3 are the fallback.

The trigger URL carries a signature, so the script fetches it from Azure Resource Manager each time and never prints or
saves it. Results go to out/eval/ (results.jsonl and report.md), which git ignores.

Configuration: this solution's azd environment (after `azd up`) or environment variables: AZURE_SUBSCRIPTION_ID,
AZURE_RESOURCE_GROUP, REVIEWER_LOGIC_APP, FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT. You need Logic App
Contributor (or Contributor) on the resource group and the Foundry User role on the Foundry account; `azd up` gives you
both as the person who runs it. The Logic App needs GITHUB_REVIEW_TOKEN, as for a real review.

Usage
  python eval_reviewer.py                    # every case: dry runs, local scores, then a Foundry evaluation
  python eval_reviewer.py --cases 36 99      # only these pull requests
  python eval_reviewer.py --reuse            # score the results of the last dry runs again, without new runs
  python eval_reviewer.py --local            # skip the Foundry evaluation
  python eval_reviewer.py --parallel 5       # dry runs at a time (default 4; each uses two of the pools' ten sessions)
  python eval_reviewer.py --show-url         # also print the Foundry report link (it contains resource ids)

Exit codes: 0 every check passed for every pull request, 1 at least one check failed, 2 configuration or service error.
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

OUT = HERE / "out" / "eval"
TRIGGER = "When_a_pull_request_event_arrives"
ARM = "https://management.azure.com"
LOGIC_API = "api-version=2019-05-01"
EVAL_NAME = "Azure pull request reviewer: labelled pull requests"
# Custom evaluators are a preview feature of Foundry: their calls must opt in.
PREVIEW = {"Foundry-Features": "Evaluations=V1Preview"}
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "pr": {"type": "integer"}, "kind": {"type": "string"}, "why": {"type": "string"},
        "expected_failures": {"type": "string"}, "expect_mentions": {"type": "string"}, "rules": {"type": "string"},
        "review": {"type": "string"}, "agent": {"type": "string"}, "sandbox": {"type": "string"},
    },
    "required": ["pr", "kind", "expected_failures", "expect_mentions", "rules", "review", "agent", "sandbox"],
}


class Arm:
    """The few Azure Resource Manager calls the script needs, with the caller's Azure CLI or developer sign-in."""

    def __init__(self, credential: DefaultAzureCredential):
        self.credential = credential
        self.workflow = (f"{ARM}/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/"
                         f"{setting('AZURE_RESOURCE_GROUP')}/providers/Microsoft.Logic/workflows/{setting('REVIEWER_LOGIC_APP')}")

    def call(self, method: str, url: str, body: object = None, signed: bool = False) -> tuple[int, dict, object]:
        headers = {"Content-Type": "application/json"}
        if not signed:
            headers["Authorization"] = "Bearer " + self.credential.get_token(f"{ARM}/.default").token
        request = urllib.request.Request(url, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
                return response.status, dict(response.headers), json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, dict(exc.headers), json.loads(data)
            except ValueError:
                return exc.code, dict(exc.headers), None

    def start_dry_run(self, pr: int) -> str:
        """Start one dry run and return its run id. The signed trigger URL lives only in this function."""
        status, _, callback = self.call("POST", f"{self.workflow}/triggers/{TRIGGER}/listCallbackUrl?{LOGIC_API}")
        if status != 200 or not isinstance(callback, dict) or "value" not in callback:
            raise RuntimeError(f"couldn't get the Logic App's trigger URL (HTTP {status})")
        status, headers, _ = self.call("POST", callback["value"], {"dryRun": True, "pr": pr}, signed=True)
        run = headers.get("x-ms-workflow-run-id")
        if status != 202 or not run:
            raise RuntimeError(f"the Logic App didn't start a run for #{pr} (HTTP {status})")
        return run

    def wait(self, run: str, timeout: int = 1800) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = self.call("GET", f"{self.workflow}/runs/{run}?{LOGIC_API}")
            state = (body or {}).get("properties", {}).get("status", "Unknown")
            if state not in ("Running", "Waiting"):
                return state
            time.sleep(15)
        return "TimedOut"

    def result(self, run: str) -> dict:
        """The Result step's output: what the reviewer produced for this pull request."""
        _, _, action = self.call("GET", f"{self.workflow}/runs/{run}/actions/Result?{LOGIC_API}")
        link = (action or {}).get("properties", {}).get("outputsLink", {}).get("uri")
        if not link:
            return {}
        _, _, outputs = self.call("GET", link, signed=True)  # a short-lived signed link to the run's stored output
        value = outputs.get("body", outputs) if isinstance(outputs, dict) else {}
        return value if isinstance(value, dict) else {}


def review_case(arm: Arm, case: dict) -> dict:
    pr = case["pr"]
    started = time.time()
    try:
        run = arm.start_dry_run(pr)
        state = arm.wait(run)
        result = arm.result(run) if state == "Succeeded" else {}
    except (RuntimeError, OSError) as exc:
        run, state, result = None, f"error: {exc}", {}
    print(f"  #{pr:<4} {state:<10} {int(time.time() - started):>4} s", flush=True)
    return {
        "pr": pr, "kind": case["kind"], "why": case["why"],
        "expected_failures": json.dumps(case["expected_failures"]), "expect_mentions": json.dumps(case["expect_mentions"]),
        "rules": json.dumps(result.get("rules") or []), "review": result.get("review") or "",
        "agent": json.dumps(result.get("agent")), "sandbox": result.get("sandbox") or "",
        "_run": run, "_status": state,
    }


def score(items: list[dict]) -> list[dict]:
    for item in items:
        item["_scores"] = {name: round(float(fn({}, item)), 3) for name, (fn, _) in GRADERS.items()}
    return items


def report(items: list[dict]) -> str:
    names = list(GRADERS)
    lines = ["| PR | Kind | " + " | ".join(GRADERS[n][1] for n in names) + " | Run |",
             "| --- | --- | " + " | ".join("---" for _ in names) + " | --- |"]
    for item in items:
        cells = ["✅" if item["_scores"][n] >= 1 else f"❌ {item['_scores'][n]:.2f}" for n in names]
        lines.append(f"| #{item['pr']} | {item['kind']} | " + " | ".join(cells) + f" | {item['_status']} |")
    passed = [sum(1 for i in items if i["_scores"][n] >= 1) for n in names]
    lines.append("| **Passed** | | " + " | ".join(f"**{p}/{len(items)}**" for p in passed) + " | |")
    return "\n".join(lines)


def grader_source(fn) -> str:
    import inspect
    return re.sub(r"^def \w+\(", "def grade(", inspect.getsource(fn), count=1)


def foundry_evaluation(items: list[dict], show_url: bool) -> bool:
    """Register the checks as code-based evaluators, then evaluate the same items in Foundry. True when it ran."""
    from azure.ai.projects import AIProjectClient

    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    criteria = []
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
            print(f"  registered evaluator {name} v{current.get('version')}")
        criteria.append({"type": "azure_ai_evaluator", "name": name, "evaluator_name": name,
                         "initialization_parameters": {"deployment_name": model, "pass_threshold": 1.0}})
    client = project.get_openai_client()
    existing = next((e for e in client.evals.list(limit=100) if e.name == EVAL_NAME
                     and sorted(c.name for c in e.testing_criteria) == sorted(GRADERS)), None)
    evaluation = existing or client.evals.create(
        name=EVAL_NAME, data_source_config={"type": "custom", "item_schema": ITEM_SCHEMA, "include_sample_schema": False},
        testing_criteria=criteria)
    versions = sorted({m.group(1) for i in items for m in [re.search(r"`requesthub-pr-reviewer` v(\d+)", i["review"])] if m})
    run = client.evals.runs.create(
        eval_id=evaluation.id,
        name=f"{len(items)} labelled pull request{'s' if len(items) != 1 else ''} · agent v{', v'.join(versions) or '?'} · "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        data_source={"type": "jsonl", "source": {"type": "file_content", "content": [
            {"item": {k: v for k, v in item.items() if not k.startswith("_")}} for item in items]}})
    print(f"  Foundry evaluation run started: {run.name}")
    while run.status not in ("completed", "failed", "canceled"):
        time.sleep(10)
        run = client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
    print(f"  Foundry evaluation run {run.status}.")
    for result in run.per_testing_criteria_results or []:
        print(f"    {result.testing_criteria:<40} passed {result.passed}, failed {result.failed}")
    if show_url and run.report_url:
        print(f"  Report: {run.report_url}")
    else:
        print(f"  See it in the Foundry portal: your project > Evaluation > \"{EVAL_NAME}\".")
    return run.status == "completed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=int, nargs="+", metavar="PR", help="Evaluate only these pull requests")
    parser.add_argument("--reuse", action="store_true", help="Score out/eval/results.jsonl again instead of running the reviewer")
    parser.add_argument("--local", action="store_true", help="Score locally only; skip the Foundry evaluation")
    parser.add_argument("--parallel", type=int, default=4, help="Dry runs at a time (default 4)")
    parser.add_argument("--show-url", action="store_true", help="Print the Foundry report link (it contains resource ids)")
    args = parser.parse_args(argv)
    utf8_stdout()
    cases = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.cases:
        cases = [c for c in cases if c["pr"] in args.cases]
    OUT.mkdir(parents=True, exist_ok=True)
    results = OUT / "results.jsonl"
    if args.reuse:
        items = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
        items = [i for i in items if not args.cases or i["pr"] in args.cases]
    else:
        print(f"Dry-running the reviewer on {len(cases)} labelled pull requests, {args.parallel} at a time:")
        arm = Arm(DefaultAzureCredential())
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            items = list(pool.map(lambda case: review_case(arm, case), cases))
        results.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    if not items:
        print("error: nothing to score", file=sys.stderr)
        return 2
    table = report(score(items))
    (OUT / "report.md").write_text(f"# Azure pull request reviewer: labelled pull requests\n\n{table}\n", encoding="utf-8")
    print("\n" + table + "\n")
    if not args.local:
        try:
            foundry_evaluation(items, args.show_url)
        except Exception as exc:  # preview service: keep the local scores, explain, and fail clearly
            print(f"error: the Foundry evaluation didn't run ({type(exc).__name__}: {str(exc)[:300]}). "
                  "The local scores above stand; run with --local to skip Foundry.", file=sys.stderr)
            return 2
    return 0 if all(s >= 1 for i in items for s in i["_scores"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
