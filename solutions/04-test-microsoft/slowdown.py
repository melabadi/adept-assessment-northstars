#!/usr/bin/env python3
"""Inject or remove a rehearsal slowdown on the deployed RequestHub API (Test phase, Microsoft track demo helper).

The API has an opt-in fault for this demo: while Faults__QueueDelayMs is set and Faults__ExpiresAtUtc is in the future,
the request list endpoint (GET /api/requests: the team queue and "my requests") waits that many milliseconds. Every
fault needs an expiry, so a forgotten slowdown switches itself off. This script changes those two settings on the API
container app, which creates a new revision, waits until that revision serves all traffic, and deactivates the older
revisions so only one copy of the API keeps running.

  python slowdown.py on                      # 1500 ms on the request list, expiring in 30 minutes
  python slowdown.py on --delay-ms 2500 --minutes 15
  python slowdown.py off                     # remove the settings (a new revision without the fault)
  python slowdown.py status                  # current revision, its fault settings, and a timed call to the list

After `on` or `off` the script times three calls to the request list as the signed-in Azure CLI identity, so you can
see the effect before you run the load test. The next `azd deploy` also removes the fault, because the deployment
template does not set it.

Settings come from environment variables, else from this solution's azd environment (after `azd up`):
  AZURE_RESOURCE_GROUP, API_APP_NAME, API_URL, API_IDENTIFIER_URI.
Needs the Azure CLI signed in with rights to update the container app (you after `azd up`; in GitHub Actions the
workflow's identity has Container Apps Contributor on the resource group).

Exit codes: 0 done, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import setting, utf8_stdout  # noqa: E402

DELAY = "Faults__QueueDelayMs"
EXPIRY = "Faults__ExpiresAtUtc"
READY_STATES = {"Running", "RunningAtMaxScale"}


class AzError(RuntimeError):
    pass


def az(*args: str):
    exe = shutil.which("az")
    if not exe:
        raise AzError("the Azure CLI (az) is required: https://learn.microsoft.com/cli/azure/install-azure-cli")
    # The Azure CLI is a Python program: ask it for UTF-8 so its output decodes the same way on Windows.
    proc = subprocess.run([exe, *args, "--only-show-errors", "--output", "json"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if proc.returncode != 0:
        raise AzError(f"az {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def app_args() -> list[str]:
    return ["--resource-group", setting("AZURE_RESOURCE_GROUP"), "--name", setting("API_APP_NAME")]


def current() -> dict:
    """The latest revision and the fault settings in the app's template."""
    app = az("containerapp", "show", *app_args(), "--query",
             "{revision:properties.latestRevisionName, env:properties.template.containers[0].env}")
    env = {item["name"]: item.get("value") for item in app["env"] or []}
    return {"revision": app["revision"], "delay": env.get(DELAY), "expiry": env.get(EXPIRY)}


def describe(state: dict) -> str:
    if not state["delay"]:
        return "no slowdown configured"
    expiry = datetime.fromisoformat(state["expiry"].replace("Z", "+00:00")) if state["expiry"] else None
    if expiry is None:
        return f"{state['delay']} ms configured without an expiry, so it is ignored"
    left = expiry - datetime.now(timezone.utc)
    if left.total_seconds() <= 0:
        return f"{state['delay']} ms, expired at {state['expiry']} (no longer active)"
    return f"{state['delay']} ms on the request list until {state['expiry']} ({int(left.total_seconds() // 60)} min left)"


def wait_for(revision: str) -> None:
    """Wait until the new revision runs, is healthy, and receives all traffic; then deactivate the others."""
    print(f"Waiting for revision {revision} to become ready and take all traffic ...")
    deadline = time.monotonic() + 600
    while True:
        state = az("containerapp", "revision", "show", *app_args(), "--revision", revision, "--query",
                   "{running:properties.runningState, health:properties.healthState, traffic:properties.trafficWeight}")
        if state["running"] in READY_STATES and state["health"] == "Healthy" and (state["traffic"] or 0) == 100:
            break
        if state["running"] == "Failed" or time.monotonic() > deadline:
            raise AzError(f"revision {revision} did not become ready: {state}")
        time.sleep(10)
    active = az("containerapp", "revision", "list", *app_args(), "--query", "[?properties.active].name") or []
    for old in active:
        if old != revision:
            az("containerapp", "revision", "deactivate", *app_args(), "--revision", old)
            print(f"Deactivated the previous revision {old}.")


def probe() -> None:
    """Time three calls to the request list as the signed-in Azure CLI identity."""
    try:
        kind = az("account", "show", "--query", "user.type")
        scope = setting("API_IDENTIFIER_URI")
        args = ["--scope", f"{scope}/user_impersonation"] if kind == "user" else ["--resource", scope]
        token = az("account", "get-access-token", *args, "--query", "accessToken")
        timings = []
        for _ in range(3):
            request = urllib.request.Request(setting("API_URL").rstrip("/") + "/api/requests?scope=mine&pageSize=1",
                                             headers={"Authorization": f"Bearer {token}"})
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
            timings.append((time.perf_counter() - started) * 1000)
        print(f"GET /api/requests now takes {statistics.median(timings):,.0f} ms (median of 3 calls).")
    except (AzError, urllib.error.URLError, OSError) as exc:
        print(f"warning: could not time the request list: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__.split("\n", 2)[2],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on", help="inject the slowdown (a new revision with the fault settings)")
    on.add_argument("--delay-ms", type=int, default=1500, help="added delay on the request list in milliseconds (default 1500)")
    on.add_argument("--minutes", type=int, default=30, help="minutes until the fault switches itself off (default 30, max 240)")
    sub.add_parser("off", help="remove the slowdown (a new revision without the fault settings)")
    sub.add_parser("status", help="show the current revision, its fault settings, and time the request list")
    args = parser.parse_args(argv)
    utf8_stdout()
    # Progress lines show up as they happen, also when output goes to a log (GitHub Actions).
    sys.stdout.reconfigure(line_buffering=True)

    try:
        state = current()
        if args.command == "status":
            print(f"Revision {state['revision']}: {describe(state)}.")
            probe()
            return 0
        if args.command == "on":
            if not 0 < args.delay_ms <= 30000 or not 0 < args.minutes <= 240:
                parser.error("--delay-ms must be 1 to 30000 and --minutes 1 to 240")
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=args.minutes)).replace(microsecond=0)
            print(f"Injecting {args.delay_ms} ms on the request list, expiring at {expiry.isoformat()} ...")
            app = az("containerapp", "update", *app_args(), "--container-name", "api", "--set-env-vars",
                     f"{DELAY}={args.delay_ms}", f"{EXPIRY}={expiry.isoformat().replace('+00:00', 'Z')}",
                     "--query", "properties.latestRevisionName")
        else:
            if not state["delay"] and not state["expiry"]:
                print(f"Revision {state['revision']}: no slowdown configured. Nothing to remove.")
                return 0
            print("Removing the slowdown ...")
            app = az("containerapp", "update", *app_args(), "--container-name", "api", "--remove-env-vars", DELAY, EXPIRY,
                     "--query", "properties.latestRevisionName")
        wait_for(app)
        print(f"Revision {app}: {describe(current())}.")
        probe()
        return 0
    except AzError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
