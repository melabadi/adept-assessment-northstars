"""Settings for this solution's scripts: environment variables first, then the solution's azd environment.

After `azd up` in solutions/02-design-microsoft, `azd env get-values` (run in that folder) holds every endpoint the
scripts need, so nobody exports anything by hand.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def azd_values() -> dict[str, str]:
    """Values of this solution's azd environment, or {} when azd is not installed or not initialized."""
    if not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=HERE)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def setting(name: str, default: str | None = None) -> str:
    """Environment variable first, then the azd environment, then the default; exits with a clear message if missing."""
    value = os.environ.get(name) or azd_values().get(name) or default
    if not value:
        raise SystemExit(f"error: {name} is not set. Run `azd up` in solutions/02-design-microsoft first, or export {name}.")
    return value


def credential():
    """Microsoft Entra ID sign-in: `az login` on your machine (the scripts and the azd hooks run as you). Tokens are
    shared across the Foundry, OpenAI, and Search clients, so the Azure CLI (which can need more than the SDK's default
    10 seconds) runs once per audience."""
    from azure.identity import DefaultAzureCredential

    return _SharedTokens(DefaultAzureCredential(process_timeout=60))


class _SharedTokens:
    """Caches one access token per scope until five minutes before it expires. Safe to share between threads."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._tokens: dict[tuple, object] = {}
        self._lock = threading.Lock()

    def get_token(self, *scopes: str, **kwargs):
        with self._lock:
            token = self._tokens.get(scopes)
            if token is None or token.expires_on - time.time() < 300 or kwargs.get("claims"):
                token = self._inner.get_token(*scopes, **kwargs)
                self._tokens[scopes] = token
            return token


def utf8_stdout() -> None:
    """Windows consoles default to a legacy code page; force UTF-8 so symbols in reports print correctly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
