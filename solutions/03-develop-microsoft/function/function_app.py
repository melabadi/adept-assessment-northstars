"""Azure Functions app of the Develop · Microsoft solution: the Azure pull request reviewer (Python 3.12, Flex
Consumption, inside the solution's virtual network).

Routes (all under /api):
  POST github/webhook   GitHub's pull_request webhook. Anonymous: GitHub's signature (X-Hub-Signature-256, made with
                        the webhook secret) is the authentication. Takes the pull request's number from a delivery that
                        asks for a review, reads the pull request from GitHub's API, and queues a review only if it can
                        be reviewed (reviewer/webhook.py). Answers within GitHub's 10 seconds; the review runs from the
                        queue.
  POST dry-runs         {"pr": <number>}: queue a dry run, which does everything a review does but posts nothing
                        (function key required). eval_reviewer.py uses it. Answers {"id": ...}.
  GET  dry-runs/{id}    The dry run's state, and its result once it's done (function key required).
Queue:
  reviews               One message per review: {"id", "pr", "dryRun"}. The review function runs reviewer/pipeline.py.

Nothing here logs the GitHub token, the webhook secret, a function key, a webhook body, or an archive link. Logs name
each review by its id; the review's footer on GitHub shows the same id.
"""
import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timezone

import azure.functions as func

from reviewer import pipeline, webhook
from reviewer.agent import Agent
from reviewer.github import GitHub
from reviewer.sessions import Session

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger("reviewer")
logging.getLogger("azure").setLevel(logging.WARNING)  # the SDKs' request logs name storage hosts; not needed
QUEUE = "reviews"
RESULTS = "dry-runs"
REVIEW_ID = re.compile(r"[0-9a-f]{12}")
_lock = threading.Lock()
_credential = None


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if not value:
        raise RuntimeError(f"app setting {name} is missing")
    return value


def credential():
    """The Function's managed identity (shared by the requests one instance serves)."""
    global _credential
    with _lock:
        if _credential is None:
            from azure.identity import DefaultAzureCredential
            _credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        return _credential


def bearer(scope: str):
    return lambda: credential().get_token(scope).token


def github() -> GitHub:
    return GitHub(env("GITHUB_REPOSITORY"), os.environ.get("GITHUB_REVIEW_TOKEN", ""))


def settings() -> pipeline.Settings:
    return pipeline.Settings(repository=env("GITHUB_REPOSITORY"), label=env("REVIEW_LABEL", "review:azure"),
                             checker_ref=env("REVIEW_CHECKER_REF", "main"),
                             scripts_path=env("REVIEW_SCRIPTS_PATH", "solutions/03-develop-microsoft/sandbox"),
                             agent_name=env("REVIEWER_AGENT_NAME", "requesthub-pr-reviewer"))


def new_id() -> str:
    return secrets.token_hex(6)


def results():
    from azure.storage.blob import ContainerClient
    return ContainerClient(account_url=env("STORAGE_BLOB_ENDPOINT"), container_name=RESULTS, credential=credential())


def save_result(review_id: str, data: dict) -> None:
    """A dry run's state for GET dry-runs/{id}. A failure to save is logged, never fatal to the review."""
    try:
        results().upload_blob(f"{review_id}.json", json.dumps(data, ensure_ascii=False), overwrite=True)
    except Exception as exc:
        log.error("review %s: couldn't save the dry run's state: %s", review_id, type(exc).__name__)


def respond(data: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype="application/json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- GitHub's webhook
@app.route(route="github/webhook", methods=["POST"])
@app.queue_output(arg_name="reviews", queue_name=QUEUE, connection="AzureWebJobsStorage")
def github_webhook(req: func.HttpRequest, reviews: func.Out[str]) -> func.HttpResponse:
    status, answer, message = webhook.intake(dict(req.headers), req.get_body(), secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
                                             repository=env("GITHUB_REPOSITORY"), label=env("REVIEW_LABEL", "review:azure"),
                                             read_pull=lambda number: github().pull(number), new_id=new_id)
    if message:
        reviews.set(json.dumps(message))
        log.info("review %s: #%s queued (%s)", message["id"], message["pr"], message["event"])
    elif status >= 400:
        log.warning("webhook delivery refused: HTTP %s", status)
    return respond(answer, status)


# ---------------------------------------------------------------- dry runs (eval_reviewer.py)
@app.route(route="dry-runs", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@app.queue_output(arg_name="reviews", queue_name=QUEUE, connection="AzureWebJobsStorage")
def dry_run_start(req: func.HttpRequest, reviews: func.Out[str]) -> func.HttpResponse:
    try:
        pr = int((req.get_json() or {}).get("pr"))
    except (ValueError, TypeError, AttributeError):
        return respond({"error": 'send {"pr": <pull request number>}'}, 400)
    if not 0 < pr < 10_000_000:
        return respond({"error": "not a pull request number"}, 400)
    review_id = new_id()
    save_result(review_id, {"id": review_id, "pr": pr, "dry_run": True, "state": "queued", "queued_at": now()})
    reviews.set(json.dumps({"id": review_id, "pr": pr, "dryRun": True}))
    log.info("review %s: dry run of #%s queued", review_id, pr)
    return respond({"id": review_id, "pr": pr, "state": "queued"}, 202)


@app.route(route="dry-runs/{id}", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def dry_run_result(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.exceptions import ResourceNotFoundError
    review_id = req.route_params.get("id", "")
    if not REVIEW_ID.fullmatch(review_id):
        return respond({"error": "unknown dry run"}, 404)
    try:
        data = json.loads(results().download_blob(f"{review_id}.json").readall())
    except ResourceNotFoundError:
        return respond({"error": "unknown dry run"}, 404)
    return respond(data)


# ---------------------------------------------------------------- the review
@app.queue_trigger(arg_name="message", queue_name=QUEUE, connection="AzureWebJobsStorage")
def review(message: func.QueueMessage) -> None:
    data = message.get_json()
    review_id, pr, dry_run = str(data.get("id", "")), int(data["pr"]), data.get("dryRun") is True
    if not REVIEW_ID.fullmatch(review_id):
        review_id = new_id()
    if dry_run:
        save_result(review_id, {"id": review_id, "pr": pr, "dry_run": True, "state": "running", "started_at": now()})
    try:
        tools = pipeline.Tools(
            github=github(),
            session=lambda pool, identifier: Session(env("JUDGE_POOL_ENDPOINT" if pool == "judge" else "RUN_POOL_ENDPOINT"),
                                                     identifier, bearer("https://dynamicsessions.io/.default")),
            agent=Agent(env("FOUNDRY_PROJECT_ENDPOINT"), env("REVIEWER_AGENT_NAME", "requesthub-pr-reviewer"),
                        bearer("https://ai.azure.com/.default")),
        )
        result = pipeline.review(pr, review_id=review_id, dry_run=dry_run, settings=settings(), tools=tools)
    except Exception as exc:  # configuration errors: only the type, a message could echo a value
        log.error("review %s: couldn't start: %s", review_id, type(exc).__name__)
        result = {"id": review_id, "pr": pr, "dry_run": dry_run, "state": "failed", "step": "start",
                  "error": type(exc).__name__}
    if dry_run:
        save_result(review_id, dict(result, finished_at=now()))
