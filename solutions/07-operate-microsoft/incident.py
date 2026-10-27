"""Run the Operate incident drill against the deployed RequestHub, and collect the evidence.

  python incident.py start     slow the notification worker down (a fault setting with an expiry) and submit
                               synthetic requests, so a backlog builds
  python incident.py watch     print the backlog, the alert, the worker's fault settings, and the SRE Agent
                               investigation every 30 seconds, until the incident is over
  python incident.py verify    check recovery: fault gone, backlog drained, a new request's notifications delivered,
                               alert resolved
  python incident.py summary   write a sanitized incident summary (out/incident-summary.md) from the drill timeline and
                               the SRE Agent's investigation; --issue files it as a GitHub Issue
  python incident.py reset     remove the fault if it is still set and reseed RequestHub's demo data

The mitigation is not a command here: Azure SRE Agent proposes it and a person approves it, or runs the command the
agent gives. Every command adds timestamped evidence to out/drill.json; `start` archives the previous drill to
out/drills/. All requests, people, and notifications are synthetic.

Settings come from environment variables or this solution's azd environment (run `azd up` first): API_URL,
API_IDENTIFIER_URI, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, WORKER_APP_NAME, BACKLOG_ALERT_NAME,
BACKLOG_ALERT_THRESHOLD_SECONDS, SRE_AGENT_NAME. You sign in with the Azure CLI (`az login`); `azd up` gave you the
RequestHub Admin role and the SRE Agent Administrator role.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azd_env import SOLUTION, setting, utf8_stdout

OUT = SOLUTION / "out"
DRILL_FILE = OUT / "drill.json"
ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
SRE_SCOPE = "https://azuresre.dev/.default"
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


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


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


# ---------- evidence file ----------

def load_drill() -> dict:
    if not DRILL_FILE.exists():
        raise SystemExit("error: no drill in progress. Run `python incident.py start` first.")
    return json.loads(DRILL_FILE.read_text(encoding="utf-8"))


def save_drill(drill: dict) -> None:
    OUT.mkdir(exist_ok=True)
    DRILL_FILE.write_text(json.dumps(drill, indent=2) + "\n", encoding="utf-8")


def record(drill: dict, event: str, at: datetime | None, **details: object) -> None:
    """Adds an event to the drill timeline once; later sightings of the same event are ignored."""
    if any(e["event"] == event for e in drill["timeline"]):
        return
    drill["timeline"].append({"event": event, "at": iso(at or now()), **details})
    drill["timeline"].sort(key=lambda e: e["at"])
    print(f"  * {event} at {clock(at or now())}" + (f" ({details})" if details else ""))


# ---------- Azure access ----------

class Azure:
    """Tokens from the Azure CLI sign-in; REST calls to RequestHub, Azure Resource Manager, and the SRE Agent."""

    def __init__(self) -> None:
        from azure.identity import AzureCliCredential

        self.credential = AzureCliCredential(process_timeout=60)
        self.tokens: dict[str, tuple[str, float]] = {}
        self.api_url = setting("API_URL").rstrip("/")
        # The Azure CLI is pre-authorized for RequestHub's user_impersonation scope; /.default requests it.
        self.api_scope = f"{setting('API_IDENTIFIER_URI')}/.default"
        self.rg_id = f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
        self.worker = setting("WORKER_APP_NAME")
        self._sre_endpoint: str | None = None

    def token(self, scope: str) -> str:
        cached = self.tokens.get(scope)
        if not cached or cached[1] - time.time() < 300:
            token = self.credential.get_token(scope)
            self.tokens[scope] = (token.token, token.expires_on)
        return self.tokens[scope][0]

    def call(self, method: str, url: str, scope: str, body: object = None, headers: dict | None = None) -> tuple[int, object]:
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method)
        request.add_header("Authorization", f"Bearer {self.token(scope)}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8", "replace")
                return response.status, parse_json(text)
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except urllib.error.URLError as error:
            return 0, str(error.reason)

    def api(self, method: str, path: str, body: object = None, headers: dict | None = None) -> tuple[int, object]:
        return self.call(method, f"{self.api_url}{path}", self.api_scope, body, headers)

    def arm(self, path: str, api_version: str) -> object:
        status, body = self.call("GET", f"{ARM}{path}{'&' if '?' in path else '?'}api-version={api_version}", ARM_SCOPE)
        if status != 200:
            raise RuntimeError(f"ARM GET {path} returned {status}: {str(body)[:200]}")
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

    def alerts(self, since: datetime) -> list[dict]:
        """Azure Monitor alerts from the backlog rule that fired since the given time, newest first."""
        query = urllib.parse.urlencode({"targetResourceGroup": setting("AZURE_RESOURCE_GROUP"), "timeRange": "1d",
                                        "sortBy": "startDateTime", "sortOrder": "desc"})
        body = self.arm(f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/providers/Microsoft.AlertsManagement/alerts?{query}",
                        "2019-05-05-preview")
        rule = setting("BACKLOG_ALERT_NAME").lower()
        found = []
        for alert in body.get("value", []):
            essentials = alert.get("properties", {}).get("essentials", {})
            started = parse_time(essentials.get("startDateTime"))
            if essentials.get("alertRule", "").lower().endswith("/" + rule) and started and started >= since - timedelta(minutes=1):
                found.append({
                    "id": alert.get("name"),
                    "condition": essentials.get("monitorCondition"),
                    "state": essentials.get("alertState"),
                    "fired": started,
                    "resolved": parse_time(essentials.get("monitorConditionResolvedDateTime")),
                    "severity": essentials.get("severity"),
                })
        return found

    def sre_endpoint(self) -> str:
        if not self._sre_endpoint:
            agent = self.arm(f"{self.rg_id}/providers/Microsoft.App/agents/{setting('SRE_AGENT_NAME')}", "2026-01-01")
            self._sre_endpoint = agent["properties"]["agentEndpoint"].rstrip("/")
        return self._sre_endpoint

    def sre(self, path: str) -> tuple[int, object]:
        return self.call("GET", f"{self.sre_endpoint()}{path}", SRE_SCOPE)

    def threads(self, since: datetime) -> list[dict]:
        """SRE Agent incident threads for the backlog alert created since the given time, newest first."""
        query = urllib.parse.urlencode({"$top": 20, "$orderby": "createdTimestamp desc"})
        status, body = self.sre(f"/api/v1/threads?{query}")
        rows = body.get("value", []) if isinstance(body, dict) else []
        rule = setting("BACKLOG_ALERT_NAME").lower()
        found = []
        for thread in rows:
            details = thread.get("incidentDetails") or {}
            created = parse_time(thread.get("createdTimestamp"))
            title = str(details.get("incidentTitle") or thread.get("title") or "")
            if created and created >= since - timedelta(minutes=1) and rule in title.lower():
                found.append({"id": thread["id"], "title": thread.get("title"), "created": created,
                              "status": details.get("investigationStatus"), "plan": details.get("filterId"),
                              "mode": thread.get("agentMode")})
        return sorted(found, key=lambda t: t["created"], reverse=True)

    def messages(self, thread_id: str) -> list[dict]:
        status, body = self.sre(f"/api/v1/threads/{thread_id}/messages")
        return body.get("value", []) if status == 200 and isinstance(body, dict) else []

    def thread_events(self, thread_id: str) -> dict[str, tuple[datetime, dict]]:
        """Milestones in an investigation thread: report, approval requested and decided, mitigation run."""
        events: dict[str, tuple[datetime, dict]] = {}
        for message in self.messages(thread_id):
            if message.get("author", {}).get("role") != "SREAgent":
                continue
            at = parse_time(message.get("timeStamp"))
            text = message.get("text") or ""
            if at and "root cause" in text.lower() and len(text) > 800 and "SRE Agent reported its findings" not in events:
                events["SRE Agent reported its findings"] = (at, {})
            approval = message.get("approval")
            if approval:
                requested = parse_time(approval.get("createdTimestamp"))
                if requested:
                    events.setdefault("approval requested", (requested, {"tool": approval.get("display", {}).get("toolName")}))
                decided = parse_time(approval.get("decisionTimestamp"))
                if decided and approval.get("status") in ("Approved", "Authorized"):
                    again = "approved by an administrator" in events and events["approved by an administrator"][0] != decided
                    events.setdefault("approved again by an administrator" if again else "approved by an administrator",
                                      (decided, {}))
            execution = message.get("azCliExecution") or {}
            completed = execution.get("status") == "Completed"
            if "--remove-env-vars" in str(execution.get("command")) and (completed or execution.get("error")):
                # A failed run is marked cancelled later, so it is dated when it started.
                done = parse_time(execution.get("completedTimestamp" if completed else "startedTimestamp")) or at
                who = execution.get("executedBy") or {}
                by_agent = isinstance(who, dict) and who.get("userId") == "agent-default"
                identity = "as the agent" if by_agent else "as the approver (on-behalf-of)"
                event = "mitigation run by SRE Agent" if completed else "mitigation run failed"
                if done:
                    events.setdefault(event, (done, {"ranWith": identity}))
        return events


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
        raise SystemExit("error: cannot read the backlog. Is the app deployed (azd up) and are you signed in (az login)?")
    state = azure.worker_state()
    if state["faults"]:
        raise SystemExit(f"error: the worker already has fault settings {sorted(state['faults'])}. "
                         "Finish the current drill or run `python incident.py reset`.")
    if DRILL_FILE.exists():
        (OUT / "drills").mkdir(parents=True, exist_ok=True)
        old = json.loads(DRILL_FILE.read_text(encoding="utf-8"))
        DRILL_FILE.replace(OUT / "drills" / f"{old.get('id', 'previous')}.json")

    started = now()
    expires = started + timedelta(minutes=args.minutes)
    drill = {"id": started.strftime("%Y%m%d-%H%M%S"), "worker": azure.worker, "faultDelayMs": args.delay_ms,
             "faultExpiresAtUtc": iso(expires), "requests": args.requests, "timeline": [], "backlogSamples": []}
    print(f"Drill {drill['id']}: worker {azure.worker}, backlog before: {before['pending']} pending, "
          f"oldest {before['oldestPendingAgeSeconds']}s")

    print(f"1. Slow the worker down: each delivery waits {args.delay_ms / 1000:g}s until {clock(expires)}")
    az("containerapp", "update", "-n", azure.worker, "-g", setting("AZURE_RESOURCE_GROUP"), "--set-env-vars",
       f"Faults__WorkerDelayMs={args.delay_ms}", f"Faults__ExpiresAtUtc={iso(expires)}")
    record(drill, "fault applied", now(), revisionBefore=state["latestRevision"])
    state = wait_for_revision(azure, state["latestRevision"], want_faults=True)
    record(drill, "faulty revision took over", now(), revision=state["readyRevision"])
    save_drill(drill)

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
        status, _ = azure.api("POST", "/api/requests", body, {"Idempotency-Key": f"drill-{drill['id']}-{index}"})
        return status

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(submit, range(args.requests)))
    created = sum(1 for s in statuses if s in (200, 201))
    record(drill, "synthetic requests submitted", now(), submitted=created, failed=args.requests - created)
    time.sleep(5)
    after = azure.backlog() or {}
    drill["backlogSamples"].append({"at": iso(now()), **after})
    save_drill(drill)
    pending = int(after.get("pending") or 0)
    per_minute = 60_000 / args.delay_ms
    print(f"Backlog now: {pending} pending. The worker delivers about {per_minute:g} per minute, so the backlog grows "
          f"older until someone acts or the fault expires at {clock(expires)}.")
    if pending / per_minute < args.minutes:
        print(f"Warning: the slowed worker can clear {pending} notifications in about {pending / per_minute:.0f} minutes, "
              "before the fault expires, and recovery would then prove nothing. Mitigate before then, or reset and start "
              "again with more --requests.")
    print("Next: python incident.py watch")
    return 0 if created == args.requests else 1


def sample(azure: Azure, drill: dict, since: datetime, threshold: float) -> tuple[str, bool]:
    """Reads every source once, records new timeline events, and returns the printed line and whether it is over."""
    moment = now()
    backlog = azure.backlog() or {}
    state = azure.worker_state()
    alerts = azure.alerts(since)
    threads = azure.threads(since)
    drill["backlogSamples"].append({"at": iso(moment), **backlog})
    events = {e["event"] for e in drill["timeline"]}

    alert = alerts[0] if alerts else None
    if alert:
        record(drill, "alert fired", alert["fired"], alertId=alert["id"], severity=alert["severity"])
        if alert["resolved"]:
            record(drill, "alert resolved", alert["resolved"])
    thread = threads[-1] if threads else None
    milestone = ""
    if thread:
        record(drill, "SRE Agent investigation started", thread["created"], threadId=thread["id"],
               responsePlan=thread["plan"], mode=thread["mode"])
        for event, (at, details) in sorted(azure.thread_events(thread["id"]).items(), key=lambda item: item[1][0]):
            record(drill, event, at, **details)
            milestone = event
    if not state["faults"] and "fault applied" in events and "fault removed" not in events:
        revision = azure.arm(f"{azure.rg_id}/providers/Microsoft.App/containerApps/{azure.worker}/revisions/"
                             f"{state['latestRevision']}", "2024-03-01")
        record(drill, "fault removed", parse_time(revision["properties"].get("createdTime")) or moment,
               revision=state["latestRevision"])
    if backlog and "fault removed" in events and backlog.get("pending", 1) == 0:
        record(drill, "backlog drained", moment)
    save_drill(drill)

    elapsed = str(timedelta(seconds=int((moment - since).total_seconds())))
    alert_text = f"{alert['condition']} {clock(alert['fired'])}" if alert else "not fired"
    if alert and alert["resolved"]:
        alert_text = f"Resolved {clock(alert['resolved'])}"
    thread_text = f"{thread['status']}: {milestone or 'investigating'}" if thread else "-"
    oldest = backlog.get("oldestPendingAgeSeconds")
    flag = "!" if oldest is not None and oldest > threshold else " "
    line = (f"{clock(moment):>9}  {elapsed:>7}  {backlog.get('pending', '?'):>7}  {oldest if oldest is not None else '?':>6}{flag}  "
            f"{'on' if state['faults'] else 'off':<5}  {alert_text:<26}  {thread_text}")
    events = {e["event"] for e in drill["timeline"]}
    return line, "alert resolved" in events and "backlog drained" in events


def watch(args: argparse.Namespace) -> int:
    azure = Azure()
    drill = load_drill()
    since = parse_time(drill["timeline"][0]["at"]) if drill["timeline"] else now()
    threshold = float(setting("BACKLOG_ALERT_THRESHOLD_SECONDS", "60"))
    deadline = time.time() + args.minutes * 60
    done = False
    print(f"{'time':>9}  {'elapsed':>7}  {'pending':>7}  {'oldest':>7}  {'fault':<5}  {'alert':<26}  SRE Agent")
    try:
        while True:
            try:
                line, done = sample(azure, drill, since, threshold)
                print(line)
            except Exception as error:  # one failed read (network, token, throttling) must not end an hour-long watch
                print(f"{clock(now()):>9}  sample failed, retrying: {str(error)[:120]}")
            if args.once or done or time.time() > deadline:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")
    save_drill(drill)
    if done:
        print("Incident over: run `python incident.py verify`.")
    return 0


def verify(args: argparse.Namespace) -> int:
    azure = Azure()
    drill = load_drill()
    since = parse_time(drill["timeline"][0]["at"]) if drill["timeline"] else now() - timedelta(hours=2)
    threshold = float(setting("BACKLOG_ALERT_THRESHOLD_SECONDS", "60"))
    results: list[tuple[str, str, str]] = []

    state = azure.worker_state()
    ok = not state["faults"] and state["readyRevision"] == state["latestRevision"]
    results.append(("Fault removed", "PASS" if ok else "FAIL",
                    f"revision {state['latestRevision']}, fault settings: {sorted(state['faults']) or 'none'}"))

    backlog = azure.backlog() or {}
    ok = backlog.get("pending") == 0 and (backlog.get("oldestPendingAgeSeconds") or 0) < threshold
    results.append(("Backlog drained", "PASS" if ok else "FAIL",
                    f"{backlog.get('pending')} pending, oldest {backlog.get('oldestPendingAgeSeconds')}s"))

    status, categories = azure.api("GET", "/api/categories")
    status2, departments = azure.api("GET", "/api/departments")
    if status != 200 or status2 != 200 or not categories or not departments:
        raise SystemExit(f"error: cannot read categories or departments ({status}, {status2}); is the API up?")
    probe = {"title": "[Drill] Recovery check", "description": "Synthetic request that checks notifications are delivered again.",
             "category": categories[0]["id"], "departmentId": departments[0]["id"], "priority": "Normal"}
    submitted_at = now()
    status, created = azure.api("POST", "/api/requests", probe, {"Idempotency-Key": f"drill-{drill['id']}-verify-{int(time.time())}"})
    delivered_in = None
    if status in (200, 201):
        time.sleep(1)
        for _ in range(30):
            current = azure.backlog() or {}
            if current.get("pending") == 0:
                delivered_in = (now() - submitted_at).total_seconds()
                break
            time.sleep(2)
    request_id = created.get("id") if isinstance(created, dict) else None
    results.append(("New request notified", "PASS" if delivered_in is not None else "FAIL",
                    f"{request_id}: notifications delivered within {delivered_in:.0f}s" if delivered_in is not None
                    else f"submit returned {status}; notifications still pending after 60s"))

    alerts = azure.alerts(since)
    alert = alerts[0] if alerts else None
    if not alert:
        results.append(("Alert resolved", "FAIL", "no backlog alert fired during this drill"))
    elif alert["resolved"]:
        results.append(("Alert resolved", "PASS", f"fired {clock(alert['fired'])}, resolved {clock(alert['resolved'])}"))
    else:
        results.append(("Alert resolved", "WAIT", f"still {alert['condition']}; Azure Monitor resolves it a few minutes after "
                                                   "the backlog drains. Run verify again."))

    threads = azure.threads(since)
    thread = threads[-1] if threads else None
    results.append(("SRE Agent investigated", "PASS" if thread else "FAIL",
                    f"thread {thread['id']} started {clock(thread['created'])}" if thread else "no investigation thread found"))

    width = max(len(r[0]) for r in results)
    for check, verdict, detail in results:
        print(f"{check:<{width}}  {verdict:<4}  {detail}")
    drill["verification"] = {"at": iso(now()), "results": [{"check": c, "verdict": v, "detail": d} for c, v, d in results]}
    if alert and alert["resolved"]:
        record(drill, "alert resolved", alert["resolved"])
    passed = all(v == "PASS" for _, v, _ in results)
    if passed:
        record(drill, "recovery verified", now(), probeDeliveredSeconds=round(delivered_in))
    save_drill(drill)
    return 0 if passed else 1


GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def sanitize(text: str) -> str:
    """Removes subscription and tenant ids, object ids, email addresses, and long tokens before anything leaves Azure."""
    text = re.sub(r"/subscriptions/[^/\s]+", "/subscriptions/<subscription>", text)
    text = GUID.sub("<id>", text)
    text = EMAIL.sub("<email>", text)
    return re.sub(r"\b[A-Za-z0-9+/_-]{60,}={0,2}", "<redacted>", text)


def message_text(message: dict) -> str:
    content = message.get("content") or message.get("text") or message.get("message") or ""
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def summary(args: argparse.Namespace) -> int:
    azure = Azure()
    drill = load_drill()
    thread_id = next((e.get("threadId") for e in drill["timeline"] if e["event"] == "SRE Agent investigation started"), None)
    if thread_id:
        # Thread milestones that `watch` did not see, for example after it stopped, complete the timeline.
        for event, (at, details) in sorted(azure.thread_events(thread_id).items(), key=lambda item: item[1][0]):
            record(drill, event, at, **details)
        save_drill(drill)
    events = {e["event"]: e for e in drill["timeline"]}
    fired, recovered = parse_time(events.get("alert fired", {}).get("at")), parse_time(
        (events.get("backlog drained") or events.get("recovery verified") or {}).get("at"))
    peak = max((s.get("oldestPendingAgeSeconds") or 0 for s in drill.get("backlogSamples", [])), default=0)
    peak_pending = max((s.get("pending") or 0 for s in drill.get("backlogSamples", [])), default=0)

    report, recovery = "", ""
    if thread_id:
        replies = [message_text(m) for m in azure.messages(thread_id)
                   if m.get("author", {}).get("role") == "SREAgent" and len(message_text(m)) > 600]
        report = next((r for r in replies if "root cause" in r.lower()), "")
        recovery = replies[-1] if replies and replies[-1] != report else ""

    lines = [
        f"## Incident summary: notification backlog (drill {drill['id']})",
        "",
        "Synthetic drill on RequestHub's demo environment. All data is synthetic.",
        "",
        "| | |",
        "| --- | --- |",
        f"| Impact | Notifications (request submitted, comment, decision) delivered late. Peak: {peak_pending} pending, "
        f"oldest waiting {peak:.0f} seconds. |",
        f"| Detected | Azure Monitor alert *{setting('BACKLOG_ALERT_NAME')}* at {events.get('alert fired', {}).get('at', 'not recorded')} |",
        f"| Duration | {str(recovered - fired).split('.')[0] if fired and recovered else 'not recorded'} from alert to drained backlog |",
        f"| Cause | Fault setting `Faults__WorkerDelayMs={drill['faultDelayMs']}` on the notification worker (expiry {drill['faultExpiresAtUtc']}) |",
        "| Investigation | Azure SRE Agent thread THREAD_ID |",
        "",
        "### Timeline (UTC)",
        "",
        "| Time | Event |",
        "| --- | --- |",
        *[f"| {e['at']} | {e['event']}{', ' + e['ranWith'] if e.get('ranWith') else ''} |" for e in drill["timeline"]],
    ]
    if drill.get("verification"):
        lines += ["", "### Recovery checks", "", "| Check | Result | Detail |", "| --- | --- | --- |",
                  *[f"| {r['check']} | {r['verdict']} | {r['detail']} |" for r in drill["verification"]["results"]]]
    if report:
        lines += ["", "### SRE Agent investigation report", "", report.strip()]
    if recovery:
        lines += ["", "### SRE Agent recovery check", "", recovery.strip()]
    # The thread id is the agent's record of this investigation, not an identity, so it stays.
    text = sanitize("\n".join(lines)).replace("THREAD_ID", f"`{thread_id}`" if thread_id else "not recorded") + "\n"
    path = OUT / "incident-summary.md"
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path.relative_to(SOLUTION)} ({len(text)} characters, sanitized).")

    if args.issue:
        gh = shutil.which("gh")
        if not gh:
            raise SystemExit("error: the GitHub CLI (gh) is required for --issue")
        command = [gh, "issue", "create", "--title", f"Incident summary: notification backlog (drill {drill['id']})",
                   "--body-file", str(path)]
        for label in args.label:
            command += ["--label", label]
        if args.repo:
            command += ["--repo", args.repo]
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise SystemExit(f"error: gh issue create failed: {proc.stderr.strip()}")
        url = proc.stdout.strip().splitlines()[-1]
        record(drill, "incident summary filed", now(), issue=url)
        save_drill(drill)
        print(f"Issue: {url}")
    return 0


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
    p = commands.add_parser("watch", help="print backlog, alert, and SRE Agent status until the incident is over")
    p.add_argument("--interval", type=int, default=30, help="seconds between samples (default 30)")
    p.add_argument("--minutes", type=int, default=60, help="stop watching after this many minutes (default 60)")
    p.add_argument("--once", action="store_true", help="print one sample and exit")
    commands.add_parser("verify", help="check that the worker recovered")
    p = commands.add_parser("summary", help="write a sanitized incident summary, optionally as a GitHub Issue")
    p.add_argument("--issue", action="store_true", help="file the summary as a GitHub Issue with `gh issue create`")
    p.add_argument("--label", action="append", default=[], help="label for the Issue (repeatable); the label must exist")
    p.add_argument("--repo", help="repository for the Issue (owner/name); default: the current repository")
    p = commands.add_parser("reset", help="remove the fault if set and reseed the demo data")
    p.add_argument("--keep-data", action="store_true", help="only remove the fault; keep the synthetic requests")
    args = parser.parse_args()
    utf8_stdout()
    return {"start": start, "watch": watch, "verify": verify, "summary": summary, "reset": reset}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
