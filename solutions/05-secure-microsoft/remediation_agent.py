"""Publish the Microsoft Foundry agent posture-remediator, and try it on your checkout.

  python remediation_agent.py publish        (azd postprovision hook)
      Creates a new version of the prompt agent posture-remediator in this solution's Foundry project when its definition
      changed: the instructions in posture-remediator.md, the model deployment, the reasoning effort, or the output schema.
      The Logic App posture-intake calls the latest version.

  python remediation_agent.py try
      Sends the agent the input posture-intake sends: the live finding (Defender for Cloud and Azure Policy, read with the
      Azure CLI), this checkout's infra/resources.bicep as the editable file, and app/infra/requesthub.bicep as a read-only
      module. It calls the REST endpoint the Logic App calls, checks the proposal the way the Logic App does (one edit of
      at most 2,000 characters to text that occurs exactly once, inside the lines marked posture:editable, naming no
      protected setting), and prints it as a diff. Nothing is changed.

Settings come from environment variables or this solution's azd environment: FOUNDRY_PROJECT_ENDPOINT,
FOUNDRY_MODEL_DEPLOYMENT, REMEDIATION_AGENT_NAME, AZURE_RESOURCE_GROUP, and STORAGE_ACCOUNT_NAME.
Requires `pip install -r requirements.txt` and an Azure sign-in (`az login`) with the Foundry User role on the project,
which `azd up` grants to whoever runs it.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from azd_env import REPO, SOLUTION, setting, utf8_stdout

INSTRUCTIONS = SOLUTION / "posture-remediator.md"
EDITABLE = "solutions/05-secure-microsoft/infra/resources.bicep"
READ_ONLY = ["app/infra/requesthub.bicep"]
REASONING_EFFORT = "low"
# The checks posture-intake applies to a proposal before it opens a pull request (infra/logic/intake.json, Edit_problems).
# Logic Apps' indexOf ignores case, so the region, uniqueness, and protected-name checks do too.
REGION = ("// posture:editable-begin", "// posture:editable-end")
PROTECTED = ("automationRoleDefinitionIds", "automationAppRoleNames", "automationCanPushImages",
             "storageAllowSharedKeyAccess", "storagePrivateLinkPolicy", "effect:", "Microsoft.Authorization",
             "posture:editable")
MAX_TEXT = 2000
# The Defender for Cloud recommendation and the built-in policy the agent is asked about (see infra/automation.bicep).
ASSESSMENT = "cdc78c07-02b0-4af0-1cb2-cb7c672a8b0a"
POLICY_DEFINITION = "6edd7eda-6dd8-40f7-810d-67160c639cd9"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "path", "find", "replace", "title", "summary", "expectedChanges", "risks"],
    "properties": {
        "decision": {"type": "string", "enum": ["change", "no_change"]},
        "path": {"type": "string", "description": "The editable file's path, exactly as given."},
        "find": {"type": "string", "description": "Text copied exactly from the editable file; it must occur exactly once."},
        "replace": {"type": "string", "description": "The text that replaces find."},
        "title": {"type": "string", "description": "Pull request title, imperative, at most 72 characters."},
        "summary": {"type": "string", "description": "Pull request description in Markdown, at most 120 words."},
        "expectedChanges": {"type": "array", "items": {"type": "string"},
                            "description": "Resource changes the deployment should cause, such as Create <type>."},
        "risks": {"type": "string", "description": "What the reviewer should check, in one or two sentences."},
    },
}


def az_json(*args: str):
    az = shutil.which("az") or "az"
    proc = subprocess.run([az, *args, "--only-show-errors", "--output", "json"], capture_output=True, text=True,
                          encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"error: az {' '.join(args[:3])} failed: {proc.stderr.strip()[:600]}")
    return json.loads(proc.stdout or "null")


def publish() -> int:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (PromptAgentDefinition, PromptAgentDefinitionTextOptions, Reasoning,
                                          TextResponseFormatJsonSchema)
    from azure.identity import DefaultAzureCredential

    endpoint, model = setting("FOUNDRY_PROJECT_ENDPOINT"), setting("FOUNDRY_MODEL_DEPLOYMENT")
    name = setting("REMEDIATION_AGENT_NAME", "posture-remediator")
    instructions = INSTRUCTIONS.read_text(encoding="utf-8")
    definition = PromptAgentDefinition(
        model=model,
        instructions=instructions,
        reasoning=Reasoning(effort=REASONING_EFFORT),
        text=PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(name="posture_fix", schema=SCHEMA, strict=True)),
    )
    digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    try:
        versions = list(project.agents.list_versions(agent_name=name))
    except Exception:  # the first publish: the agent does not exist yet
        versions = []
    current = next((v for v in versions if (v.metadata or {}).get("definitionHash") == digest), None)
    if current:
        print(f"Foundry agent {name} v{current.version} is up to date.")
        return 0
    created = project.agents.create_version(
        agent_name=name,
        definition=definition,
        description="Drafts the smallest Bicep fix for a cloud posture finding; posture-intake opens it as a pull request.",
        metadata={"definitionHash": digest, "source": "solutions/05-secure-microsoft/posture-remediator.md"},
    )
    print(f"Foundry agent {name}: published version {created.version}.")
    return 0


def live_finding(resource_group: str, account: str) -> tuple[dict, str]:
    """The finding as posture-intake builds it, read from Azure with the CLI, and the storage account's id."""
    storage = az_json("storage", "account", "show", "--resource-group", resource_group, "--name", account)
    query = (f"securityresources | where type == 'microsoft.security/assessments' and name == '{ASSESSMENT}' "
             f"and tolower(tostring(properties.resourceDetails.Id)) == '{storage['id'].lower()}' | project properties")
    rows = (az_json("graph", "query", "-q", query) or {}).get("data") or [{}]
    defender = rows[0].get("properties") or {}
    policy = az_json("policy", "state", "list", "--resource", storage["id"],
                     "--filter", f"policyDefinitionName eq '{POLICY_DEFINITION}'") or []
    approved = [c for c in storage.get("privateEndpointConnections") or []
                if (c.get("privateLinkServiceConnectionState") or {}).get("status") == "Approved"]
    finding = {
        "recommendation": defender.get("displayName", "Storage account should use a private link connection"),
        "severity": (defender.get("metadata") or {}).get("severity", ""),
        "description": (defender.get("metadata") or {}).get("description", ""),
        "remediation": (defender.get("metadata") or {}).get("remediationDescription", ""),
        "resourceType": "Microsoft.Storage/storageAccounts",
        "resourceGroup": resource_group,
        "azurePolicy": [{"assignment": s.get("policyAssignmentName"), "state": s.get("complianceState")} for s in policy],
        "liveConfiguration": {"approvedPrivateEndpoints": len(approved),
                              "publicNetworkAccess": storage.get("publicNetworkAccess")},
    }
    return finding, storage["id"]


def edit_problems(content: str, proposal: dict) -> list[str]:
    """Why posture-intake would refuse to apply this proposal to `content`; an empty list means it would apply it."""
    find, replace = proposal.get("find") or "", proposal.get("replace") or ""
    lower, needle = content.lower(), find.lower()
    position = lower.find(needle) if find else -1
    begin, end = lower.find(REGION[0].lower()), lower.find(REGION[1].lower())
    problems = []
    if proposal.get("path") != EDITABLE:
        problems.append("it targets a file other than the solution's own Bicep file")
    if not find or find not in content or position != lower.rfind(needle):
        problems.append("its search text does not occur exactly once in the file")
    if not replace.strip():
        problems.append("its replacement is empty")
    if find == replace:
        problems.append("it changes nothing")
    if len(find) > MAX_TEXT or len(replace) > MAX_TEXT:
        problems.append(f"its search or replacement text is longer than {MAX_TEXT:,} characters")
    if not (begin >= 0 and end > begin and position > begin and position + len(find) <= end):
        problems.append("it changes text outside the lines marked posture:editable")
    if any(name.lower() in f"{find}\n{replace}".lower() for name in PROTECTED):
        problems.append("its text names a protected setting (roles, app roles, registry push, shared key access, the "
                        "policy assignment or its effect, or the editable markers)")
    return problems


def try_agent() -> int:
    from azure.identity import DefaultAzureCredential

    endpoint = setting("FOUNDRY_PROJECT_ENDPOINT")
    name = setting("REMEDIATION_AGENT_NAME", "posture-remediator")
    finding, _ = live_finding(setting("AZURE_RESOURCE_GROUP"), setting("STORAGE_ACCOUNT_NAME"))
    editable = (REPO / EDITABLE).read_text(encoding="utf-8")
    document = {
        "finding": finding,
        "editableFile": {"path": EDITABLE, "content": editable},
        "readOnlyFiles": [{"path": p, "content": (REPO / p).read_text(encoding="utf-8")} for p in READ_ONLY],
    }
    token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
    # The same request the Logic App sends: the Responses API of the project, with a reference to the agent.
    request = urllib.request.Request(
        f"{endpoint}/openai/v1/responses",
        data=json.dumps({"agent_reference": {"name": name, "type": "agent_reference"},
                         "input": json.dumps(document)}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"error: the agent call failed: HTTP {exc.code} {exc.read().decode(errors='replace')[:400]}")
    seconds = time.monotonic() - started
    message = next(item for item in body["output"] if item.get("type") == "message")
    proposal = json.loads(message["content"][0]["text"])
    usage = body.get("usage") or {}
    print(f"agent {name} answered in {seconds:.0f} s ({usage.get('input_tokens', '?')} input and "
          f"{usage.get('output_tokens', '?')} output tokens): decision {proposal['decision']}")

    problems = [] if proposal["decision"] == "change" else ["the agent found no safe change"]
    problems += edit_problems(editable, proposal)
    print(f"\ntitle: {proposal['title']}\n\n{proposal['summary']}\n")
    print("expected changes:\n" + "\n".join(f"  - {c}" for c in proposal["expectedChanges"]))
    print(f"risks: {proposal['risks']}\n")
    if not problems:
        fixed = editable.replace(proposal["find"], proposal["replace"])
        sys.stdout.writelines(difflib.unified_diff(editable.splitlines(True), fixed.splitlines(True),
                                                   f"a/{EDITABLE}", f"b/{EDITABLE}"))
        print("\nOK: posture-intake would apply this change and open it as a draft pull request.")
        return 0
    print("REJECTED: posture-intake would not apply it: " + "; ".join(problems) + ".")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["publish", "try"],
                        help="publish: create a new agent version when the definition changed; try: ask the agent about "
                             "the live finding and check its proposal against this checkout")
    args = parser.parse_args()
    utf8_stdout()
    return publish() if args.command == "publish" else try_agent()


if __name__ == "__main__":
    sys.exit(main())
