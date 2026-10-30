"""Preflight for releases on Azure Container Apps: is everything the release needs in place and in its starting state?

Run it after `azd up` and before each demo. Each check prints PASS, WARN, or FAIL with what to do. The exit code is 1
when any check fails. It changes nothing.

  Azure CLI   you are signed in
  App         multiple-revision mode (a candidate runs beside the stable revision), external ingress
  Traffic     exactly one revision serves 100%, and whether a candidate is waiting for a person's go or no-go
  Probes      the revision users get has startup, liveness, and readiness probes (the gate trusts readiness)
  Database    the PostgreSQL server is Ready: a tenant policy can stop it on a schedule, and then every revision fails
              readiness, so a gate would fail for the wrong reason
  Production  the production URL's readiness endpoint answers 200
  Jobs        the five release jobs exist, run as the release identity, and none is running now, by the same rule the
              release's own lock uses (release.py, still_running)
  Identity    the release identity holds what a release needs and no more: Container Apps Contributor and Container
              Apps Jobs Reader on the resource group, and AcrPull on the registry
  Trigger     the Logic App is enabled and may start the release job, and Event Grid delivers pushed builds to it
  Build       the ACR task that builds main exists, and whether its commit trigger is on
  Workbook    the release-records workbook exists

Settings come from the options, then environment variables, then this solution's azd environment:

  python preflight.py
  python preflight.py --resource-group rg-ai-sdlc-release
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

import release
from azd_env import SOLUTION, azd_values, utf8_stdout

STEPS = ["release", "promote", "abort", "rollback", "drill"]
RELEASE_ROLES = {"Container Apps Contributor": "resourcegroups/{rg}", "Container Apps Jobs Reader": "resourcegroups/{rg}",
                 "AcrPull": "/registries/"}
BROAD_ROLES = {"Owner", "Contributor", "User Access Administrator", "Role Based Access Control Administrator", "AcrPush"}
JOBS_OPERATOR = "Container Apps Jobs Operator"
counts = {"PASS": 0, "WARN": 0, "FAIL": 0}


def run(tool: str, *args: str) -> tuple[int, str]:
    exe = shutil.which(tool)
    if not exe:
        return 127, f"{tool} is not installed"
    proc = subprocess.run([exe, *args], capture_output=True, text=True, cwd=SOLUTION)
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr or proc.stdout).strip()


def az(*args: str):
    code, out = run("az", *args, "--only-show-errors", "--output", "json")
    if code:
        raise RuntimeError(out.splitlines()[-1] if out else f"az {' '.join(args[:3])} failed")
    return json.loads(out or "null")


def report(level: str, area: str, message: str, fix: str = "") -> None:
    counts[level] += 1
    print(f"{level:<4}  {area:<10} {message}")
    if fix and level != "PASS":
        print(f"{'':16}→ {fix}")


def check_app(s: dict) -> dict | None:
    try:
        app = az("containerapp", "show", "--name", s["app"], "--resource-group", s["rg"])
    except RuntimeError as error:
        report("FAIL", "App", f"{s['app']} not found in {s['rg']}: {error}", "Run `azd up` in this folder.")
        return None
    config = app["properties"]["configuration"]
    mode = config.get("activeRevisionsMode")
    report("PASS" if mode == "Multiple" else "FAIL", "App", f"{s['app']}: activeRevisionsMode {mode}",
           "Set activeRevisionsMode to Multiple (app/infra/api.bicep does) so a candidate can run beside stable.")
    ingress = config.get("ingress") or {}
    report("PASS" if ingress.get("external") else "FAIL", "App", f"ingress {'external' if ingress.get('external') else 'internal or off'}",
           "The release reaches the candidate through its label URL, which needs ingress.")
    return app


def check_traffic_and_probes(s: dict, app: dict) -> None:
    revisions = {r["name"]: r for r in az("containerapp", "revision", "list", "--name", s["app"],
                                          "--resource-group", s["rg"], "--all")}
    latest_ready = app["properties"].get("latestReadyRevisionName")
    weights: dict[str, int] = {}
    labels: dict[str, str] = {}
    for entry in app["properties"]["configuration"]["ingress"].get("traffic") or []:
        name = entry.get("revisionName") or (latest_ready if entry.get("latestRevision") else None)
        weights[name] = weights.get(name, 0) + int(entry.get("weight") or 0)
        if entry.get("label"):
            labels[entry["label"]] = name
    short = lambda name: (name or "-").split("--", 1)[-1]  # noqa: E731
    serving = [name for name, weight in weights.items() if weight > 0]
    if len(serving) != 1:
        report("FAIL", "Traffic", "traffic is split: " + ", ".join(f"{short(n)} {weights[n]}%" for n in serving),
               "Finish the release: run the promote, abort, or rollback job.")
        return
    stable = serving[0]
    report("PASS", "Traffic", f"{short(stable)} serves 100%" + (" (label stable)" if labels.get("stable") == stable else
                                                              " (no stable label yet: the first release adds it)"))
    if labels.get("candidate") and labels["candidate"] != stable:
        report("WARN", "Traffic", f"candidate {short(labels['candidate'])} is waiting for a go or no-go",
               "Show it, or run the abort job for a clean start. The next release replaces it anyway.")
    containers = revisions.get(stable, {}).get("properties", {}).get("template", {}).get("containers") or []
    probes = {p.get("type"): p for c in containers for p in (c.get("probes") or [])}
    missing = [kind for kind in ("Startup", "Liveness", "Readiness") if kind not in probes]
    readiness = probes.get("Readiness", {}).get("httpGet", {}).get("path")
    report("FAIL" if "Readiness" in missing else "WARN" if missing else "PASS", "Probes",
           f"readiness {readiness or 'missing'}" + (f"; missing {', '.join(missing)}" if missing else "; startup and liveness present"),
           "The gate trusts the readiness probe: give the container an HTTP readiness probe that checks its dependencies.")


def check_database(s: dict) -> None:
    servers = az("postgres", "flexible-server", "list", "--resource-group", s["rg"])
    if not servers:
        report("WARN", "Database", f"no PostgreSQL flexible server in {s['rg']}", "Check that `azd up` finished.")
        return
    for server in servers:
        state = server.get("state")
        if state == "Ready":
            report("PASS", "Database", f"{server['name']} is Ready")
        elif state in ("Starting", "Updating"):
            report("WARN", "Database", f"{server['name']} is {state}", "Wait until it is Ready (a few minutes), then run the preflight again.")
        else:
            report("FAIL", "Database", f"{server['name']} is {state}",
                   f"Start it: az postgres flexible-server start -g {s['rg']} -n {server['name']} (3 to 5 minutes). A tenant "
                   "policy can stop servers on a schedule; a stopped database makes every revision fail readiness.")


def check_production(app: dict) -> None:
    fqdn = app["properties"]["configuration"]["ingress"].get("fqdn")
    try:
        with urllib.request.urlopen(f"https://{fqdn}/health/ready", timeout=20) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        status = f"no answer ({getattr(error, 'reason', error)})"
    report("PASS" if status == 200 else "FAIL", "Production", f"/health/ready answers {status}",
           "The revision users get is not ready. Check the Database line first; then ask Azure Copilot on the container app.")


def check_jobs(s: dict) -> dict:
    jobs = {(j.get("tags") or {}).get("requesthub-release"): j for j in az("containerapp", "job", "list", "--resource-group", s["rg"])}
    found = [step for step in STEPS if step in jobs]
    missing = [step for step in STEPS if step not in jobs]
    report("FAIL" if missing else "PASS", "Jobs", f"release jobs: {', '.join(found) or 'none'}" + (f"; missing {', '.join(missing)}" if missing else ""),
           "Run `azd deploy release` in this folder.")
    identities = {next(iter((j.get("identity") or {}).get("userAssignedIdentities") or {}), "").lower() for j in jobs.values() if j}
    if found:
        expected = (s["identity"] or "").lower()
        report("PASS" if identities == {expected} else "FAIL", "Jobs",
               "all run as the release identity" if identities == {expected} else "they do not all run as the release identity",
               "Run `azd deploy release` in this folder.")
        running = []
        now = release.utc_now()
        for step in found:
            executions = az("containerapp", "job", "execution", "list", "--name", jobs[step]["name"], "--resource-group", s["rg"]) or []
            time_limit = ((jobs[step].get("properties") or {}).get("configuration") or {}).get("replicaTimeout")
            running += [f"{step} ({str((e.get('properties') or {}).get('status') or 'unknown').lower()})"
                        for e in executions if release.still_running(e.get("properties") or {}, time_limit, now)]
        report("WARN" if running else "PASS", "Jobs", f"running now: {', '.join(running)}" if running else "none running now",
               "Wait for it to finish before you start the demo: release steps run one at a time.")
    return jobs


def check_identity(s: dict) -> None:
    if not s["identity"]:
        report("FAIL", "Identity", "AUTOMATION_IDENTITY_ID is not set", "Run `azd provision` in this folder.")
        return
    identity = az("identity", "show", "--ids", s["identity"])
    assignments = az("role", "assignment", "list", "--all", "--assignee", identity["principalId"])
    held = [(a.get("roleDefinitionName"), a.get("scope", "").lower()) for a in assignments]
    for role, scope_hint in RELEASE_ROLES.items():
        hint = scope_hint.format(rg=s["rg"].lower()).lower()
        scopes = [scope for name, scope in held if name == role and hint in scope]
        report("PASS" if scopes else "FAIL", "Identity", f"{role} " + ("on " + scopes[0].split("/")[-1] if scopes else "missing"),
               "Run `azd provision` in this folder.")
    broad = [f"{name} on {scope.split('/')[-1]}" for name, scope in held if name in BROAD_ROLES]
    if broad:
        report("WARN", "Identity", f"more than a release needs: {', '.join(broad)}", "Remove those role assignments.")
    credentials = az("identity", "federated-credential", "list", "--identity-name", identity["name"], "--resource-group", s["rg"]) or []
    if credentials:
        report("WARN", "Identity", f"{len(credentials)} federated credential(s) left from an earlier GitHub Actions setup",
               f"Nothing outside Azure needs them: az identity federated-credential delete -g {s['rg']} --identity-name "
               f"{identity['name']} -n <name>")


def check_trigger(s: dict, jobs: dict) -> None:
    try:
        trigger = az("resource", "show", "--resource-group", s["rg"], "--resource-type", "Microsoft.Logic/workflows", "--name", s["trigger"])
    except RuntimeError as error:
        report("FAIL", "Trigger", f"Logic App {s['trigger']} not found: {error}", "Run `azd provision` in this folder.")
        return
    state = trigger["properties"].get("state")
    report("PASS" if state == "Enabled" else "FAIL", "Trigger", f"Logic App {state.lower()}",
           f"Enable it: az resource update --ids {trigger['id']} --set properties.state=Enabled")
    release = jobs.get("release")
    if release:
        principal = (trigger.get("identity") or {}).get("principalId")
        roles = az("role", "assignment", "list", "--assignee", principal, "--scope", release["id"]) if principal else []
        ok = any(r.get("roleDefinitionName") == JOBS_OPERATOR for r in roles)
        report("PASS" if ok else "FAIL", "Trigger", f"may start the release job ({JOBS_OPERATOR})" if ok else "may not start the release job",
               "Run `azd deploy release` in this folder.")
    topics = az("eventgrid", "system-topic", "list", "--resource-group", s["rg"]) or []
    topic = next((t for t in topics if t.get("topicType") == "Microsoft.ContainerRegistry.Registries"), None)
    if not topic:
        report("FAIL", "Trigger", "no Event Grid topic on the registry", "Run `azd provision` in this folder.")
        return
    subscription = az("eventgrid", "system-topic", "event-subscription", "show", "--resource-group", s["rg"],
                      "--system-topic-name", topic["name"], "--name", "release-on-push")
    state = subscription.get("provisioningState")
    report("PASS" if state == "Succeeded" else "FAIL", "Trigger", f"Event Grid delivers pushes of requesthub-api to it ({state})",
           "Run `azd provision` in this folder.")


def check_build(s: dict) -> None:
    code, out = run("az", "acr", "task", "show", "--registry", s["registry"], "--name", "build-api", "--only-show-errors", "--output", "json")
    if code:
        report("WARN", "Build", "the build task build-api is not set up",
               "See the README, Set up: a person creates it with a token for this repository. Until then, build from a "
               "clone with az acr build; the release starts the same way.")
        return
    task = json.loads(out)
    triggers = (task.get("trigger") or {}).get("sourceTriggers") or []
    enabled = any(t.get("status") == "Enabled" and "commit" in (t.get("sourceTriggerEvents") or []) for t in triggers)
    report("PASS" if enabled else "WARN", "Build",
           "build-api builds every commit to main" if enabled else "build-api exists; its commit trigger is off",
           f"Pushes to main do not start builds. Start one for a commit of main with: az acr task run --registry "
           f"{s['registry']} --name build-api --context <repository URL>.git#<commit> --set commit=<commit> (README, "
           f"Run the demo, step 2) — or turn the trigger on: az acr task update --registry "
           f"{s['registry']} --name build-api --commit-trigger-enabled true")


def check_workbook(s: dict) -> None:
    books = az("resource", "list", "--resource-group", s["rg"], "--resource-type", "Microsoft.Insights/workbooks") or []
    report("PASS" if books else "FAIL", "Workbook", "RequestHub release records" if books else "release-records workbook missing",
           "Run `azd provision` in this folder.")


def main() -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resource-group", help="resource group of the app (default: AZURE_RESOURCE_GROUP)")
    args = parser.parse_args()
    values = azd_values()
    pick = lambda name: os.environ.get(name) or values.get(name, "")  # noqa: E731
    s = {"rg": args.resource_group or pick("AZURE_RESOURCE_GROUP"), "app": pick("API_APP_NAME"),
         "registry": pick("AZURE_CONTAINER_REGISTRY_NAME"), "identity": pick("AUTOMATION_IDENTITY_ID"),
         "trigger": pick("RELEASE_TRIGGER_NAME")}
    if not s["rg"] or not s["app"]:
        raise SystemExit("error: run `azd up` in this folder first, or pass --resource-group.")

    code, out = run("az", "account", "show", "--query", "user.name", "--output", "tsv")
    report("PASS" if code == 0 else "FAIL", "Azure CLI", f"signed in as {out}" if code == 0 else "not signed in", "Run `az login`.")
    if code:
        return 1
    app = check_app(s)
    if app:
        check_traffic_and_probes(s, app)
    check_database(s)
    if app:
        check_production(app)
    jobs = check_jobs(s)
    check_identity(s)
    check_trigger(s, jobs)
    check_build(s)
    check_workbook(s)
    print(f"\n{counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
