"""Start and reset the Operate incident drill against the deployed RequestHub. This is the drill harness: it causes the
incident and cleans up afterwards. Everything in between happens in Azure.

  python incident.py start     slow the notification worker down (a fault setting with an expiry) and submit
                               synthetic requests, so a backlog builds and the backlog alert fires
  python incident.py reset     remove the fault if it is still set and reseed RequestHub's demo data

The mitigation is not a command here: Azure SRE Agent proposes it and a person approves it in the agent's portal, or
runs the command the agent gives. The evidence stays in Azure: the alert's history in Azure Monitor, the investigation
thread in Azure SRE Agent, and the workbook. The workbook's "Ready for a drill" table shows whether the demo is in its
starting state. All requests, people, and notifications are synthetic.

Settings come from environment variables or this solution's azd environment (run `azd up` first): API_URL,
API_IDENTIFIER_URI, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, WORKER_APP_NAME, BACKLOG_ALERT_THRESHOLD_SECONDS. You
sign in with the Azure CLI (`az login`); `azd up` gave you the RequestHub Admin role.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from azd_env import setting, utf8_stdout

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
FAULT_SETTINGS = ("Faults__WorkerDelayMs", "Faults__ExpiresAtUtc")
REQUEST_TEMPLATES = [
    ("Replacement laptop charger", "My laptop charger stopped working. I need a replacement to keep working on site."),
    ("Second monitor for the help desk", "The help desk station needs a second monitor to follow the ticket queue."),
    ("Access to the shared planning folder", "I joined the planning team and need read access to the shared folder."),
    ("Desk chair repair", "The height lever on my desk chair is broken. Please repair or replace it."),
    ("Conference room display not working", "The display in the third-floor conference room shows no signal."),
    ("Travel booking for a training course", "I am attending a two-day training course next month and need travel booked."),
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def clock(moment: datetime | None) -> str:
    return moment.strftime("%H:%M:%SZ") if moment else "-"


def parse_json(text: str) -> object:
    """JSON when the body is JSON; otherwise the text itself, so an unexpected page never stops a drill."""
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ---------- Azure access ----------

class Azure:
    """Tokens from the Azure CLI sign-in; REST calls to RequestHub and Azure Resource Manager."""

    def __init__(self) -> None:
        from azure.identity import AzureCliCredential

        self.credential = AzureCliCredential(process_timeout=60)
        self.tokens: dict[str, tuple[str, float]] = {}
        self.api_url = setting("API_URL").rstrip("/")
        # The Azure CLI is pre-authorized for RequestHub's user_impersonation scope; /.default requests it.
        self.api_scope = f"{setting('API_IDENTIFIER_URI')}/.default"
        self.rg_id = f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
        self.worker = setting("WORKER_APP_NAME")

    def token(self, scope: str) -> str:
        cached = self.tokens.get(scope)
        if not cached or cached[1] - time.time() < 300:
            token = self.credential.get_token(scope)
            self.tokens[scope] = (token.token, token.expires_on)
        return self.tokens[scope][0]

    def call(self, method: str, url: str, scope: str, body: object = None, headers: dict | None = None,
             timeout: int = 60) -> tuple[int, object]:
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method)
        request.add_header("Authorization", f"Bearer {self.token(scope)}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", "replace")
                return response.status, parse_json(text)
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except urllib.error.URLError as error:
            return 0, str(error.reason)
        except OSError as error:  # a read timeout or a reset connection
            return 0, str(error) or type(error).__name__

    def api(self, method: str, path: str, body: object = None, headers: dict | None = None,
            timeout: int = 60) -> tuple[int, object]:
        return self.call(method, f"{self.api_url}{path}", self.api_scope, body, headers, timeout)

    def arm(self, path: str, api_version: str) -> object:
        status, body = self.call("GET", f"{ARM}{path}{'&' if '?' in path else '?'}api-version={api_version}", ARM_SCOPE)
        if status != 200:
            raise RuntimeError(f"HTTP {status} reading {path.rsplit('/providers/', 1)[-1]}: {str(body)[:200]}")
        return body

    def backlog(self) -> dict | None:
        status, body = self.api("GET", "/api/admin/notifications/backlog")
        return body if status == 200 and isinstance(body, dict) else None

    def worker_state(self) -> dict:
        app = self.arm(f"{self.rg_id}/providers/Microsoft.App/containerApps/{self.worker}", "2024-03-01")
        props = app["properties"]
        env = {e["name"]: e.get("value") for e in props["template"]["containers"][0].get("env", [])}
        return {
            "latestRevision": props.get("latestRevisionName"),
            "readyRevision": props.get("latestReadyRevisionName"),
            "faults": {name: env[name] for name in FAULT_SETTINGS if name in env},
        }


def az(*args: str) -> str:
    """Runs an Azure CLI command and prints it first, so the audience sees exactly what changed."""
    executable = shutil.which("az")
    if not executable:
        raise SystemExit("error: the Azure CLI (az) is required")
    print(f"  > az {' '.join(args)}")
    proc = subprocess.run([executable, *args, "--only-show-errors", "-o", "none"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"error: az {args[0]} {args[1]} failed: {proc.stderr.strip()}")
    return proc.stdout


def wait_for_revision(azure: Azure, previous: str | None, want_faults: bool, timeout: int = 600) -> dict:
    """Waits until a new revision is ready and the previous one has no replicas left, so only one worker runs."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = azure.worker_state()
        ready = state["readyRevision"] == state["latestRevision"] and state["latestRevision"] != previous
        if ready and bool(state["faults"]) == want_faults:
            revisions = azure.arm(f"{azure.rg_id}/providers/Microsoft.App/containerApps/{azure.worker}/revisions", "2024-03-01")
            others = [r["name"] for r in revisions.get("value", [])
                      if r["name"] != state["latestRevision"] and (r["properties"].get("replicas") or 0) > 0]
            if not others:
                return state
        time.sleep(10)
    raise SystemExit("error: the worker's new revision did not take over in time; check `az containerapp revision list`")


# ---------- commands ----------

def start(args: argparse.Namespace) -> int:
    azure = Azure()
    before = azure.backlog()
    if before is None:
        raise SystemExit("error: cannot read the backlog. Is the app deployed (azd up), is the database running, and are "
                         "you signed in (az login)? The workbook's 'Ready for a drill' table shows what is missing.")
    state = azure.worker_state()
    if state["faults"]:
        raise SystemExit(f"error: the worker already has fault settings {sorted(state['faults'])}. "
                         "Finish the current drill or run `python incident.py reset`.")

    started = now()
    drill = started.strftime("%Y%m%d-%H%M%S")
    expires = started + timedelta(minutes=args.minutes)
    print(f"Drill {drill} started at {clock(started)}. Backlog before: {before['pending']} pending, "
          f"oldest {before['oldestPendingAgeSeconds']}s")

    print(f"1. Slow the worker down: each delivery waits {args.delay_ms / 1000:g}s until {clock(expires)}")
    az("containerapp", "update", "-n", azure.worker, "-g", setting("AZURE_RESOURCE_GROUP"), "--set-env-vars",
       f"Faults__WorkerDelayMs={args.delay_ms}", f"Faults__ExpiresAtUtc={iso(expires)}")
    wait_for_revision(azure, state["latestRevision"], want_faults=True)
    print(f"  * the slowed worker revision took over at {clock(now())}")

    status, categories = azure.api("GET", "/api/categories")
    status2, departments = azure.api("GET", "/api/departments")
    if status != 200 or status2 != 200:
        raise SystemExit(f"error: cannot read categories or departments ({status}, {status2})")
    category_ids = [c["id"] for c in categories]
    department_ids = [d["id"] for d in departments]

    print(f"2. Submit {args.requests} synthetic requests (each notifies the department's reviewers)")

    def submit(index: int) -> int:
        title, description = REQUEST_TEMPLATES[index % len(REQUEST_TEMPLATES)]
        body = {"title": f"[Drill] {title} #{index + 1}", "description": description,
                "category": category_ids[index % len(category_ids)], "departmentId": department_ids[index % len(department_ids)],
                "priority": "Normal"}
        status, _ = azure.api("POST", "/api/requests", body, {"Idempotency-Key": f"drill-{drill}-{index}"})
        return status

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(submit, range(args.requests)))
    created = sum(1 for s in statuses if s in (200, 201))
    print(f"  * {created} submitted, {args.requests - created} failed, at {clock(now())}")
    time.sleep(5)
    after = azure.backlog() or {}
    pending = int(after.get("pending") or 0)
    per_minute = 60_000 / args.delay_ms
    print(f"Backlog now: {pending} pending. The worker delivers about {per_minute:g} per minute, so the backlog grows "
          f"older until someone acts or the fault expires at {clock(expires)}.")
    if pending / per_minute < args.minutes:
        print(f"Warning: the slowed worker can clear {pending} notifications in about {pending / per_minute:.0f} minutes, "
              "before the fault expires, and recovery would then prove nothing. Mitigate before then, or reset and start "
              "again with more --requests.")
    print(f"Next: the alert fires once the oldest notification has waited {setting('BACKLOG_ALERT_THRESHOLD_SECONDS')}s, "
          "and Azure SRE Agent opens an investigation. Follow both in the Azure portal (README, steps 3 and 4).")
    return 0 if created == args.requests else 1


def reset(args: argparse.Namespace) -> int:
    azure = Azure()
    state = azure.worker_state()
    if state["faults"]:
        print("Removing the fault settings from the worker")
        az("containerapp", "update", "-n", azure.worker, "-g", setting("AZURE_RESOURCE_GROUP"), "--remove-env-vars",
           *sorted(state["faults"]))
        wait_for_revision(azure, state["latestRevision"], want_faults=False)
    else:
        print("The worker has no fault settings.")
    if not args.keep_data:
        status, _ = azure.api("POST", "/api/admin/reset")
        print(f"RequestHub demo data reseeded (HTTP {status})." if status == 200 else f"error: reset returned HTTP {status}")
        if status != 200:
            return 1
    backlog = azure.backlog() or {}
    print(f"Backlog: {backlog.get('pending')} pending. SRE Agent threads stay in the agent's history as the record of past drills.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("start", help="slow the worker down and submit synthetic requests")
    p.add_argument("--delay-ms", type=int, default=10_000, help="extra delay per delivered notification (default 10000)")
    p.add_argument("--minutes", type=int, default=45, help="the fault switches itself off after this many minutes (default 45)")
    p.add_argument("--requests", type=int, default=200,
                   help="synthetic requests to submit (default 200, about 360 notifications: more than the slowed worker "
                        "can deliver before the fault expires, so only the mitigation or the expiry clears them)")
    p = commands.add_parser("reset", help="remove the fault if set and reseed the demo data")
    p.add_argument("--keep-data", action="store_true", help="only remove the fault; keep the synthetic requests")
    args = parser.parse_args()
    utf8_stdout()
    return {"start": start, "reset": reset}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
