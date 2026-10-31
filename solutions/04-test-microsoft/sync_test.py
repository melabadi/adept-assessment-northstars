#!/usr/bin/env python3
"""Copy the committed RequestHub load test into Azure Load Testing (Test phase, Microsoft track).

The journey lives in this repository, where people change it through pull requests: loadtest/locustfile.py (requester
and approver virtual users) and loadtest/requesthub-journey.yaml (workload settings and pass/fail criteria). Azure does
the rest. Azure Load Testing holds the test, runs it on demand or on a schedule, and judges each run with the criteria.
A notification rule sends every finished run to an Azure Function that reports it to GitHub (function/, deployed by
infra/reporting.bicep).

This script is the bridge, and `azd provision` runs it (azure.yaml hooks):

  python sync_test.py setup    check the scenario, then create or update the test, its notification rule, and its
                               weekday schedule in Azure Load Testing (postprovision hook). After you merge a change
                               to loadtest/, run `azd provision` (or this command) to apply it.
  python sync_test.py check    only check the scenario against the guardrails below
  python sync_test.py config   only write out/loadtest.yaml: the committed configuration plus this deployment's values
  python sync_test.py prepare  record the GitHub repository for the reporting function's Issues in the azd
                               environment, from this clone's origin remote (preprovision hook)
  python sync_test.py report <test-run-id>
                               send a finished run to the reporting function again, as the notification rule does,
                               and print its answer. It accepts only this test's runs that ended in the last 60 minutes.

What `config` adds to requesthub-journey.yaml
  - LOCUST_HOST (the API URL), API_SCOPE (RequestHub's application ID URI), and the client ids of the two identities;
  - the two identities as engine identities, so the test signs in without any secret;
  - the API container app, Application Insights, and PostgreSQL as app components, for server-side metrics.

Guardrails (`check`, and the first step of `setup`): Azure Load Testing runs whatever the scenario says against a real
environment, so a change that breaks one of these never reaches Azure:
  1. Locust test type, an existing test plan, one or two engines.
  2. Every pass/fail criterion parses and names a request the journey makes (name="..." in the locustfile).
  3. The gate stays meaningful: an error-rate criterion of at most 5 %, and p95 criteria of at most 2000 ms on the team
     queue (the endpoint the slowdown rehearsal targets), submit, and decide.
  4. Rehearsal scale for a demo environment: at most 50 users, 600 seconds, and pacing of at least 1 second.
  5. Every setting the configuration passes is read by the locustfile.
  6. The locustfile runs on the engines (Python 3.9): no `X | Y` annotations, no `from __future__` import (the service
     adds lines before the script), and only the standard library, locust, and gevent.
  7. No credentials or ids are committed; this script adds the deployment's values when it renders the configuration.

The schedule
  `setup` creates one schedule, weekdays at 22:00 UTC, and pauses it. Enable it with
  `az load trigger schedule enable --load-test-resource <name> -g <group> --trigger-id weekday-evenings` once the
  environment stays up: a run against a stopped database fails, and Azure Load Testing disables a schedule after three
  consecutive failures. `setup` never changes an existing schedule, so one you enabled stays enabled.

Settings come from environment variables, else from this solution's azd environment (after `azd up`):
  AZURE_RESOURCE_GROUP, LOAD_TEST_NAME, LOAD_TEST_REQUESTER_IDENTITY, LOAD_TEST_APPROVER_IDENTITY, API_URL,
  API_IDENTIFIER_URI, API_APP_NAME, APPLICATIONINSIGHTS_NAME, POSTGRES_HOST, ACTION_GROUP_ID, and (for `report`)
  FUNCTION_APP_NAME.

Needs the Azure CLI with the `load` extension, signed in with Load Test Contributor on the Load Testing resource
(`azd up` grants it to you).

Exit codes: 0 success, 1 a guardrail check failed, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import azd_values, setting, utf8_stdout  # noqa: E402

TEMPLATE = HERE / "loadtest" / "requesthub-journey.yaml"
OUT = HERE / "out"
RULE_ID = "runs-to-github"
SCHEDULE_ID = "weekday-evenings"
CRITERION = re.compile(r"^(?P<aggregate>[a-z0-9]+)\((?P<metric>[a-z_]+)\)\s*(?P<condition>[<>])\s*(?P<value>\d+(\.\d+)?)$")
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SECRET = re.compile(r"(Bearer\s+ey[A-Za-z0-9_-]{10,}|client_secret|AccountKey=|SharedAccessSignature|sig=[A-Za-z0-9%]{20,})")
LOCUST_SETTINGS = {"LOCUST_HOST", "LOCUST_USERS", "LOCUST_SPAWN_RATE", "LOCUST_RUN_TIME"}
ALLOWED_IMPORTS = {"locust", "gevent"}
LIMITS = {"users": 50, "run_time": 600, "engines": 2, "error_pct": 5, "p95_ms": 2000}
REQUIRED_P95 = {"team-queue", "submit", "decide"}


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


def exists(*args: str) -> bool:
    """Whether an `az ... show` command finds the object."""
    try:
        az(*args)
        return True
    except AzError:
        return False


# ---------- check ----------

def check_scenario(config_path: Path = TEMPLATE) -> list[str]:
    """Problems that keep the scenario out of Azure; empty when every guardrail holds."""
    problems: list[str] = []
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("testType") != "Locust":
        problems.append(f"testType is {config.get('testType')!r}; this scenario is a Locust test")
    plan = config_path.parent / str(config.get("testPlan", ""))
    if not plan.is_file():
        return problems + [f"testPlan {config.get('testPlan')!r} does not exist next to {config_path.name}"]
    engines = config.get("engineInstances")
    if not isinstance(engines, int) or not 1 <= engines <= LIMITS["engines"]:
        problems.append(f"engineInstances must be 1 to {LIMITS['engines']} for a demo environment, got {engines!r}")

    source = plan.read_text(encoding="utf-8")
    names = set(re.findall(r'name="([^"]+)"', source))
    env = {str(item["name"]): str(item["value"]) for item in config.get("env", [])}

    # 2 and 3: criteria
    criteria = (config.get("failureCriteria") or {}).get("clientMetrics") or []
    error_ok, p95_targets = False, set()
    for item in criteria:
        request, text = (next(iter(item.items())) if isinstance(item, dict) else (None, item))
        match = CRITERION.match(str(text).strip())
        label = f"{request + ': ' if request else ''}{text}"
        if not match:
            problems.append(f"criterion '{label}' does not parse as aggregate(metric) > or < value")
            continue
        if request and request not in names:
            problems.append(f"criterion '{label}' names request '{request}', which the locustfile never makes "
                            f"(names: {', '.join(sorted(names))})")
        value = float(match["value"])
        if match["metric"] == "error" and match["aggregate"] == "percentage" and match["condition"] == ">":
            error_ok = error_ok or value <= LIMITS["error_pct"]
        if match["metric"] == "response_time_ms" and match["aggregate"] == "p95" and match["condition"] == ">" and request:
            if value <= LIMITS["p95_ms"]:
                p95_targets.add(request)
            else:
                problems.append(f"criterion '{label}' allows a p95 above {LIMITS['p95_ms']} ms; the gate would miss the slowdown")
    if not error_ok:
        problems.append(f"add an error-rate criterion of at most {LIMITS['error_pct']} %, for example 'percentage(error) > 1'")
    for request in sorted(REQUIRED_P95 - p95_targets):
        problems.append(f"add a p95 criterion of at most {LIMITS['p95_ms']} ms for '{request}'")

    # 4: workload guardrails
    try:
        if int(env.get("LOCUST_USERS", "0")) > LIMITS["users"]:
            problems.append(f"LOCUST_USERS {env['LOCUST_USERS']} exceeds {LIMITS['users']}, the rehearsal limit for a demo environment")
        if int(env.get("LOCUST_RUN_TIME", "0")) > LIMITS["run_time"]:
            problems.append(f"LOCUST_RUN_TIME {env['LOCUST_RUN_TIME']} s exceeds {LIMITS['run_time']} s")
        if float(env.get("PACING_SECONDS", "1")) < 1:
            problems.append("PACING_SECONDS below 1 turns the journey into a stress test; keep realistic pacing")
    except ValueError as exc:
        problems.append(f"workload settings must be numbers: {exc}")
    if env.get("CLEANUP", "before") not in {"before", "after", "both", "none"}:
        problems.append(f"CLEANUP must be before, after, both, or none, got {env.get('CLEANUP')!r}")

    # 5: every setting is read
    read = set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', source))
    for name in sorted(set(env) - read - LOCUST_SETTINGS):
        problems.append(f"setting {name} is passed to the test but the locustfile never reads it")

    # 6: engine compatibility
    try:
        tree = ast.parse(source, feature_version=(3, 9))
    except SyntaxError as exc:
        problems.append(f"{plan.name} is not valid Python 3.9 (line {exc.lineno}): {exc.msg}")
        tree = None
    if tree is not None:
        stdlib = set(sys.stdlib_module_names)
        annotations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotations += [a.annotation for a in node.args.args + node.args.kwonlyargs if a.annotation] + [node.returns]
            elif isinstance(node, ast.AnnAssign):
                annotations.append(node.annotation)
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                problems.append(f"{plan.name} line {node.lineno}: remove `from __future__ import ...`; Azure Load Testing adds "
                                "lines before the script, so the import would no longer come first")
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for module in modules:
                top = module.split(".")[0]
                if top and top not in stdlib and top not in ALLOWED_IMPORTS and top != "__future__":
                    problems.append(f"{plan.name} imports '{module}', which the engines do not install")
        for annotation in filter(None, annotations):
            if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation)):
                problems.append(f"{plan.name} line {annotation.lineno}: `X | Y` annotations fail on Python 3.9; use typing.Optional or Union")

    # 7: nothing secret or environment-specific
    for path in (config_path, plan):
        text = path.read_text(encoding="utf-8")
        if SECRET.search(text):
            problems.append(f"{path.name} contains what looks like a credential; sign in with managed identities instead")
        if GUID.search(text):
            problems.append(f"{path.name} contains an id; sync_test.py adds deployment values when it renders the configuration")
    return problems


def check() -> int:
    problems = check_scenario()
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"{len(problems)} problem(s) in loadtest/{TEMPLATE.name}; nothing was sent to Azure.")
        return 1
    print(f"PASS loadtest/{TEMPLATE.name}: criteria name real requests, thresholds and workload within guardrails, "
          "every setting read, Python 3.9 compatible, no secrets")
    return 0


# ---------- config ----------

def resource_id(subscription: str, provider: str, name: str) -> str:
    return f"/subscriptions/{subscription}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}/providers/{provider}/{name}"


def render_config() -> Path:
    """Write out/loadtest.yaml: the committed configuration plus this deployment's values."""
    config = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    subscription = az("account", "show", "--query", "id")
    group = setting("AZURE_RESOURCE_GROUP")
    identities = {}
    for role in ("REQUESTER", "APPROVER"):
        name = setting(f"LOAD_TEST_{role}_IDENTITY")
        identities[role] = az("identity", "show", "--resource-group", group, "--name", name, "--query", "{id:id, clientId:clientId}")

    env = {item["name"]: str(item["value"]) for item in config.get("env", [])}
    env.update({
        "LOCUST_HOST": setting("API_URL"),
        "RH_AUTH": "managed-identity",
        "API_SCOPE": setting("API_IDENTIFIER_URI"),
        "REQUESTER_CLIENT_ID": identities["REQUESTER"]["clientId"],
        "APPROVER_CLIENT_ID": identities["APPROVER"]["clientId"],
    })
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
    path.write_text("# Generated by sync_test.py from loadtest/requesthub-journey.yaml. Do not commit.\n"
                    + yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


# ---------- setup ----------

def setup() -> int:
    if check() != 0:
        return 1
    path = render_config()
    test_id = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["testId"]
    common = ["--load-test-resource", setting("LOAD_TEST_NAME"), "--resource-group", setting("AZURE_RESOURCE_GROUP")]

    verb = "update" if exists("load", "test", "show", *common, "--test-id", test_id, "--query", "testId") else "create"
    az("load", "test", verb, *common, "--test-id", test_id, "--load-test-config-file", str(path), parse=False)
    print(f"Test '{test_id}': {verb}d from loadtest/ (rendered to {path.relative_to(HERE).as_posix()}).")

    # Every finished run (passed, failed, or stopped) goes to the action group, which calls the reporting function.
    event = ["event-id=run-ended", "type=TestRunEnded", "status=DONE,FAILED,CANCELLED", "result=PASSED,FAILED,NOT_APPLICABLE"]
    rule = ["--notification-rule-id", RULE_ID, "--display-name", "Report finished runs to GitHub",
            "--action-groups", setting("ACTION_GROUP_ID"), "--test-ids", test_id]
    if exists("load", "notification-rule", "show", *common, "--notification-rule-id", RULE_ID):
        verb = "update"
        az("load", "notification-rule", "update", *common, *rule, "--add-event", *event, parse=False)
    else:
        verb = "create"
        az("load", "notification-rule", "create", *common, *rule, "--event", *event, parse=False)
    print(f"Notification rule '{RULE_ID}': {verb}d; every finished run goes to the reporting function, which reports "
          "it to GitHub.")

    if exists("load", "trigger", "schedule", "show", *common, "--trigger-id", SCHEDULE_ID):
        state = az("load", "trigger", "schedule", "show", *common, "--trigger-id", SCHEDULE_ID, "--query", "state")
        print(f"Schedule '{SCHEDULE_ID}': unchanged ({str(state).lower()}).")
    else:
        start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
        az("load", "trigger", "schedule", "create", *common, "--trigger-id", SCHEDULE_ID,
           "--display-name", "Weekday evenings", "--description", "The journey, every weekday at 22:00 UTC.",
           "--test-ids", test_id, "--recurrence-type", "Weekly", "--recurrence-interval", "1",
           "--recurrence-week-days", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
           "--start-date-time", start.strftime("%Y-%m-%dT%H:%M:%SZ"), parse=False)
        az("load", "trigger", "schedule", "pause", *common, "--trigger-id", SCHEDULE_ID, parse=False)
        print(f"Schedule '{SCHEDULE_ID}': created for weekdays at 22:00 UTC, and paused. Enable it when the environment "
              "stays up (see `python sync_test.py --help`).")
    return 0


# ---------- prepare ----------

def prepare() -> int:
    """Record owner/name of this clone's GitHub origin as GITHUB_REPOSITORY, unless it is already set."""
    if os.environ.get("GITHUB_REPOSITORY") or azd_values().get("GITHUB_REPOSITORY"):
        return 0
    proc = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=HERE)
    match = re.search(r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$", proc.stdout.strip())
    if not match:
        print("warning: no GitHub origin remote found; set GITHUB_REPOSITORY (owner/name) with `azd env set` so the "
              "reporting function can open Issues.", file=sys.stderr)
        return 0
    subprocess.run(["azd", "env", "set", "GITHUB_REPOSITORY", match["repo"]], cwd=HERE, check=True)
    print(f"GITHUB_REPOSITORY: {match['repo']} (from the origin remote); the reporting function opens its Issues there.")
    return 0


# ---------- report ----------

def report(test_run_id: str) -> int:
    """Send one finished run to the reporting function, as the notification rule does, and print its answer."""
    import urllib.error
    import urllib.request

    app = ["--resource-group", setting("AZURE_RESOURCE_GROUP"), "--name", setting("FUNCTION_APP_NAME")]
    host = az("functionapp", "show", *app, "--query", "properties.defaultHostName || defaultHostName")
    keys = az("functionapp", "keys", "list", *app).get("functionKeys") or {}
    key = keys.get("actiongroup") or keys.get("default")  # never printed
    if not key:
        raise AzError("the function app has no function key yet; deploy it with `azd deploy reporter`")
    body = json.dumps({"data": {"alertContext": {"testRunId": test_run_id}}}).encode("utf-8")
    request = urllib.request.Request(f"https://{host}/api/test-run-ended", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "x-functions-key": key})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status, text = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    try:
        message = json.loads(text).get("message", text)
    except (json.JSONDecodeError, AttributeError):
        message = text
    print(f"{status}: {str(message).strip()}")
    return 0 if status == 202 else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__.split("\n", 2)[2],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="check the scenario, then create or update the test, notification rule, and schedule")
    sub.add_parser("check", help="only check the scenario against the guardrails")
    sub.add_parser("config", help="only write out/loadtest.yaml for this deployment")
    sub.add_parser("prepare", help="record the GitHub repository for the reporting function's Issues (preprovision hook)")
    resend = sub.add_parser("report", help="send a finished run to the reporting function again")
    resend.add_argument("test_run_id", help="the run's id, for example from `az load test-run list`")
    args = parser.parse_args(argv)
    utf8_stdout()
    try:
        if args.command == "check":
            return check()
        if args.command == "config":
            print(f"Wrote {render_config().relative_to(HERE).as_posix()}")
            return 0
        if args.command == "prepare":
            return prepare()
        if args.command == "report":
            return report(args.test_run_id)
        return setup()
    except AzError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
