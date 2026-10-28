"""RequestHub load test: an authenticated request-and-approval journey (Test phase, Microsoft track).

Azure Load Testing runs this Locust script on its test engines (Locust 2.33.2 on Python 3.9). The same file runs on your
machine against a local RequestHub while you develop it:

    locust -f loadtest/locustfile.py --headless -u 4 -r 2 -t 1m -H http://localhost:5080

Virtual users
  Requester  submits a synthetic request, lists their own requests, and opens the one they submitted. Every fifth
             iteration it also checks two denials: an invalid token gets 401, and a request from a department it has
             no access to gets 403.
  Approver   lists the team queue, opens a request this run submitted, and approves or rejects some of them.
Requesters and approvers are two different identities, so the API's rule that nobody decides their own request holds.
Approvers only decide requests this run submitted; the seeded demo data is never changed.

Sign-in (RH_AUTH)
  managed-identity  Azure Load Testing: tokens for the two managed identities from the engine's instance metadata
                    service (IMDS). No secret exists anywhere.
  persona           a local RequestHub with development sign-in: the X-RequestHub-User header picks a persona.

Settings (environment variables; Azure Load Testing passes them from requesthub-journey.yaml)
  LOCUST_HOST, LOCUST_USERS, LOCUST_SPAWN_RATE, LOCUST_RUN_TIME   standard Locust settings
  RH_AUTH               managed-identity or persona (default persona)
  API_SCOPE             RequestHub's application ID URI; managed-identity tokens are issued for it
  REQUESTER_CLIENT_ID   client id of the requester managed identity
  APPROVER_CLIENT_ID    client id of the approver managed identity
  REQUESTER_PERSONA     local requester persona (default u-ben, who owns no seeded request)
  APPROVER_PERSONA      local approver persona (default u-chloe)
  PACING_SECONDS        each virtual user starts at most one iteration every this many seconds (default 6)
  DECIDE_PERCENT        share of submitted requests that an approver decides (default 50)
  DEPARTMENTS           departments the synthetic requests are routed to (default IT,FAC)
  DENIED_REQUEST        a request the requester may not open, for the 403 check (default REQ-1018, a Finance request)
  DATASET_REQUESTS      extra synthetic requests created before the measured load starts (default 0)
  CLEANUP               before, after, both, or none: when the requester identity deletes the requests it submitted
                        earlier (default before, so every run starts from the same data)

Request names in the results: submit, my-requests, open-request, team-queue, decide, denied-invalid-token,
denied-other-department. The pass/fail criteria in requesthub-journey.yaml refer to these names.
"""
# No `from __future__` import: Azure Load Testing adds lines before this script, and such imports must come first.
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from typing import Optional

from gevent.lock import Semaphore
from locust import HttpUser, constant_pacing, events, task

log = logging.getLogger("requesthub-load-test")

AUTH = os.environ.get("RH_AUTH", "persona")
API_SCOPE = os.environ.get("API_SCOPE", "")
REQUESTER_CLIENT_ID = os.environ.get("REQUESTER_CLIENT_ID", "")
APPROVER_CLIENT_ID = os.environ.get("APPROVER_CLIENT_ID", "")
REQUESTER_PERSONA = os.environ.get("REQUESTER_PERSONA", "u-ben")
APPROVER_PERSONA = os.environ.get("APPROVER_PERSONA", "u-chloe")
PACING_SECONDS = float(os.environ.get("PACING_SECONDS", "6"))
DECIDE_PERCENT = float(os.environ.get("DECIDE_PERCENT", "50"))
DEPARTMENTS = [d.strip() for d in os.environ.get("DEPARTMENTS", "IT,FAC").split(",") if d.strip()]
DENIED_REQUEST = os.environ.get("DENIED_REQUEST", "REQ-1018")
DATASET_REQUESTS = int(os.environ.get("DATASET_REQUESTS", "0"))
CLEANUP = os.environ.get("CLEANUP", "before").lower()
RUN_TAG = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

CATEGORY = {"IT": "equipment", "FAC": "facilities", "FIN": "purchase", "HR": "people", "OPS": "access"}
ITEMS = ["Replacement laptop", "Second monitor", "Docking station", "Headset", "Standing desk", "Desk lamp",
         "Keyboard and mouse", "Meeting room screen", "Badge holder", "Webcam"]

# Requests this engine submitted and nobody decided yet; approvers take them from here.
submitted: deque = deque(maxlen=5000)
_tokens: dict = {}
_token_lock = Semaphore()


def managed_identity_token(client_id: str) -> str:
    """Access token for RequestHub from the engine's managed identity, cached until five minutes before it expires."""
    with _token_lock:
        token, expires_on = _tokens.get(client_id, ("", 0))
        if token and expires_on - 300 > time.time():
            return token
        query = urllib.parse.urlencode({"api-version": "2018-02-01", "resource": API_SCOPE, "client_id": client_id})
        request = urllib.request.Request(f"http://169.254.169.254/metadata/identity/oauth2/token?{query}", headers={"Metadata": "true"})
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    body = json.load(response)
                _tokens[client_id] = (body["access_token"], int(body["expires_on"]))
                return body["access_token"]
            except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
                log.warning("Managed identity token for %s failed (attempt %s): %s", client_id, attempt, exc)
                time.sleep(2 * attempt)
        raise RuntimeError(f"no managed identity token for client id {client_id}; is the identity assigned to the engines?")


def auth_headers(role: str) -> dict:
    """Headers that sign in as the requester or the approver."""
    if AUTH == "managed-identity":
        client_id = REQUESTER_CLIENT_ID if role == "requester" else APPROVER_CLIENT_ID
        return {"Authorization": "Bearer " + managed_identity_token(client_id)}
    return {"X-RequestHub-User": REQUESTER_PERSONA if role == "requester" else APPROVER_PERSONA}


def synthetic_request() -> dict:
    department = random.choice(DEPARTMENTS)
    return {
        "title": f"Load test: {random.choice(ITEMS)}",
        "description": f"Synthetic request created by the RequestHub load test (run {RUN_TAG}). No action needed.",
        "category": CATEGORY.get(department, "equipment"),
        "departmentId": department,
        "priority": "Normal",
    }


def call(host: str, method: str, path: str, body: Optional[dict] = None) -> tuple:
    """A request as the requester identity outside the measured load (setup and cleanup are not part of the results)."""
    data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(host.rstrip("/") + path, data=data, method=method,
                                     headers={**auth_headers("requester"), "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")


def cleanup(host: str) -> None:
    status, body = call(host, "POST", "/api/admin/load-test/cleanup")
    if status == 200:
        log.info("Cleanup: deleted %s requests owned by %s", body["deleted"], ", ".join(body["owners"]))
    else:
        log.warning("Cleanup refused (HTTP %s): %s. Earlier load-test requests stay until an admin cleans them up.", status, body)


@events.test_start.add_listener
def on_test_start(environment, **_kwargs) -> None:
    log.info("RequestHub load test against %s: sign-in %s, pacing %ss, decide %s%%, cleanup %s, extra dataset %s",
             environment.host, AUTH, PACING_SECONDS, DECIDE_PERCENT, CLEANUP, DATASET_REQUESTS)
    if CLEANUP in ("before", "both"):
        cleanup(environment.host)
    for _ in range(DATASET_REQUESTS):
        status, _body = call(environment.host, "POST", "/api/requests", synthetic_request())
        if status != 201:
            log.warning("Could not create a dataset request (HTTP %s)", status)
            break


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs) -> None:
    if CLEANUP in ("after", "both"):
        cleanup(environment.host)


class Requester(HttpUser):
    wait_time = constant_pacing(PACING_SECONDS)

    def on_start(self) -> None:
        self.iterations = 0

    @task
    def submit_and_follow_up(self) -> None:
        self.iterations += 1
        headers = auth_headers("requester")
        with self.client.post("/api/requests", json=synthetic_request(), name="submit", catch_response=True,
                              headers={**headers, "Idempotency-Key": str(uuid.uuid4())}) as response:
            if response.status_code != 201:
                response.failure(f"expected 201, got {response.status_code}")
                return
            request_id = response.json()["id"]
        self.client.get("/api/requests?scope=mine&pageSize=20", headers=headers, name="my-requests")
        self.client.get(f"/api/requests/{request_id}", headers=headers, name="open-request")
        submitted.append(request_id)
        if self.iterations % 5 == 1:
            self.check_denials(headers)

    def check_denials(self, headers: dict) -> None:
        with self.client.get("/api/requests?scope=mine", name="denied-invalid-token", catch_response=True, allow_redirects=False,
                             headers={"Authorization": "Bearer not-a-valid-token"}) as response:
            if response.status_code == 401:
                response.success()
            else:
                response.failure(f"an invalid token must get 401, got {response.status_code}")
        with self.client.get(f"/api/requests/{DENIED_REQUEST}", name="denied-other-department", catch_response=True,
                             headers=headers) as response:
            if response.status_code == 403:
                response.success()
            else:
                response.failure(f"a request outside the caller's access must get 403, got {response.status_code}")


class Approver(HttpUser):
    wait_time = constant_pacing(PACING_SECONDS)

    @task
    def review_queue(self) -> None:
        headers = auth_headers("approver")
        self.client.get("/api/requests?scope=queue&status=Submitted&pageSize=20", headers=headers, name="team-queue")
        try:
            request_id = submitted.popleft()
        except IndexError:
            return
        self.client.get(f"/api/requests/{request_id}", headers=headers, name="open-request")
        if random.uniform(0, 100) < DECIDE_PERCENT:
            outcome = "Rejected" if random.random() < 0.2 else "Approved"
            decision = {"outcome": outcome, "comment": f"{outcome} by the load-test approver identity."}
            self.client.post(f"/api/requests/{request_id}/decisions", json=decision, name="decide",
                             headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
