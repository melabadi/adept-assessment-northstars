"""Only the advisor's Logic Apps may call the Function's work routes, with their managed identity. No keys.

The Logic Apps call with a short-lived Microsoft Entra token for their user-assigned managed identity. Entra does not
issue tokens whose audience is a managed identity (AADSTS100040), and an app registration would be a tenant object
outside the resource group, so the token's audience is Azure Storage, a resource the Logic Apps' identity has no
role on: the token proves who is calling and grants nothing anywhere else. The Function checks the token itself
(signature against the tenant's published keys, issuer, audience, expiry, and the identity's object and client ids),
so the routes fail closed even if the platform's authentication settings change.
"""
from __future__ import annotations

import threading

CALLER_AUDIENCE = "https://storage.azure.com/"
_clients: dict = {}
_lock = threading.Lock()


class Unauthorized(PermissionError):
    pass


def _signing_key(tenant: str, token: str):
    import jwt

    with _lock:
        client = _clients.get(tenant)
        if client is None:
            client = _clients[tenant] = jwt.PyJWKClient(
                f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", cache_keys=True, lifespan=3600)
    return client.get_signing_key_from_jwt(token).key


def caller(authorization: str | None, tenant: str, client_id: str, principal: str, signing_key=None,
           audience: str = CALLER_AUDIENCE) -> dict:
    """The verified claims of the caller's token, or Unauthorized. signing_key is for tests."""
    import jwt

    if not (tenant and client_id and principal):
        raise Unauthorized("the Function is missing its caller settings")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("a bearer token is required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        key = signing_key or _signing_key(tenant, token)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=[audience, audience.rstrip("/")],
                            options={"require": ["exp", "iat", "aud", "iss"]})
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"invalid token: {type(exc).__name__}") from None
    issuers = {f"https://sts.windows.net/{tenant}/", f"https://login.microsoftonline.com/{tenant}/v2.0"}
    if claims.get("iss") not in issuers:
        raise Unauthorized("token from another tenant")
    if claims.get("oid") != principal or (claims.get("appid") or claims.get("azp")) != client_id:
        raise Unauthorized("only the advisor's Logic App identity may call this route")
    return claims
