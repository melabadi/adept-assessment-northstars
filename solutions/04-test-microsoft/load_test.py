#!/usr/bin/env python3
"""Run the RequestHub load test in Azure Load Testing and summarize the result for the team (Test phase, Microsoft track).

The test itself is loadtest/locustfile.py (the journey) and loadtest/requesthub-journey.yaml (workload settings and
pass/fail criteria). This script adds what depends on your deployment, runs the test, and explains the result:

  python load_test.py run                 render the configuration, create or update the test, run it, and report
  python load_test.py run --open          ...and open the run's live dashboard in the Azure portal as soon as it starts
  python load_test.py run --issue         ...and open, update, or close the GitHub Issue that tracks a failing journey
  python load_test.py config              only render out/loadtest.yaml (the GitHub workflow passes it to azure/load-testing)
  python load_test.py report --run-id ID  report on an existing test run (criteria, percentiles, server-side telemetry)
  python load_test.py cleanup             as an Admin, delete every request the load-test identities submitted

What `config` adds to requesthub-journey.yaml
  - LOCUST_HOST (the API URL), API_SCOPE (RequestHub's application ID URI), and the client ids of the two identities;
  - the two identities as engine identities, so the test signs in without any secret;
  - the API container app, Application Insights, and PostgreSQL as monitored app components.

What `report` shows
  The test result (PASSED or FAILED) and each criterion with its actual value, client-side percentiles per request,
  and the same time window from Application Insights: server-side p95 per operation and how many requests carried the
  rehearsal slowdown (requesthub.fault.queue_delay_ms). A failure while the slowdown was active is labelled an expected
  failure, a rehearsal of the gate rather than an acceptance run. The report also names the tested load, dataset,
  region, and compute shape, because a performance result means nothing without them. Output: out/report.md and
  out/run.json, plus the GitHub job summary when running in Actions. The report is posted to pull requests and Issues,
  so it never contains host names, resource names, ids, or subscription details; out/run.json does, and stays local.

Settings come from environment variables, else from this solution's azd environment (after `azd up`):
  AZURE_RESOURCE_GROUP, LOAD_TEST_NAME, LOAD_TEST_REQUESTER_IDENTITY, LOAD_TEST_APPROVER_IDENTITY, API_URL,
  API_IDENTIFIER_URI, API_APP_NAME, APPLICATIONINSIGHTS_NAME, POSTGRES_HOST, and GITHUB_REPOSITORY for --issue.

Needs the Azure CLI signed in with the Load Test Contributor role on the Load Testing resource (azd up grants it to
you and to the GitHub Actions identity), and the GitHub CLI for --issue.

Exit codes: 0 the run passed, 1 the run failed its criteria, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import setting, utf8_stdout  # noqa: E402

TEMPLATE = HERE / "loadtest" / "requesthub-journey.yaml"
OUT = HERE / "out"
ISSUE_LABEL = "load-test"
TERMINAL = {"DONE", "FAILED", "CANCELLED"}
FAULT_TAG = "requesthub.fault.queue_delay_ms"
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class AzError(RuntimeError):
    pass


def az(*args: str, parse: bool = True):
    """Run an Azure CLI command and return its JSON output."""
    exe = shutil.which("az")
    if not exe:
        raise AzError("the Azure CLI (az) is required: https://learn.microsoft.com/cli/azure/install-azure-cli")
    # The Azure CLI is a Python program: ask it for UTF-8 so names such as "Test · Microsoft" survive on Windows too.
    proc = subprocess.run([exe, *args, "--only-show-errors", "--output", "json"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if proc.returncode != 0:
        raise AzError(f"az {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return json.loads(proc.stdout) if parse and proc.stdout.strip() else proc.stdout


def resource_id(subscription: str, provider: str, name: str) -> str:
    return f"/subscriptions/{subscription}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}/providers/{provider}/{name}"


# ---------- config ----------

def render_config(users: int | None = None, duration: int | None = None) -> Path:
    """Write out/loadtest.yaml: the committed configuration plus this deployment's values."""
    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    subscription = az("account", "show", "--query", "id")
    group = setting("AZURE_RESOURCE_GROUP")
    identities = {}
    for role in ("REQUESTER", "APPROVER"):
        name = setting(f"LOAD_TEST_{role}_IDENTITY")
        identity = az("identity", "show", "--resource-group", group, "--name", name, "--query", "{id:id, clientId:clientId}")
        identities[role] = identity

    env = {item["name"]: str(item["value"]) for item in config.get("env", [])}
    env.update({
        "LOCUST_HOST": setting("API_URL"),
        "RH_AUTH": "managed-identity",
        "API_SCOPE": setting("API_IDENTIFIER_URI"),
        "REQUESTER_CLIENT_ID": identities["REQUESTER"]["clientId"],
        "APPROVER_CLIENT_ID": identities["APPROVER"]["clientId"],
    })
    if users:
        env["LOCUST_USERS"] = str(users)
    if duration:
        env["LOCUST_RUN_TIME"] = str(duration)
    config["env"] = [{"name": name, "value": value} for name, value in env.items()]

    config["testPlan"] = os.path.relpath(TEMPLATE.parent / config["testPlan"], OUT).replace("\\", "/")
    config["referenceIdentities"] = [
        {"kind": "Engine", "type": "UserAssigned", "value": identities["REQUESTER"]["id"]},
        {"kind": "Engine", "type": "UserAssigned", "value": identities["APPROVER"]["id"]},
        {"kind": "Metrics", "type": "SystemAssigned"},
    ]
    postgres = setting("POSTGRES_HOST").split(".")[0]
    config["appComponents"] = [
        {
            "resourceId": resource_id(subscription, "Microsoft.App/containerApps", setting("API_APP_NAME")),
            "kind": "containerapp",
            "metrics": [
                {"name": "Requests", "namespace": "Microsoft.App/containerApps", "aggregation": "Total"},
                {"name": "ResponseTime", "namespace": "Microsoft.App/containerApps", "aggregation": "Average"},
                {"name": "CpuPercentage", "namespace": "Microsoft.App/containerApps", "aggregation": "Average"},
                {"name": "Replicas", "namespace": "Microsoft.App/containerApps", "aggregation": "Maximum"},
            ],
        },
        {
            "resourceId": resource_id(subscription, "Microsoft.Insights/components", setting("APPLICATIONINSIGHTS_NAME")),
            "kind": "web",
            "metrics": [
                {"name": "requests/duration", "namespace": "microsoft.insights/components", "aggregation": "Average"},
                {"name": "requests/count", "namespace": "microsoft.insights/components", "aggregation": "Count"},
                {"name": "requests/failed", "namespace": "microsoft.insights/components", "aggregation": "Count"},
            ],
        },
        {
            "resourceId": resource_id(subscription, "Microsoft.DBforPostgreSQL/flexibleServers", postgres),
            "metrics": [
                {"name": "cpu_percent", "namespace": "Microsoft.DBforPostgreSQL/flexibleServers", "aggregation": "Average"},
                {"name": "active_connections", "namespace": "Microsoft.DBforPostgreSQL/flexibleServers", "aggregation": "Maximum"},
            ],
        },
    ]
    OUT.mkdir(exist_ok=True)
    path = OUT / "loadtest.yaml"
    path.write_text("# Generated by load_test.py from loadtest/requesthub-journey.yaml. Do not commit.\n"
                    + yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


# ---------- run ----------

def run_test(args) -> str:
    """Create or update the test from the rendered configuration, start a run, and wait until it finishes."""
    path = render_config(args.users, args.duration)
    resource, group = setting("LOAD_TEST_NAME"), setting("AZURE_RESOURCE_GROUP")
    test_id = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["testId"]
    common = ["--load-test-resource", resource, "--resource-group", group, "--test-id", test_id]
    try:
        az("load", "test", "show", *common, "--query", "testId")
        verb = "update"
    except AzError:
        verb = "create"
    print(f"{'Updating' if verb == 'update' else 'Creating'} test '{test_id}' in the Load Testing resource of {group} "
          f"from {path.relative_to(HERE).as_posix()} ...")
    az("load", "test", verb, *common, "--load-test-config-file", str(path), parse=False)

    run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    description = args.description or "Started from a terminal with load_test.py"
    az("load", "test-run", "create", *common, "--test-run-id", run_id, "--display-name", run_id,
       "--description", description, "--no-wait", parse=False)
    print(f"Started test run {run_id}. Engines take a few minutes to start; the run itself lasts LOCUST_RUN_TIME seconds.")

    started, status, opened = time.monotonic(), "", not args.open
    while status not in TERMINAL:
        if time.monotonic() - started > 3600:
            raise AzError(f"test run {run_id} did not finish within an hour; check it in the Azure portal")
        time.sleep(15)
        run = az("load", "test-run", "show", "--load-test-resource", resource, "--resource-group", group,
                 "--test-run-id", run_id, "--query", "{status:status, portal:portalUrl}")
        if not opened and run.get("portal"):
            # Opened, not printed: the link contains the subscription id.
            webbrowser.open(run["portal"])
            print("Opened the run's dashboard in the Azure portal; it fills in once the engines start.")
            opened = True
        if run["status"] != status:
            status = run["status"]
            print(f"  {int(time.monotonic() - started):>4}s  {status}")
    return run_id


# ---------- report ----------

def fetch_run(run_id: str) -> dict:
    """The finished run, once its result and statistics are populated (the service adds them shortly after DONE)."""
    resource, group = setting("LOAD_TEST_NAME"), setting("AZURE_RESOURCE_GROUP")
    for _ in range(30):
        run = az("load", "test-run", "show", "--load-test-resource", resource, "--resource-group", group, "--test-run-id", run_id)
        if run.get("status") in TERMINAL and run.get("testResult") and run.get("testRunStatistics"):
            return run
        if run.get("status") in {"FAILED", "CANCELLED"}:
            return run
        time.sleep(10)
    return run


def server_side(start: str, end: str) -> list[dict]:
    """Application Insights requests in the run window: count, failures, p95, and how many carried the injected delay."""
    query = (
        "requests"
        f" | where timestamp between (datetime({start}) .. datetime({end}))"
        " | where name has '/api/'"
        f" | extend has_delay = isnotempty(tostring(customDimensions['{FAULT_TAG}']))"
        " | summarize requests = count(), server_errors = countif(toint(resultCode) >= 500),"
        " denied = countif(resultCode in ('401', '403')), p95_ms = round(percentile(duration, 95), 0),"
        " delayed = countif(has_delay), last_seen = max(timestamp) by name"
        " | order by requests desc"
    )
    ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
    # The query filters the exact window; --offset only has to reach back to the start of the run.
    hours = int((datetime.now(timezone.utc) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() // 3600) + 1
    for attempt in range(8):
        result = az("monitor", "app-insights", "query", "--app", setting("APPLICATIONINSIGHTS_NAME"),
                    "--resource-group", setting("AZURE_RESOURCE_GROUP"), "--analytics-query", query, "--offset", f"{hours}h")
        table = result["tables"][0]
        columns = [c["name"] for c in table["columns"]]
        rows = [dict(zip(columns, row)) for row in table["rows"]]
        latest = max((datetime.fromisoformat(r["last_seen"][:19] + "+00:00") for r in rows), default=None)
        # Telemetry arrives a minute or two after the requests; wait until it covers the end of the run.
        if latest and latest >= ended - timedelta(seconds=90):
            return rows
        if datetime.now(timezone.utc) - ended > timedelta(minutes=8):
            return rows
        if attempt == 0:
            print("Waiting for Application Insights to receive the server-side telemetry ...")
        time.sleep(20)
    return rows


def compute_shape() -> str:
    """What the load ran against, without host or resource names: compute, database tier, and region."""
    group = setting("AZURE_RESOURCE_GROUP")
    try:
        app = az("containerapp", "show", "--resource-group", group, "--name", setting("API_APP_NAME"), "--query",
                 "{cpu:properties.template.containers[0].resources.cpu, memory:properties.template.containers[0].resources.memory,"
                 " min:properties.template.scale.minReplicas, max:properties.template.scale.maxReplicas, region:location}")
        server = az("postgres", "flexible-server", "show", "--resource-group", group, "--name",
                    setting("POSTGRES_HOST").split(".")[0], "--query", "{sku:sku.name, tier:sku.tier}")
        return (f"RequestHub API on Azure Container Apps ({app['cpu']} vCPU, {app['memory']}, {app['min']} to {app['max']} "
                f"replicas) with PostgreSQL Flexible Server {server['tier']} {server['sku']}, in {app['region']}")
    except AzError:
        return "RequestHub API (compute details unavailable)"


def engine_region() -> str:
    """Display name of the Load Testing resource's region, where the test engines run."""
    try:
        location = az("load", "show", "--name", setting("LOAD_TEST_NAME"), "--resource-group", setting("AZURE_RESOURCE_GROUP"),
                      "--query", "location")
        names = az("account", "list-locations", "--query", f"[?name=='{location}'].displayName")
        return names[0] if names else location
    except AzError:
        return "the Load Testing resource's region"


def run_label(run: dict) -> str:
    """How the report names a run: its display name, or its id unless that is a GUID (runs started by the GitHub action)."""
    name = run.get("displayName") or run.get("testRunId") or "test run"
    return "a test run" if GUID.match(name) else name


def fmt_ms(value) -> str:
    return "n/a" if value is None else f"{float(value):,.0f}"


def verdict(result: str, delayed: int | None) -> str:
    if result == "PASSED":
        if delayed:
            return ("**Warning:** the rehearsal slowdown was active, yet no criterion caught it. "
                    "Tighten the thresholds before trusting this gate.")
        return "**Accepted:** the journey met every criterion. This is an acceptance run."
    if result == "FAILED":
        if delayed:
            return (f"**Expected failure:** the API ran with the rehearsal slowdown ({delayed:,} server requests carried "
                    f"`{FAULT_TAG}`), and the criteria caught it. This run proves the gate works; it is not an acceptance run.")
        if delayed == 0:
            return "**Regression:** the journey missed its criteria and no slowdown was injected. Investigate before releasing."
        return "**Failed:** the journey missed its criteria. Server-side telemetry was not available to tell why."
    if result.startswith("NOT RUN"):
        return "**Not run:** the engines could not run the test, so there is no result. Fix the cause below and run it again."
    return f"**Not completed:** the run ended with status {result}. Check the test run in the Azure portal."


def build_report(run: dict, server: list[dict]) -> tuple[str, dict]:
    env = run.get("environmentVariables") or {}
    # A run that never executed has no test result (NOT_APPLICABLE); its status (FAILED, CANCELLED) says what happened.
    result = run.get("testResult") if run.get("testResult") in ("PASSED", "FAILED") else run.get("status")
    stats = run.get("testRunStatistics") or {}
    if run.get("status") in ("FAILED", "CANCELLED") and not any(s.get("sampleCount") for s in stats.values()):
        result = f"NOT RUN ({run.get('status')})"
    delayed = sum(int(r["delayed"]) for r in server) if server else None
    start, end = run.get("startDateTime", ""), run.get("endDateTime", "")
    seconds = run.get("duration", 0) / 1000 if run.get("duration") else None

    lines = [
        f"## Load test: {run_label(run)}",
        "",
        f"**{result}** · test `{run.get('testId')}` · "
        f"{run.get('virtualUsers') or env.get('LOCUST_USERS')} virtual users · "
        f"{env.get('LOCUST_RUN_TIME', '?')} s of load{f' ({seconds:,.0f} s measured)' if seconds else ''}",
        "",
        verdict(result, delayed),
    ]
    for error in run.get("errorDetails") or []:
        lines += ["", f"> **{error.get('code', 'Error')}:** {' '.join(str(error.get('message', '')).split())}"]
    lines += [
        "",
        "### Pass/fail criteria",
        "",
        "| Criterion | Fails when | Actual | Result |",
        "|---|---|---|---|",
    ]
    criteria = (run.get("passFailCriteria") or {}).get("passFailMetrics", {}).values()
    for criterion in sorted(criteria, key=lambda c: (c.get("requestName") or "", c["clientMetric"])):
        target = criterion.get("requestName") or "all requests"
        metric = f"{criterion['aggregate']}({criterion['clientMetric']})"
        unit = "%" if criterion["clientMetric"] == "error" else " ms" if "time" in criterion["clientMetric"] or criterion["clientMetric"] == "latency" else ""
        limit = float(criterion["value"])
        limit_text = f"{limit:,.0f}" if limit.is_integer() else f"{limit:,}"
        actual = criterion.get("actualValue")
        if actual is not None and float(actual) < 0:
            actual = None  # the service reports -1 when it could not evaluate a criterion
        actual_text = "n/a" if actual is None else f"{float(actual):,.1f}{unit}" if unit == "%" else f"{float(actual):,.0f}{unit}"
        lines.append(f"| {target} {metric} | {criterion['condition']} {limit_text}{unit} | {actual_text} | {criterion.get('result', 'n/a')} |")

    lines += ["", "### Client side (Azure Load Testing)", "",
              "| Request | Requests | Errors | p50 ms | p95 ms | p99 ms | Requests/s |", "|---|---|---|---|---|---|---|"]
    for name, s in sorted(stats.items(), key=lambda item: (item[0] == "Total", item[0])):
        if not s.get("sampleCount"):
            continue
        lines.append(f"| {name} | {s.get('sampleCount', 0):,.0f} | {s.get('errorPct', 0):.1f}% | {fmt_ms(s.get('medianResTime'))} | "
                     f"{fmt_ms(s.get('pct2ResTime'))} | {fmt_ms(s.get('pct3ResTime'))} | {s.get('throughput', 0):.1f} |")

    lines += ["", "### Server side (Application Insights, same window)", ""]
    if server:
        lines += ["| Operation | Requests | Server errors | Denied (401/403) | p95 ms | With injected delay |", "|---|---|---|---|---|---|"]
        for r in server:
            lines.append(f"| {r['name']} | {int(r['requests']):,} | {int(r['server_errors']):,} | {int(r['denied']):,} | "
                         f"{fmt_ms(r['p95_ms'])} | {int(r['delayed']):,} |")
    elif result.startswith("NOT RUN"):
        lines.append("The test did not run, so there is no server-side telemetry.")
    else:
        lines.append("No server-side telemetry for this window yet. Run `python load_test.py report --run-id <test run id>` "
                     "again in a few minutes.")

    lines += [
        "",
        "### What was tested",
        "",
        f"- **Load:** {env.get('LOCUST_USERS')} virtual users (half requesters, half approvers), spawned at "
        f"{env.get('LOCUST_SPAWN_RATE')}/s, for {env.get('LOCUST_RUN_TIME')} s, one journey per user every "
        f"{env.get('PACING_SECONDS')} s; approvers decide {env.get('DECIDE_PERCENT')}% of new requests.",
        f"- **Dataset:** the 24 seeded requests plus {env.get('DATASET_REQUESTS', '0')} extra, after cleanup "
        f"`{env.get('CLEANUP')}` of earlier load-test requests; departments {env.get('DEPARTMENTS')}.",
        f"- **Target:** {compute_shape()}.",
        f"- **Engines:** {(run.get('loadTestConfiguration') or {}).get('engineInstances', 1)} Azure Load Testing engine(s) "
        f"in {engine_region()}; window {start} to {end}.",
        "",
        f"Dashboard: Azure portal › resource group `{setting('AZURE_RESOURCE_GROUP')}` › the Load Testing resource › Tests › "
        f"`{run.get('testId')}` › `{run_label(run)}` (client and server metrics side by side).",
    ]
    summary = {
        "testRunId": run.get("testRunId"), "label": run_label(run), "testId": run.get("testId"), "result": result,
        "status": run.get("status"), "startDateTime": start, "endDateTime": end, "virtualUsers": run.get("virtualUsers"),
        "delayedServerRequests": delayed,
    }
    return "\n".join(lines).rstrip() + "\n", summary


def gh(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def sync_issue(summary: dict, report: str) -> None:
    """One open Issue tracks a failing journey: opened on the first failure, updated on later ones, closed on a pass."""
    if not shutil.which("gh"):
        raise RuntimeError("--issue needs the GitHub CLI (gh)")
    repo = os.environ.get("GITHUB_REPOSITORY") or setting("GITHUB_REPOSITORY", "")
    scope = ["--repo", repo] if repo else []
    prefix = f"[load-test {summary['testId']}]"
    gh("label", "create", ISSUE_LABEL, *scope, "--color", "D93F0B", "--description", "RequestHub load test missed its criteria", "--force")
    issues = json.loads(gh("issue", "list", *scope, "--label", ISSUE_LABEL, "--state", "open", "--limit", "50", "--json", "number,title"))
    existing = next((i for i in issues if i["title"].startswith(prefix)), None)
    where = ""
    if os.environ.get("GITHUB_RUN_ID"):
        where = f" in [workflow run {os.environ['GITHUB_RUN_ID']}]({os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']})"
    if summary["result"] == "PASSED":
        if existing:
            gh("issue", "close", str(existing["number"]), *scope, "--comment",
               f"`{summary['label']}` passed every criterion{where}. Closing.\n\n{report}")
            print(f"Closed Issue #{existing['number']}: the journey passes again.")
        return
    if summary["result"] != "FAILED":
        return
    body = (f"`{summary['label']}` missed its performance criteria{where}.\n\n{report}\n"
            "Reproduce: `python solutions/04-test-microsoft/load_test.py run`. This Issue closes automatically when a run passes.\n")
    if existing:
        gh("issue", "comment", str(existing["number"]), *scope, "--body-file", "-", stdin=body)
        print(f"Updated Issue #{existing['number']}.")
    else:
        url = gh("issue", "create", *scope, "--title", f"{prefix} RequestHub journey missed its performance criteria",
                 "--label", ISSUE_LABEL, "--body-file", "-", stdin=body).strip()
        print(f"Opened {url}")


def report(run_id: str, issue: bool, open_portal: bool = False) -> int:
    run = fetch_run(run_id)
    server = []
    executed = any(s.get("sampleCount") for s in (run.get("testRunStatistics") or {}).values())
    if executed and run.get("startDateTime") and run.get("endDateTime"):
        print(f"Test result: {run.get('testResult')}. Reading Application Insights for the same window ...")
        try:
            server = server_side(run["startDateTime"], run["endDateTime"])
        except AzError as exc:
            print(f"warning: could not read Application Insights: {exc}", file=sys.stderr)
    markdown, summary = build_report(run, server)
    OUT.mkdir(exist_ok=True)
    (OUT / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(markdown, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(markdown)
    print()
    print(markdown)
    if open_portal and run.get("portalUrl"):
        webbrowser.open(run["portalUrl"])
        print("Opened the test run in the Azure portal.")
    print(f"Report: {(OUT / 'report.md').relative_to(HERE).as_posix()} · raw result: {(OUT / 'run.json').relative_to(HERE).as_posix()}")
    if issue:
        sync_issue(summary, markdown)
    return {"PASSED": 0, "FAILED": 1}.get(summary["result"], 2)


# ---------- cleanup ----------

def api_token() -> str:
    """Token for RequestHub as the signed-in Azure CLI identity (a person, or a service principal in a workflow)."""
    kind = az("account", "show", "--query", "user.type")
    scope = setting("API_IDENTIFIER_URI")
    args = ["--scope", f"{scope}/user_impersonation"] if kind == "user" else ["--resource", scope]
    return az("account", "get-access-token", *args, "--query", "accessToken")


def api_call(method: str, path: str, token: str) -> tuple[int, object]:
    request = urllib.request.Request(setting("API_URL").rstrip("/") + path, method=method, data=b"" if method == "POST" else None,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, raw


def cleanup() -> int:
    token = api_token()
    status, before = api_call("GET", "/api/requests?scope=all&pageSize=1", token)
    if status != 200:
        print(f"error: listing requests returned HTTP {status}: {before}. Cleanup needs the RequestHub Admin role.", file=sys.stderr)
        return 2
    status, body = api_call("POST", "/api/admin/load-test/cleanup", token)
    if status != 200:
        print(f"error: cleanup returned HTTP {status}: {body}", file=sys.stderr)
        return 2
    _, after = api_call("GET", "/api/requests?scope=all&pageSize=1", token)
    owners = len(body["owners"])
    who = "the load-test identity" if owners == 1 else f"the {owners} load-test identities"
    print(f"Deleted {body['deleted']} requests that {who} submitted.")
    print(f"Requests in RequestHub: {before['totalCount']} before, {after['totalCount']} after. Nothing else changed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__.split("\n", 2)[2],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="render the configuration, run the test in Azure Load Testing, and report")
    run_parser.add_argument("--users", type=int, help="override LOCUST_USERS (concurrent virtual users) for this run")
    run_parser.add_argument("--duration", type=int, help="override LOCUST_RUN_TIME (seconds of load) for this run")
    run_parser.add_argument("--description", help="description stored with the test run")
    run_parser.add_argument("--open", action="store_true", help="open the run's live dashboard in the Azure portal as soon as it starts")
    run_parser.add_argument("--issue", action="store_true", help="open, update, or close the GitHub Issue that tracks a failing journey")
    config_parser = sub.add_parser("config", help="write out/loadtest.yaml for this deployment")
    config_parser.add_argument("--users", type=int, help="override LOCUST_USERS in the written configuration")
    config_parser.add_argument("--duration", type=int, help="override LOCUST_RUN_TIME (seconds) in the written configuration")
    report_parser = sub.add_parser("report", help="report on an existing test run")
    report_parser.add_argument("--run-id", required=True, help="test run id, for example run-20260101-120000")
    report_parser.add_argument("--open", action="store_true", help="open the test run in the Azure portal")
    report_parser.add_argument("--issue", action="store_true", help="open, update, or close the GitHub Issue that tracks a failing journey")
    sub.add_parser("cleanup", help="as an Admin, delete every request the load-test identities submitted")
    args = parser.parse_args(argv)
    utf8_stdout()
    # Progress lines show up as they happen, also when output goes to a log (GitHub Actions).
    sys.stdout.reconfigure(line_buffering=True)

    try:
        if args.command == "config":
            path = render_config(args.users, args.duration)
            print(f"Wrote {path.relative_to(HERE)}")
            return 0
        if args.command == "cleanup":
            return cleanup()
        run_id = run_test(args) if args.command == "run" else args.run_id
        # `run --open` already opened the dashboard when the run started.
        return report(run_id, args.issue, open_portal=args.open and args.command == "report")
    except (AzError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
