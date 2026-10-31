"""Azure Functions app of the Secure · Microsoft solution: the posture automation (Python 3.12, Flex Consumption, in the
solution's own virtual network, at most one instance).

Functions:
  intake   POST /api/intake    Defender for Cloud's recommendation, forwarded by the Logic App posture-intake, the only
                               caller: the token of its managed identity is checked (posture/auth.py). One intake runs
                               at a time. Answers 503 when the Logic App should send it again later; its retry policy
                               does.
  preview  POST /api/preview   The repository webhook (pull_request events). The signature, made with the webhook secret
                               in Key Vault, is the authentication. A fork's or an outside author's pull request is
                               dropped before any call; any other is read again from GitHub's API before the what-if job
                               starts.
  verify   every hour          Once the fix is deployed, waits for Azure Policy to report it compliant, records the
                               evidence on the Issue, and closes it. Start it now with the README's `az rest` command.
Nothing here logs or returns a token, a secret, a webhook body, a resource id, or a host name.
"""
import json
import logging
import os
import threading

import azure.functions as func

from posture import auth, checks, flows
from posture.clients import Azure, GitHub, HttpError, Identity, Secrets
from posture.config import Settings

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger("posture")
# The Azure SDK logs every token request at INFO (headers redacted); keep only its warnings.
logging.getLogger("azure").setLevel(logging.WARNING)
_identity = Identity()
_secrets: list[Secrets] = []
# The app runs on at most one instance (infra/automation.bicep), so this lock makes intake run one at a time, on top of
# the Logic App's own one-run-at-a-time trigger.
_intake_lock = threading.Lock()


class NotConnected(RuntimeError):
    """The GitHub token is not in Key Vault yet."""


def secret(name: str) -> str | None:
    if not _secrets:
        _secrets.append(Secrets(_identity, os.environ["KEY_VAULT_URI"]))
    return _secrets[0].get(name)


def github(settings: Settings) -> GitHub:
    token = secret("github-token")
    if not token:
        raise NotConnected("the GitHub token is not set: store it in the azd environment and run azd provision")
    return GitHub(settings.repository, token)


def respond(data: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype="application/json")


@app.route(route="intake", methods=["POST"])
def intake(req: func.HttpRequest) -> func.HttpResponse:
    try:
        auth.caller(req.headers.get("Authorization"), os.environ.get("AZURE_TENANT_ID", ""),
                    os.environ.get("INTAKE_CALLER_CLIENT_ID", ""), os.environ.get("INTAKE_CALLER_PRINCIPAL_ID", ""))
    except auth.Unauthorized as exc:
        return respond({"error": str(exc)}, 401)
    try:
        event = req.get_json()
    except ValueError:
        return respond({"error": "the body is not JSON"}, 400)
    if not isinstance(event, dict):
        return respond({"error": "the body is not a JSON object"}, 400)
    if not _intake_lock.acquire(timeout=30):
        return respond({"result": "another intake is running; send it again later"}, 503)
    try:
        settings = Settings.from_environment()
        result = flows.intake(event, settings, Azure(_identity), github(settings))
        log.info("intake: %s", result.get("result"))
        return respond(result)
    except flows.Retry as exc:
        log.info("intake: %s; asking the Logic App to send it again", exc)
        return respond({"result": str(exc)}, 503)
    except NotConnected as exc:
        return respond({"error": str(exc)}, 409)
    except HttpError as exc:
        log.warning("intake failed: %s", exc)
        return respond({"error": str(exc)}, 502)
    except Exception as exc:
        log.exception("intake failed")
        return respond({"error": f"intake failed: {type(exc).__name__}"}, 500)
    finally:
        _intake_lock.release()


@app.route(route="preview", methods=["POST"])
def preview(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_body()
    webhook_secret = secret("github-webhook-secret")
    if not webhook_secret:
        return respond({"error": "the webhook secret is not set: run azd provision"}, 503)
    if not checks.verify_signature(webhook_secret, body, req.headers.get("X-Hub-Signature-256")):
        return respond({"error": "invalid signature"}, 401)
    try:
        payload = json.loads(body)
    except ValueError:
        return respond({"error": "the body is not JSON"}, 400)
    settings = Settings.from_environment()
    number, reason = checks.webhook_number(req.headers.get("X-GitHub-Event", ""), payload, settings.repository)
    if number is None:
        log.info("preview: delivery ignored: %s", reason)
        return respond({"result": "ignored", "reason": reason})
    try:
        result = flows.preview(number, settings, Azure(_identity), github(settings))
    except NotConnected as exc:
        return respond({"error": str(exc)}, 409)
    except HttpError as exc:
        log.warning("preview of pull request #%s failed: %s", number, exc)
        return respond({"error": str(exc)}, 502)
    log.info("preview of pull request #%s (%s): %s", number, reason, result["result"])
    return respond(result, 202 if result["started"] else 200)


@app.timer_trigger(schedule="0 0 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def verify(timer: func.TimerRequest) -> None:
    settings = Settings.from_environment()
    result = flows.verify(settings, Azure(_identity), github(settings))
    log.info("verify: %s", json.dumps(result, ensure_ascii=False))
