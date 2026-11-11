"""What the posture Function posts on GitHub and sends to the Foundry agent. Pure text, no I/O.

Nothing here names a resource, a host, or a GUID: the resource group's name, this solution's policy assignment, and
resource types only. An assignment inherited from a management group or the subscription appears by its kind of scope.
The agent's answer is model output, so its texts are capped and cannot add an HTML comment (the automation's markers).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import checks

POLICY_NAME = "Storage accounts should use private link"
DEFENDER_NAME = "Storage account should use a private link connection"
FIX_MARKER = "<!-- posture:fix -->"
_FRACTION = re.compile(r"(\.\d{6})\d+")


def parse_utc(value: str) -> datetime:
    """An ISO 8601 time from Azure (up to 7 fractional digits, often with Z) as an aware UTC datetime."""
    moment = datetime.fromisoformat(_FRACTION.sub(r"\1", value.replace("Z", "+00:00")))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def utc(value: str | datetime | None = None) -> str:
    """A time as 'yyyy-MM-dd HH:mm' in UTC; now when value is empty."""
    if not value:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        moment = parse_utc(value)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def model_text(value, limit: int) -> str:
    """The agent's text, capped, without HTML comments (which would carry the automation's markers)."""
    text = str(value or "").strip().replace("<!--", "&lt;!--")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def policy_rows(states: list[dict], resource_group_id: str) -> list[str]:
    rows = []
    for state in states or []:
        label = checks.assignment_label(state, resource_group_id)
        where = "this resource group" if checks.in_resource_group(state.get("policyAssignmentScope"), resource_group_id) \
            else "inherited"
        compliance = state.get("complianceState") or "Unknown"
        mark = " ✅" if compliance == "Compliant" else " ❌"
        rows.append(f"| Azure Policy · `{label}` ({where}) | {compliance}{mark} | evaluated {utc(state.get('timestamp'))} UTC |")
    return rows


def policy_summary(states: list[dict], resource_group_id: str) -> list[dict]:
    return [{"assignment": checks.assignment_label(s, resource_group_id), "state": s.get("complianceState")}
            for s in states or []]


def configuration_row(approved: int, public_network_access: str | None, now: str) -> str:
    result = f"{approved} approved private endpoint ✅" if approved else "no private endpoint ❌"
    return (f"| Resource configuration | {result} | public network access {public_network_access or 'Enabled'}; "
            f"read from Azure Resource Manager at {now} UTC |")


def issue_title(resource_group: str) -> str:
    return f"Posture: attachment storage in {resource_group} has no private endpoint"


def issue_body(resource_group: str, resource_group_id: str, assessment: dict, storage: dict, states: list[dict],
               finding_marker: str, now: str) -> str:
    properties = assessment.get("properties") or {}
    status = properties.get("status") or {}
    public = (storage.get("properties") or {}).get("publicNetworkAccess") or "Enabled"
    reach = ("and its public endpoint is closed, so RequestHub cannot reach it: attachment uploads fail."
             if public == "Disabled" else
             "and its public endpoint is open, so the account is reachable from the internet and only authentication "
             "protects the attachments.")
    rows = [configuration_row(len(checks.approved_private_endpoints(storage)), public, now),
            *policy_rows(states, resource_group_id),
            f"| Microsoft Defender for Cloud · {properties.get('displayName') or DEFENDER_NAME} | "
            f"{status.get('code') or 'Unknown'} ❌ | {(properties.get('metadata') or {}).get('severity') or '-'} severity, "
            f"status since {utc(status.get('statusChangeDate'))} UTC (Defender for Cloud > Recommendations) |"]
    return "\n".join([
        f"**{POLICY_NAME}** · RequestHub's attachment storage account in resource group `{resource_group}`",
        "",
        f"RequestHub keeps every attachment in this account. It has no approved private endpoint, {reach}",
        "",
        "| Source | Result | Evidence |",
        "| --- | --- | --- |",
        *rows,
        "",
        f"Azure Policy and Defender for Cloud evaluate the same built-in policy definition, *{POLICY_NAME}*, on separate "
        "schedules, so their results can differ for a while. Neither proves on its own that the configuration changed: "
        "the resource configuration does.",
        "",
        "### Where to fix it",
        "",
        "In this repository's Bicep for the solution, `solutions/05-secure-microsoft/infra/`, not in the portal, so the "
        "next deployment keeps the fix. The Foundry agent `posture-remediator` drafts the change as a pull request; a "
        "person reviews and merges it.",
        "",
        "### Done when",
        "",
        "- [ ] A pull request changes the Bicep, and its Azure what-if preview (commit status `posture/what-if`) shows "
        "only storage networking changes.",
        "- [ ] A person reviews and merges it, then applies it with `azd provision`.",
        "- [ ] The Azure Function `verify` records the private endpoint in place and Azure Policy compliant on this "
        "Issue, and closes it. Defender for Cloud confirms on its own schedule.",
        "",
        "Do not add a policy exemption, change the assignment's effect, or open the public endpoint to make the finding "
        "disappear.",
        "",
        f"Filed in Azure by the Function `intake` from the Defender for Cloud recommendation at {now} UTC.",
        checks.marker(finding_marker),
    ])


def agent_document(assessment: dict, storage: dict, states: list[dict], resource_group: str, resource_group_id: str,
                   editable: tuple[str, str], read_only: list[tuple[str, str]]) -> dict:
    """The one JSON document the agent receives (posture-remediator.md describes it). Files are (path, content)."""
    properties = assessment.get("properties") or {}
    metadata = properties.get("metadata") or {}
    return {
        "finding": {
            "recommendation": properties.get("displayName") or DEFENDER_NAME,
            "severity": metadata.get("severity") or "",
            "description": metadata.get("description") or "",
            "remediation": metadata.get("remediationDescription") or "",
            "resourceType": "Microsoft.Storage/storageAccounts",
            "resourceGroup": resource_group,
            "azurePolicy": policy_summary(states, resource_group_id),
            "liveConfiguration": {
                "approvedPrivateEndpoints": len(checks.approved_private_endpoints(storage)),
                "publicNetworkAccess": (storage.get("properties") or {}).get("publicNetworkAccess") or "",
            },
        },
        "editableFile": {"path": editable[0], "content": editable[1]},
        "readOnlyFiles": [{"path": path, "content": content} for path, content in read_only],
    }


def pull_request_title(proposal: dict) -> str:
    return model_text(proposal.get("title"), 100).replace("\n", " ") or "Fix the storage posture finding"


def pull_request_body(proposal: dict, issue_number: int, agent_name: str) -> str:
    changes = [f"- {model_text(c, 160)}" for c in (proposal.get("expectedChanges") or [])[:12]]
    return "\n".join([
        model_text(proposal.get("summary"), 2000),
        "",
        f"Remediates #{issue_number}. Merging does not close the Issue: the Azure Function `verify` closes it once the "
        "fix is deployed and Azure Policy reports it compliant.",
        "",
        "**Expected changes** (the Azure what-if preview checks them):",
        "",
        *(changes or ["- none listed"]),
        "",
        f"**Risks:** {model_text(proposal.get('risks'), 600)}",
        "",
        f"Drafted in Azure by the Microsoft Foundry agent `{agent_name}`, run by the Azure Function `intake` from the "
        "Defender for Cloud recommendation. The Azure what-if preview runs next (commit status `posture/what-if`). A "
        "person reviews and merges; nothing is deployed until someone runs `azd provision`.",
        FIX_MARKER,
    ])


def commit_message(proposal: dict, issue_number: int) -> str:
    return f"{pull_request_title(proposal)} (#{issue_number})"


def draft_fix_comment(agent_name: str, pull_number: int, preview_started: bool) -> str:
    if preview_started:
        return (f"The Microsoft Foundry agent `{agent_name}` drafted a fix: #{pull_number}. The Azure what-if preview "
                "runs on it now; a person reviews and merges it.")
    return (f"The Microsoft Foundry agent `{agent_name}` drafted a fix: #{pull_number}. The Azure what-if preview did not "
            "start; the next push to the pull request starts it again, and the posture Function app's logs say why. A "
            "person reviews and merges the fix.")


def rejected_comment(agent_name: str, proposal: dict, problems: list[str], attempts: int = 1) -> str:
    if proposal.get("decision") == "no_change":
        return (f"The Microsoft Foundry agent `{agent_name}` proposes no change: {model_text(proposal.get('summary'), 1000)} "
                "If a fix is already merged, deploy it with `azd provision`; otherwise fix it by hand in a pull request.")
    tries = f", in {attempts} tries. The last one" if attempts > 1 else ""
    return (f"The Microsoft Foundry agent `{agent_name}` proposed a change the Azure Function `intake` will not apply"
            f"{tries}: {'; '.join(problems)}. It accepts one exact edit, inside the lines marked posture:editable in the "
            "solution's own Bicep file, that leaves roles and the policy assignment alone. Fix it by hand in a pull request.")


def existing_fix_comment(pull_number: int) -> str:
    return f"Defender for Cloud reported this again. A draft fix is already open: #{pull_number}."


def defender_confirmed_comment(assessment: dict) -> str:
    properties = assessment.get("properties") or {}
    since = utc((properties.get("status") or {}).get("statusChangeDate"))
    return (f"Microsoft Defender for Cloud now reports the storage account **Healthy** for "
            f"*{properties.get('displayName') or DEFENDER_NAME}* (status since {since} UTC). Recorded by Defender's "
            "workflow automation through the Logic App `posture-intake` and the Azure Function `intake`.\n"
            + checks.DEFENDER_CONFIRMED)


def evidence_comment(resource_group: str, resource_group_id: str, storage: dict, states: list[dict],
                     defender: dict | None, now: str) -> str:
    approved = len(checks.approved_private_endpoints(storage))
    public = (storage.get("properties") or {}).get("publicNetworkAccess")
    status = ((defender or {}).get("properties") or {}).get("status") or {}
    state = status.get("code") or "not assessed"
    healthy = state == "Healthy"
    evidence = "no assessment yet" if not defender else f"status since {utc(status.get('statusChangeDate'))} UTC"
    return "\n".join([
        f"### Posture verification: `{resource_group}`",
        "",
        "| Source | Result | Evidence |",
        "| --- | --- | --- |",
        configuration_row(approved, public, now),
        *policy_rows(states, resource_group_id),
        f"| Microsoft Defender for Cloud · {DEFENDER_NAME} | {state} {'✅' if healthy else '⏳ not reassessed since the fix'} "
        f"| {evidence} |",
        "",
        "**Verified**: the configuration is fixed and Azure Policy reports Compliant. "
        + ("Defender for Cloud confirms it." if healthy else
           "Defender for Cloud reassesses on its own schedule, usually within a day; its workflow automation records the "
           "confirmation on this Issue."),
        "",
        f"Checked in Azure by the Function `verify` at {now} UTC.",
        checks.VERIFIED,
    ])
