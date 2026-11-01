"""The Plan · Microsoft run as an Azure Function app (Flex Consumption, Python 3.12): three functions, no state in memory.

  runs           HTTP, with the Function app's key. runs.py, in the solution folder, calls it for the presenter.
                   POST   /api/runs         start a run; body {"compareWithPullRequest": 129} is optional
                   GET    /api/runs         the runs in progress, the newest runs, and whether GitHub takes the token
                   GET    /api/runs/{run}   one run: its state and every event so far
                   DELETE /api/runs/{run}   cancel a run that hasn't published; closes its review Issue
  run_step       Storage queue plan-steps. One step per message: draft, evaluate, or publish (planner/steps.py). A
                 step can take minutes while it polls Foundry: up to 45 for evaluate's three attempts, well within
                 host.json's one-hour functionTimeout. One that raises is delivered again, up to three times (host.json),
                 and resumes from what its record saved; on the last attempt the run is marked failed instead. A
                 delivery the host stops (a timeout, or a platform update, which gives a running function 10 minutes)
                 is delivered again too, and the timer ends a run whose step stopped for good.
  check_reviews  Timer, every 30 seconds. Reads each review Issue that waits for a person, and queues the publish
                 step when the brief-approved label is on it. Also queues a publish again that made no progress for
                 5 minutes, and ends a run whose draft or evaluate step saved nothing for 45 minutes.

The run's state lives in its record, a blob in the storage account (planner/store.py), and in the review Issue: every
function is stateless, and any instance can run any step. Nothing in Azure calls these functions with a key: only
runs.py does, and it reads the key from Azure each time, so there's no second copy to go stale.

Settings (app settings, from infra/resources.bicep): FOUNDRY_PROJECT_ENDPOINT, GITHUB_REPOSITORY, KEY_VAULT_URI,
STORAGE_BLOB_ENDPOINT, and the identity-based AzureWebJobsStorage connection. The agent's name and request come from
bundle/agent.yaml, and the quotes from bundle/inputs/: the azd prepackage hook copies both from the solution folder
(`python setup_foundry.py bundle`). The GitHub token is the Key Vault secret github-token, read with the Function app's
managed identity and kept in memory for five minutes. It never reaches a log, a response, or a run record: an error this
code didn't write is logged and answered by its type only (steps.describe()), and never re-raised with its text.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import typing
from pathlib import Path

import azure.functions as func

from planner import brief, clients, steps, store

QUEUE = "plan-steps"
MAX_DEQUEUE_COUNT = 3  # host.json: extensions.queues.maxDequeueCount
BUNDLE = Path(__file__).resolve().parent / "bundle"
TOKEN_SECONDS = 300

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_lock = threading.Lock()
_cache: dict[str, typing.Any] = {}
# The Azure SDKs log every request (URL and headers) at INFO. Keep Application Insights to the run's own lines.
logging.getLogger("azure").setLevel(logging.WARNING)


def credential():
    with _lock:
        if "credential" not in _cache:
            from azure.identity import ManagedIdentityCredential

            _cache["credential"] = ManagedIdentityCredential()
        return _cache["credential"]


def foundry_token() -> str:
    """A Microsoft Entra token for Foundry (the Foundry User role): the managed identity, no key."""
    return credential().get_token("https://ai.azure.com/.default").token


def github() -> clients.GitHub:
    with _lock:
        cached = _cache.get("github")
        if cached and time.monotonic() - cached[1] < TOKEN_SECONDS:
            return cached[0]
    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets import SecretClient

    try:
        secret = SecretClient(os.environ["KEY_VAULT_URI"], credential()).get_secret("github-token").value
    except ResourceNotFoundError:
        secret = None
    # Refuses a missing token, and one with spaces or line breaks inside, without quoting it.
    client = clients.GitHub(os.environ["GITHUB_REPOSITORY"], clients.github_token(secret))
    with _lock:
        _cache["github"] = (client, time.monotonic())
    return client


def settings() -> steps.Settings:
    import yaml

    agent = yaml.safe_load((BUNDLE / "agent.yaml").read_text(encoding="utf-8"))
    transcript = (BUNDLE / "inputs" / "stakeholder-transcript.md").read_text(encoding="utf-8")
    policies = (BUNDLE / "inputs" / "routing-policies.md").read_text(encoding="utf-8")
    return steps.Settings(agent=agent["name"], prompt=agent["prompt"], excerpts=brief.source_excerpts(transcript, policies))


def services() -> steps.Services:
    with _lock:
        built = _cache.get("services")
    if built:
        return built
    from azure.storage.blob import ContainerClient

    built = steps.Services(
        store=store.BlobStore(ContainerClient(os.environ["STORAGE_BLOB_ENDPOINT"], "runs", credential=credential())),
        foundry=clients.Foundry(os.environ["FOUNDRY_PROJECT_ENDPOINT"], foundry_token),
        github=github,
        settings=settings(),
        log=logging.info,
    )
    with _lock:
        _cache["services"] = built
    return built


def answer(payload, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json")


def message(run_id: str, step: str) -> str:
    return json.dumps({"run": run_id, "step": step})


class StepFailed(Exception):
    """Raised so the queue delivers a step again. Its message is steps.describe() of the error: no request, no host."""


def handle_runs(req: func.HttpRequest, run_id: str | None, next_steps: func.Out[str]) -> func.HttpResponse:
    if req.method == "POST" and not run_id:
        try:
            body = req.get_json() if req.get_body() else {}
        except ValueError:
            return answer({"error": "the body must be JSON"}, 400)
        pull_request = (body or {}).get("compareWithPullRequest")
        if pull_request is not None and (not isinstance(pull_request, int) or isinstance(pull_request, bool) or pull_request < 1):
            return answer({"error": "compareWithPullRequest must be a pull request number"}, 400)
        record = steps.start(services(), pull_request)
        next_steps.set(message(record["id"], "draft"))
        return answer(steps.summary(record), 202)
    if req.method == "GET" and not run_id:
        return answer(steps.overview(services()))
    if req.method == "GET":
        return answer(steps.summary(services().store.load(run_id)[0]))
    if req.method == "DELETE" and run_id:
        return answer(steps.cancel(services(), run_id))
    return answer({"error": "not supported"}, 405)


@app.route(route="runs/{run?}", methods=["GET", "POST", "DELETE"])
@app.queue_output(arg_name="next_steps", queue_name=QUEUE, connection="AzureWebJobsStorage")
def runs(req: func.HttpRequest, next_steps: func.Out[str]) -> func.HttpResponse:
    run_id = req.route_params.get("run")
    if run_id and not steps.RUN_ID.match(run_id):
        return answer({"error": "not a run id"}, 404)
    try:
        return handle_runs(req, run_id, next_steps)
    except store.NotFound:
        return answer({"error": "no such run"}, 404)
    except steps.Busy as error:
        return answer({"error": str(error)}, 409)
    except Exception as error:  # noqa: BLE001 - answered and logged by its type only
        failure = steps.describe(error)
    logging.error("runs: %s %s failed (%s)", req.method, "/api/runs" + (f"/{run_id}" if run_id else ""), failure)
    return answer({"error": f"the Function app couldn't answer ({failure})"}, 500)


@app.queue_trigger(arg_name="msg", queue_name=QUEUE, connection="AzureWebJobsStorage")
@app.queue_output(arg_name="next_steps", queue_name=QUEUE, connection="AzureWebJobsStorage")
def run_step(msg: func.QueueMessage, next_steps: func.Out[str]) -> None:
    try:
        payload = json.loads(msg.get_body().decode("utf-8"))
    except ValueError:
        payload = {}
    run_id, step = payload.get("run"), payload.get("step")
    if step not in steps.STEPS or not isinstance(run_id, str) or not steps.RUN_ID.match(run_id):
        logging.warning("ignored a queue message that names no known step")
        return
    svc = None
    failure = None
    try:
        svc = services()
        # The message's id stays the same when the queue delivers it again: publish uses it to claim the run.
        following = steps.STEPS[step](svc, run_id, owner=msg.id or "")
    except (steps.Stop, store.NotFound):
        return
    except Exception as error:  # noqa: BLE001
        failure = error
    if failure is not None:
        reason = steps.describe(failure)
        if (msg.dequeue_count or 1) < MAX_DEQUEUE_COUNT:
            logging.warning("run %s [%s] delivery %s failed (%s); the queue delivers it again", run_id, step,
                            msg.dequeue_count, reason)
            # Raised outside the handler, so the host logs this exception and nothing chained to it.
            raise StepFailed(f"run {run_id} [{step}] {reason}")
        logging.error("run %s [%s] failed on its last delivery (%s)", run_id, step, reason)
        problem = None
        try:
            steps.give_up(svc or services(), run_id, step, failure)
        except Exception as error:  # noqa: BLE001 - the timer ends the run later (steps.STEP_STALE, PUBLISH_STALE)
            problem = steps.describe(error)
        if problem:
            logging.error("run %s [%s] couldn't record that the run failed (%s); the timer ends it later",
                          run_id, step, problem)
        return
    if following:
        next_steps.set(message(run_id, following))


@app.timer_trigger(arg_name="timer", schedule="*/30 * * * * *", run_on_startup=False, use_monitor=False)
@app.queue_output(arg_name="next_steps", queue_name=QUEUE, connection="AzureWebJobsStorage")
def check_reviews(timer: func.TimerRequest, next_steps: func.Out[typing.List[str]]) -> None:
    try:
        to_publish = steps.check_reviews(services())
    except Exception as error:  # noqa: BLE001 - logged by its type; the next tick, 30 seconds later, tries again
        logging.error("check_reviews: %s", steps.describe(error))
        return
    if to_publish:
        next_steps.set([message(run_id, "publish") for run_id in to_publish])
