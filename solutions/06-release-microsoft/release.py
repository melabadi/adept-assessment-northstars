"""Release RequestHub on Azure Container Apps without exposing users to an untested revision.

The API container app runs in multiple-revision mode. A release never replaces the revision users are on. It adds a
candidate revision that receives no traffic, checks it on its own URL, and moves traffic only when a person decides to.
Revision labels describe the state at any moment, and each label has its own URL
(https://<app>---<label>.<environment domain>):

  stable      the revision users get: 100% of traffic
  candidate   the revision being released: 0% of traffic until a person promotes it
  previous    the revision that was stable before the last promotion, kept running for an instant rollback

In Azure, this script runs as five Container Apps jobs that share one image (infra/jobs.bicep):

  release    Started for every build pushed to the registry (Event Grid and a Logic App pass the image's digest), or
             by a person with Run now (the newest build, requesthub-api:main). Deploys the build as a candidate, gates
             it, and removes it if the gate fails. A pushed build that already serves users, or is already the
             candidate, is skipped.
  promote    A person's go: checks the candidate again on its own URL, then moves 100% of traffic to it in one change.
  abort      A person's no-go: removes the candidate and keeps users on stable.
  rollback   Moves 100% of traffic back to the previous revision, which is still running.
  drill      Rehearses a bad release: the stable build again, with a readiness probe that fails. It succeeds when the
             gate blocks the candidate.

Each step prints its progress. In a job, it also prints one JSON line per step (RELEASE-RECORD {...}): Log Analytics
keeps them, and the "RequestHub release records" workbook shows them. Only builds of requesthub-api in this solution's
registry are released, whoever names the image.

Commands (every one of them also works from a terminal signed in with `az login`):

  status     Revisions, labels, traffic, health, build, and URLs.
  release    Deploy a build as a candidate, gate it, and remove it if the gate fails.
  drill      The stable build as a candidate with a readiness fault that expires after 30 minutes; the gate must catch it.
  deploy     Add a candidate: the stable revision's exact configuration with a new image pinned by digest, no traffic.
  gate       Wait until the candidate is ready, smoke-test it on its own URL, then watch it for a bake period.
  promote    Check the candidate again on its own URL, then move 100% of traffic to it and verify production.
  abort      Remove the candidate (label, then revision) without touching traffic, then verify production.
  rollback   Move 100% of traffic back to the previous revision, then verify production.
  verify     Smoke-test the production URL, or one label's URL with --label.
  watch      Call the production URL every second, as a user would, and show where Azure routes traffic.

The smoke test uses the API the way people do: readiness, build provenance (/api/meta must report the commit the build
was made from), sign-in enforcement, then it submits a request (twice with the same Idempotency-Key: one request),
reads it back, attaches a file and downloads it again (Blob storage, which the readiness probe does not check), tries to
approve its own request (the API must refuse with decision.self_approval), and reads the request's audit history.

One release step at a time: release waits for another release step to finish; the other commands refuse to start
while one runs.

Settings come from environment variables (infra/jobs.bicep sets them on the jobs), or from this solution's azd
environment after `azd up`: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, API_APP_NAME, API_IDENTIFIER_URI, and
AZURE_CONTAINER_REGISTRY_ENDPOINT. In a job, Azure calls use the job's managed identity; in a terminal, your Azure CLI
sign-in.

Examples:
  python release.py status
  python release.py release                          # the newest build: requesthub-api:main
  python release.py release --image <registry>.azurecr.io/requesthub-api:<commit>
  python release.py promote                          # or: python release.py abort
  python release.py drill
  python release.py rollback
  python release.py watch
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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from azd_env import SOLUTION, azd_values, setting, utf8_stdout

API_VERSION = "2025-07-01"  # Microsoft.App GA version for revisions, labels, traffic, and jobs
ARM = "https://management.azure.com"
CONTRACT = "requesthub.v1"
CONTAINER = "api"
REPOSITORY = "requesthub-api"
OUT = SOLUTION / "out" / "release"
RECORD_SCHEMA = "requesthub-release/2"
RECORD_PREFIX = "RELEASE-RECORD "
FAULT_MINUTES = 30  # every fault expires; after this the injected readiness failure switches itself off
RUNNING = {"Running", "RunningAtMaxScale"}
EXECUTING = {"Running", "Processing"}
COMMIT = re.compile(r"[0-9a-f]{40}")
JOB_EXECUTION = os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME", "")
IN_JOB = bool(JOB_EXECUTION or os.environ.get("RELEASE_STEP"))


class ReleaseError(Exception):
    """A release step cannot continue. The message says why and what to do."""


# ---------------------------------------------------------------------------------------------------------------------
# Small helpers: time, tokens (managed identity in a job, Azure CLI in a terminal), HTTP
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


def managed_identity() -> bool:
    """True inside a Container Apps job or app with a managed identity: tokens come from its local endpoint."""
    return bool(os.environ.get("IDENTITY_ENDPOINT") and os.environ.get("IDENTITY_HEADER"))


_tokens: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def access_token(*, resource: str | None = None, scope: str | None = None) -> str:
    """A token from the managed identity (in a job) or the Azure CLI sign-in, cached until five minutes before expiry."""
    key = scope or resource or ""
    with _token_lock:
        cached = _tokens.get(key)
        if cached and cached[1] - time.time() > 300:
            return cached[0]
        if managed_identity():
            query = {"api-version": "2019-08-01", "resource": resource or (scope or "").rsplit("/", 1)[0]}
            if os.environ.get("AZURE_CLIENT_ID"):
                query["client_id"] = os.environ["AZURE_CLIENT_ID"]
            request = urllib.request.Request(f"{os.environ['IDENTITY_ENDPOINT']}?{urllib.parse.urlencode(query)}",
                                             headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            token, expires = data["access_token"], float(data.get("expires_on") or 0)
        else:
            args = ["account", "get-access-token", "--output", "json"]
            args += ["--scope", scope] if scope else ["--resource", resource or ""]
            data = json.loads(az(*args))
            token, expires = data["accessToken"], float(data.get("expires_on") or 0)
        _tokens[key] = (token, expires or time.time() + 1800)
        return token


def token_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def api_token() -> str:
    """Token for the RequestHub API: app-only for the job's identity, delegated for a person signed in to the CLI."""
    uri = setting("API_IDENTIFIER_URI")
    if not managed_identity() and "scp" in token_claims(access_token(resource=f"{ARM}/")):
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
    request.add_header("User-Agent", "requesthub-release/2.0")
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
# Azure Resource Manager: the container app and the release jobs
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
        self.subscription = subscription
        self.resource_group = resource_group
        self.group_url = f"{ARM}/subscriptions/{subscription}/resourceGroups/{resource_group}"
        self.url = f"{self.group_url}/providers/Microsoft.App/containerApps/{name}"

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


def short_image(image: str) -> str:
    """repository@digest, without the registry's host name."""
    return image.split("/", 1)[-1]


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
        """A revision by its suffix (r1029141500): the full name starts with the app's name and its unique token."""
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
        return {"revision": self.short(revision), "image": short_image(image_of(self.revisions.get(revision, {}))),
                "commit": commit_of(self.revisions.get(revision, {})), "createdTime": props.get("createdTime")}

    def traffic_summary(self) -> list[dict]:
        return [{"revision": self.short(t["revision"]), "weight": t["weight"], "label": t["label"]} for t in self.traffic]


def subscription_id() -> str:
    return (os.environ.get("AZURE_SUBSCRIPTION_ID") or azd_values().get("AZURE_SUBSCRIPTION_ID")
            or az("account", "show", "--query", "id", "--output", "tsv"))


def connect() -> ContainerApp:
    return ContainerApp(subscription_id(), setting("AZURE_RESOURCE_GROUP"), setting("API_APP_NAME"))


def busy_executions(app: ContainerApp) -> list[str]:
    """Release steps running now in other job executions. Jobs carry the tag requesthub-release=<step>."""
    host = os.environ.get("HOSTNAME", "")
    busy = []
    jobs = arm("GET", f"{app.group_url}/providers/Microsoft.App/jobs").json().get("value", [])
    if IN_JOB and not any((job.get("tags") or {}).get("requesthub-release") for job in jobs):
        # A job always sees itself; seeing none means its identity cannot read jobs. Fail closed rather than run
        # a second release step at the same time as another.
        raise ReleaseError("This job's identity cannot see the release jobs. Grant it Container Apps Jobs Reader on "
                           "the resource group (infra/main.bicep does).")
    for job in jobs:
        step = (job.get("tags") or {}).get("requesthub-release")
        if not step:
            continue
        for execution in arm("GET", f"{ARM}{job['id']}/executions").json().get("value", []):
            name = execution.get("name", "")
            status = execution.get("properties", {}).get("status")
            if status in EXECUTING and name != JOB_EXECUTION and not (host and host.startswith(name)):
                busy.append(f"{step} ({status.lower()})")
    return busy


# ---------------------------------------------------------------------------------------------------------------------
# The registry and the repository: which build an image is
# ---------------------------------------------------------------------------------------------------------------------

MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])


def registry_token(host: str, repository: str) -> str:
    """A pull token for one repository, from an Entra ID token (the identity needs AcrPull on the registry)."""
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    exchange = http("POST", f"https://{host}/oauth2/exchange", headers=form, raw=urllib.parse.urlencode(
        {"grant_type": "access_token", "service": host, "access_token": access_token(resource=f"{ARM}/")}).encode())
    refresh = (exchange.json() or {}).get("refresh_token")
    if not refresh:
        raise ReleaseError(f"The registry refused the sign-in ({exchange.outcome}). The identity needs AcrPull on it.")
    issued = http("POST", f"https://{host}/oauth2/token", headers=form, raw=urllib.parse.urlencode(
        {"grant_type": "refresh_token", "service": host, "scope": f"repository:{repository}:pull",
         "refresh_token": refresh}).encode())
    token = (issued.json() or {}).get("access_token")
    if not token:
        raise ReleaseError(f"The registry refused a pull token for {repository} ({issued.outcome}).")
    return token


def resolve_image(reference: str) -> tuple[str, str]:
    """The image pinned by digest, and the commit baked into it (its BUILD_SHA), read from the registry itself."""
    host, _, path = reference.partition("/")
    if not host.endswith(".azurecr.io"):
        raise ReleaseError(f"{reference} is not in an Azure container registry.")
    if "@" in path:
        repository, _, ref = path.partition("@")
    elif ":" in path:
        repository, _, ref = path.rpartition(":")
    else:
        repository, ref = path, "latest"
    token = registry_token(host, repository)
    accept = {"Accept": MANIFEST_TYPES}
    found = http("GET", f"https://{host}/v2/{repository}/manifests/{ref}", bearer=token, headers=accept)
    if found.status != 200:
        raise ReleaseError(f"{repository}:{ref} is not in the registry ({found.outcome}).")
    digest = found.headers.get("docker-content-digest") or ref
    manifest = found.json() or {}
    if manifest.get("manifests"):  # a multi-platform index: the linux/amd64 image is the one Container Apps runs
        entry = next((m for m in manifest["manifests"] if (m.get("platform") or {}).get("architecture") == "amd64"),
                     manifest["manifests"][0])
        manifest = http("GET", f"https://{host}/v2/{repository}/manifests/{entry['digest']}", bearer=token,
                        headers=accept).json() or {}
    commit = ""
    config = (manifest.get("config") or {}).get("digest")
    if config:
        blob = http("GET", f"https://{host}/v2/{repository}/blobs/{config}", bearer=token)
        if blob.status in (301, 302, 303, 307, 308) and blob.headers.get("location"):
            blob = http("GET", blob.headers["location"])  # blobs are served from storage through a signed URL
        env = ((blob.json() or {}).get("config") or {}).get("Env") or []
        commit = next((e.split("=", 1)[1] for e in env if e.startswith("BUILD_SHA=")), "")
    return f"{host}/{repository}@{digest}", "" if commit == "local" else commit


def tag_commit(reference: str) -> str:
    """The commit in a tag such as requesthub-api:<40 hex characters>, else ''."""
    path = reference.split("/", 1)[-1]
    tag = path.rsplit(":", 1)[-1] if "@" not in path and ":" in path else ""
    return tag if COMMIT.fullmatch(tag) else ""


def require_own_build(reference: str) -> None:
    """Only builds of the API in this solution's registry are released, whoever names the image: a person, or the push
    trigger, whose event anyone holding the Logic App's URL could forge."""
    host, _, path = reference.partition("/")
    repository = re.split(r"[@:]", path, maxsplit=1)[0]
    if host.lower() != setting("AZURE_CONTAINER_REGISTRY_ENDPOINT").lower() or repository != REPOSITORY:
        raise ReleaseError(f"{(path or 'The image')[:72]} is not a build of {REPOSITORY} in this solution's registry: "
                           "not released.")


# ---------------------------------------------------------------------------------------------------------------------
# Records: progress for people, one JSON line per step for Log Analytics and the workbook
# ---------------------------------------------------------------------------------------------------------------------

def source() -> str:
    return f"job {JOB_EXECUTION}" if JOB_EXECUTION else ("job" if IN_JOB else "terminal")


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
        print(f"\n{title}", flush=True)

    def note(self, message: str) -> None:
        print(f"  · {message}", flush=True)
        self.data["events"].append({"at": iso(utc_now()), "message": message})

    def checks(self, where: str, checks: list[Check]) -> bool:
        for check in checks:
            print(f"    {'✓' if check.ok else '✗'} {check.name:<16} {check.detail}", flush=True)
            self.data["checks"].append({"where": where, "name": check.name, "ok": check.ok, "detail": check.detail,
                                        "ms": round(check.ms)})
        return all(c.ok for c in checks)

    def finish(self, ok: bool, outcome: str, *, status: str | None = None) -> int:
        Record.current = None
        finished = utc_now()
        self.data.update(status=status or ("pass" if ok else "fail"), outcome=outcome, finishedAt=iso(finished),
                         seconds=round((finished - self.started).total_seconds(), 1))
        print(f"{'✓' if ok else '✗'} {outcome}\n", flush=True)
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{self.started:%Y%m%dT%H%M%S}-{self.command}.json").write_text(json.dumps(self.data, indent=2),
                                                                                  encoding="utf-8")
        except OSError:
            pass  # a read-only file system: the JSON line below is the record
        if IN_JOB:
            line = {k: v for k, v in self.data.items() if k != "events"}
            line.update(execution=JOB_EXECUTION, step=os.environ.get("RELEASE_STEP", ""))
            print(RECORD_PREFIX + json.dumps(line, separators=(",", ":")), flush=True)
        return 0 if ok else 1


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


def smoke(base: str, bearer: str, *, label: str, expect_commit: str | None = None,
          expect_from: str = "the release commit") -> list[Check]:
    """Use the API like a person would. Stops at the first failure that makes later checks meaningless.

    expect_commit is the build the target must report; expect_from names where it comes from in the record.
    """
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
        detail += f" (matches {expect_from})" if build == expect_commit else f" (expected {expect_commit[:12]})"
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
        "description": "Synthetic request created by a release check to test submit, read, an attachment, the "
                       "self-approval guard, and audit history on this revision.",
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
             body={"outcome": "Approved", "comment": "Release check: a requester must not approve their own request."})
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
                message = event.get("Msg", "").strip()
                if message.startswith("Target resource doesn't exist"):
                    continue  # a transient event while the revision is created, not a reason it fails
                key = f"Azure: {message}"
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


def _note_users(record: Record) -> None:
    users = record.data["measurements"].get("production") or {}
    if users.get("probes"):
        record.note(f"Users meanwhile: {users['ok']}/{users['probes']} calls to production succeeded "
                    f"({users['availability']}%)")


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
    busy = busy_executions(app)
    print(f"\nRelease steps running now: {', '.join(busy) if busy else 'none'}")
    return 0


def deploy_candidate(app: ContainerApp, image_ref: str | None, commit: str | None, fault: str, prefix: str) -> int:
    """Add a candidate revision with no traffic. Revision suffixes have no hyphens (r1029141500): Azure's system logs
    cut a revision name at the first hyphen of its suffix, which would break log queries by revision."""
    record = Record("deploy", "Deploy a candidate revision (no traffic)")
    state = State.load(app)
    stable = state.stable()
    previous = state.previous()
    leftover = state.labels.get("candidate")
    if leftover and leftover != stable:
        record.note(f"Replacing the waiting candidate {state.short(leftover)}, which was never promoted")
        app.patch(traffic_body(stable, previous))
        if state.active(leftover):
            app.deactivate(leftover)
        state = State.load(app)
    stable_revision = state.revisions[stable]
    if image_ref:
        require_own_build(image_ref)
    image, baked = resolve_image(image_ref or image_of(stable_revision))
    commit = commit or baked or ("" if image_ref else commit_of(stable_revision))
    now = utc_now()
    suffix = f"{prefix}{now:%m%d%H%M%S}"
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
    if fault == "fail-readiness":
        expires = iso(now + timedelta(minutes=FAULT_MINUTES))
        env += [{"name": "Faults__FailReadiness", "value": "true"}, {"name": "Faults__ExpiresAtUtc", "value": expires}]
        record.note(f"Fault injected: the readiness probe fails until {expires} (then it switches itself off)")
    container["env"] = env

    record.data.update(stable=state.describe(stable), trafficBefore=state.traffic_summary(),
                       candidate={"revision": suffix, "image": short_image(image), "commit": commit, "fault": fault})
    record.note(f"Stable revision {state.short(stable)} keeps 100% of traffic")
    record.note(f"Candidate {suffix}: {short_image(image)[:72]}" + (f", commit {commit[:12]}" if commit else ""))
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
    return record.finish(True, f"Candidate {suffix} created with 0% of traffic; {state.short(stable)} still serves 100%.")


def cmd_deploy(args) -> int:
    return deploy_candidate(connect(), args.image, args.commit, args.fault, "t")


def cmd_gate(args) -> int:
    record = Record("gate", "Gate: readiness, smoke test, and bake on the candidate's own URL")
    app = connect()
    state = State.load(app)
    candidate = state.labels.get("candidate")
    if not candidate:
        return record.finish(False, "No candidate revision to check. Run release or deploy first.")
    bearer = api_token()
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
    record.note(f"Ready {verdict:.0f} s after it was created. Smoke test on the candidate's own URL")
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
    return True, f"Candidate {name} passed the gate and still has 0% of traffic. It waits for a person's go or no-go."


def wait_for_turn(app: ContainerApp, record: Record, seconds: int) -> bool:
    """Wait until no other release step runs, for at most this many seconds."""
    end = time.time() + seconds
    while True:
        busy = busy_executions(app)
        if not busy:
            return True
        if time.time() > end:
            return False
        record.note(f"Waiting for another release step to finish: {', '.join(busy)}")
        time.sleep(15)


def cmd_release(args) -> int:
    app = connect()
    pushed = bool(os.environ.get("IMAGE")) and not args.image  # started by the push trigger for one pushed build
    record = Record("release", "Release a build: candidate, gate, and removal if it fails")
    reference = args.image or os.environ.get("IMAGE") or f"{setting('AZURE_CONTAINER_REGISTRY_ENDPOINT')}/{REPOSITORY}:main"
    require_own_build(reference)
    if not wait_for_turn(app, record, args.wait):
        return record.finish(False, f"Another release step was still running after {args.wait} s; nothing was released.")
    image, baked = resolve_image(reference)
    pushed_commit = os.environ.get("COMMIT", "") if pushed else ""
    commit = args.commit or (pushed_commit if COMMIT.fullmatch(pushed_commit) else "") or tag_commit(reference) or baked
    state = State.load(app)
    stable = state.stable()
    candidate = state.labels.get("candidate")
    stable_commit = commit_of(state.revisions[stable])
    record.data.update(trigger="push" if pushed else "person", image=short_image(image), commit=commit,
                       stable=state.describe(stable))
    record.note(f"Build {commit[:12] or '(no commit)'}: {short_image(image)[:72]}, "
                + ("pushed to the registry" if pushed else "started by a person"))
    if baked and commit and baked != commit:
        return record.finish(False, f"The image reports build {baked[:12]}, not {commit[:12]}: not released.")
    if pushed and not args.force and commit:
        reason = None
        if commit == stable_commit:
            reason = f"Build {commit[:7]} already serves users ({state.short(stable)}): nothing to release."
        elif candidate and candidate != stable and commit == commit_of(state.revisions.get(candidate, {})):
            reason = f"Build {commit[:7]} is already the candidate ({state.short(candidate)}): it waits for a person."
        if reason:
            return record.finish(True, reason, status="skipped")
    record.finish(True, f"Releasing build {commit[:7] or short_image(image)[:40]}.")
    if deploy_candidate(app, image, commit, "none", "r") != 0:
        return 1
    if cmd_gate(args) == 0:
        return 0
    cmd_abort(args)
    return 1


def cmd_drill(args) -> int:
    app = connect()
    record = Record("drill", "Drill: rehearse a bad release")
    busy = busy_executions(app)
    if busy:
        return record.finish(False, f"A release step is running ({', '.join(busy)}). Run the drill when it finishes.")
    record.finish(True, "Deploying the stable build again with a readiness probe that fails; the gate must catch it.")
    if deploy_candidate(app, None, None, "fail-readiness", "d") != 0:
        return 1
    caught = cmd_gate(args) != 0
    cleaned = cmd_abort(args) == 0
    outcome = Record("drill-result", "Drill result")
    if caught:
        return outcome.finish(cleaned, "The gate blocked the bad candidate, which never received traffic, and it was "
                                       "removed." if cleaned else "The gate blocked the bad candidate, but production "
                                       "failed its check afterwards: investigate now.")
    return outcome.finish(False, "The gate did not catch the injected fault. The candidate was removed; fix the gate.")


def refuse_while_busy(app: ContainerApp, record: Record) -> int | None:
    busy = busy_executions(app)
    if busy:
        return record.finish(False, f"A release step is running ({', '.join(busy)}). Try again when it finishes.")
    return None


def cmd_promote(args) -> int:
    record = Record("promote", "Go: promote the candidate to 100% of traffic")
    app = connect()
    refused = refuse_while_busy(app, record)
    if refused is not None:
        return refused
    state = State.load(app)
    candidate = state.labels.get("candidate")
    stable = state.stable()
    if not candidate or candidate == stable:
        return record.finish(False, "No candidate revision to promote. Run the release job first.")
    revision = state.revisions[candidate]
    name = state.short(candidate)
    props = revision["properties"]
    if env_of(revision).get("Faults__FailReadiness") == "true":
        return record.finish(False, f"Refusing to promote {name}: it is a drill candidate with an injected fault.")
    if not (props.get("active") and props.get("healthState") == "Healthy" and props.get("runningState") in RUNNING):
        return record.finish(False, f"Refusing to promote {name}: it is {props.get('runningState')}, "
                                    f"health {props.get('healthState')}. Run the release job again.")
    bearer = api_token()
    record.data.update(candidate=state.describe(candidate), stable=state.describe(stable), trafficBefore=state.traffic_summary())
    record.note(f"Checking {name} again on its own URL before moving traffic")
    if not record.checks("candidate", smoke(state.label_url("candidate"), bearer, label=name,
                                            expect_commit=commit_of(revision) or None, expect_from=f"{name}'s commit")):
        return record.finish(False, f"{name} failed the check on its own URL; traffic was not moved.")
    retire = [n for n in state.revisions if state.active(n) and n not in (candidate, stable)]
    users = ProductionProbe(state.production_url, interval=0.25)
    users.start()
    try:
        record.note(f"Traffic: {state.short(stable)} 100% → {name} 100% (one atomic change)")
        seconds = app.patch(traffic_body(candidate, stable))
        record.data["measurements"]["secondsToSwitch"] = round(seconds, 1)
        for other in retire:
            record.note(f"Deactivating {state.short(other)} (only stable and previous stay running)")
            app.deactivate(other)
        time.sleep(5)
    finally:
        record.data["measurements"]["production"] = users.stop()
    state = State.load(app)
    record.data["trafficAfter"] = state.traffic_summary()
    _note_users(record)
    if state.weights.get(candidate) != 100 or state.labels.get("stable") != candidate:
        return record.finish(False, "Traffic did not move as expected; run status.")
    record.note(f"Verifying production ({name})")
    ok = record.checks("production", smoke(state.production_url, bearer, label=name,
                                           expect_commit=commit_of(revision) or None, expect_from=f"{name}'s commit"))
    return record.finish(ok, f"{name} is now stable with 100% of traffic, switched in {seconds:.0f} s and verified; "
                             f"{state.short(stable)} is previous, still running for an instant rollback." if ok
                         else f"{name} serves users but failed the production check: roll back now.")


def cmd_abort(args) -> int:
    record = Record("abort", "Abort: remove the candidate, keep users on stable")
    app = connect()
    refused = refuse_while_busy(app, record)
    if refused is not None:
        return refused
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
                                           expect_commit=commit_of(state.revisions[stable]) or None,
                                           expect_from=f"{state.short(stable)}'s commit"))
    return record.finish(ok, f"Users stayed on {state.short(stable)} and production passed the smoke test." if ok
                         else "Production failed the smoke test after the abort: investigate now.")


def cmd_rollback(args) -> int:
    record = Record("rollback", "Roll back to the previous revision")
    app = connect()
    refused = refuse_while_busy(app, record)
    if refused is not None:
        return refused
    state = State.load(app)
    stable = state.stable()
    target = args.to and (args.to if args.to.startswith(f"{app.name}--") else f"{app.name}--{args.to}")
    target = target or state.labels.get("previous")
    if not target or target not in state.revisions or target == stable:
        return record.finish(False, "No previous revision to roll back to. Release an earlier build instead: "
                                    "release --image REGISTRY/requesthub-api:COMMIT, then promote.")
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
                                           expect_commit=commit_of(state.revisions[target]) or None,
                                           expect_from=f"{state.short(target)}'s commit"))
    ok = ok and state.weights.get(target) == 100
    return record.finish(ok, f"Rolled back in {seconds:.0f} s: {state.short(target)} serves 100% of traffic and passed "
                             f"the smoke test. {state.short(stable)} is kept as previous." if ok
                         else "The rollback did not verify; run status and investigate.")


def cmd_verify(args) -> int:
    app = connect()
    state = State.load(app)
    url = state.label_url(args.label) if args.label else state.production_url
    revision = state.labels.get(args.label) if args.label else state.stable()
    where = f"the {args.label} label's URL" if args.label else "production"
    record = Record("verify", f"Verify {where}")
    if not IN_JOB:
        print(f"  {url}")
    if not revision:
        return record.finish(False, f"No revision has the label {args.label}.")
    record.data.update(stable=state.describe(state.stable()), revision=state.short(revision), trafficAfter=state.traffic_summary())
    ok = record.checks(args.label or "production", smoke(url, api_token(), label=state.short(revision),
                                                         expect_commit=commit_of(state.revisions[revision]) or None,
                                                         expect_from=f"{state.short(revision)}'s commit"))
    return record.finish(ok, f"{state.short(revision)} passed the smoke test on {where}." if ok
                         else f"{state.short(revision)} failed the smoke test on {where}.")


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


def main() -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    def gate_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ready-timeout", type=int, default=300, help="seconds the candidate gets to become ready (default 300)")
        p.add_argument("--not-ready-grace", type=int, default=60,
                       help="seconds a started container may stay not ready before the gate fails (default 60)")
        p.add_argument("--bake", type=int, default=60, help="seconds to keep calling the candidate after the smoke test (default 60)")

    p = commands.add_parser("status", help="show revisions, labels, traffic, health, URLs, and running release steps")
    p.add_argument("--limit", type=int, default=8, help="number of revisions to list, active ones first (default 8)")
    p.set_defaults(func=cmd_status)

    p = commands.add_parser("release", help="deploy a build as a candidate, gate it, and remove it if the gate fails")
    p.add_argument("--image", help="image to release, by tag or digest: a build of requesthub-api in this solution's "
                                   "registry. Default: IMAGE (set by the push trigger), else the newest build, "
                                   "requesthub-api:main")
    p.add_argument("--commit", help="commit the image was built from. Default: COMMIT, the tag, or the image's BUILD_SHA")
    p.add_argument("--wait", type=int, default=900, help="seconds to wait for another release step to finish (default 900)")
    p.add_argument("--force", action="store_true", help="release a pushed build even if it would be skipped")
    gate_options(p)
    p.set_defaults(func=cmd_release)

    p = commands.add_parser("drill", help="rehearse a bad release: the stable build with a readiness probe that fails")
    gate_options(p)
    p.set_defaults(func=cmd_drill)

    p = commands.add_parser("deploy", help="add a candidate revision with no traffic")
    p.add_argument("--image", help="image to deploy, by tag or digest (pinned to its digest): a build of requesthub-api "
                                   "in this solution's registry. Default: the stable revision's image")
    p.add_argument("--commit", help="commit the image was built from; the gate checks that /api/meta reports it. "
                                    "Default: the image's BUILD_SHA")
    p.add_argument("--fault", choices=["none", "fail-readiness"], default="none",
                   help="fail-readiness makes the candidate's readiness probe fail (expires after 30 minutes)")
    p.set_defaults(func=cmd_deploy)

    p = commands.add_parser("gate", help="readiness, smoke test, and bake on the candidate's own URL")
    gate_options(p)
    p.set_defaults(func=cmd_gate)

    p = commands.add_parser("promote", help="check the candidate again, move 100%% of traffic to it, verify production")
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
