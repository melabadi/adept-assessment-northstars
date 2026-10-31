"""What the posture Function does, step by step. Each flow takes its connections as arguments: clients.Azure and
clients.GitHub in Azure, fakes in the offline tests.

  intake   A Defender for Cloud recommendation for RequestHub's storage account, forwarded by the Logic App
           posture-intake. Unhealthy: file or reuse the Issue, ask the Foundry agent for the smallest Bicep fix, check
           the edited file, open it as a draft pull request, and start its preview. Healthy: record Defender's
           confirmation on the Issue.
  preview  A pull request from this repository's branches, opened by its owner, a member, or a collaborator, that
           changes the solution's infra/: start the posture-whatif job, which posts the preview and the commit status.
  verify   Once the storage account has an approved private endpoint: wait for Azure Policy to report it compliant,
           record each source's evidence on the Issue, and close it.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import checks, messages
from .clients import HttpError

log = logging.getLogger("posture")
# Defender's workflow automation can report Healthy before the assessment Azure returns does. For this long after the
# event, intake asks to be called again (the Logic App retries) rather than act on the older status.
HEALTHY_GRACE = timedelta(minutes=10)
# The agent's answer is model output and can miss the checks (it rewrites a marker line, or drops indentation, so its
# search text is not in the file). It gets this many tries, told each time why the last was refused, and no new try
# after this many seconds, so intake answers the Logic App within its 120-second limit.
AGENT_ATTEMPTS = 3
AGENT_BUDGET = 45
_preview_lock = threading.Lock()


class Retry(Exception):
    """Not yet: the route answers 503, and the Logic App's retry policy sends the recommendation again later."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(assessment: dict | None) -> str:
    return (((assessment or {}).get("properties") or {}).get("status") or {}).get("code") or ""


def _age(timestamp: str | None, now: datetime) -> timedelta:
    try:
        return now - messages.parse_utc(timestamp or "")
    except ValueError:
        return HEALTHY_GRACE  # no usable time: treat the event as old, so the run ends


def _compliant(states: list[dict]) -> bool:
    return bool(states) and states[0].get("complianceState") == "Compliant"


def _definition_filter(s) -> str:
    return f"resourceId eq '{s.storage_account_id}' and policyDefinitionName eq '{s.policy_definition_name}'"


def _assignment_filter(s) -> str:
    return f"resourceId eq '{s.storage_account_id}' and policyAssignmentName eq '{s.policy_assignment_name}'"


# ---------------------------------------------------------------- intake
def intake(event: dict, s, azure, github, now=_now, sleep=time.sleep) -> dict:
    """event: what the Logic App kept from Defender's: resourceId, assessment, status, triggeredAt. Only the first two
    choose what to read; the recommendation's status and text are read again from Azure."""
    if ((event.get("resourceId") or "").lower() != s.storage_account_id.lower()
            or (event.get("assessment") or "").lower() != s.assessment_key.lower()):
        return {"result": "ignored: another resource or recommendation"}
    assessment = azure.assessment(s.storage_account_id, s.assessment_key)
    if event.get("status") == "Healthy" and _status(assessment) != "Healthy":
        for _ in range(3):
            sleep(10)
            assessment = azure.assessment(s.storage_account_id, s.assessment_key)
            if _status(assessment) == "Healthy":
                break
        else:
            if _age(event.get("triggeredAt"), now()) < HEALTHY_GRACE:
                raise Retry("Defender for Cloud reported Healthy, and Azure does not return it yet")
    status = _status(assessment)
    if status == "Unhealthy":
        return _file_finding(assessment, s, azure, github, now)
    if status == "Healthy":
        return _record_confirmation(assessment, s, github)
    return {"result": f"the recommendation's status is {status or 'unknown'}: nothing to do"}


def _file_finding(assessment: dict, s, azure, github, now) -> dict:
    storage = azure.storage_account(s.storage_account_id)
    if checks.approved_private_endpoints(storage):
        return {"result": "the storage account already has an approved private endpoint: Defender for Cloud has not "
                          "reassessed it since the fix. Nothing to file."}
    states = azure.policy_states(s.resource_group_id, _definition_filter(s))
    stamp = messages.utc(now())
    issues = checks.issues_for_finding(github.call("GET", "issues?labels=posture&state=open&per_page=50"), s.marker)
    if issues:
        number, filed = issues[0]["number"], False
    else:
        created = github.call("POST", "issues", {
            "title": messages.issue_title(s.resource_group_name),
            "body": messages.issue_body(s.resource_group_name, s.resource_group_id, assessment, storage, states, s.marker,
                                        stamp),
            "labels": ["posture"]})
        number, filed = created["number"], True
    result = {"issue": number, "filed": filed}

    fixes = [p for p in github.call("GET", "pulls?state=open&per_page=50") if checks.is_fix_for(p, number, s.repository)]
    if fixes:
        github.call("POST", f"issues/{number}/comments", {"body": messages.existing_fix_comment(fixes[0]["number"])})
        return {**result, "result": "a draft fix is already open", "pullRequest": fixes[0]["number"]}

    editable, editable_sha = github.file(s.editable_path)
    module, _ = github.file(s.module_path)
    document = messages.agent_document(assessment, storage, states, s.resource_group_name, s.resource_group_id,
                                       (s.editable_path, editable), [(s.module_path, module)])
    proposal, problems, attempts = _ask_for_an_applicable_edit(azure, s, document, editable)
    result["agentAttempts"] = attempts
    if proposal.get("decision") != "change" or problems:
        github.call("POST", f"issues/{number}/comments",
                    {"body": messages.rejected_comment(s.agent_name, proposal, problems, attempts)})
        return {**result, "result": "the agent's proposal was not applied", "problems": problems}

    branch = f"posture/issue-{number}-{now():%m%d%H%M}"
    main = github.call("GET", "git/ref/heads/main")
    github.call("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": main["object"]["sha"]})
    fixed = editable.replace(proposal["find"], proposal["replace"])
    github.call("PUT", f"contents/{urllib.parse.quote(s.editable_path)}", {
        "message": messages.commit_message(proposal, number),
        "content": base64.b64encode(fixed.encode("utf-8")).decode("ascii"),
        "sha": editable_sha, "branch": branch})
    pull = github.call("POST", "pulls", {
        "title": messages.pull_request_title(proposal), "head": branch, "base": "main", "draft": True,
        "body": messages.pull_request_body(proposal, number, s.agent_name)})
    try:
        started = preview(pull["number"], s, azure, github)["started"]
    except Exception as exc:  # the pull request stands; the next push starts the preview again
        log.warning("intake: the preview of pull request #%s did not start: %s", pull["number"], exc)
        started = False
    github.call("POST", f"issues/{number}/comments",
                {"body": messages.draft_fix_comment(s.agent_name, pull["number"], started)})
    return {**result, "result": "drafted a fix", "pullRequest": pull["number"], "previewStarted": started}


def _ask_for_an_applicable_edit(azure, s, document: dict, editable: str, clock=time.monotonic) -> tuple[dict, list, int]:
    """The agent's proposal, checked. A refused answer goes back to the agent with its problems (rejectedProposals in
    the document), up to AGENT_ATTEMPTS times and while AGENT_BUDGET seconds allow another call: every attempt meets the
    same checks, so retrying weakens none. Returns the last proposal, its problems, and the number of attempts."""
    started, rejected = clock(), []
    for attempt in range(1, AGENT_ATTEMPTS + 1):
        asked = {**document, "rejectedProposals": list(rejected)} if rejected else document
        proposal = azure.ask_agent(s.foundry_project_endpoint, s.agent_name, asked)
        decision = proposal.get("decision")
        if decision == "no_change":
            return proposal, [], attempt
        problems = (checks.edit_problems(editable, proposal, s.editable_path) if decision == "change"
                    else ["its decision is neither change nor no_change"])
        if not problems:
            return proposal, [], attempt
        log.info("intake: the agent's answer %s was refused: %s", attempt, "; ".join(problems))
        rejected.append({"find": proposal.get("find"), "replace": proposal.get("replace"), "problems": problems})
        if clock() - started > AGENT_BUDGET:
            break
    return proposal, problems, attempt


def _record_confirmation(assessment: dict, s, github) -> dict:
    issues = checks.issues_for_finding(github.call("GET", "issues?labels=posture&state=all&per_page=20"), s.marker)
    if not issues:
        return {"result": "Defender for Cloud reports the storage account Healthy; no Issue for this finding"}
    issue = issues[0]
    comments = github.call("GET", f"issues/{issue['number']}/comments?per_page=100")
    if checks.marker_comments(comments, checks.DEFENDER_CONFIRMED) and issue.get("state") != "open":
        return {"result": "Defender's confirmation is already on the Issue", "issue": issue["number"]}
    github.call("POST", f"issues/{issue['number']}/comments", {"body": messages.defender_confirmed_comment(assessment)})
    return {"result": "recorded Defender's confirmation", "issue": issue["number"]}


# ---------------------------------------------------------------- preview
def preview(number: int, s, azure, github) -> dict:
    """Start the what-if job for one pull request, read again from GitHub's API. Only the number comes from the caller."""
    number = int(number)
    pull = github.call("GET", f"pulls/{number}")
    refused = checks.outside_pull_request(pull, s.repository)
    if refused:
        # Only the pull request's own record was read: nothing is started in Azure or written to GitHub.
        return {"result": f"not previewed: {refused}", "started": False}
    if pull.get("state") != "open":
        return {"result": "not previewed: the pull request is not open", "started": False}
    files = github.call("GET", f"pulls/{number}/files?per_page=100")
    if not checks.touches_infra(files, int(pull.get("changed_files") or 0), s.infra_prefix):
        return {"result": "not previewed: it does not change the solution's infra/", "started": False}
    sha = (pull.get("head") or {}).get("sha") or ""
    with _preview_lock:  # one webhook delivery at a time decides, so a commit gets one job
        if not checks.needs_preview(github.call("GET", f"commits/{sha}/statuses?per_page=100")):
            return {"result": "already previewed", "started": False}
        github.call("POST", f"statuses/{sha}", {"state": "pending", "context": checks.STATUS_CONTEXT,
                                                "description": "Azure what-if preview is running in Azure (posture-whatif job)"})
        try:
            container = azure.job_container(s.whatif_job_id)
            azure.start_job(s.whatif_job_id, container, ["--pull-request", str(number)])
        except Exception:
            github.call("POST", f"statuses/{sha}", {"state": "error", "context": checks.STATUS_CONTEXT,
                                                    "description": "The preview could not start in Azure; see the posture Function app's logs"})
            raise
    return {"result": "preview started", "pullRequest": number, "started": True}


# ---------------------------------------------------------------- verify
def verify(s, azure, github, now=_now, sleep=time.sleep, polls: int = 40, poll_seconds: float = 30) -> dict:
    storage = azure.storage_account(s.storage_account_id)
    if not checks.approved_private_endpoints(storage):
        return {"result": "not fixed yet: the storage account has no approved private endpoint"}
    issues = checks.issues_for_finding(github.call("GET", "issues?labels=posture&state=all&per_page=20"), s.marker)
    if not issues:
        return {"result": "the storage account is fixed, and no Issue tracks it"}
    issue = issues[0]
    number, was_open = issue["number"], issue.get("state") == "open"
    comments = github.call("GET", f"issues/{number}/comments?per_page=100")
    if checks.marker_comments(comments, checks.VERIFIED) and not was_open:
        return {"result": "already verified", "issue": number}

    progress = {"evaluationStarted": False, "policyChecks": 1}
    if not _compliant(azure.policy_states(s.resource_group_id, _assignment_filter(s))):
        # The evaluation's own status URL is at subscription scope, where the identity has no access: poll the results.
        azure.start_policy_evaluation(s.resource_group_id)
        progress["evaluationStarted"] = True
        for _ in range(polls):
            sleep(poll_seconds)
            progress["policyChecks"] += 1
            if _compliant(azure.policy_states(s.resource_group_id, _assignment_filter(s))):
                break
    every = azure.policy_states(s.resource_group_id, _definition_filter(s))
    if not _compliant([x for x in every if x.get("policyAssignmentName") == s.policy_assignment_name]):
        return {"result": "Azure Policy does not report the storage account compliant yet; the next run tries again",
                "issue": number, **progress}
    try:
        defender = azure.assessment(s.storage_account_id, s.assessment_key)
    except HttpError as exc:
        log.warning("verify: Defender for Cloud's assessment could not be read: %s", exc)
        defender = None
    github.call("POST", f"issues/{number}/comments", {"body": messages.evidence_comment(
        s.resource_group_name, s.resource_group_id, storage, every, defender, messages.utc(now()))})
    if was_open:
        github.call("PATCH", f"issues/{number}", {"state": "closed", "state_reason": "completed"})
    return {"result": "verified", "issue": number, "closed": was_open, **progress}
