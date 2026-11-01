"""Microsoft Foundry and GitHub over HTTPS, with the standard library only.

Foundry: the project's OpenAI-compatible v1 API, the same calls the Foundry portal makes. The run asks the agent for
the brief in background mode (POST responses returns at once; GET responses/{id} until it's done), then runs the
evaluation (POST evals/{id}/runs; GET until it's done; GET its output items). The caller passes a function that returns
a Microsoft Entra access token for https://ai.azure.com: the Function app's managed identity, no key.

GitHub: the REST API with a fine-grained token limited to this repository. Errors carry GitHub's status and message,
never the request, so the token can't reach a log, an exception, or a run record. A request that couldn't be sent or got
no answer raises ServiceUnreachable, which names only the service and the kind of failure: Python's own errors can quote
a header (http.client rejects a header value with a line break by quoting it) or a host name.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

USER_AGENT = "ai-sdlc-plan-microsoft"
GITHUB_API = "https://api.github.com"
# What GitHub vouches for: on a public repository anyone else can open an Issue or a pull request, or copy a marker.
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")


def trusted(item: dict | None) -> bool:
    """Whether GitHub says the Issue's or pull request's author is the repository's owner, a member, or a collaborator."""
    return (item or {}).get("author_association") in TRUSTED_AUTHORS


def same_repository(pull: dict, repository: str) -> bool:
    """Whether a pull request's branch is in this repository, not a fork: only people with write access push there."""
    head = (((pull.get("head") or {}).get("repo") or {}).get("full_name") or "")
    return bool(head) and head.lower() == repository.lower()


class TokenMissing(Exception):
    """No usable GitHub token. The message never contains the token."""


def github_token(raw: str | None) -> str:
    """The token as GitHub expects it: surrounding spaces and line breaks are dropped (a pasted token often ends with
    one), and a token with any inside is refused, without quoting it."""
    token = (raw or "").strip()
    if not token:
        raise TokenMissing("Key Vault has no GitHub token yet: set PLAN_GITHUB_TOKEN in the azd environment and run "
                           "`azd provision` (README, Set up)")
    if any(char.isspace() or not char.isprintable() for char in token):
        raise TokenMissing("the GitHub token in Key Vault contains spaces or control characters: set PLAN_GITHUB_TOKEN "
                           "again and run `azd provision` (README, Set up)")
    return token


class ServiceError(Exception):
    """A service answered with an error status. str() names the service, the status, and the service's message."""

    def __init__(self, service: str, status: int, message: str):
        super().__init__(f"{service} answered HTTP {status}: {message}")
        self.service, self.status, self.message = service, status, message


class ServiceUnreachable(OSError):
    """A request couldn't be sent, or got no answer. str() names the service and the kind of failure, nothing else."""

    def __init__(self, service: str, kind: str):
        super().__init__(f"{service} didn't answer ({kind})")
        self.service, self.kind = service, kind


def failure_kind(error: BaseException) -> str:
    """The type of a failure, and of its cause for a URLError (for example "URLError: TimeoutError"): never its text."""
    reason = getattr(error, "reason", None)
    if isinstance(error, urllib.error.URLError) and isinstance(reason, BaseException):
        return f"{type(error).__name__}: {type(reason).__name__}"
    return type(error).__name__


def exchange(service: str, transport, method: str, url: str, headers: dict[str, str], body=None):
    """Calls the transport. Any exception becomes a ServiceUnreachable raised outside the handler, so it carries no
    chained exception that could quote the request."""
    try:
        return transport(method, url, headers, body)
    except Exception as error:  # noqa: BLE001 - every failure is reported the same way, without its text
        kind = failure_kind(error)
    raise ServiceUnreachable(service, kind)

def send(method: str, url: str, headers: dict[str, str], body=None, timeout: float = 60) -> tuple[int, str, dict]:
    """One HTTPS call. Returns (status, response text, response headers); an error status is returned, not raised."""
    data = None
    headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace"), dict(error.headers or {})


def error_message(text: str) -> str:
    """The service's own message from an error body: {"message": ...} (GitHub) or {"error": {"message": ...}} (Foundry)."""
    try:
        payload = json.loads(text)
    except ValueError:
        return text.strip()[:200] or "no message"
    if isinstance(payload, dict):
        inner = payload.get("error")
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner["message"])[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
    return "no message"


class Foundry:
    def __init__(self, endpoint: str, token: Callable[[], str], transport=send):
        self.base = endpoint.rstrip("/") + "/openai/v1"
        self.token = token
        self.transport = transport

    def call(self, method: str, path: str, body=None) -> dict:
        headers = {"Authorization": f"Bearer {self.token()}", "User-Agent": USER_AGENT}
        status, text, _ = exchange("Foundry", self.transport, method, self.base + path, headers, body)
        if status >= 400:
            raise ServiceError("Foundry", status, error_message(text))
        return json.loads(text) if text else {}

    def start_response(self, agent: str, prompt: str) -> dict:
        """Runs the agent's latest version in background mode: the answer comes back with status queued."""
        return self.call("POST", "/responses", {
            "agent_reference": {"type": "agent_reference", "name": agent},
            "input": prompt,
            "background": True,
        })

    def response(self, response_id: str) -> dict:
        return self.call("GET", f"/responses/{urllib.parse.quote(response_id)}")

    def evaluation_id(self, name: str) -> str | None:
        """The newest evaluation with this name: setup_foundry.py creates a new one when the evaluators change."""
        listed = self.call("GET", "/evals?limit=100&order=desc")
        return next((e.get("id") for e in listed.get("data") or [] if e.get("name") == name), None)

    def start_evaluation_run(self, evaluation_id: str, name: str, items: list[dict]) -> dict:
        return self.call("POST", f"/evals/{evaluation_id}/runs", {
            "name": name,
            "data_source": {"type": "jsonl", "source": {"type": "file_content", "content": items}},
        })

    def evaluation_run(self, evaluation_id: str, run_id: str) -> dict:
        return self.call("GET", f"/evals/{evaluation_id}/runs/{run_id}")

    def output_items(self, evaluation_id: str, run_id: str) -> list[dict]:
        return self.call("GET", f"/evals/{evaluation_id}/runs/{run_id}/output_items?limit=20").get("data") or []


def answer_text(response: dict) -> str | None:
    """The text of the agent's last message in a completed response."""
    messages = [item for item in response.get("output") or [] if item.get("type") == "message"]
    if not messages:
        return None
    content = messages[-1].get("content") or []
    return content[0].get("text") if content else None


class GitHub:
    def __init__(self, repository: str, token: str, transport=send):
        self.repository = repository
        self._token = github_token(token)
        self.transport = transport

    def __repr__(self) -> str:  # never shows the token
        return f"GitHub({self.repository!r})"

    def call(self, method: str, path: str, body=None, accept: str = "application/vnd.github+json") -> tuple[object, dict]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        status, text, response_headers = exchange("GitHub", self.transport, method,
                                                  f"{GITHUB_API}/repos/{self.repository}{path}", headers, body)
        if status >= 400:
            raise ServiceError("GitHub", status, error_message(text))
        if accept.endswith("raw+json"):
            return text, response_headers
        return (json.loads(text) if text else None), response_headers

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self.call("POST", "/issues", {"title": title, "body": body, "labels": labels})[0]

    def issue(self, number: int) -> dict:
        return self.call("GET", f"/issues/{number}")[0]

    def comment(self, number: int, body: str) -> None:
        self.call("POST", f"/issues/{number}/comments", {"body": body})

    def close(self, number: int, reason: str) -> None:
        self.call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": reason})

    def add_sub_issue(self, parent: int, child_id: int) -> None:
        self.call("POST", f"/issues/{parent}/sub_issues", {"sub_issue_id": child_id})

    def add_blocked_by(self, number: int, blocker_id: int) -> None:
        self.call("POST", f"/issues/{number}/dependencies/blocked_by", {"issue_id": blocker_id})

    def read_file(self, path: str, ref: str) -> str:
        query = urllib.parse.urlencode({"ref": ref})
        return self.call("GET", f"/contents/{path}?{query}", accept="application/vnd.github.raw+json")[0]

    def pull_request(self, number: int) -> dict:
        """The pull request, with its author's association and its branch's repository (Contents or Pull requests: read)."""
        return self.call("GET", f"/pulls/{number}")[0]

    def list_issues(self, labels: list[str]) -> list[dict]:
        """The newest 50 Issues with all these labels, open or closed, newest first. Pull requests can carry labels
        too: the caller tells them apart by their pull_request field."""
        query = urllib.parse.urlencode({"labels": ",".join(labels), "state": "all", "sort": "created",
                                        "direction": "desc", "per_page": 50})
        issues, _ = self.call("GET", f"/issues?{query}")
        return issues or []

    def check(self) -> dict:
        """Whether GitHub accepts the token, and when it expires (GitHub sends the date for fine-grained tokens)."""
        status, text, headers = exchange("GitHub", self.transport, "GET", f"{GITHUB_API}/repos/{self.repository}/issues?per_page=1", {
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": USER_AGENT}, None)
        expires = next((v for k, v in headers.items() if k.lower() == "github-authentication-token-expiration"), None)
        return {"status": status, "expires": expires, "error": error_message(text) if status >= 400 else None}
