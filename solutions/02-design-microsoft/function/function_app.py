"""Azure Functions app of the Design · Microsoft solution (Python, Flex Consumption, inside the solution's VNet).

Routes (all under /api):
  POST github/webhook          The GitHub App's webhook. Verifies the signature, ignores a repeated delivery
                               (X-GitHub-Delivery) and a repeated question (one advisor run per issue), then starts the
                               advisor or the standards Logic App. Anonymous: the signature is the authentication.
  GET  github/setup            Connect GitHub (function key required): the app-manifest page with a one-time state.
  GET  github/setup/complete   GitHub's redirect once the app exists: stores the app id, private key, and webhook
                               secret in Key Vault, nothing else. Answers 409 once an app is connected.
  GET  github/status           Whether GitHub is connected, and how (function key required; no secret is returned).
  POST advisor/check           The gate: deterministic checks of an advisor answer against the standards index.
  POST repo/{operation}        The advisor's only GitHub writes: branch, commit, pull-request, comment.
  POST standards/sync          Push path: re-index the standards of a merged commit.
  POST agents/publish          Push path: update the knowledge bases, publish new agent versions if agent.yaml changed.
  POST evaluations/start       Push path: start one Foundry evaluation run per profile.
The last six accept only the advisor's Logic App identity (advisor_core.auth). Nothing here logs a token, a key, a
secret, a webhook body, or what GitHub returns when the app is created.
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

from advisor_core import auth, checks, github, report, setup_flow, webhook

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
log = logging.getLogger("advisor")
STATE_CONTAINER = "advisor-state"
SOLUTION = "solutions/02-design-microsoft"
_cache: dict = {}
_lock = threading.Lock()


class NotConnected(RuntimeError):
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


def respond(data, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype="application/json")


def page(result: tuple[int, str]) -> func.HttpResponse:
    status, text = result
    return func.HttpResponse(text, status_code=status, mimetype="text/html", headers={"Cache-Control": "no-store"})


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


def start_workflow(secret_name: str, payload: dict) -> None:
    """Start a Logic App run through its trigger URL, which only Key Vault holds (never logged)."""
    import requests
    url = secret(secret_name)
    if not url:
        raise RuntimeError(f"Key Vault has no {secret_name}; run azd provision")
    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        raise RuntimeError(f"the Logic App refused the run: HTTP {response.status_code}")


def logic_app_only(handler):
    """Accept only the advisor's Logic App identity, and turn known errors into clear responses."""
    def wrapper(req: func.HttpRequest) -> func.HttpResponse:
        try:
            auth.caller(req.headers.get("Authorization"), env("AZURE_TENANT_ID"), env("LOGIC_APP_CLIENT_ID"),
                        env("LOGIC_APP_PRINCIPAL_ID"))
        except auth.Unauthorized as exc:
            return respond({"error": str(exc)}, 401)
        try:
            return handler(req)
        except github.GuardError as exc:
            log.warning("guard refused a write: %s", exc)
            return respond({"error": str(exc)}, 403)
        except NotConnected as exc:
            return respond({"error": str(exc)}, 409)
        except (github.GitHubError, ValueError, KeyError) as exc:
            log.warning("%s failed: %s", req.url.split("?")[0].rsplit("/api/", 1)[-1], exc)
            return respond({"error": str(exc)}, 502 if isinstance(exc, github.GitHubError) else 400)
    wrapper.__name__ = handler.__name__
    return wrapper


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
    if not claim(marker, {"event": event, "at": datetime.now(timezone.utc).isoformat()}):
        log.info("delivery %s ignored: already handled", delivery)
        return respond({"result": "duplicate delivery ignored"})
    decision = webhook.classify(event, json.loads(body), env("GITHUB_REPOSITORY"))
    log.info("delivery %s (%s): %s", delivery, event, decision["route"] if decision["route"] != "ignore" else decision["reason"])
    try:
        if decision["route"] == "advisor":
            question = f"issues/{decision['issue']}.json"
            if not claim(question, {"delivery": delivery, "at": datetime.now(timezone.utc).isoformat()}):
                return respond({"result": f"issue #{decision['issue']} already has an advisor run"})
            try:
                start_workflow("advisor-workflow-url", {k: decision[k] for k in ("issue", "title", "profile", "question")})
            except Exception:
                release(question)
                raise
            return respond({"result": f"advisor started for issue #{decision['issue']}"}, 202)
        if decision["route"] == "standards":
            start_workflow("standards-workflow-url", {"sha": decision["sha"], "files": decision["files"]})
            return respond({"result": f"standards workflow started for {decision['sha'][:7]}"}, 202)
    except Exception as exc:
        release(marker)
        log.error("delivery %s: could not start the workflow: %s", delivery, exc)
        return respond({"error": "could not start the workflow; redeliver to retry"}, 500)
    return respond({"result": "ignored", "reason": decision["reason"]})


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
    exchange = requests.post(f"https://api.github.com/app-manifests/{code}/conversions", timeout=30,
                             headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
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


# ---------------------------------------------------------------- the gate
def standards_snapshot(search_filter: str | None = None) -> dict:
    from advisor_core import standards
    return cached(("snapshot", search_filter), 300, lambda: standards.snapshot(
        env("SEARCH_ENDPOINT"), credential(), env("SEARCH_INDEX", "architecture-standards"), search_filter))


def project_client():
    def make():
        from azure.ai.projects import AIProjectClient
        return AIProjectClient(endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), credential=credential())
    return cached("project", float("inf"), make)


@app.route(route="advisor/check", methods=["POST"])
@logic_app_only
def advisor_check(req: func.HttpRequest) -> func.HttpResponse:
    from advisor_core import agents

    body = req.get_json()
    response, profile, question = body["response"], body["profile"], body["question"]
    agent = response.get("agent_reference") or {}
    run = {"issue": body.get("issue"), "question": question, "profile": profile, "workflowRun": body.get("workflowRun", ""),
           "agent": {"name": agent.get("name", "?"), "version": str(agent.get("version", "?"))},
           "model": response.get("model", ""), "responseId": response.get("id", ""),
           "index": env("SEARCH_INDEX", "architecture-standards")}
    created, completed = response.get("created_at"), response.get("completed_at")
    run["startedAt"] = datetime.fromtimestamp(created or time.time(), timezone.utc).isoformat(timespec="seconds")
    run["durationSeconds"] = round(completed - created, 1) if created and completed else None
    output = [item for item in response.get("output") or [] if isinstance(item, dict)]
    run["knowledgeCalls"] = sum(item.get("type") in ("mcp_call", "azure_ai_search_call") for item in output)
    run["retrievedStandards"] = checks.retrieved_ids([item for item in output if item.get("type") != "message"])
    usage = response.get("usage") or {}
    run["usage"] = {"inputTokens": usage.get("input_tokens"), "outputTokens": usage.get("output_tokens")}

    problems = []
    answer = None
    if response.get("status") != "completed":
        problems.append(f"response: the agent's response ended with status {response.get('status')}")
    try:
        answer = checks.parse_answer(checks.answer_text(response))
    except ValueError as exc:
        problems.append(f"format: {exc}")
    try:
        agent_profile, scope = cached(("scope", run["agent"]["name"], run["agent"]["version"]), 3600, lambda: agents.scope_filter_of(
            project_client(), run["agent"]["name"], run["agent"]["version"]))
    except Exception as exc:  # unknown agent version: nothing can be checked against its scope
        agent_profile, scope = None, ""
        problems.append(f"access: could not read the scope of agent {run['agent']['name']} v{run['agent']['version']} "
                        f"({type(exc).__name__})")
    if agent_profile and agent_profile != profile:
        problems.append(f"access: agent {run['agent']['name']} serves the '{agent_profile}' profile, not '{profile}'")
    run["scopes"] = re.findall(r"scope eq '([^']+)'", scope)
    if answer is not None and scope:
        problems += checks.check(answer, question, run["retrievedStandards"], standards_snapshot(),
                                 list(standards_snapshot(scope)), profile)
    run["result"] = answer or {"answerable": False, "summary": "", "recommendation": None, "options": [],
                               "constraints": [], "conflicts": [], "unknowns": []}
    run["checks"] = problems
    log.info("issue %s: %s with %d problem(s), response %s", run["issue"], "passed" if not problems else "failed",
             len(problems), run["responseId"])
    return respond({"passed": not problems, "problems": problems, "run": run})


# ---------------------------------------------------------------- GitHub writes (guarded)
@app.route(route="repo/{operation}", methods=["POST"])
@logic_app_only
def repo_write(req: func.HttpRequest) -> func.HttpResponse:
    operation, body = req.route_params.get("operation"), req.get_json()
    issue = int(body["issue"])
    client = github_client()
    if operation == "branch":
        result = client.ensure_branch(issue)
    elif operation == "commit":
        result = client.put_adr(issue, report.adr_markdown(body["run"]), f"Design: Foundry advisor ADR draft for #{issue}")
    elif operation == "pull-request":
        title, text = report.pull_request_text(body["run"], github.adr_path_for(issue))
        result = client.open_pull_request(issue, title, text)
    elif operation == "comment":
        text = (report.unavailable_markdown(body.get("workflowRun", "")) if body.get("kind") == "unavailable"
                else report.comment_markdown(body["run"], body.get("pullRequest")))
        result = client.comment(issue, text)
    else:
        return respond({"error": f"unknown operation {operation}"}, 404)
    log.info("issue %s: %s done", issue, operation)
    return respond(result)


# ---------------------------------------------------------------- push path (optional step)
def merged_spec(client: github.GitHub, sha: str) -> dict:
    from advisor_core import agents
    text = client.read_text(f"{SOLUTION}/agent.yaml", sha)
    if text is None:
        raise ValueError(f"agent.yaml not found at {sha[:7]}")
    return agents.load_spec(text)


def commit_of(body: dict) -> str:
    sha = str(body.get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("sha must be a full commit id")
    return sha


@app.route(route="standards/sync", methods=["POST"])
@logic_app_only
def standards_sync(req: func.HttpRequest) -> func.HttpResponse:
    from advisor_core import standards

    sha, client = commit_of(req.get_json()), github_client()
    spec = merged_spec(client, sha)
    docs, skipped = standards.parse(client.read_folder(standards.SOURCE_DIR, sha), spec)
    result = standards.sync(env("SEARCH_ENDPOINT"), credential(), env("SEARCH_INDEX", "architecture-standards"), docs, spec)
    forget(("snapshot", None))
    return respond({"commit": sha, "skipped": skipped, "summary": standards.summary_lines(result), "result": result})


@app.route(route="agents/publish", methods=["POST"])
@logic_app_only
def agents_publish(req: func.HttpRequest) -> func.HttpResponse:
    from advisor_core import agents, knowledge

    sha, client = commit_of(req.get_json()), github_client()
    spec = merged_spec(client, sha)
    lines = knowledge.sync(env("SEARCH_ENDPOINT"), credential(), spec, spec["search"]["index"]) if spec["knowledge"] == "foundry-iq" else []
    published = agents.publish(project_client(), spec, env("FOUNDRY_MODEL_DEPLOYMENT"), env("SEARCH_ENDPOINT"))
    return respond({"commit": sha, "knowledge": lines, "agents": published})


@app.route(route="evaluations/start", methods=["POST"])
@logic_app_only
def evaluations_start(req: func.HttpRequest) -> func.HttpResponse:
    from advisor_core import agents, evaluation

    sha, client = commit_of(req.get_json()), github_client()
    spec = merged_spec(client, sha)
    cases_text = client.read_text(f"{SOLUTION}/eval_cases.jsonl", sha) or ""
    cases = [json.loads(line) for line in cases_text.splitlines() if line.strip()]
    published = agents.publish(project_client(), spec, env("FOUNDRY_MODEL_DEPLOYMENT"), env("SEARCH_ENDPOINT"))
    runs = evaluation.start(project_client(), env("FOUNDRY_MODEL_DEPLOYMENT"), cases, env("SEARCH_ENDPOINT"), credential(),
                            spec["search"]["index"], published, f"commit {sha[:7]}")
    return respond({"commit": sha, "runs": runs})
