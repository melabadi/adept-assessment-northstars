#!/usr/bin/env python3
"""Start and follow the Plan · Microsoft run from your shell. The run happens in Azure, in the solution's Function app;
this script only calls the app's HTTP function, with the app's key.

  python runs.py start [--compare-with-pull-request N] [--no-follow]
      Starts a run, then prints what it does as it happens: the agent's draft, each evaluation attempt, and the review
      Issue it opens. It stops following when the run waits for a person, or ends. Ctrl+C stops following, not the run.
      --compare-with-pull-request N also scores the Copilot brief on 01-plan-github pull request N, in the same
      evaluation run. --no-follow prints the new run's id and returns at once.

  python runs.py status
      The runs in progress, the five newest runs, and whether GitHub accepts the Function app's token (the one in
      Key Vault), with its expiry date. The README's starting-state check runs this.

  python runs.py show RUN [--follow]
      Everything one run did so far. --follow keeps printing until the run ends: published, rejected, timed out,
      cancelled, or failed.

  python runs.py cancel (RUN ... | --all)
      Cancels unfinished runs; --all cancels every run in progress. A run that waits for a person gets a comment on
      its review Issue, which is closed as not planned. A run that is publishing can't be cancelled: wait until it ends.

Configuration (environment variables, or read from `azd env get-values`, run in this folder): AZURE_RESOURCE_GROUP,
FUNCTION_APP_NAME, and GITHUB_REPOSITORY, all set by `azd provision`. The script asks the Azure CLI, signed in as you,
for the Function app's host name and key. It never prints or saves either.

Exit codes: 0 done, 1 the run failed or wasn't found, 2 configuration or connection error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAITING = "awaiting_review"
FINISHED = ("published", "rejected", "timed_out", "cancelled", "failed")
POLL_SECONDS = 3


def azd_values() -> dict[str, str]:
    if not shutil.which("azd"):
        return {}
    name = os.environ.get("AZURE_ENV_NAME")
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json", *(["-e", name] if name else [])],
                          capture_output=True, text=True, cwd=HERE)
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else {}
    except json.JSONDecodeError:
        return {}


def setting(name: str, values: dict[str, str]) -> str:
    value = os.environ.get(name) or values.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set. Run `azd up` in solutions/01-plan-microsoft first, or set {name}.")
    return value


def az(*args: str) -> str:
    """Runs the Azure CLI and returns its output. It's asked twice before giving up: a token refresh or a network blip
    can fail one call. Its error output is never printed, because it can name the subscription or a resource."""
    exe = shutil.which("az")
    if not exe:
        raise SystemExit("error: the Azure CLI (az) is not installed.")
    for attempt in range(2):
        proc = subprocess.run([exe, *args], capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        if attempt == 0:
            time.sleep(3)
    raise SystemExit(f"error: `az {args[0]} {args[1]}` failed twice. Sign in with `az login`, check that the solution is "
                     f"deployed, and try again.")


class Api:
    """The Function app's runs endpoint. The host name and key stay in this object: nothing prints them."""

    def __init__(self):
        values = azd_values()
        group, app = setting("AZURE_RESOURCE_GROUP", values), setting("FUNCTION_APP_NAME", values)
        self.repository = setting("GITHUB_REPOSITORY", values)
        # Flex Consumption apps come back in the raw Resource Manager shape; others are flattened.
        self._host = az("functionapp", "show", "-g", group, "-n", app, "--query",
                        "properties.defaultHostName || defaultHostName", "-o", "tsv")
        self._key = az("functionapp", "keys", "list", "-g", group, "-n", app, "--query", "functionKeys.default", "-o", "tsv")

    def call(self, method: str, path: str = "", body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"https://{self._host}/api/runs{path}", data=data, method=method,
                                         headers={"x-functions-key": self._key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {"error": f"HTTP {error.code}"}
        except (urllib.error.URLError, OSError) as error:
            reason = str(getattr(error, "reason", error)).replace(self._host, "<function app>")
            raise SystemExit(f"error: couldn't reach the Function app ({reason}).") from None

    def issue_url(self, number: int) -> str:
        return f"https://github.com/{self.repository}/issues/{number}"


def clock(at: str) -> str:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")


def print_events(events: list[dict], skip: int = 0) -> int:
    for event in events[skip:]:
        print(f"{clock(event['at'])}  {event['step']:<9} {event['text']}", flush=True)
    return len(events)


def outcome(api: Api, run: dict) -> int:
    state = run["state"]
    review = (run.get("review") or {}).get("issue")
    if state == WAITING:
        print(f"\nThe review Issue waits for a person: {api.issue_url(review)}\n"
              f"Apply the brief-approved label to publish the backlog, or close the Issue to reject it.")
    elif state == "failed":
        error = run.get("error") or {}
        print(f"\nThe run failed: {error.get('code')}: {error.get('message')}")
        return 1
    elif state in FINISHED:
        print(f"\nThe run ended: {state.replace('_', ' ')}.")
    else:
        print(f"\nThe run is still {state.replace('_', ' ')}. Follow it with: python runs.py show {run['id']} --follow")
    return 0


def follow(api: Api, run_id: str, until: tuple[str, ...], seen: int = 0) -> int:
    try:
        while True:
            status, run = api.call("GET", f"/{run_id}")
            if status != 200:
                print(f"error: run {run_id}: {run.get('error', status)}", file=sys.stderr)
                return 1
            seen = print_events(run.get("events") or [], seen)
            if run["state"] in until:
                return outcome(api, run)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print(f"\nStopped following. The run goes on in Azure: python runs.py show {run_id} --follow")
        return 0


def start(api: Api, pull_request: int | None, keep_following: bool) -> int:
    status, run = api.call("POST", "", {"compareWithPullRequest": pull_request} if pull_request else {})
    if status != 202:
        print(f"error: the Function app refused the run: {run.get('error', status)}", file=sys.stderr)
        return 2
    print(f"Run {run['id']} started in Azure.")
    if not keep_following:
        print(f"Follow it with: python runs.py show {run['id']} --follow")
        return 0
    print("Following it until it waits for a person (Ctrl+C stops following, not the run):\n")
    return follow(api, run["id"], (WAITING, *FINISHED))


def status(api: Api) -> int:
    code, overview = api.call("GET")
    if code != 200:
        print(f"error: the Function app answered {code}: {overview.get('error')}", file=sys.stderr)
        return 2
    print(f"Runs in progress: {len(overview['inProgress'])}")
    for run in overview["inProgress"]:
        print(f"  {run['id']}  {run['state']}")
    if overview["recent"]:
        print("Newest runs:")
        for run in overview["recent"]:
            print(f"  {run['id']}  {run['state']}")
    token = overview["github"]
    if token.get("status") == 200:
        print(f"GitHub token in Key Vault: HTTP 200, expires {token.get('expires') or 'never'}")
    else:
        print(f"GitHub token in Key Vault: {token.get('status') or 'not usable'}: {token.get('error')}")
    return 0


def show(api: Api, run_id: str, keep_following: bool) -> int:
    code, run = api.call("GET", f"/{run_id}")
    if code != 200:
        print(f"error: run {run_id}: {run.get('error', code)}", file=sys.stderr)
        return 1
    print(f"Run {run['id']}, created {clock(run['created'])}: {run['state'].replace('_', ' ')}\n")
    seen = print_events(run.get("events") or [])
    if keep_following and run["state"] not in FINISHED:
        return follow(api, run_id, FINISHED, seen)
    return outcome(api, run)


def cancel(api: Api, run_ids: list[str], every: bool) -> int:
    if every:
        code, overview = api.call("GET")
        if code != 200:
            print(f"error: the Function app answered {code}: {overview.get('error')}", file=sys.stderr)
            return 2
        run_ids = [run["id"] for run in overview["inProgress"]]
    if not run_ids:
        print("No run in progress.")
    failed = 0
    for run_id in run_ids:
        code, run = api.call("DELETE", f"/{run_id}")
        if code == 200:
            print(f"Run {run_id}: {run['state'].replace('_', ' ')}")
        else:
            failed += 1
            print(f"Run {run_id}: not cancelled: {run.get('error', code)}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    start_cmd = commands.add_parser("start", help="start a run and follow it until it waits for a person")
    start_cmd.add_argument("--compare-with-pull-request", type=int, metavar="N",
                           help="also score the Copilot brief on this 01-plan-github pull request")
    start_cmd.add_argument("--no-follow", action="store_true", help="print the run's id and return at once")
    commands.add_parser("status", help="runs in progress, the newest runs, and the GitHub token's state")
    show_cmd = commands.add_parser("show", help="everything one run did so far")
    show_cmd.add_argument("run", help="the run's id, for example 20261031-151200-7f3c")
    show_cmd.add_argument("--follow", action="store_true", help="keep printing until the run ends")
    cancel_cmd = commands.add_parser("cancel", help="cancel unfinished runs")
    cancel_cmd.add_argument("runs", nargs="*", help="the runs to cancel")
    cancel_cmd.add_argument("--all", action="store_true", help="cancel every run in progress")
    args = parser.parse_args(argv)
    if args.command == "cancel" and not (args.runs or args.all):
        parser.error("cancel needs run ids or --all")
    api = Api()
    if args.command == "start":
        return start(api, args.compare_with_pull_request, not args.no_follow)
    if args.command == "status":
        return status(api)
    if args.command == "show":
        return show(api, args.run, args.follow)
    return cancel(api, args.runs, args.all)


if __name__ == "__main__":
    sys.exit(main())
