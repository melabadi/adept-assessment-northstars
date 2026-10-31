"""Connections of the posture Function: Azure Resource Manager, Microsoft Foundry, and Key Vault with the Function's
managed identity, and GitHub's REST API with the token Key Vault holds.

An error carries the service, the status code, and the service's short message: never a URL (it names resources), a
header, a token, or a request body. Function responses and logs show only these errors.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ARM = "https://management.azure.com"
GITHUB = "https://api.github.com"


class HttpError(RuntimeError):
    def __init__(self, service: str, status: int, message: str):
        super().__init__(f"{service} answered HTTP {status}: {message}" if status else f"{service}: {message}")
        self.service, self.status = service, status


def send(service: str, method: str, url: str, *, headers: dict, body=None, timeout: float = 30) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={**headers, **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as exc:
        # Azure's error messages can name the resource, so only its error code is kept; GitHub's message names none.
        try:
            detail = json.loads(exc.read() or b"{}")
        except ValueError:
            detail = {}
        error = detail.get("error") if isinstance(detail, dict) else None
        message = error.get("code") if isinstance(error, dict) else (detail or {}).get("message")
        raise HttpError(service, exc.code, str(message or exc.reason or "error")[:200]) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(service, 0, f"no answer ({type(getattr(exc, 'reason', exc)).__name__})") from None
    return status, (json.loads(raw) if raw else None)


class Identity:
    """Tokens of the Function's managed identity, kept until five minutes before they expire."""

    def __init__(self, client_id: str | None = None):
        self._client_id, self._credential, self._tokens = client_id, None, {}
        self._lock = threading.Lock()

    def token(self, scope: str) -> str:
        with self._lock:
            cached = self._tokens.get(scope)
            if cached and cached[1] - time.time() > 300:
                return cached[0]
            if self._credential is None:
                from azure.identity import ManagedIdentityCredential
                self._credential = (ManagedIdentityCredential(client_id=self._client_id) if self._client_id
                                    else ManagedIdentityCredential())
            access = self._credential.get_token(scope)
            self._tokens[scope] = (access.token, access.expires_on)
            return access.token


class Secrets:
    """Key Vault secrets, read through the vault's private endpoint and kept for five minutes."""

    def __init__(self, identity: Identity, vault_uri: str):
        self._identity, self._vault, self._cache = identity, vault_uri.rstrip("/"), {}
        self._lock = threading.Lock()

    def get(self, name: str) -> str | None:
        with self._lock:
            hit = self._cache.get(name)
            if hit and time.monotonic() - hit[1] < 300:
                return hit[0]
        try:
            _, body = send("Key Vault", "GET", f"{self._vault}/secrets/{name}?api-version=7.4",
                           headers={"Authorization": "Bearer " + self._identity.token("https://vault.azure.net/.default")})
            value = (body or {}).get("value") or None
        except HttpError as exc:
            if exc.status != 404:
                raise
            value = None
        with self._lock:
            self._cache[name] = (value, time.monotonic())
        return value


class Azure:
    """The Azure calls the posture automation makes, with the Function's managed identity."""

    def __init__(self, identity: Identity):
        self._identity = identity

    def _arm(self, method: str, path: str, api_version: str, *, query: dict | None = None, body=None,
             timeout: float = 30):
        params = urllib.parse.urlencode({"api-version": api_version, **(query or {})}, quote_via=urllib.parse.quote)
        _, result = send("Azure Resource Manager", method, f"{ARM}{path}?{params}", body=body, timeout=timeout,
                         headers={"Authorization": "Bearer " + self._identity.token(f"{ARM}/.default")})
        return result

    def assessment(self, storage_account_id: str, key: str) -> dict | None:
        """The Defender for Cloud recommendation's current status and text, or None before Defender assessed it."""
        try:
            return self._arm("GET", f"{storage_account_id}/providers/Microsoft.Security/assessments/{key}", "2021-06-01",
                             query={"$expand": "metadata"})
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise

    def storage_account(self, storage_account_id: str) -> dict:
        return self._arm("GET", storage_account_id, "2023-05-01")

    def policy_states(self, resource_group_id: str, odata_filter: str) -> list[dict]:
        result = self._arm("POST", f"{resource_group_id}/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults",
                           "2019-10-01", query={"$filter": odata_filter})
        return (result or {}).get("value") or []

    def start_policy_evaluation(self, resource_group_id: str) -> None:
        """Starts an on-demand evaluation of the resource group (202). Its status URL is at subscription scope, where the
        identity has no access, so the caller polls the compliance results instead."""
        self._arm("POST", f"{resource_group_id}/providers/Microsoft.PolicyInsights/policyStates/latest/triggerEvaluation",
                  "2019-10-01")

    def job_container(self, job_id: str) -> dict:
        job = self._arm("GET", job_id, "2025-07-01")
        return (((job or {}).get("properties") or {}).get("template") or {}).get("containers", [{}])[0]

    def start_job(self, job_id: str, container: dict, args: list[str]) -> None:
        """Starts one execution of the what-if job with these arguments and the job's own image, command, and settings."""
        self._arm("POST", f"{job_id}/start", "2025-07-01", body={"containers": [{
            "name": container.get("name"), "image": container.get("image"), "command": container.get("command"),
            "args": args, "env": container.get("env"), "resources": container.get("resources")}]})

    def ask_agent(self, project_endpoint: str, agent_name: str, document: dict, timeout: float = 40) -> dict:
        """The Foundry agent's proposal: the project's Responses API with a reference to the published agent."""
        _, body = send("Microsoft Foundry", "POST", f"{project_endpoint}/openai/v1/responses", timeout=timeout,
                       headers={"Authorization": "Bearer " + self._identity.token("https://ai.azure.com/.default")},
                       body={"agent_reference": {"name": agent_name, "type": "agent_reference"},
                             "input": json.dumps(document)})
        message = next((item for item in (body or {}).get("output") or [] if item.get("type") == "message"), None)
        if not message:
            raise HttpError("Microsoft Foundry", 0, "the agent returned no message")
        try:
            return json.loads(message["content"][0]["text"])
        except (KeyError, IndexError, ValueError):
            raise HttpError("Microsoft Foundry", 0, "the agent's answer is not the expected JSON") from None


class GitHub:
    """GitHub's REST API for one repository, with a fine-grained token for that repository only."""

    def __init__(self, repository: str, token: str, user_agent: str = "posture-function"):
        self.repository = repository
        self._headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": user_agent}

    def call(self, method: str, path: str, body=None):
        """A call relative to /repos/<owner>/<name>/, for example ("GET", "pulls/12")."""
        _, result = send("GitHub", method, f"{GITHUB}/repos/{self.repository}/{path}", headers=self._headers, body=body)
        return result

    def file(self, path: str, ref: str = "main") -> tuple[str, str]:
        """A file's text and blob sha on a branch."""
        found = self.call("GET", f"contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref, safe='')}")
        return base64.b64decode(found["content"]).decode("utf-8"), found["sha"]
