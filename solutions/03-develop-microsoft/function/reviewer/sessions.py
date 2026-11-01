"""Azure Container Apps dynamic sessions: one Shell session in a pool, reached through the pool's data plane.

The Function authenticates with its managed identity (audience https://dynamicsessions.io); no GitHub token, key, or
secret ever reaches a session. A session cuts a command's output after 4 KB (the first 4,093 bytes, then "..."), so
results travel as files: a command writes its result in the session and prints only a short status line, and
download() reads the whole file.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "api-version=2025-10-02-preview"
DELETE_API = "api-version=2025-02-02-preview"
SCOPE = "https://dynamicsessions.io/.default"


class SessionError(RuntimeError):
    """A session call failed. The message names the call and the HTTP status."""


def _default_open(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


class Session:
    """One session, named by its identifier. The pool creates it on first use."""

    def __init__(self, pool_endpoint: str, identifier: str, token, open_url=_default_open, sleep=time.sleep):
        self.endpoint = pool_endpoint.rstrip("/")
        self.identifier = identifier
        self.used = False  # True once a call may have created the session
        self._token = token  # () -> bearer token for the sessions data plane
        self._open = open_url
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"Session({self.identifier!r})"

    def _call(self, what: str, method: str, path: str, query: str = "", data: bytes | None = None,
              content_type: str | None = None, timeout: float = 120, retries: int = 2, api: str = API) -> bytes:
        url = f"{self.endpoint}/{path}?{api}&identifier={urllib.parse.quote(self.identifier, safe='')}{query}"
        if method != "DELETE":
            self.used = True
        for attempt in range(retries + 1):
            headers = {"Authorization": f"Bearer {self._token()}"}
            if content_type:
                headers["Content-Type"] = content_type
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._open(request, timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < retries:
                    self._sleep(3 * (attempt + 1))
                    continue
                raise SessionError(f"{what} in {self.identifier}: HTTP {exc.code}") from None
            except (urllib.error.URLError, OSError) as exc:
                if attempt < retries:
                    self._sleep(3 * (attempt + 1))
                    continue
                raise SessionError(f"{what} in {self.identifier}: {type(exc).__name__}") from None
        raise SessionError(f"{what} in {self.identifier}: no answer")  # pragma: no cover

    def upload(self, name: str, data: bytes) -> None:
        """Puts a file in /mnt/data."""
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode()
        self._call(f"upload {name}", "POST", "files", data=body, content_type=f"multipart/form-data; boundary={boundary}",
                   timeout=300)

    def execute(self, command: str, timeout: int) -> dict:
        """Runs a shell command. Returns {"status": exit code as text, "stdout": ..., "stderr": ...}; both outputs are cut
        after 4 KB, so never read a result from them."""
        raw = self._call("run a command", "POST", "executions", content_type="application/json", timeout=timeout + 60,
                         data=json.dumps({"shellCommand": command, "timeoutInSeconds": timeout}).encode("utf-8"))
        try:
            answer = json.loads(raw)
        except ValueError:
            raise SessionError(f"run a command in {self.identifier}: the answer isn't JSON") from None
        result = answer.get("result") or {}
        return {"status": str(answer.get("status", "")), "stdout": str(result.get("stdout") or ""),
                "stderr": str(result.get("stderr") or "")}

    def download(self, name: str, path: str | None = None) -> bytes:
        """Reads a whole file from /mnt/data (or /mnt/data/<path>)."""
        query = f"&path={urllib.parse.quote(path, safe='')}" if path else ""
        return self._call(f"read {f'{path}/' if path else ''}{name}", "GET",
                          f"files/{urllib.parse.quote(name, safe='')}/content", query=query)

    def delete(self) -> None:
        """Deletes the session and everything in it."""
        self._call("delete the session", "DELETE", "session", api=DELETE_API, retries=1, timeout=60)
