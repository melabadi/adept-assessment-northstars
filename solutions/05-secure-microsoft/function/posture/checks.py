"""The posture Function's decisions, kept apart from all I/O so the offline tests exercise exactly what runs in Azure.

Who the automation acts for: on a public repository anyone can open a pull request from a fork, name a branch like the
remediation's, and comment. Only pull requests from this repository's branches, opened by its owner, members, or
collaborators, reach Azure; and a marker (on an Issue or a comment) counts only from them.

What the automation writes: the Foundry agent's proposal is model output, so `edit_problems` checks the edited file itself
before anything reaches GitHub. remediation_agent.py `try` imports this module, so it checks a proposal exactly as the
Function does.
"""
from __future__ import annotations

import hashlib
import hmac

# GitHub's author_association values for people the repository trusts. CONTRIBUTOR (someone whose pull request was
# merged), FIRST_TIME_CONTRIBUTOR, FIRST_TIMER, MANNEQUIN, and NONE (bots included) are outside contributors.
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")
STATUS_CONTEXT = "posture/what-if"
VERIFIED = "<!-- posture:verified -->"
DEFENDER_CONFIRMED = "<!-- posture:defender-confirmed -->"

# The edit the agent may propose. The guard is the result: everything outside the editable region stays byte-identical,
# and between the markers the edited file holds only // comments and one ALLOWED_LINES line, with lines split at LF and
# CR as Bicep's lexer splits them. Markers and the search text are matched without regard to case, which only makes the
# check stricter. The protected names are a second check on the agent's texts.
REGION = ("// posture:editable-begin", "// posture:editable-end")
ALLOWED_LINES = ("storageprivateendpoint: true", "storageprivateendpoint: false")
PROTECTED = ("automationRoleDefinitionIds", "automationAppRoleNames", "automationCanPushImages",
             "storageAllowSharedKeyAccess", "storagePrivateLinkPolicy", "effect:", "Microsoft.Authorization")
MAX_TEXT = 2000
# A pull request lists at most this many files per page; a bigger one is previewed, whatever it changes.
MAX_LISTED_FILES = 100


def trusted(item: dict | None) -> bool:
    """Whether GitHub says this Issue, pull request, or comment comes from the owner, a member, or a collaborator."""
    return (item or {}).get("author_association") in TRUSTED_AUTHORS


def same_repository(pull: dict, repository: str) -> bool:
    """Whether a pull request's branch is in this repository (only people with write access push there)."""
    head = (((pull.get("head") or {}).get("repo") or {}).get("full_name") or "")
    return bool(head) and head.lower() == repository.lower()


def outside_pull_request(pull: dict, repository: str) -> str | None:
    """Why a pull request must not reach Azure, or None. whatif.py applies the same rule in the job."""
    if not same_repository(pull, repository):
        return "its branch is in a fork"
    if not trusted(pull):
        return f"its author is outside the repository (author_association {pull.get('author_association') or 'unknown'})"
    return None


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub signs the raw request body with the webhook secret (X-Hub-Signature-256: sha256=<hex>)."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def webhook_number(event: str, payload: dict, repository: str) -> tuple[int | None, str]:
    """The pull request number a signed webhook delivery asks to preview, or None and the reason it is ignored.

    A fork's pull request, or one opened by anyone outside the repository, is dropped here, before any call to GitHub
    or Azure. Only the number goes further: the preview reads the pull request again from GitHub's API.
    """
    if event == "ping":
        return None, "ping"
    if event != "pull_request":
        return None, f"event {event or 'unknown'}"
    if ((payload.get("repository") or {}).get("full_name") or "").lower() != repository.lower():
        return None, "another repository"
    pull = payload.get("pull_request") or {}
    refused = outside_pull_request(pull, repository)
    if refused:
        return None, refused
    number = pull.get("number")
    if not isinstance(number, int) or number <= 0:
        return None, "no pull request number"
    return number, f"pull_request.{payload.get('action') or 'unknown'}"


def marker(name: str) -> str:
    return f"<!-- {name} -->"


def issues_for_finding(issues: list[dict], finding_marker: str) -> list[dict]:
    """This finding's Issues: the full marker in the body, filed by the owner, a member, or a collaborator (the
    automation's token is a person's), and not a pull request. GitHub lists the newest first."""
    text = marker(finding_marker)
    return [i for i in issues or [] if text in (i.get("body") or "") and not i.get("pull_request") and trusted(i)]


def marker_comments(comments: list[dict], text: str) -> list[dict]:
    """Comments that carry one of the automation's markers, from the owner, a member, or a collaborator only."""
    return [c for c in comments or [] if text in (c.get("body") or "") and trusted(c)]


def is_fix_for(pull: dict, issue_number: int, repository: str) -> bool:
    """Whether an open pull request is the remediation of this Issue: its branch posture/issue-<n>-..., in this
    repository. A fork can name its branch the same way; it must not pass for the fix."""
    ref = (pull.get("head") or {}).get("ref") or ""
    return ref.startswith(f"posture/issue-{issue_number}-") and same_repository(pull, repository)


def approved_private_endpoints(storage: dict) -> list[dict]:
    connections = (storage.get("properties") or {}).get("privateEndpointConnections") or []
    return [c for c in connections
            if (((c.get("properties") or {}).get("privateLinkServiceConnectionState") or {}).get("status")) == "Approved"]


def in_resource_group(scope: str | None, resource_group_id: str) -> bool:
    """Whether a scope is the resource group or below it. The trailing slash keeps rg-a2 out of rg-a."""
    return ((scope or "").lower() + "/").startswith(resource_group_id.lower() + "/")


def assignment_label(state: dict, resource_group_id: str) -> str:
    """How the automation names a policy assignment in what it posts. Only assignments in this solution's resource
    group, or below it, are named. One inherited from a management group or the subscription belongs to the tenant's
    governance, so it appears only as the kind of scope it comes from."""
    scope = state.get("policyAssignmentScope")
    if in_resource_group(scope, resource_group_id):
        return state.get("policyAssignmentName") or ""
    return "management group assignment" if "/managementgroups/" in (scope or "").lower() else "subscription assignment"


def needs_preview(statuses: list[dict]) -> bool:
    """Whether a commit still needs a what-if preview. GitHub lists a commit's statuses newest first: preview when
    posture/what-if never ran on it, or when its latest result is an error (Azure failed, not the template)."""
    previews = [s for s in statuses or [] if s.get("context") == STATUS_CONTEXT]
    return not previews or previews[0].get("state") == "error"


def touches_infra(files: list[dict], changed_files: int, prefix: str) -> bool:
    """Whether a pull request changes the solution's infra/ folder (or is too big to tell from one page of files)."""
    return any((f.get("filename") or "").startswith(prefix) for f in files or []) or changed_files > MAX_LISTED_FILES


def region(text: str) -> dict[str, int]:
    """Where the editable region is: its begin marker, the start of the line after it, and the end marker."""
    lower = text.lower()
    begin = lower.find(REGION[0].lower())
    anchor = max(begin, 0)
    return {"begin": begin, "beginLast": lower.rfind(REGION[0].lower()),
            "start": anchor + lower[anchor:].find("\n") + 1,
            "end": lower.find(REGION[1].lower()), "endLast": lower.rfind(REGION[1].lower())}


def edit_problems(content: str, proposal: dict, editable_path: str) -> list[str]:
    """Why the Function refuses to apply this proposal to `content`; an empty list means it applies it."""
    find, replace = proposal.get("find") or "", proposal.get("replace") or ""
    lower, needle = content.lower(), find.lower()
    position = lower.find(needle) if find else -1
    before = region(content)
    result = content.replace(find, replace) if find else content
    after = region(result)
    code = [line.strip() for line in result[after["start"]:max(after["end"], 0)].replace("\r", "\n").split("\n")
            if line.strip() and not line.strip().startswith("//")]
    problems = []
    if proposal.get("path") != editable_path:
        problems.append("it targets a file other than the solution's own Bicep file")
    if not find or find not in content or position != lower.rfind(needle):
        problems.append("its search text does not occur exactly once in the file")
    if not replace.strip():
        problems.append("its replacement is empty")
    if "\r" in replace:
        # Bicep ends a line, and a // comment, at a bare carriage return.
        problems.append("its replacement contains a carriage return, which Bicep reads as a line break")
    if find == replace:
        problems.append("it changes nothing")
    if len(find) > MAX_TEXT or len(replace) > MAX_TEXT:
        problems.append(f"its search or replacement text is longer than {MAX_TEXT:,} characters")
    if not (before["begin"] >= 0 and before["start"] > before["begin"] and before["end"] > before["start"]
            and content[:before["start"]] == result[:after["start"]]
            and content[max(before["end"], 0):] == result[max(after["end"], 0):]):
        problems.append("it changes text outside the lines between the posture:editable markers")
    if not (after["begin"] >= 0 and after["begin"] == after["beginLast"] and after["start"] > after["begin"]
            and after["end"] > after["start"] and after["end"] == after["endLast"]):
        problems.append("the result does not keep exactly one pair of posture:editable markers")
    if any(line.lower() not in ALLOWED_LINES for line in code):
        problems.append("between the markers, the result has a line that is neither a // comment nor "
                        "storagePrivateEndpoint: true or false")
    if len(code) != 1:
        problems.append("between the markers, the result must set storagePrivateEndpoint exactly once")
    if any(name.lower() in f"{find}\n{replace}".lower() for name in PROTECTED):
        problems.append("its text names a protected setting (roles, app roles, registry push, shared key access, or the "
                        "policy assignment or its effect)")
    return problems
