"""The real Azure and GitHub calls behind flow.py.

Azure: the function's managed identity, through azure-identity, reads runs from Azure Load Testing (Load Test Reader),
queries Log Analytics (Log Analytics Reader), and uses its own storage account through private endpoints: the queue of
report steps and the blob lease that lets one report post to GitHub at a time.
GitHub: the fine-grained token (this repository only, Issues read and write), which only Key Vault holds. The function
reads the github-token secret with its identity (Key Vault Secrets User) when a report step needs GitHub.

Nothing here logs a token or a request header. A GitHub error names the status, the call, and GitHub's message only.
"""
from __future__ import annotations

import json
import os
import re
import threading
from types import SimpleNamespace
from urllib.parse import quote

from . import report

LOAD_TESTING_SCOPE = "https://cnt-prod.loadtesting.azure.com/.default"
LOAD_TESTING_API = "2024-12-01-preview"
LOG_ANALYTICS_SCOPE = "https://api.loganalytics.io/.default"
LOG_ANALYTICS_URL = "https://api.loganalytics.azure.com/v1/workspaces/{workspace}/query"
GITHUB_API = "https://api.github.com"
GITHUB_TOKEN_SECRET = "github-token"
REPOSITORY = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
LOCK_CONTAINER = "reporter"
LOCK_BLOB = "github.lock"
TIMEOUT = 30
_lock = threading.Lock()
_shared: dict = {}


class ServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class GitHubError(ServiceError):
    pass


def _once(key, make):
    with _lock:
        if key not in _shared:
            _shared[key] = make()
        return _shared[key]


def credential():
    def make():
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return _once("credential", make)


def session():
    def make():
        import requests
        return requests.Session()
    return _once("session", make)


def _bearer(scope: str) -> dict:
    return {"Authorization": f"Bearer {credential().get_token(scope).token}"}


class Runs:
    """Test runs in Azure Load Testing's data plane."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip("/")

    def get(self, test_run_id: str) -> dict | None:
        response = session().get(f"{self.endpoint}/test-runs/{quote(test_run_id, safe='')}",
                                 params={"api-version": LOAD_TESTING_API}, headers=_bearer(LOAD_TESTING_SCOPE),
                                 timeout=TIMEOUT)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ServiceError(f"Azure Load Testing answered {response.status_code} for a test run", response.status_code)
        return response.json()


class Telemetry:
    """report.kql on the Log Analytics workspace that holds RequestHub's Application Insights data."""

    def __init__(self, workspace_id: str):
        self.url = LOG_ANALYTICS_URL.format(workspace=workspace_id)

    def server_rows(self, started, ended) -> list[dict]:
        response = session().post(self.url, json={"query": report.server_query(started, ended)},
                                  headers=_bearer(LOG_ANALYTICS_SCOPE), timeout=TIMEOUT)
        if response.status_code >= 400:
            raise ServiceError(f"Log Analytics answered {response.status_code}", response.status_code)
        body = response.json()
        if body.get("error"):
            raise ServiceError(f"Log Analytics returned an error: {body['error'].get('message', '')}")
        table = (body.get("tables") or [{}])[0]
        columns = [column["name"] for column in table.get("columns", [])]
        return [dict(zip(columns, row)) for row in table.get("rows", [])]


class Queue:
    """The queue of report steps. A step that has to wait becomes visible after its delay."""

    def __init__(self, endpoint: str, name: str):
        self.endpoint, self.name = endpoint, name

    def send(self, message: dict, delay: int) -> None:
        from azure.storage.queue import QueueClient, TextBase64EncodePolicy
        client = QueueClient(self.endpoint, self.name, credential=credential(),
                             message_encode_policy=TextBase64EncodePolicy())
        client.send_message(json.dumps(message), visibility_timeout=delay if delay > 0 else None)


class Lock:
    """A 60-second blob lease: one report posts to GitHub at a time. acquire() returns None while another holds it."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def acquire(self):
        from azure.core.exceptions import HttpResponseError
        from azure.storage.blob import BlobClient
        blob = BlobClient(self.endpoint, LOCK_CONTAINER, LOCK_BLOB, credential=credential())
        try:
            blob.upload_blob(b"", overwrite=False)
        except HttpResponseError as exc:
            if exc.status_code not in (409, 412):
                raise
        try:
            return blob.acquire_lease(lease_duration=60)
        except HttpResponseError as exc:
            if exc.status_code == 409:
                return None
            raise


class GitHub:
    """The repository's Issues, through GitHub's REST API with the fine-grained token."""

    def __init__(self, repository: str, token: str):
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("GITHUB_REPOSITORY must be owner/name")
        self.base = f"{GITHUB_API}/repos/{repository}/issues"
        self._token = token

    def _call(self, method: str, path: str = "", **kwargs):
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "requesthub-load-test-function"}
        response = session().request(method, self.base + path, headers=headers, timeout=TIMEOUT, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", "")
            except ValueError:
                detail = ""
            raise GitHubError(f"GitHub answered {response.status_code} to {method} issues{path}: {detail}",
                              response.status_code)
        return response.json()

    def open_issues(self, label: str) -> list[dict]:
        return self._call("GET", params={"state": "open", "labels": label, "per_page": 100})

    def comments(self, number: int, since: str | None = None) -> list[dict]:
        params = {"per_page": 100, **({"since": since} if since else {})}
        return self._call("GET", f"/{int(number)}/comments", params=params)

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self._call("POST", json={"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> dict:
        return self._call("POST", f"/{int(number)}/comments", json={"body": body})

    def close(self, number: int) -> dict:
        return self._call("PATCH", f"/{int(number)}", json={"state": "closed", "state_reason": "completed"})


def vault_secret(vault_uri: str, name: str) -> str:
    """A Key Vault secret, read with the function's identity; empty when the vault has no secret by that name."""
    identity = credential()  # outside _once: its lock isn't reentrant

    def make():
        from azure.keyvault.secrets import SecretClient
        return SecretClient(vault_uri, identity)
    client = _once(("vault", vault_uri), make)
    try:
        return client.get_secret(name).value or ""
    except Exception as exc:  # azure.core's ResourceNotFoundError: no token was set
        if getattr(exc, "status_code", None) == 404:
            return ""
        raise


def connect(env=None, github: bool = True) -> SimpleNamespace:
    """The services flow.py uses, from the function's app settings.

    `github` is None when the step doesn't need GitHub (the HTTP route), or when Key Vault holds no token yet.
    """
    env = os.environ if env is None else env
    client = None
    if github and env.get("GITHUB_REPOSITORY"):
        token = vault_secret(env["KEY_VAULT_URI"], GITHUB_TOKEN_SECRET)
        client = GitHub(env["GITHUB_REPOSITORY"], token) if token else None
    return SimpleNamespace(
        runs=Runs(env["LOAD_TESTING_ENDPOINT"]),
        telemetry=Telemetry(env["WORKSPACE_ID"]),
        queue=Queue(env["STORAGE_QUEUE_ENDPOINT"], env["QUEUE_NAME"]),
        lock=Lock(env["STORAGE_BLOB_ENDPOINT"]),
        github=client,
    )
