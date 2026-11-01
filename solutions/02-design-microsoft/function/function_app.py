"""Azure Functions app of the Design · Microsoft solution (Python, Flex Consumption, inside the solution's VNet).

Routes (all under /api):
  POST github/webhook          The GitHub App's webhook. Anonymous: GitHub's signature (X-Hub-Signature-256, made with
                               the webhook secret) is the authentication. Ignores a repeated delivery
                               (X-GitHub-Delivery), an Issue from anyone but the repository's owner, members, and
                               collaborators, and a second question about the same issue. Then it queues an advisor run
                               or a standards run, and answers within GitHub's 10 seconds.
  GET  github/setup            Connect GitHub (function key required): the app-manifest page with a one-time state.
  GET  github/setup/complete   GitHub's redirect once the app exists: stores the app id, private key, and webhook
                               secret in Key Vault, nothing else. Answers 409 once an app is connected.
  GET  github/status           Whether GitHub is connected, and how (function key required; no secret is returned).
Queues (in the Function's own storage, reached through a private endpoint):
  advisor-runs                 One message per question. advise() asks the profile's agent, runs the gate, and only
                               then writes the ADR draft and comments (advisor_core/runs.py).
  standards-runs               One message per merged change to the standards. publish_standards() re-indexes,
                               publishes the agents if their definition changed, and starts an evaluation.

Each step logs one line to Application Insights that starts with the run's id; the issue comment shows the same id.
Nothing here logs a token, a key, a secret, a webhook body, the question, the answer, or what GitHub returns when the
app is created.
"""
import hmac
import json
import logging
import os
import re
import secrets as token_generator
import threading
import time
from datetime import datetime, timezone

import azure.functions as func

from advisor_core import foundry, github, runs, setup_flow, webhook

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger("advisor")
logging.getLogger("azure").setLevel(logging.WARNING)  # the SDKs' request logs name storage hosts; not needed
STATE_CONTAINER = "advisor-state"
ADVISOR_QUEUE = "advisor-runs"
STANDARDS_QUEUE = "standards-runs"
RUN_ID = re.compile(r"[0-9a-f]{12}")
_cache: dict = {}
_lock = threading.Lock()


class NotConnected(runs.StepError):
    """GitHub is not connected yet: no app and no token in Key Vault."""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"app setting {name} is missing")
    return value


def cached(key, ttl: float, produce):
    """A value kept for ttl seconds (shared by the requests one instance serves)."""
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[1] < ttl:
            return hit[0]
    value = produce()
    with _lock:
        _cache[key] = (value, time.monotonic())
    return value


def forget(*keys) -> None:
    with _lock:
        for key in keys:
            _cache.pop(key, None)


def credential():
    def make():
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return cached("credential", float("inf"), make)


def secret(name: str) -> str | None:
    """A Key Vault secret, read through the vault's private endpoint. Kept 5 minutes; a missing one is rechecked
    after 30 seconds, so a new connection works almost at once."""
    key = ("secret", name)
    with _lock:
        hit = _cache.get(key)
    if hit is not None and time.monotonic() - hit[1] < (300 if hit[0] is not None else 30):
        return hit[0]
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets import SecretClient
    try:
        value = SecretClient(env("KEY_VAULT_URI"), credential()).get_secret(name).value
    except ResourceNotFoundError:
        value = None
    with _lock:
        _cache[key] = (value, time.monotonic())
    return value


def store_secret(name: str, value: str) -> None:
    from azure.keyvault.secrets import SecretClient
    SecretClient(env("KEY_VAULT_URI"), credential()).set_secret(name, value, content_type="text/plain")
    forget(("secret", name))


def new_id() -> str:
    return token_generator.token_hex(6)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- markers: handled deliveries and asked issues
def state_container():
    from azure.storage.blob import ContainerClient
    return ContainerClient(account_url=env("STORAGE_BLOB_ENDPOINT"), container_name=STATE_CONTAINER, credential=credential())


def claim(name: str, data: dict) -> bool:
    """Create a marker blob once. False when it already exists: the delivery or the question was already handled."""
    from azure.core.exceptions import ResourceExistsError
    try:
        state_container().upload_blob(name, json.dumps(data), overwrite=False)
        return True
    except ResourceExistsError:
        return False


def release(*names: str) -> None:
    """Remove markers again when the work could not start, so GitHub's redelivery can retry it."""
    for name in names:
        try:
            state_container().delete_blob(name)
        except Exception:
            log.warning("could not remove marker %s", name)


def read_marker(name: str) -> tuple[dict | None, str | None]:
    """A marker's content and ETag, or (None, None) when there is none."""
    from azure.core.exceptions import ResourceNotFoundError
    try:
        download = state_container().get_blob_client(name).download_blob()
    except ResourceNotFoundError:
        return None, None
    return json.loads(download.readall()), download.properties.etag


def swap_marker(name: str, data: dict, etag: str) -> bool:
    """Replace a marker only if nobody changed it since it was read (its ETag). False when someone did."""
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
    try:
        state_container().get_blob_client(name).upload_blob(json.dumps(data), overwrite=True, etag=etag,
                                                             match_condition=MatchConditions.IfNotModified)
        return True
    except (ResourceModifiedError, ResourceNotFoundError):
        return False


def issue_marker(issue) -> str:
    return f"issues/{int(issue)}.json"


def reserve_issue(issue: int, run_id: str, delivery: str) -> str | None:
    """Reserve the issue for one advisor run: None when reserved, otherwise why not. A question gets one run; a new
    run may take over only when the last one couldn't finish (runs.retryable), which is how a maintainer asks again:
    remove the design-advisor label and add it back."""
    name, record = issue_marker(issue), {"state": "queued", "run": run_id, "delivery": delivery, "since": time.time(),
                                         "at": now()}
    if claim(name, record):
        return None
    current, etag = read_marker(name)
    if current is None:  # released in between
        return None if claim(name, record) else f"issue #{issue} already has an advisor run"
    if not runs.retryable(current, time.time()):
        return f"issue #{issue} already has an advisor run ({current.get('state', 'answered')})"
    return None if swap_marker(name, record, etag) else f"issue #{issue} already has an advisor run"


def mark_issue(issue: int, run_id: str, state: str) -> bool:
    """Record the run's state on its issue's marker, only while the marker names this run: False when a newer run took
    the issue over. A lost marker is written again."""
    name = issue_marker(issue)
    record = {"state": state, "run": run_id, "since": time.time(), "at": now()}
    current, etag = read_marker(name)
    if current is None:
        return claim(name, record)
    if current.get("run") != run_id:
        return False
    return swap_marker(name, dict(current, **record), etag)


def begin_run(issue: int, run_id: str) -> bool:
    """Whether a queued advisor run may start: only when its issue's marker names this run and still says queued, which
    the webhook wrote when it queued the run. The swap to running is conditional, so a second copy of the message, or
    one the webhook never wrote, never asks the agent or writes to GitHub."""
    name = issue_marker(issue)
    current, etag = read_marker(name)
    if current is None or current.get("run") != run_id or current.get("state") != "queued":
        return False
    return swap_marker(name, dict(current, state="running", since=time.time(), at=now()), etag)


def enqueue(queue: str, message: dict) -> None:
    """Add a run to one of the Function's queues (Base64, as the queue trigger reads it)."""
    from azure.storage.queue import QueueClient, TextBase64EncodePolicy
    QueueClient(account_url=env("STORAGE_QUEUE_ENDPOINT"), queue_name=queue, credential=credential(),
                message_encode_policy=TextBase64EncodePolicy()).send_message(json.dumps(message))


def respond(data, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype="application/json")


def page(result: tuple[int, str]) -> func.HttpResponse:
    status, text = result
    return func.HttpResponse(text, status_code=status, mimetype="text/html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- GitHub and Azure clients
def connected() -> bool:
    return bool(secret("github-app-id") or secret("github-token"))


def github_client() -> github.GitHub:
    """GitHub App installation token (default) or a fine-grained token (fallback), both read from Key Vault."""
    repo = env("GITHUB_REPOSITORY")
    personal = secret("github-token")
    if personal:
        return github.GitHub(repo, lambda: personal)
    app_id, private_key = secret("github-app-id"), secret("github-app-private-key")
    if not (app_id and private_key):
        raise NotConnected("GitHub is not connected yet: open the setup link that azd printed")
    tokens = cached(("installation", app_id), float("inf"),
                    lambda: github.TokenCache(lambda: github.installation_token(repo, app_id, private_key)))
    return github.GitHub(repo, tokens)


def project_client():
    def make():
        from azure.ai.projects import AIProjectClient
        return AIProjectClient(endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), credential=credential())
    return cached("project", float("inf"), make)


def standards_snapshot(search_filter: str | None = None) -> dict:
    """The index as it is now: read on every check (two cheap queries), so a re-indexed standard counts at once."""
    from advisor_core import standards
    return standards.snapshot(env("SEARCH_ENDPOINT"), credential(), env("SEARCH_INDEX", "architecture-standards"),
                              search_filter)


def agent_scope(name: str, version: str) -> tuple[str, str]:
    """(profile, scope filter) recorded on an agent version when it was published; versions never change."""
    from advisor_core import agents
    return cached(("scope", name, version), 3600, lambda: agents.scope_filter_of(project_client(), name, version))


def ask_agent(question: str, profile: str) -> dict:
    return foundry.ask(env("FOUNDRY_PROJECT_ENDPOINT"), f"{env('ADVISOR_AGENT_NAME', 'architecture-advisor')}-{profile}",
                       question, lambda: credential().get_token(foundry.SCOPE).token)


def advisor_tools() -> runs.AdvisorTools:
    index = env("SEARCH_INDEX", "architecture-standards")
    return runs.AdvisorTools(
        ask=ask_agent,
        check=lambda response, job: runs.check_answer(response, job, scope_of=agent_scope, snapshot=standards_snapshot,
                                                      index=index),
        github=github_client)


def publish_agents(spec: dict) -> dict:
    """Update each profile's knowledge base, then publish the agents: a new version only if the definition changed."""
    from advisor_core import agents, knowledge
    if spec["knowledge"] == "foundry-iq":
        knowledge.sync(env("SEARCH_ENDPOINT"), credential(), spec, spec["search"]["index"])
    return agents.publish(project_client(), spec, env("FOUNDRY_MODEL_DEPLOYMENT"), env("SEARCH_ENDPOINT"))


def standards_tools() -> runs.StandardsTools:
    from advisor_core import evaluation, standards
    return runs.StandardsTools(
        github=github_client,
        reindex=lambda docs, spec: standards.sync(env("SEARCH_ENDPOINT"), credential(), spec["search"]["index"], docs, spec),
        publish=publish_agents,
        evaluate=lambda spec, cases, published, label: evaluation.start(
            project_client(), env("FOUNDRY_MODEL_DEPLOYMENT"), cases, env("SEARCH_ENDPOINT"), credential(),
            spec["search"]["index"], published, label))


# ---------------------------------------------------------------- GitHub webhook
@app.route(route="github/webhook", methods=["POST"])
def github_webhook(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_body()
    secret_value = secret("github-webhook-secret")
    if not secret_value:
        return respond({"error": "GitHub is not connected yet"}, 503)
    if not webhook.verify_signature(secret_value, body, req.headers.get("X-Hub-Signature-256")):
        return respond({"error": "invalid signature"}, 401)
    delivery, event = req.headers.get("X-GitHub-Delivery", ""), req.headers.get("X-GitHub-Event", "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", delivery):
        return respond({"error": "missing delivery id"}, 400)
    marker = f"deliveries/{delivery}.json"
    if not claim(marker, {"event": event, "at": now()}):
        log.info("delivery %s ignored: already handled", delivery)
        return respond({"result": "duplicate delivery ignored"})
    payload = json.loads(body)
    decision = webhook.classify(event, payload, env("GITHUB_REPOSITORY"))
    if decision["route"] == "ignore":
        log.info("delivery %s (%s) ignored: %s", delivery, event, decision["reason"])
        return respond({"result": "ignored", "reason": decision["reason"]})
    run_id = new_id()
    try:
        if decision["route"] == "advisor":
            issue = decision["issue"]
            busy = reserve_issue(issue, run_id, delivery)
            if busy:
                log.info("delivery %s ignored: %s", delivery, busy)
                return respond({"result": busy})
            try:
                enqueue(ADVISOR_QUEUE, {"id": run_id, **{k: decision[k] for k in ("issue", "title", "profile", "question")}})
            except Exception:
                release(issue_marker(issue))
                raise
            log.info("advisor run %s: #%s queued (issues.%s, %s profile)", run_id, issue, payload.get("action"),
                     decision["profile"])
            return respond({"result": f"advisor run {run_id} queued for issue #{issue}"}, 202)
        enqueue(STANDARDS_QUEUE, {"id": run_id, "sha": decision["sha"], "files": decision["files"]})
        log.info("standards run %s: %s queued (push to the default branch, %d file(s) in the solution)", run_id,
                 decision["sha"][:7], len(decision["files"]))
        return respond({"result": f"standards run {run_id} queued for {decision['sha'][:7]}"}, 202)
    except Exception as exc:  # the type only: a storage error's message names hosts
        release(marker)
        log.error("delivery %s: could not queue the run: %s", delivery, type(exc).__name__)
        return respond({"error": "could not queue the run; redeliver to retry"}, 500)


# ---------------------------------------------------------------- the advisor run (from the queue)
def advisor_job(message: func.QueueMessage) -> dict | None:
    """The queued question, or None if the message isn't one the webhook wrote."""
    try:
        job = message.get_json()
        valid = (isinstance(job, dict) and RUN_ID.fullmatch(str(job.get("id", ""))) and int(job["issue"]) > 0
                 and job.get("profile") in webhook.PROFILES and isinstance(job.get("question"), str) and job["question"].strip())
    except (ValueError, TypeError, KeyError):
        valid = False
    return job if valid else None


@app.queue_trigger(arg_name="message", queue_name=ADVISOR_QUEUE, connection="AzureWebJobsStorage")
def advise(message: func.QueueMessage) -> None:
    job = advisor_job(message)
    if job is None:
        log.error("advisor queue: dropped a message that isn't an advisor run")
        return
    run_id, issue = job["id"], int(job["issue"])
    try:
        started = begin_run(issue, run_id)
    except Exception as exc:  # without the marker, this run can't prove the webhook queued it
        log.error("advisor run %s: #%s dropped: couldn't read the issue's marker: %s", run_id, issue, type(exc).__name__)
        return
    if not started:
        log.info("advisor run %s: #%s dropped: the issue isn't waiting for this run", run_id, issue)
        return
    try:
        result = runs.advise(job, advisor_tools(), log.info)
    except Exception as exc:  # runs.advise handles its own errors; this is a configuration error
        log.error("advisor run %s: #%s couldn't start: %s", run_id, issue, runs.describe(exc))
        result = {"state": "unavailable"}
    try:
        if not mark_issue(issue, run_id, result["state"]):
            log.warning("advisor run %s: #%s ended %s, but a newer run took the issue over", run_id, issue, result["state"])
    except Exception as exc:
        log.warning("advisor run %s: #%s couldn't record its state: %s", run_id, issue, type(exc).__name__)


# ---------------------------------------------------------------- the standards run (from the queue)
@app.queue_trigger(arg_name="message", queue_name=STANDARDS_QUEUE, connection="AzureWebJobsStorage")
def publish_standards(message: func.QueueMessage) -> None:
    try:
        job = message.get_json()
        valid = isinstance(job, dict) and RUN_ID.fullmatch(str(job.get("id", "")))
    except ValueError:
        valid = False
    if not valid:
        log.error("standards queue: dropped a message that isn't a standards run")
        return
    try:
        runs.publish_standards(job, standards_tools(), log.info)
    except Exception as exc:  # runs.publish_standards handles its own errors; this is a configuration error
        log.error("standards run %s: couldn't start: %s", job["id"], runs.describe(exc))


# ---------------------------------------------------------------- connect GitHub (app-manifest flow)
@app.route(route="github/status", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def github_status(req: func.HttpRequest) -> func.HttpResponse:
    mode = "app" if secret("github-app-id") else "token" if secret("github-token") else None
    return respond({"connected": bool(mode), "mode": mode, "repository": env("GITHUB_REPOSITORY"),
                    "webhookSecret": bool(secret("github-webhook-secret"))})


@app.route(route="github/setup", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def github_setup(req: func.HttpRequest) -> func.HttpResponse:
    if connected():
        return page(setup_flow.connected_page())
    import requests
    repo, state = env("GITHUB_REPOSITORY"), token_generator.token_urlsafe(32)
    state_container().upload_blob("setup/state.json", json.dumps({"state": state, "created": time.time()}), overwrite=True)
    owner = requests.get(f"https://api.github.com/users/{repo.split('/')[0]}", timeout=15)
    owner_is_org = owner.ok and owner.json().get("type") == "Organization"
    base = req.url.split("/api/", 1)[0]  # the Function's own address, as the person reached it
    return page(setup_flow.setup_page(repo, owner_is_org, state,
                                      setup_flow.manifest(repo, base, env("GITHUB_APP_NAME", "AI-SDLC design advisor"))))


@app.route(route="github/setup/complete", methods=["GET"])
def github_setup_complete(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.exceptions import ResourceNotFoundError
    import requests

    if connected():
        return page(setup_flow.connected_page())
    state, code = req.params.get("state", ""), req.params.get("code", "")
    blob = state_container().get_blob_client("setup/state.json")
    try:
        stored = json.loads(blob.download_blob().readall())
        blob.delete_blob()  # the state works once, whatever happens next
    except ResourceNotFoundError:
        return page(setup_flow.error_page("This setup link was already used or never started."))
    if not hmac.compare_digest(str(stored.get("state", "")), state) or time.time() - stored.get("created", 0) > 3600:
        return page(setup_flow.error_page("The setup link expired or does not match."))
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", code):
        return page(setup_flow.error_page("GitHub did not return a code."))
    try:  # the URL contains the one-time code, and requests puts URLs in its exception messages
        exchange = requests.post(f"https://api.github.com/app-manifests/{code}/conversions", timeout=30,
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    except requests.RequestException as exc:
        log.warning("app-manifest conversion failed: %s", type(exc).__name__)
        return page(setup_flow.error_page("The Function could not reach GitHub. Open the setup link again.", 502))
    if exchange.status_code != 201:
        log.warning("app-manifest conversion refused: HTTP %s", exchange.status_code)
        return page(setup_flow.error_page("GitHub did not accept the code (it works once, for one hour).", 502))
    data = exchange.json()
    try:  # only these three; the client id and client secret are dropped
        store_secret("github-app-id", str(data["id"]))
        store_secret("github-app-private-key", data["pem"])
        store_secret("github-webhook-secret", data["webhook_secret"])
    except Exception as exc:  # the type only: an SDK message could echo a value
        log.error("storing the GitHub App credentials failed: %s", type(exc).__name__)
        return page(setup_flow.error_page("The Function could not store the credentials in Key Vault.", 500))
    slug = data.get("slug", "")
    del data, exchange
    log.info("GitHub App connected")
    return page(setup_flow.done_page(env("GITHUB_REPOSITORY"), slug))
