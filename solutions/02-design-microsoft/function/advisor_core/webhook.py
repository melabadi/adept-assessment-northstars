"""GitHub webhooks for the advisor: verify the signature, read the issue form, and decide what Azure does.

Two events start work in Azure, everything else is acknowledged and ignored:
  - issues (opened with, or labeled, design-advisor) whose author is the repository's owner, a member, or a
    collaborator: the advisor workflow answers the question.
  - push to the default branch that changes the standards, agent.yaml, or the evaluation cases: the standards
    workflow re-indexes, re-publishes the agents, and re-runs the evaluation (the optional step of the demo).

On a public repository anyone can open an Issue, and the issue form applies the design-advisor label for them, so the
label alone proves nothing. GitHub computes the author's association with the repository and signs the delivery; an
Issue from anyone else starts nothing in Azure, even when someone with triage access labels it later.
"""
from __future__ import annotations

import hashlib
import hmac
import re

LABEL = "design-advisor"
PROFILES = ("small-team", "enterprise")
SOLUTION = "solutions/02-design-microsoft/"
WATCHED = (SOLUTION + "standards/", SOLUTION + "agent.yaml", SOLUTION + "eval_cases.jsonl")
MAX_QUESTION = 4000
# GitHub's author_association values for people the repository trusts. CONTRIBUTOR (someone whose pull request was
# merged), FIRST_TIME_CONTRIBUTOR, FIRST_TIMER, MANNEQUIN, and NONE (bots included) are outside contributors.
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub signs the raw request body with the webhook secret (X-Hub-Signature-256: sha256=<hex>)."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def parse_issue_form(body: str) -> tuple[str, str]:
    """(profile, question) from the issue form's Markdown. An unknown or missing profile falls back to enterprise,
    the stricter one; a body without the form's headings is the question itself."""
    def section(heading: str) -> str:
        match = re.search(rf"(?ms)^###\s+{heading}\s*\n(.*?)(?=^###\s|\Z)", body or "")
        text = match.group(1).strip() if match else ""
        return "" if text == "_No response_" else text

    profile = section("Operating profile")
    question = section("Question") or (body or "").strip()
    return (profile if profile in PROFILES else "enterprise"), question[:MAX_QUESTION]


def classify(event: str, payload: dict, repo: str) -> dict:
    """What a delivery asks Azure to do: {"route": "advisor" | "standards" | "ignore", ...}."""
    def ignore(reason: str) -> dict:
        return {"route": "ignore", "reason": reason}

    if event == "ping":
        return ignore("ping")
    if (payload.get("repository") or {}).get("full_name", "").lower() != repo.lower():
        return ignore("another repository")
    if event == "issues":
        issue, action = payload.get("issue") or {}, payload.get("action")
        labels = {label.get("name") for label in issue.get("labels") or []}
        asked = (action == "opened" and LABEL in labels) or (action == "labeled" and (payload.get("label") or {}).get("name") == LABEL)
        if not asked:
            return ignore(f"issues.{action} without the {LABEL} label")
        association = issue.get("author_association") or "unknown"
        if association not in TRUSTED_AUTHORS:
            return ignore(f"asked by an outside contributor (author_association {association}); only the repository's "
                          "owner, members, and collaborators start the advisor")
        if "pull_request" in issue or issue.get("state") != "open":
            return ignore("not an open issue")
        profile, question = parse_issue_form(issue.get("body") or "")
        if not question:
            return ignore("empty question")
        return {"route": "advisor", "issue": int(issue["number"]), "title": issue.get("title", ""), "profile": profile,
                "question": question}
    if event == "push":
        default = (payload.get("repository") or {}).get("default_branch", "main")
        if payload.get("ref") != f"refs/heads/{default}" or payload.get("deleted"):
            return ignore("not a push to the default branch")
        changed = set()
        for commit in (payload.get("commits") or []) + [payload.get("head_commit") or {}]:
            for key in ("added", "modified", "removed"):
                changed.update(commit.get(key) or [])
        watched = sorted(path for path in changed if path.startswith(WATCHED))
        if not watched:
            return ignore("no standard, agent.yaml, or evaluation case changed")
        sha = payload.get("after", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            return ignore("no commit")
        return {"route": "standards", "sha": sha, "files": watched[:50]}
    return ignore(f"event {event}")
