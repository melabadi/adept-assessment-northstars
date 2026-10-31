"""GitHub's pull_request webhook: check the delivery, decide whether it asks for a review, and say why not.

GitHub signs every delivery with the webhook secret (X-Hub-Signature-256), so an unsigned or wrongly signed request is
refused before anything else. Even a signed payload is used only to filter: the review takes the pull request's number
from it, then reads the pull request, its branch's repository, its state, and its labels from GitHub's API.

A review starts only for this repository's branches (a fork's code never reaches a session or the agent, not even in a
dry run) and, for a real review, only on an open, non-draft pull request into the default branch that carries the
review label. Only people with triage access can apply labels, so nobody outside the repository can start a review.
"""
from __future__ import annotations

import hashlib
import hmac
import json

LABEL_ACTIONS = ("synchronize", "reopened", "ready_for_review")


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub signs the raw request body with the webhook secret: X-Hub-Signature-256: sha256=<hex>."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def triage(event: str, payload: dict, repository: str, label: str) -> tuple[int | None, str]:
    """(pull request number, why) when the delivery asks for a review, else (None, why not)."""
    if event == "ping":
        return None, "ping"
    if event != "pull_request":
        return None, f"event {event or 'unknown'}"
    if str((payload.get("repository") or {}).get("full_name", "")).lower() != repository.lower():
        return None, "another repository"
    pull, action = payload.get("pull_request") or {}, str(payload.get("action") or "")
    number = pull.get("number")
    if not isinstance(number, int) or number < 1:
        return None, "no pull request number"
    if action == "labeled":
        name = str((payload.get("label") or {}).get("name", ""))
        if name != label:
            return None, f"labeled {name}, not {label}"
    elif action in LABEL_ACTIONS:
        if label not in {str(item.get("name")) for item in pull.get("labels") or [] if isinstance(item, dict)}:
            return None, f"{action} on a pull request without the {label} label"
    else:
        return None, f"action {action or 'unknown'}"
    return number, f"pull_request.{action}"


def eligibility(pull: dict, repository: str, label: str, dry_run: bool) -> str | None:
    """Why the pull request, as read from GitHub's API, can't be reviewed; None when it can."""
    head_repo = str(((pull.get("head") or {}).get("repo") or {}).get("full_name") or "")
    if head_repo.lower() != repository.lower():
        return "its branch isn't in this repository: a fork's pull request is never built or reviewed"
    if dry_run:
        return None
    base = pull.get("base") or {}
    default = str((base.get("repo") or {}).get("default_branch") or "")
    labels = {str(item.get("name")) for item in pull.get("labels") or [] if isinstance(item, dict)}
    if pull.get("state") != "open":
        return "it isn't open"
    if pull.get("draft") is not False:
        return "it's a draft"
    if not default or base.get("ref") != default:
        return f"it targets {base.get('ref')}, not the default branch {default}"
    if label not in labels:
        return f"it doesn't carry the {label} label"
    return None


def intake(headers: dict, body: bytes, *, secret: str, repository: str, label: str, read_pull, new_id) -> tuple[int, dict, dict | None]:
    """What the webhook function does with one delivery: (HTTP status, response, queue message or None).

    read_pull(number) reads the pull request from GitHub's API; new_id() names the review."""
    lower = {str(k).lower(): v for k, v in headers.items()}
    if not secret:
        return 503, {"error": "the reviewer has no webhook secret yet: run azd provision"}, None
    if not verify_signature(secret, body, lower.get("x-hub-signature-256")):
        return 401, {"error": "invalid signature"}, None
    event = str(lower.get("x-github-event") or "")
    try:
        payload = json.loads(body)
    except ValueError:
        return 400, {"error": "the body isn't JSON"}, None
    if not isinstance(payload, dict):
        return 400, {"error": "the body isn't a JSON object"}, None
    number, reason = triage(event, payload, repository, label)
    if number is None:
        return 200, {"result": "ignored", "reason": reason}, None
    try:
        pull = read_pull(number)
    except Exception as exc:  # GitHubError names the call and the status; anything else, only its type
        detail = str(exc) if exc.__class__.__name__ == "GitHubError" else type(exc).__name__
        return 502, {"error": f"couldn't read pull request #{number} from GitHub: {detail}"}, None
    refusal = eligibility(pull, repository, label, dry_run=False)
    if refusal:
        return 200, {"result": "ignored", "reason": f"#{number}: {refusal}"}, None
    review_id = new_id()
    message = {"id": review_id, "pr": number, "dryRun": False, "event": reason,
               "delivery": str(lower.get("x-github-delivery") or "")[:64]}
    return 202, {"result": f"review {review_id} of #{number} queued"}, message
