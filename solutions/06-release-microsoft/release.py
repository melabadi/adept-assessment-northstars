"""Release RequestHub on Azure Container Apps without exposing users to an untested revision.

The API container app runs in multiple-revision mode. A release never replaces the revision users are on. It adds a
candidate revision that receives no traffic, checks it on its own URL, and only then moves traffic. Revision labels
describe the state at any moment, and each label has its own URL (https://<app>---<label>.<environment domain>):

  stable      the revision users get: 100% of traffic
  candidate   the revision being released: 0% of traffic until it is promoted
  previous    the revision that was stable before the last promotion, kept running for an instant rollback

Commands, in release order. Each prints progress, writes a JSON record under out/release/, and adds a section to the
GitHub Actions job summary when it runs in a workflow.

  status     Revisions, labels, traffic, health, build, and URLs.
  deploy     Add a candidate: the stable revision's exact configuration with a new image pinned by digest, no traffic.
  gate       Wait until the candidate is ready, smoke-test it on its own URL, then watch it for a bake period.
             Exits 1 with the reason when the candidate fails. Never moves traffic.
  promote    Move 100% of traffic to a candidate that is healthy. The old stable revision becomes previous.
  abort      Remove the candidate (label, then revision) without touching traffic, then verify production.
  rollback   Move 100% of traffic back to the previous revision, then verify production.
  verify     Smoke-test the production URL, or one label's URL with --label.
  watch      Call the production URL every second, as a user would, and show where Azure routes traffic.
  record     Combine the JSON records in out/release/ into one release record (Markdown and JSON).

The smoke test uses the API the way people do: readiness, build provenance (/api/meta), sign-in enforcement, then it
submits a request (twice with the same Idempotency-Key: one request), reads it back, attaches a file and downloads it
again (Blob storage, which the readiness probe does not check), tries to approve its own request (the API must refuse
with decision.self_approval), and reads the request's audit history.

Settings come from environment variables, or from this solution's azd environment after `azd up`:
AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, API_APP_NAME, API_IDENTIFIER_URI.
Azure calls use your Azure CLI sign-in (`az login`); in GitHub Actions, the workflow's OIDC sign-in.

What is published never names your resources. Release records, job summaries, and pull request comments use
placeholders (<app>, <environment domain>, <registry>, <id>) instead of host names, resource names with their unique
token, and ids, and name revisions by their suffix (run12). In GitHub Actions the workflow log gets the same treatment,
and every such value is masked with ::add-mask:: before it can be printed. Your own terminal shows the real values.

Examples:
  python release.py status
  python release.py deploy --image <registry>.azurecr.io/requesthub-api:<commit> --commit <commit>
  python release.py deploy --fault fail-readiness      # the stable image again, with a readiness probe that fails
  python release.py gate
  python release.py promote                            # or: python release.py abort
  python release.py rollback
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from azd_env import SOLUTION, azd_values, setting, utf8_stdout

API_VERSION = "2025-07-01"  # Microsoft.App GA version used for revisions, labels, and traffic
ARM = "https://management.azure.com"
CONTRACT = "requesthub.v1"
CONTAINER = "api"
OUT = SOLUTION / "out" / "release"
RECORD_SCHEMA = "requesthub-release/1"
FAULT_MINUTES = 30  # every fault expires; after this the injected readiness failure switches itself off
RUNNING = {"Running", "RunningAtMaxScale"}


class ReleaseError(Exception):
    """A release step cannot continue. The message says why and what to do."""


# ---------------------------------------------------------------------------------------------------------------------
# What leaves this machine. Release records, job summaries, workflow logs, and pull request comments can become public,
# so they never contain host names, resource names with their unique token, or ids. Those are replaced with placeholders
# such as <app> and <environment domain>, and revisions are named by their suffix. Only your own terminal shows the
# real values.
# ---------------------------------------------------------------------------------------------------------------------

GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
_private: dict[str, str] = {}  # lower-cased value that names a deployed resource -> placeholder


def keep_private(value: str | None, placeholder: str) -> None:
    """Never publish this value. In GitHub Actions, also mask it in the log before anything can print it."""
    if not value or value.lower() in _private:
        return
    _private[value.lower()] = placeholder
    if IN_ACTIONS:
        # A workflow command: the runner consumes the line and masks the value from then on; the log never shows it.
        sys.__stdout__.write(f"::add-mask::{value}\n")
        sys.__stdout__.flush()


def keep_image_private(image: str | None) -> None:
    registry = (image or "").split("/")[0]
    if "." in registry:  # a registry host such as <name>.azurecr.io
        keep_private(registry, "<registry>")


def public(text: str) -> str:
    """The text with every private value replaced by its placeholder, and every id by <id>."""
    for value in sorted(_private, key=len, reverse=True):
        text = re.sub(re.escape(value), lambda _: _private[value], text, flags=re.IGNORECASE)
    return GUID.sub("<id>", text)


class PublicStream:
    """In GitHub Actions, stdout and stderr go through public(), so the workflow log never shows a private value."""

    def __init__(self, raw):
        self.raw = raw

    def write(self, text: str) -> int:
        return self.raw.write(public(text))

    def __getattr__(self, name):
        return getattr(self.raw, name)


# ---------------------------------------------------------------------------------------------------------------------
# Small helpers: time, the Azure CLI, tokens, HTTP
# ---------------------------------------------------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str | None) -> datetime | None:
    """ARM timestamps use up to 7 fractional digits; Python accepts 6."""
    if not value:
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def az(*args: str) -> str:
    exe = shutil.which("az")
    if not exe:
        raise SystemExit("error: the Azure CLI (az) is required. Install it and run `az login`.")
    proc = subprocess.run([exe, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReleaseError(f"az {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip()


_tokens: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def access_token(*, resource: str | None = None, scope: str | None = None) -> str:
    """A token from the Azure CLI sign-in, cached until five minutes before it expires."""
    key = scope or resource or ""
    if key == f"{ARM}/" and key not in _tokens:
        arm_session()
    with _token_lock:
        cached = _tokens.get(key)
        if cached and cached[1] - time.time() > 300:
            return cached[0]
        args = ["account", "get-access-token", "--output", "json"]
        args += ["--scope", scope] if scope else ["--resource", resource or ""]
        data = json.loads(az(*args))
        expires = float(data.get("expires_on") or 0) or time.time() + 1800
        _tokens[key] = (data["accessToken"], expires)
        return data["accessToken"]


@lru_cache(maxsize=1)
def arm_session() -> dict:
    """One Azure CLI call: the ARM token plus the signed-in subscription."""
    data = json.loads(az("account", "get-access-token", "--resource", f"{ARM}/", "--output", "json"))
    with _token_lock:
        _tokens[f"{ARM}/"] = (data["accessToken"], float(data.get("expires_on") or 0) or time.time() + 1800)
    return data


def token_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def api_token() -> str:
    """Token for the RequestHub API: delegated for a person (Azure CLI), app-only for the GitHub Actions identity."""
    uri = setting("API_IDENTIFIER_URI")
    if "scp" in token_claims(access_token(resource=f"{ARM}/")):  # delegated tokens carry scopes; app tokens do not
        return access_token(scope=f"{uri}/user_impersonation")
    return access_token(resource=uri)


@dataclass
class Response:
    status: int  # 0 when the server could not be reached
    body: bytes
    headers: dict[str, str]
    ms: float
    error: str = ""

    def json(self):
        try:
            return json.loads(self.body or b"null")
        except ValueError:
            return None

    def text(self, limit: int = 300) -> str:
        return self.body[:limit].decode(errors="replace").strip() or self.error

    @property
    def outcome(self) -> str:
        return f"HTTP {self.status}" if self.status else (self.error or "no response")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report redirects (sign-in pages) instead of following them
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http(method: str, url: str, *, bearer: str | None = None, body=None, raw: bytes | None = None,
         headers: dict | None = None, timeout: float = 20.0) -> Response:
    """JSON by default; pass raw bytes (with a Content-Type header) for other bodies, such as a file upload."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "requesthub-release/1.0")
    if data is not None and raw is None:
        request.add_header("Content-Type", "application/json")
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    start = time.perf_counter()
    try:
        with _opener.open(request, timeout=timeout) as response:
            return Response(response.status, response.read(), {k.lower(): v for k, v in response.headers.items()},
                            (time.perf_counter() - start) * 1000)
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read(), {k.lower(): v for k, v in (error.headers or {}).items()},
                        (time.perf_counter() - start) * 1000)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Response(0, b"", {}, (time.perf_counter() - start) * 1000, str(getattr(error, "reason", error)))


# ---------------------------------------------------------------------------------------------------------------------
# The container app, through Azure Resource Manager
# ---------------------------------------------------------------------------------------------------------------------

def arm(method: str, url: str, body=None, *, ok=(200,)) -> Response:
    if "api-version=" not in url:
        url += ("&" if "?" in url else "?") + f"api-version={API_VERSION}"
    for attempt in range(4):
        response = http(method, url, bearer=access_token(resource=f"{ARM}/"), body=body, timeout=60)
        if response.status in (0, 429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(int(response.headers.get("retry-after", 0) or 2 * (attempt + 1)))
            continue
        break
    if response.status not in ok:
        raise ReleaseError(f"{method} {url.split('?')[0].split('/providers/')[-1]} returned HTTP {response.status}: "
                           f"{response.text(600)}")
    return response


class ContainerApp:
    def __init__(self, subscription: str, resource_group: str, name: str):
        self.name = name
        self.resource_group = resource_group
        self.url = (f"{ARM}/subscriptions/{subscription}/resourceGroups/{resource_group}"
                    f"/providers/Microsoft.App/containerApps/{name}")

    def get(self) -> dict:
        return arm("GET", self.url).json()

    def revisions(self) -> list[dict]:
        items, url = [], f"{self.url}/revisions"
        while url:
            page = arm("GET", url).json()
            items += page.get("value", [])
            url = page.get("nextLink")
        return items

    def revision(self, name: str) -> dict:
        return arm("GET", f"{self.url}/revisions/{name}").json()

    def replicas(self, name: str) -> list[dict]:
        return arm("GET", f"{self.url}/revisions/{name}/replicas").json().get("value", [])

    def deactivate(self, name: str) -> None:
        arm("POST", f"{self.url}/revisions/{name}/deactivate", ok=(200, 202, 204))

    def activate(self, name: str) -> None:
        arm("POST", f"{self.url}/revisions/{name}/activate", ok=(200, 202, 204))

    def patch(self, body: dict, *, timeout: float = 600) -> float:
        """PATCH the app (JSON merge patch) and wait for the operation to finish. Returns the seconds it took."""
        start = time.time()
        response = arm("PATCH", self.url, body, ok=(200, 201, 202))
        operation = response.headers.get("azure-asyncoperation")
        location = response.headers.get("location")
        if response.status != 202 or not (operation or location):
            return time.time() - start
        while time.time() - start < timeout:
            time.sleep(3)
            if operation:
                status = arm("GET", operation).json() or {}
                state = status.get("status", "")
                if state == "Succeeded":
                    return time.time() - start
                if state in ("Failed", "Canceled"):
                    raise ReleaseError(f"Azure reported the change as {state}: {json.dumps(status.get('error') or status)[:600]}")
            else:
                polled = arm("GET", location, ok=(200, 202))
                if polled.status == 200:
                    return time.time() - start
        raise ReleaseError(f"Azure did not finish the change within {timeout:.0f} s.")


def traffic_body(stable: str, previous: str | None = None, candidate: str | None = None) -> dict:
    traffic = [{"revisionName": stable, "weight": 100, "label": "stable"}]
    if previous and previous != stable:
        traffic.append({"revisionName": previous, "weight": 0, "label": "previous"})
    if candidate:
        traffic.append({"revisionName": candidate, "weight": 0, "label": "candidate"})
    return {"properties": {"configuration": {"ingress": {"traffic": traffic}}}}


def container_of(template: dict) -> dict:
    containers = template.get("containers") or []
    return next((c for c in containers if c.get("name") == CONTAINER), containers[0] if containers else {})


def without_nulls(value):
    """ARM returns unset fields as null; leave them out of a PATCH so they keep their defaults."""
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value]
    return value


def container_started(container: dict) -> float | None:
    """Start time from the platform's detail text ("Container started at: 10/27/2026 1:38:54 PM.", UTC)."""
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M)", container.get("runningStateDetails") or "")
    if not match:
        return None
    started = datetime.strptime(match.group(1), "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=timezone.utc).timestamp()
    return started if time.time() - 3600 < started <= time.time() + 60 else None


def env_of(revision: dict) -> dict[str, str]:
    container = container_of(revision.get("properties", {}).get("template", {}))
    return {e["name"]: e.get("value", "") for e in container.get("env", []) if "name" in e}


def image_of(revision: dict) -> str:
    return container_of(revision.get("properties", {}).get("template", {})).get("image", "")


def commit_of(revision: dict) -> str:
    env = env_of(revision)
    return env.get("RELEASE_COMMIT") or env.get("BUILD_SHA") or ""


def short_name(revision: str | None) -> str:
    """A revision by its suffix (run12). The full name starts with the app's name, which carries its unique token."""
    return (revision or "-").split("--", 1)[-1]


@dataclass
class State:
    """The app's revisions and traffic, normalized: labels map to revision names, weights per revision."""
    app: ContainerApp
    data: dict
    revisions: dict[str, dict]
    traffic: list[dict]
    labels: dict[str, str]
    weights: dict[str, int]

    @classmethod
    def load(cls, app: ContainerApp) -> "State":
        data = app.get()
        revisions = {r["name"]: r for r in app.revisions()}
        keep_private(data["properties"]["configuration"]["ingress"]["fqdn"].split(".", 1)[1], "<environment domain>")
        for revision in revisions.values():
            keep_image_private(image_of(revision))
        latest_ready = data["properties"].get("latestReadyRevisionName")
        traffic, labels, weights = [], {}, {}
        for entry in data["properties"]["configuration"]["ingress"].get("traffic") or []:
            name = entry.get("revisionName") or (latest_ready if entry.get("latestRevision") else None)
            weight = int(entry.get("weight") or 0)
            traffic.append({"revision": name, "weight": weight, "label": entry.get("label"),
                            "latestRevision": bool(entry.get("latestRevision"))})
            if entry.get("label"):
                labels[entry["label"]] = name
            weights[name] = weights.get(name, 0) + weight
        return cls(app, data, revisions, traffic, labels, weights)

    @property
    def fqdn(self) -> str:
        return self.data["properties"]["configuration"]["ingress"]["fqdn"]

    @property
    def production_url(self) -> str:
        return f"https://{self.fqdn}"

    def label_url(self, label: str) -> str:
        host, domain = self.fqdn.split(".", 1)
        return f"https://{host}---{label}.{domain}"

    def short(self, revision: str | None) -> str:
        return (revision or "-").removeprefix(f"{self.app.name}--")

    def active(self, revision: str | None) -> bool:
        return bool(revision) and bool(self.revisions.get(revision, {}).get("properties", {}).get("active"))

    def stable(self) -> str:
        serving = [name for name, weight in self.weights.items() if weight > 0]
        if len(serving) != 1:
            split = ", ".join(f"{self.short(n)} {w}%" for n, w in self.weights.items() if w > 0) or "no revision"
            raise ReleaseError(f"Traffic is split ({split}). Finish the current release with promote, abort, or "
                               "rollback, or set 100% on one revision in the portal, before starting another.")
        return serving[0]

    def previous(self) -> str | None:
        previous = self.labels.get("previous")
        return previous if self.active(previous) and previous != self.stable() else None

    def describe(self, revision: str) -> dict:
        props = self.revisions.get(revision, {}).get("properties", {})
        return {"revision": revision, "image": image_of(self.revisions.get(revision, {})),
                "commit": commit_of(self.revisions.get(revision, {})), "createdTime": props.get("createdTime")}

    def traffic_summary(self) -> list[dict]:
        return [{"revision": t["revision"], "weight": t["weight"], "label": t["label"]} for t in self.traffic]


def connect() -> ContainerApp:
    subscription = (os.environ.get("AZURE_SUBSCRIPTION_ID") or azd_values().get("AZURE_SUBSCRIPTION_ID")
                    or arm_session()["subscription"])
    name = setting("API_APP_NAME")
    keep_private(subscription, "<subscription>")
    keep_private(name, "<app>")
    return ContainerApp(subscription, setting("AZURE_RESOURCE_GROUP"), name)


# ---------------------------------------------------------------------------------------------------------------------
# Records: progress for the presenter, JSON for the release record, Markdown for the GitHub job summary
# ---------------------------------------------------------------------------------------------------------------------

def source() -> str:
    if os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return "terminal"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    ms: float = 0.0


class Record:
    current: "Record | None" = None  # the step in progress, finished as failed if an Azure call stops it

    def __init__(self, command: str, title: str):
        self.command = command
        self.title = title
        self.started = utc_now()
        self.data: dict = {"schema": RECORD_SCHEMA, "command": command, "title": title, "status": "running",
                           "startedAt": iso(self.started), "source": source(), "events": [], "checks": [],
                           "measurements": {}}
        Record.current = self
        print(f"\n{title}")

    def note(self, message: str) -> None:
        print(f"  · {message}", flush=True)
        self.data["events"].append({"at": iso(utc_now()), "message": message})

    def checks(self, where: str, checks: list[Check]) -> bool:
        for check in checks:
            print(f"    {'✓' if check.ok else '✗'} {check.name:<16} {check.detail}", flush=True)
            self.data["checks"].append({"where": where, "name": check.name, "ok": check.ok, "detail": check.detail,
                                        "ms": round(check.ms)})
        return all(c.ok for c in checks)

    def finish(self, ok: bool, outcome: str) -> int:
        Record.current = None
        finished = utc_now()
        self.data.update(status="pass" if ok else "fail", outcome=outcome, finishedAt=iso(finished),
                         seconds=round((finished - self.started).total_seconds(), 1))
        print(f"{'✓' if ok else '✗'} {outcome}\n", flush=True)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{self.started:%Y%m%dT%H%M%S}-{self.command}.json"
        path.write_text(public(json.dumps(self.data, indent=2)), encoding="utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(public(self.markdown()))
        return 0 if ok else 1

    def markdown(self) -> str:
        lines = [f"### {'✅' if self.data['status'] == 'pass' else '❌'} {self.title}", "", self.data.get("outcome", ""), ""]
        if self.data.get("evidence"):
            lines += ["Evidence from the candidate's live logs:", ""] + [f"- {e}" for e in self.data["evidence"]] + [""]
        if self.data["checks"]:
            lines += ["| Where | Check | Result | Detail |", "| --- | --- | --- | --- |"]
            lines += [f"| {c['where']} | {c['name']} | {'pass' if c['ok'] else 'FAIL'} | {c['detail']} |" for c in self.data["checks"]]
            lines.append("")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------------------
# Probes and the smoke test
# ---------------------------------------------------------------------------------------------------------------------

class ProductionProbe(threading.Thread):
    """Calls the production URL on a fixed interval while a step runs: the users' view of the release."""

    def __init__(self, url: str, interval: float = 1.0):
        super().__init__(daemon=True)
        self.url, self.interval = url, interval
        self.results: list[tuple[float, int, str, float]] = []
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            response = http("GET", f"{self.url}/api/meta", timeout=5)
            build = (response.json() or {}).get("buildSha", "") if response.status == 200 else ""
            self.results.append((time.time(), response.status, build, response.ms))
            self._stop_event.wait(self.interval)

    def stop(self) -> dict:
        self._stop_event.set()
        self.join(timeout=10)
        ok = [r for r in self.results if r[1] == 200]
        builds: list[dict] = []
        for at, status, build, _ in ok:
            if not builds or builds[-1]["build"] != build:
                builds.append({"build": build, "firstSeen": iso(datetime.fromtimestamp(at, timezone.utc))})
        latencies = sorted(r[3] for r in ok)
        return {"probes": len(self.results), "ok": len(ok), "failed": len(self.results) - len(ok),
                "availability": round(100 * len(ok) / len(self.results), 2) if self.results else None,
                "p95Ms": round(latencies[int(0.95 * (len(latencies) - 1))]) if latencies else None,
                "failures": [{"at": iso(datetime.fromtimestamp(at, timezone.utc)), "status": status}
                             for at, status, _, _ in self.results if status != 200][:20],
                "builds": builds}


def smoke(base: str, bearer: str, *, label: str, expect_commit: str | None = None) -> list[Check]:
    """Use the API like a person would. Stops at the first failure that makes later checks meaningless."""
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str, response: Response | None = None) -> bool:
        checks.append(Check(name, ok, detail, response.ms if response else 0.0))
        return ok

    r = http("GET", f"{base}/health/ready")
    if not add("ready", r.status == 200, f"/health/ready {r.outcome}", r):
        return checks

    r = http("GET", f"{base}/api/meta")
    meta = r.json() or {}
    build = meta.get("buildSha", "?")
    ok = r.status == 200 and meta.get("contractVersion") == CONTRACT and meta.get("authMode") == "EasyAuth"
    detail = f"build {build[:12]}, contract {meta.get('contractVersion')}, auth {meta.get('authMode')}"
    if expect_commit:
        ok = ok and build == expect_commit
        detail += " (matches the release commit)" if build == expect_commit else f" (expected {expect_commit[:12]})"
    add("build", ok, detail, r)

    r = http("GET", f"{base}/api/me")
    add("sign-in required", r.status in (401, 403, 302), f"/api/me without a token: {r.outcome}", r)

    r = http("GET", f"{base}/api/me", bearer=bearer)
    me = r.json() or {}
    roles = set(me.get("roles") or [])
    # Roles only: the caller's name and ids identify an account, and this detail ends up in release records.
    if not add("signed in", r.status == 200 and {"Requester", "Approver"} <= roles,
               f"HTTP {r.status}: roles {', '.join(sorted(roles)) or 'none'}", r):
        return checks

    categories = http("GET", f"{base}/api/categories", bearer=bearer).json() or []
    departments = [d["id"] for d in (http("GET", f"{base}/api/departments", bearer=bearer).json() or [])]
    if not categories or not departments:
        add("submit", False, "the API returned no categories or departments")
        return checks
    key = f"release-check-{label}-{utc_now():%Y%m%dT%H%M%S}"
    request = {
        "title": f"Release check {label}"[:120],
        "description": "Synthetic request created by the release gate to check submit, read, the self-approval "
                       "guard, and audit history on this revision.",
        "category": categories[0]["id"],
        "departmentId": "OPS" if "OPS" in departments else departments[0],
        "priority": "Normal",
    }
    first = http("POST", f"{base}/api/requests", bearer=bearer, body=request, headers={"Idempotency-Key": key})
    created = first.json() or {}
    if not add("submit", first.status == 201 and bool(created.get("id")), f"HTTP {first.status}: {created.get('id') or first.text()}", first):
        return checks
    request_id = created["id"]
    retry = http("POST", f"{base}/api/requests", bearer=bearer, body=request, headers={"Idempotency-Key": key})
    add("retry is safe", retry.status == 200 and (retry.json() or {}).get("id") == request_id,
        f"same Idempotency-Key: HTTP {retry.status}, {(retry.json() or {}).get('id')}", retry)

    r = http("GET", f"{base}/api/requests/{request_id}", bearer=bearer)
    detail = r.json() or {}
    permissions = detail.get("permissions") or {}
    add("read", r.status == 200 and detail.get("title") == request["title"]
        and permissions.get("canDecide") is False and permissions.get("decideBlockedReason") == "self_approval",
        f"HTTP {r.status}: {detail.get('status')}, canDecide={permissions.get('canDecide')} "
        f"({permissions.get('decideBlockedReason')})", r)

    # Attachments live in Blob storage, a dependency the readiness probe does not check.
    content = f"Release check {label} at {utc_now():%Y-%m-%dT%H:%M:%SZ}\n".encode()
    boundary = f"release-check-{os.urandom(8).hex()}"
    form = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="release-check.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    upload = http("POST", f"{base}/api/requests/{request_id}/attachments", bearer=bearer, raw=form,
                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    attachment = upload.json() or {}
    download = http("GET", f"{base}{attachment['downloadUrl']}", bearer=bearer) if upload.status == 201 and attachment.get("downloadUrl") else None
    same = download is not None and download.status == 200 and download.body == content
    if same:
        detail = f"upload {upload.outcome}, download {download.outcome}, {len(content)} bytes identical"
    elif download is None:
        detail = f"upload {upload.outcome}: {upload.text(160)}"
    else:
        detail = f"upload {upload.outcome}, download {download.outcome}" + (" but the bytes differ" if download.status == 200 else "")
    add("attachment", same, detail, upload)

    r = http("POST", f"{base}/api/requests/{request_id}/decisions", bearer=bearer,
             body={"outcome": "Approved", "comment": "Release gate: a requester must not approve their own request."})
    problem = r.json() or {}
    add("approval guard", r.status == 403 and problem.get("code") == "decision.self_approval",
        f"self-approval: HTTP {r.status} {problem.get('code', r.text(120))}", r)

    r = http("GET", f"{base}/api/requests/{request_id}/history", bearer=bearer)
    actions = [e.get("action") for e in (r.json() or [])] if r.status == 200 else []
    expected = ["request.created"] + (["attachment.added"] if same else [])
    add("history", r.status == 200 and all(a in actions for a in expected),
        f"HTTP {r.status}: {len(actions)} audit event(s): {', '.join(actions[:4])}", r)
    return checks


def failure_evidence(app: ContainerApp, revision: str, limit: int = 6) -> list[str]:
    """Why a revision is not ready, in the platform's and the app's own words, from the live log streams (no
    Log Analytics delay). Repeated messages are counted once."""
    found: dict[str, int] = {}
    try:
        token = arm("POST", f"{app.url}/getAuthtoken").json()["properties"]["token"]
        endpoint = next((c.get("logStreamEndpoint") for replica in app.replicas(revision)
                         for c in replica.get("properties", {}).get("containers", []) if c.get("name") == CONTAINER), None)
        if not endpoint:
            return ["no replica is running, so there are no logs to read"]
        base, path = endpoint.split("/subscriptions/", 1)
        events = http("GET", f"{base}/subscriptions/{path.split('/revisions/')[0]}/eventstream?tailLines=200&follow=false",
                      bearer=token, timeout=30)
        for line in events.body.decode(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("RevisionName") == revision and event.get("Type") == "Warning":
                key = f"Azure: {event.get('Msg', '').strip()}"
                found[key] = found.get(key, 0) + 1
        console = http("GET", f"{endpoint}?tailLines=200&follow=false&output=text", bearer=token, timeout=30)
        for line in console.body.decode(errors="replace").splitlines():
            message = re.sub(r"^\S+ (stdout|stderr) [FP] ", "", line).strip()
            if re.search(r"Unhealthy|Exception|failed", message):
                key = "App: " + re.sub(r" completed after [\d.]+ms", "", message)[:240]
                found[key] = found.get(key, 0) + 1
    except (ReleaseError, KeyError, StopIteration) as error:
        return [f"log streams unavailable: {error}"]
    return [f"{text} (x{count})" if count > 1 else text for text, count in list(found.items())[:limit]]


def wait_until_ready(app: ContainerApp, revision: str, record: Record, *, timeout: float, grace: float) -> tuple[bool, str]:
    """Poll the revision and its replicas until every container is ready, or a failure is certain."""
    start = time.time()
    started_at: dict[str, float] = {}
    last = ""
    while True:
        props = app.revision(revision).get("properties", {})
        containers = [(rep.get("name", "?"), c) for rep in app.replicas(revision)
                      for c in rep.get("properties", {}).get("containers", [])]
        ready = sum(1 for _, c in containers if c.get("ready"))
        status = (f"{props.get('runningState', '?')}, health {props.get('healthState', '?')}, "
                  f"{ready}/{len(containers)} container(s) ready")
        if status != last:
            record.note(f"{time.time() - start:5.0f} s  {status}")
            last = status
        if containers and ready == len(containers) and props.get("healthState") == "Healthy" and props.get("runningState") in RUNNING:
            return True, status
        if props.get("provisioningState") == "Failed":
            return False, f"provisioning failed: {props.get('provisioningError') or props.get('runningStateDetails')}"
        if props.get("runningState") == "Failed":
            return False, f"revision failed: {props.get('runningStateDetails') or status}"
        for replica, container in containers:
            if container.get("restartCount", 0) > 0:
                return False, (f"container {container.get('name')} restarted {container['restartCount']} time(s) in "
                               f"replica {replica}: the startup or liveness probe is failing")
            if container.get("started") and not container.get("ready"):
                key = f"{replica}/{container.get('name')}"
                since = started_at.setdefault(key, container_started(container) or time.time())
                if time.time() - since > grace:
                    return False, (f"readiness probe failing: container {container.get('name')} started "
                                   f"{time.time() - since:.0f} s ago and is still not ready ({status})")
        if time.time() - start > timeout:
            return False, f"not ready after {timeout:.0f} s ({status})"
        time.sleep(5)


# ---------------------------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------------------------

def cmd_status(args) -> int:
    app = connect()
    state = State.load(app)
    labels_by_revision: dict[str, list[str]] = {}
    for label, revision in state.labels.items():
        labels_by_revision.setdefault(revision, []).append(label)
    print(f"\nRequestHub API {app.name} in {app.resource_group}")
    print(f"Production URL   {state.production_url}")
    for label in ("stable", "candidate", "previous"):
        if label in state.labels:
            print(f"{label.capitalize():<16} {state.label_url(label)}")
    rows = sorted(state.revisions.values(), key=lambda r: r.get("properties", {}).get("createdTime", ""), reverse=True)
    rows.sort(key=lambda r: not r.get("properties", {}).get("active"))  # active revisions (stable, previous, candidate) first
    print(f"\n{'REVISION':<24} {'LABEL':<10} {'TRAFFIC':>7}  {'ACTIVE':<6} {'STATE':<10} {'HEALTH':<9} {'REPLICAS':>8}  "
          f"{'BUILD':<9} CREATED (UTC)")
    for revision in rows[: args.limit]:
        props = revision.get("properties", {})
        name = revision["name"]
        created = parse_time(props.get("createdTime"))
        print(f"{state.short(name):<24} {','.join(labels_by_revision.get(name, [])) or '-':<10} "
              f"{state.weights.get(name, 0):>6}%  {'yes' if props.get('active') else 'no':<6} "
              f"{props.get('runningState', '?'):<10} {props.get('healthState', '?'):<9} {props.get('replicas', 0):>8}  "
              f"{commit_of(revision)[:7] or '?':<9} {f'{created:%Y-%m-%d %H:%M}' if created else ''}")
    return 0


def revision_suffix(now: datetime) -> str:
    """run<number> in GitHub Actions (matches the run), t<MMDDhhmmss> from a terminal. No hyphens: Azure's system
    logs cut a revision name at the first hyphen of its suffix, which would break log queries by revision."""
    if os.environ.get("GITHUB_RUN_NUMBER"):
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        return f"run{os.environ['GITHUB_RUN_NUMBER']}" + (f"x{attempt}" if attempt != "1" else "")
    return f"t{now:%m%d%H%M%S}"


def pin_digest(image: str) -> str:
    """Resolve a tag to its digest so a revision always runs exactly the bytes that were tested."""
    if "@sha256:" in image:
        return image
    registry, _, repository = image.partition("/")
    if not registry.endswith(".azurecr.io"):
        raise ReleaseError(f"{image} is not pinned. Pass an image by digest (<image>@sha256:...).")
    name, _, tag = repository.rpartition(":") if ":" in repository else (repository, "", "latest")
    digest = az("acr", "repository", "show", "--name", registry.split(".")[0], "--image", f"{name}:{tag}",
                "--query", "digest", "--output", "tsv")
    return f"{registry}/{name}@{digest}"


def cmd_deploy(args) -> int:
    record = Record("deploy", "Deploy a candidate revision (no traffic)")
    app = connect()
    state = State.load(app)
    stable = state.stable()
    previous = state.previous()
    leftover = state.labels.get("candidate")
    if leftover and leftover != stable:
        record.note(f"Removing the unfinished candidate {state.short(leftover)} first")
        app.patch(traffic_body(stable, previous))
        if state.active(leftover):
            app.deactivate(leftover)
        state = State.load(app)
    stable_revision = state.revisions[stable]
    image = pin_digest(args.image or image_of(stable_revision))
    commit = args.commit or ("" if args.image else commit_of(stable_revision))
    now = utc_now()
    suffix = revision_suffix(now)
    candidate = f"{app.name}--{suffix}"

    template = without_nulls(copy.deepcopy(stable_revision["properties"]["template"]))
    template["revisionSuffix"] = suffix
    container = container_of(template)
    container["image"] = image
    # BUILD_SHA is left out so /api/meta reports the commit baked into the image, not a deploy-time claim.
    env = [e for e in container.get("env", []) if e.get("name") != "BUILD_SHA"
           and not e.get("name", "").startswith(("Faults__", "RELEASE_"))]
    env += [{"name": "RELEASE_SOURCE", "value": source()}]
    if commit:
        env += [{"name": "RELEASE_COMMIT", "value": commit}]
    if args.fault == "fail-readiness":
        expires = iso(now + timedelta(minutes=FAULT_MINUTES))
        env += [{"name": "Faults__FailReadiness", "value": "true"}, {"name": "Faults__ExpiresAtUtc", "value": expires}]
        record.note(f"Fault injected: the readiness probe fails until {expires} (then it switches itself off)")
    container["env"] = env

    record.data.update(stable=state.describe(stable), trafficBefore=state.traffic_summary(),
                       candidate={"revision": candidate, "image": image, "commit": commit, "fault": args.fault,
                                  "url": state.label_url("candidate")})
    record.note(f"Stable revision {state.short(stable)} keeps 100% of traffic")
    record.note(f"Candidate {suffix}: image {image.split('/')[-1][:60]}")
    # One atomic change: the new template creates the candidate, and the traffic list pins 100% on stable and gives the
    # candidate its label with 0%, so the platform never routes a user to it.
    body = traffic_body(stable, previous, candidate)
    body["properties"]["template"] = template
    seconds = app.patch(body)
    state = State.load(app)
    record.data["trafficAfter"] = state.traffic_summary()
    record.data["candidate"]["createdTime"] = state.revisions.get(candidate, {}).get("properties", {}).get("createdTime")
    record.data["measurements"]["secondsToCreate"] = round(seconds, 1)
    if state.weights.get(candidate, 0) != 0 or state.weights.get(stable) != 100:
        return record.finish(False, "Traffic did not stay on the stable revision; check the app in the portal.")
    record.note(f"Candidate URL {state.label_url('candidate')}")
    _write_output("candidate", state.short(candidate))
    return record.finish(True, f"Candidate {suffix} created with 0% of traffic; {state.short(stable)} still serves 100%.")


def cmd_gate(args) -> int:
    record = Record("gate", "Gate: readiness, smoke test, and bake on the candidate's own URL")
    app = connect()
    state = State.load(app)
    candidate = state.labels.get("candidate")
    if not candidate:
        return record.finish(False, "No candidate revision to check. Run deploy first.")
    bearer = api_token()  # acquired up front: CI sign-in tokens are short-lived
    record.data.update(candidate=state.describe(candidate), stable=state.describe(state.stable()))
    users = ProductionProbe(state.production_url)
    users.start()
    try:
        ok, outcome = run_gate(app, state, candidate, bearer, record, args)
    finally:
        record.data["measurements"]["production"] = users.stop()
    _note_users(record)
    return record.finish(ok, outcome)


def run_gate(app: ContainerApp, state: State, candidate: str, bearer: str, record: Record, args) -> tuple[bool, str]:
    revision = state.revisions[candidate]
    name = state.short(candidate)
    url = state.label_url("candidate")
    created = parse_time(revision["properties"].get("createdTime")) or utc_now()
    record.note(f"Waiting for {name} to become ready (timeout {args.ready_timeout} s)")
    ready, reason = wait_until_ready(app, candidate, record, timeout=args.ready_timeout, grace=args.not_ready_grace)
    verdict = round((utc_now() - created).total_seconds(), 1)
    if not ready:
        record.data["measurements"]["secondsToDetectFailure"] = verdict
        probe = http("GET", f"{url}/health/ready", timeout=10)
        record.note(f"Candidate URL /health/ready: {probe.outcome}")
        record.data["evidence"] = failure_evidence(app, candidate)
        for line in record.data["evidence"]:
            record.note(f"Evidence · {line}")
        record.checks("candidate", [Check("ready", False, reason)])
        return False, f"Candidate {name} failed the gate {verdict:.0f} s after it was created: {reason}. It never received traffic."
    record.data["measurements"]["secondsToReady"] = verdict
    record.note(f"Ready {verdict:.0f} s after it was created. Smoke test on {url}")
    if not record.checks("candidate", smoke(url, bearer, label=name, expect_commit=env_of(revision).get("RELEASE_COMMIT"))):
        return False, f"Candidate {name} failed the smoke test. It never received traffic."
    if args.bake > 0:
        record.note(f"Bake: calling the candidate every 5 s for {args.bake} s")
        failures, calls, end = [], 0, time.time() + args.bake
        while time.time() < end:
            for path in ("/health/ready", "/api/meta"):
                calls += 1
                response = http("GET", f"{url}{path}", timeout=10)
                if response.status != 200:
                    failures.append(f"{path} {response.outcome}")
            time.sleep(5)
        detail = f"{calls - len(failures)}/{calls} calls OK over {args.bake} s" + (f"; {failures[0]}" if failures else "")
        if not record.checks("candidate", [Check("bake", not failures, detail)]):
            return False, f"Candidate {name} failed during the bake period. It never received traffic."
    return True, f"Candidate {name} passed the gate and still has 0% of traffic."


def cmd_promote(args) -> int:
    record = Record("promote", "Promote the candidate to 100% of traffic")
    app = connect()
    state = State.load(app)
    candidate = state.labels.get("candidate")
    if not candidate:
        return record.finish(False, "No candidate revision to promote. Run deploy and gate first.")
    stable = state.stable()
    props = state.revisions[candidate]["properties"]
    if not (props.get("active") and props.get("healthState") == "Healthy" and props.get("runningState") in RUNNING):
        return record.finish(False, f"Refusing to promote {state.short(candidate)}: it is {props.get('runningState')}, "
                                    f"health {props.get('healthState')}. Run the gate.")
    retire = [name for name in state.revisions if state.active(name) and name not in (candidate, stable)]
    record.data.update(candidate=state.describe(candidate), stable=state.describe(stable), trafficBefore=state.traffic_summary())
    users = ProductionProbe(state.production_url, interval=0.25)
    users.start()
    try:
        record.note(f"Traffic: {state.short(stable)} 100% → {state.short(candidate)} 100% (one atomic change)")
        seconds = app.patch(traffic_body(candidate, stable))
        record.data["measurements"]["secondsToSwitch"] = round(seconds, 1)
        for name in retire:
            record.note(f"Deactivating {state.short(name)} (only stable and previous stay running)")
            app.deactivate(name)
        time.sleep(5)
    finally:
        record.data["measurements"]["production"] = users.stop()
    state = State.load(app)
    record.data["trafficAfter"] = state.traffic_summary()
    _note_users(record)
    ok = state.weights.get(candidate) == 100 and state.labels.get("stable") == candidate
    return record.finish(ok, f"{state.short(candidate)} is now stable with 100% of traffic in {seconds:.0f} s; "
                             f"{state.short(stable)} is previous, still running for an instant rollback." if ok
                         else "Traffic did not move as expected; run status.")


def cmd_abort(args) -> int:
    record = Record("abort", "Abort: remove the candidate, keep users on stable")
    app = connect()
    state = State.load(app)
    candidate = state.labels.get("candidate")
    stable = state.stable()
    if candidate and candidate != stable:
        record.data.update(candidate=state.describe(candidate), stable=state.describe(stable), trafficBefore=state.traffic_summary())
        record.note(f"Removing the candidate label from {state.short(candidate)} (it had {state.weights.get(candidate, 0)}% of traffic)")
        app.patch(traffic_body(stable, state.previous()))
        if state.active(candidate):
            record.note(f"Deactivating {state.short(candidate)}")
            app.deactivate(candidate)
        created = parse_time(state.revisions[candidate]["properties"].get("createdTime"))
        if created:
            record.data["measurements"]["secondsFromCandidateToRemoved"] = round((utc_now() - created).total_seconds(), 1)
    else:
        record.note("No candidate revision: nothing to remove")
    state = State.load(app)
    record.data["trafficAfter"] = state.traffic_summary()
    record.note(f"Verifying production ({state.short(stable)}, 100% of traffic)")
    ok = record.checks("production", smoke(state.production_url, api_token(), label=state.short(stable),
                                           expect_commit=commit_of(state.revisions[stable]) or None))
    return record.finish(ok, f"Users stayed on {state.short(stable)} and production passed the smoke test." if ok
                         else "Production failed the smoke test after the abort: investigate now.")


def cmd_rollback(args) -> int:
    record = Record("rollback", "Roll back to the previous revision")
    app = connect()
    state = State.load(app)
    stable = state.stable()
    target = args.to and (args.to if args.to.startswith(f"{app.name}--") else f"{app.name}--{args.to}")
    target = target or state.labels.get("previous")
    if not target or target not in state.revisions or target == stable:
        return record.finish(False, "No previous revision to roll back to. Release an earlier image instead: "
                                    "deploy --image <registry>/<repository>@sha256:<digest>, then gate and promote.")
    bearer = api_token()
    record.data.update(stable=state.describe(stable), rolledBackTo=state.describe(target), trafficBefore=state.traffic_summary())
    if not state.active(target):
        record.note(f"{state.short(target)} is inactive: activating it and waiting until it is ready")
        app.activate(target)
        ready, reason = wait_until_ready(app, target, record, timeout=args.ready_timeout, grace=args.not_ready_grace)
        if not ready:
            return record.finish(False, f"Cannot roll back: {state.short(target)} is not ready ({reason}). Users stay on {state.short(stable)}.")
    users = ProductionProbe(state.production_url, interval=0.25)
    users.start()
    try:
        record.note(f"Traffic: {state.short(stable)} 100% → {state.short(target)} 100% (one atomic change)")
        seconds = app.patch(traffic_body(target, stable))
        record.data["measurements"]["secondsToSwitch"] = round(seconds, 1)
        time.sleep(5)
    finally:
        record.data["measurements"]["production"] = users.stop()
    state = State.load(app)
    record.data["trafficAfter"] = state.traffic_summary()
    _note_users(record)
    record.note(f"Verifying production ({state.short(target)})")
    ok = record.checks("production", smoke(state.production_url, bearer, label=state.short(target),
                                           expect_commit=commit_of(state.revisions[target]) or None))
    ok = ok and state.weights.get(target) == 100
    return record.finish(ok, f"Rolled back in {seconds:.0f} s: {state.short(target)} serves 100% of traffic and passed "
                             f"the smoke test. {state.short(stable)} is kept as previous." if ok
                         else "The rollback did not verify; run status and investigate.")


def cmd_verify(args) -> int:
    app = connect()
    state = State.load(app)
    url = state.label_url(args.label) if args.label else state.production_url
    revision = state.labels.get(args.label) if args.label else state.stable()
    record = Record("verify", f"Verify {'the ' + args.label + ' revision' if args.label else 'production'} ({url})")
    if not revision:
        return record.finish(False, f"No revision has the label {args.label}.")
    record.data.update(stable=state.describe(state.stable()), url=url, revision=revision, trafficAfter=state.traffic_summary())
    ok = record.checks(args.label or "production", smoke(url, api_token(), label=state.short(revision),
                                                         expect_commit=commit_of(state.revisions[revision]) or None))
    return record.finish(ok, f"{state.short(revision)} passed the smoke test on {url}." if ok
                         else f"{state.short(revision)} failed the smoke test on {url}.")


def cmd_watch(args) -> int:
    app = connect()
    state = State.load(app)
    url = state.production_url
    print(f"Watching {url} every {args.interval:g} s (Ctrl+C to stop)")

    def describe(current: State) -> str:
        return ", ".join(f"{current.short(t['revision'])} {t['weight']}%" + (f" [{t['label']}]" if t["label"] else "")
                         for t in current.traffic)

    route = {"text": describe(state), "changed": True}

    def follow_traffic() -> None:
        while True:
            time.sleep(5)
            try:
                text = describe(State.load(app))
                if text != route["text"]:
                    route.update(text=text, changed=True)
            except Exception as error:  # keep watching users even if Azure is briefly unreachable
                route.update(text=f"(traffic unavailable: {error})", changed=True)

    threading.Thread(target=follow_traffic, daemon=True).start()
    results: list[tuple[int, float, str]] = []
    end = time.time() + args.duration if args.duration else None
    try:
        while end is None or time.time() < end:
            response = http("GET", f"{url}/api/meta", timeout=5)
            build = (response.json() or {}).get("buildSha", "") if response.status == 200 else ""
            results.append((response.status, response.ms, build))
            if route["changed"]:
                print(f"{utc_now():%H:%M:%S}  traffic → {route['text']}", flush=True)
                route["changed"] = False
            print(f"{utc_now():%H:%M:%S}  {response.status or 'ERR':>3}  {response.ms:6.0f} ms  build {build[:7] or '-'}", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    ok = [r for r in results if r[0] == 200]
    if results:
        print(f"\n{len(ok)}/{len(results)} calls succeeded ({100 * len(ok) / len(results):.1f}%), "
              f"median {statistics.median(r[1] for r in results):.0f} ms")
    return 0 if len(ok) == len(results) else 1


def cmd_record(args) -> int:
    folder = Path(args.dir)
    records = sorted((r for r in (json.loads(p.read_text(encoding="utf-8")) for p in folder.rglob("*.json")
                                  if p.name != "release-record.json") if r.get("schema") == RECORD_SCHEMA),
                     key=lambda r: r.get("startedAt", ""))
    starts = [i for i, r in enumerate(records) if r["command"] in ("deploy", "rollback")]
    records = records[starts[-1]:] if starts else records  # the latest release only
    if not records:
        print(f"No release records in {folder}")
        return 1
    build = next((json.loads(p.read_text(encoding="utf-8")) for p in folder.rglob("build.json")), None)
    by = {r["command"]: r for r in records}
    candidate = (by.get("deploy") or by.get("gate") or {}).get("candidate", {})
    passed = {command: r["status"] == "pass" for command, r in by.items()}
    if "rollback" in by:
        outcome = "Rolled back" if passed["rollback"] else "Rollback failed"
    elif "promote" in by:
        outcome = "Released" if passed["promote"] and passed.get("verify", False) else "Promotion did not verify: roll back"
    elif "gate" in by and not passed["gate"]:
        outcome = "Blocked: the candidate failed the gate and never received traffic"
    elif "gate" in by and "abort" in by:
        outcome = "Rehearsal: the candidate passed the gate and was removed; production unchanged"
    else:
        outcome = "In progress"
    origin = parse_time(candidate.get("createdTime")) or parse_time(records[0]["startedAt"])
    finished = parse_time(records[-1].get("finishedAt"))

    rows = [("Run", records[0].get("source", ""))]
    commit = (build or {}).get("commit") or candidate.get("commit")
    image = (build or {}).get("image") or candidate.get("image")
    if commit:
        rows.append(("Commit", f"`{commit}`"))
    if image:
        how = "" if not build else (" (reused: already built for this commit)" if build.get("reused") else " (built in this run)")
        rows.append(("Image", f"`{image}`{how}"))
    if candidate:
        rows.append(("Candidate", f"`{short_name(candidate.get('revision'))}`"
                     + (f", fault `{candidate['fault']}`" if candidate.get("fault") not in (None, "none") else "")))
    before = next((r.get("stable") for r in records if r.get("stable")), None)
    if before:
        rows.append(("Stable before", f"`{short_name(before.get('revision'))}`"))
    if "rollback" in by and by["rollback"].get("rolledBackTo"):
        rows.append(("Rolled back to", f"`{short_name(by['rollback']['rolledBackTo'].get('revision'))}`"))

    lines = [f"## Release record: {outcome}", "", "| | |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += ["", "### Steps", "", "| Started (UTC) | Step | Result | Seconds | Outcome |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {r['startedAt'][11:19]} | {r['command']} | {r['status']} | {r.get('seconds', '')} | {r.get('outcome', '')} |"
              for r in records]
    lines += ["", "### Measurements", ""]
    gate = by.get("gate", {}).get("measurements", {})
    if gate.get("secondsToReady") is not None:
        lines.append(f"- Candidate ready **{gate['secondsToReady']:.0f} s** after it was created.")
    if gate.get("secondsToDetectFailure") is not None:
        lines.append(f"- Failure detected **{gate['secondsToDetectFailure']:.0f} s** after the candidate was created.")
    for command in ("promote", "rollback"):
        seconds = by.get(command, {}).get("measurements", {}).get("secondsToSwitch")
        if seconds is not None:
            lines.append(f"- Traffic switch ({command}): **{seconds:.0f} s**, one atomic change.")
    verified = next((r for r in reversed(records) if r["command"] in ("verify", "rollback", "abort")), None)
    if origin and verified and verified["status"] == "pass":
        start = "candidate created" if candidate else "rollback started"
        lines.append(f"- From {start} to production verified: **{(parse_time(verified['finishedAt']) - origin).total_seconds():.0f} s**.")
    for record in records:
        users = record.get("measurements", {}).get("production")
        if users and users.get("probes"):
            builds = " → ".join(b["build"][:7] for b in users.get("builds", []))
            lines.append(f"- Users during **{record['command']}**: {users['ok']}/{users['probes']} calls to production "
                         f"succeeded ({users['availability']}%), p95 {users['p95Ms']} ms, build {builds or '-'}.")
    if origin and finished:
        lines.append(f"- Whole release: {(finished - origin).total_seconds():.0f} s.")
    evidence = by.get("gate", {}).get("evidence")
    if evidence:
        lines += ["", "### Why the candidate failed", "", "From the candidate's live logs, captured before it was removed:", ""]
        lines += [f"- {e}" for e in evidence]
    lines += ["", "### Checks", "", "| Step | Where | Check | Result | Detail |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {r['command']} | {c['where']} | {c['name']} | {'pass' if c['ok'] else 'FAIL'} | {c['detail']} |"
              for r in records for c in r.get("checks", [])]
    after = next((r.get("trafficAfter") for r in reversed(records) if r.get("trafficAfter")), None)
    if after:
        lines += ["", "### Traffic after the release", "", "| Revision | Label | Traffic |", "| --- | --- | --- |"]
        lines += [f"| `{short_name(t['revision'])}` | {t.get('label') or ''} | {t['weight']}% |" for t in after]
    markdown = public("\n".join(lines) + "\n")
    (folder / "release-record.md").write_text(markdown, encoding="utf-8")
    (folder / "release-record.json").write_text(public(json.dumps({"schema": RECORD_SCHEMA, "outcome": outcome, "build": build,
                                                                   "records": records}, indent=2)), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(markdown)
    print(markdown)
    return 0


def _note_users(record: Record) -> None:
    users = record.data["measurements"].get("production") or {}
    if users.get("probes"):
        record.note(f"Users meanwhile: {users['ok']}/{users['probes']} calls to production succeeded "
                    f"({users['availability']}%)")


def _write_output(name: str, value: str) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    utf8_stdout()
    if IN_ACTIONS:
        sys.stdout, sys.stderr = PublicStream(sys.stdout), PublicStream(sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = commands.add_parser("status", help="show revisions, labels, traffic, health, and URLs")
    p.add_argument("--limit", type=int, default=8, help="number of most recent revisions to list (default 8)")
    p.set_defaults(func=cmd_status)

    p = commands.add_parser("deploy", help="add a candidate revision with no traffic")
    p.add_argument("--image", help="image to release, by digest or ACR tag (resolved to its digest). "
                                   "Default: the stable revision's image")
    p.add_argument("--commit", help="git commit the image was built from; the gate checks that /api/meta reports it")
    p.add_argument("--fault", choices=["none", "fail-readiness"], default="none",
                   help="fail-readiness makes the candidate's readiness probe fail (expires after 30 minutes)")
    p.set_defaults(func=cmd_deploy)

    p = commands.add_parser("gate", help="readiness, smoke test, and bake on the candidate's own URL")
    p.add_argument("--ready-timeout", type=int, default=300, help="seconds the candidate gets to become ready (default 300)")
    p.add_argument("--not-ready-grace", type=int, default=60,
                   help="seconds a started container may stay not ready before the gate fails (default 60)")
    p.add_argument("--bake", type=int, default=60, help="seconds to keep calling the candidate after the smoke test (default 60)")
    p.set_defaults(func=cmd_gate)

    p = commands.add_parser("promote", help="move 100%% of traffic to the candidate")
    p.set_defaults(func=cmd_promote)

    p = commands.add_parser("abort", help="remove the candidate without touching traffic, then verify production")
    p.set_defaults(func=cmd_abort)

    p = commands.add_parser("rollback", help="move 100%% of traffic back to the previous revision")
    p.add_argument("--to", help="revision name or suffix to roll back to (default: the revision labelled previous)")
    p.add_argument("--ready-timeout", type=int, default=300, help="seconds an inactive target gets to become ready (default 300)")
    p.add_argument("--not-ready-grace", type=int, default=60, help="seconds a started container may stay not ready (default 60)")
    p.set_defaults(func=cmd_rollback)

    p = commands.add_parser("verify", help="smoke-test the production URL, or a label's URL")
    p.add_argument("--label", choices=["stable", "candidate", "previous"], help="test this label's URL instead of production")
    p.set_defaults(func=cmd_verify)

    p = commands.add_parser("watch", help="call the production URL every second and show where traffic goes")
    p.add_argument("--interval", type=float, default=1.0, help="seconds between calls (default 1)")
    p.add_argument("--duration", type=int, default=0, help="stop after this many seconds (default: until Ctrl+C)")
    p.set_defaults(func=cmd_watch)

    p = commands.add_parser("record", help="combine the JSON records of one release into a release record")
    p.add_argument("--dir", default=str(OUT), help=f"folder with the JSON records (default {OUT.relative_to(SOLUTION.parents[1])})")
    p.set_defaults(func=cmd_record)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ReleaseError as error:
        print(f"\nerror: {error}", file=sys.stderr)
        if Record.current:
            Record.current.finish(False, f"Stopped: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
