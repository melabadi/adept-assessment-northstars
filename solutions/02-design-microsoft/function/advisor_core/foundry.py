"""Ask an advisor agent in Microsoft Foundry, through the project's Responses API, with the Function's managed identity
(audience https://ai.azure.com), the way the agent's Playground and the evaluations ask it.

ask() names the agent, not a version: Foundry answers with the agent's latest version, and the response's
agent_reference says which version answered. The gate then checks the answer against that version's scope.
A throttled or failing call is tried again twice. Errors name the HTTP status or the error's type, never a URL, a
header, or a token.
"""
from __future__ import annotations

import time

import requests

SCOPE = "https://ai.azure.com/.default"
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)
MAX_OUTPUT_TOKENS = 8000  # an answer uses about 1,000 to 2,000 tokens, reasoning included


class FoundryError(RuntimeError):
    """The agent couldn't be asked. The message names the HTTP status or the error's type."""


def ask(project_endpoint: str, agent: str, question: str, token, session=None, sleep=time.sleep, attempts: int = 3,
        timeout: float = 150) -> dict:
    """The Responses API's result for one question to the named agent. token: () -> a bearer token for Foundry."""
    http = session or requests
    url = f"{project_endpoint.rstrip('/')}/openai/v1/responses"
    body = {"input": question, "agent_reference": {"type": "agent_reference", "name": agent},
            "max_output_tokens": MAX_OUTPUT_TOKENS}
    problem = "no attempt"
    for attempt in range(1, attempts + 1):
        try:
            response = http.post(url, json=body, headers={"Authorization": f"Bearer {token()}"}, timeout=timeout)
        except requests.RequestException as exc:  # its message holds the URL: keep only the type
            problem = type(exc).__name__
        else:
            if response.status_code < 300:
                try:
                    data = response.json()
                except ValueError:
                    data = None
                if not isinstance(data, dict):
                    raise FoundryError("Foundry's answer is not a JSON object")
                return data
            problem = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUSES:
                raise FoundryError(f"Foundry refused the question: {problem}")
        if attempt < attempts:
            sleep(10 * attempt)
    raise FoundryError(f"Foundry didn't answer after {attempts} attempts: {problem}")
