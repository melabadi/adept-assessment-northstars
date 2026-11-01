"""The reviewer agent in Microsoft Foundry, called through the project's Responses API with the Function's managed
identity (audience https://ai.azure.com).

The agent runs in background mode, and the Function polls for its answer, so a long review never hits an HTTP timeout.
If the answer doesn't complete (for example when a content filter flags text from the pull request), the agent is asked
once more. The rule results never depend on the agent: without an answer, the review still posts them.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

SCOPE = "https://ai.azure.com/.default"
WAITING = ("queued", "in_progress")


class AgentError(RuntimeError):
    """A call to Foundry failed. The message names the call and the HTTP status."""


def _default_open(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


class Agent:
    def __init__(self, project_endpoint: str, name: str, token, open_url=_default_open, sleep=time.sleep,
                 clock=time.monotonic):
        self.endpoint = project_endpoint.rstrip("/")
        self.name = name
        self._token = token  # () -> bearer token for Foundry
        self._open = open_url
        self._sleep = sleep
        self._clock = clock

    def _call(self, what: str, method: str, path: str, body: dict | None = None, retries: int = 2) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(retries + 1):
            headers = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
            request = urllib.request.Request(f"{self.endpoint}/{path}", data=data, method=method, headers=headers)
            try:
                with self._open(request, 120) as response:
                    answer = json.loads(response.read() or b"{}")
                    return answer if isinstance(answer, dict) else {}
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < retries:
                    self._sleep(5 * (attempt + 1))
                    continue
                raise AgentError(f"{what}: HTTP {exc.code}") from None
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if attempt < retries:
                    self._sleep(5 * (attempt + 1))
                    continue
                raise AgentError(f"{what}: {type(exc).__name__}") from None
        raise AgentError(f"{what}: no answer")  # pragma: no cover

    def _once(self, request: dict, wait_seconds: float, poll_seconds: float) -> dict:
        response = self._call("ask the agent", "POST", "openai/v1/responses", {
            "agent_reference": {"type": "agent_reference", "name": self.name},
            "input": json.dumps(request, ensure_ascii=False),
            "background": True,
        })
        deadline = self._clock() + wait_seconds
        while response.get("status") in WAITING and self._clock() < deadline:
            self._sleep(poll_seconds)
            response = self._call("read the agent's answer", "GET", f"openai/v1/responses/{response.get('id', '')}")
        return response

    def ask(self, request: dict, wait_seconds: float = 600, poll_seconds: float = 5) -> tuple[dict, str]:
        """(the Responses API result, its status). Asks once more if the first answer didn't complete. Never raises:
        a failed call is returned as its status, "error: <what failed>", with the last answer the agent gave, if any."""
        response, status = {}, ""
        for _ in range(2):
            try:
                answer = self._once(request, wait_seconds, poll_seconds)
                response, status = answer, str(answer.get("status") or "missing")
            except AgentError as exc:
                status = f"error: {exc}"
            if status == "completed":
                break
        return response, status
