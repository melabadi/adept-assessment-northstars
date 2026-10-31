"""The reviewer's two secrets, read from the solution's Key Vault with the Function's managed identity.

Neither the GitHub token nor the webhook secret is an app setting, which anyone who can change the Function could read
back. Bicep writes both to Key Vault through Azure Resource Manager; the vault takes no traffic from the internet, and
only the Function's identity can read its secrets (Key Vault Secrets User), through a private endpoint in the solution's
virtual network.

A value is kept in memory for 5 minutes, so a rotated token is in use within 5 minutes; a missing secret is checked
again after 30 seconds. Errors name the secret and the error's type, never a value or the vault's own message.
"""
from __future__ import annotations

import threading
import time

GITHUB_TOKEN = "github-review-token"
WEBHOOK_SECRET = "github-webhook-secret"


class VaultError(RuntimeError):
    """Key Vault couldn't be read. The message names the secret and the error's type."""


class Secrets:
    """read(name) returns a secret's value from Key Vault, or raises azure.core's ResourceNotFoundError when there is
    no such secret."""

    def __init__(self, read, keep_seconds: float = 300, recheck_missing_seconds: float = 30, clock=time.monotonic):
        self._read = read
        self._keep, self._recheck = keep_seconds, recheck_missing_seconds
        self._clock = clock
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # never a value
        return f"Secrets({sorted(self._cache)!r})"

    def get(self, name: str) -> str:
        """The secret's value, or "" when the vault has no such secret."""
        now = self._clock()
        with self._lock:
            hit = self._cache.get(name)
        if hit is not None and now - hit[1] < (self._keep if hit[0] else self._recheck):
            return hit[0]
        try:
            value = self._read(name) or ""
        except Exception as exc:
            if type(exc).__name__ != "ResourceNotFoundError":
                raise VaultError(f"couldn't read {name} from Key Vault: {type(exc).__name__}") from None
            value = ""
        with self._lock:
            self._cache[name] = (value, now)
        return value
