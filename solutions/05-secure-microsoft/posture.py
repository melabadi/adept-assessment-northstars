#!/usr/bin/env python3
"""Find, track, and verify a cloud posture finding in this solution's resource group (Secure phase, Microsoft track).

The control: "Storage accounts should use private link" on RequestHub's attachment storage. Two Azure services judge it,
each on its own clock, and this script keeps their answers apart:
  - Azure Policy reports the compliance state of every assignment that evaluates the control's policy definition,
    including this solution's own assignment. It is the fast signal: an on-demand evaluation takes minutes.
  - Microsoft Defender for Cloud reports the recommendation linked to the same policy definition. The script finds it
    through the recommendation's metadata, never through a hard-coded assessment id. It is the slow signal: Defender
    reassesses on its own schedule, typically within 24 hours.
The resource's live configuration, read from Azure Resource Manager, is the ground truth both are compared with. The
app check shows what the finding means for users: it uploads and downloads an attachment through the RequestHub API.

Commands
  scan     Reports the control for every storage account in the resource group, source by source, runs the app check,
           and summarizes the other findings in the resource group for context. With --issue, opens one GitHub Issue
           per misconfigured account that Azure Policy or Defender for Cloud has reported, or comments on the Issue
           already open for it (deduplicated by a marker in the Issue body). A misconfiguration that no service has
           reported yet is printed, not filed.
  verify   Run after the remediation is deployed. Confirms the configuration, starts a Policy evaluation and polls until
           this solution's assignment reports Compliant (bounded by --timeout), reads Defender's state and reports it
           as pending when Defender has not reassessed yet, and runs the app check. With --issue, comments the evidence
           on the Issue, closes it when verified, and reopens it when the fix is not in place.

Examples
  python solutions/05-secure-microsoft/posture.py scan
  python solutions/05-secure-microsoft/posture.py scan --refresh --issue
  python solutions/05-secure-microsoft/posture.py verify --issue 42
  python solutions/05-secure-microsoft/posture.py verify --issue 42 --timeout 0     # later: record Defender's result

Settings come from environment variables first, then from this solution's azd environment: AZURE_SUBSCRIPTION_ID,
AZURE_RESOURCE_GROUP, POLICY_ASSIGNMENT_NAME, API_URL, API_IDENTIFIER_URI. Sign in with `az login` (or azure/login in
GitHub Actions). The identity needs Reader and Policy Insights rights on the resource group (the solution's GitHub
identity has Reader and Policy Enrollments Contributor) and a RequestHub app role for the app check. --issue uses the
GitHub CLI. Results are written to solutions/05-secure-microsoft/out/ (scan.json, scan.md, verify.json, verify.md).

Everything the script prints, posts, or saves is masked first, because it ends up in Issues, workflow logs, and run
artifacts: GUIDs (subscription and tenant ids among them) and the random token in resource names (the 13 letters and
digits in `st<token>` or `vnet-<token>`) are shown as `…`.

Exit codes: scan 0 = scan completed; verify 0 = verified, 1 = not verified (pending or failed); 2 = configuration or
Azure error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from azd_env import REPO, SOLUTION, setting, utf8_stdout

GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
NAME_TOKEN = re.compile(r"(?<![a-z0-9])[a-z0-9]{13}(?![a-z0-9])")


class Masker:
    """Hides what identifies a deployment: GUIDs, and the random token that azd-style templates put in every resource name
    of a group (13 letters and digits, as in `st<token>` and `vnet-<token>`). learn() finds the token in resource names:
    a 13-character word with letters and digits, or a 13-character ending that several names share."""

    def __init__(self) -> None:
        self.tokens: set[str] = set()

    def learn(self, names: list[str]) -> None:
        lowered = {n.lower() for n in names if n}
        endings = Counter(n[-13:] for n in lowered if len(n) > 13 and re.fullmatch(r"[a-z0-9]{13}", n[-13:]))
        self.tokens |= {t for t, count in endings.items() if count >= 2}
        self.tokens |= {t for n in lowered for t in NAME_TOKEN.findall(n) if re.search(r"\d", t) and re.search(r"[a-z]", t)}

    def __call__(self, text: str) -> str:
        for token in sorted(self.tokens, key=len, reverse=True):
            text = re.sub(re.escape(token), "…", text, flags=re.I)
        return GUID.sub("…", text)


mask = Masker()


class MaskedOutput:
    """Stands in for stdout and stderr, so nothing reaches a console or a workflow log unmasked."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def write(self, text: str) -> int:
        return self.stream.write(mask(text))

    def __getattr__(self, name: str):
        return getattr(self.stream, name)


@dataclass(frozen=True)
class Check:
    """What the live configuration says about the control."""

    compliant: bool
    summary: str  # short result, for example "no private endpoint"
    details: str  # the settings behind it
    impact: str  # what it means for this resource right now


@dataclass(frozen=True)
class Control:
    """One posture control: the policy definition both services evaluate, and how to judge the live resource."""

    key: str
    title: str
    policy_definition: str  # built-in policy definition name (a GUID)
    resource_type: str
    assignment: str  # this solution's Azure Policy assignment for the control (POLICY_ASSIGNMENT_NAME overrides it)
    issue_title: str
    bicep: str  # where the fix belongs
    fix: str  # what the fix changes
    evaluate: Callable[[dict], Check]  # resource properties -> Check


def private_link(properties: dict) -> Check:
    approved = [c for c in properties.get("privateEndpointConnections") or []
                if ((c.get("properties") or {}).get("privateLinkServiceConnectionState") or {}).get("status") == "Approved"]
    public = properties.get("publicNetworkAccess") or "Enabled"
    default_action = (properties.get("networkAcls") or {}).get("defaultAction") or "Allow"
    details = f"public network access {public}, network rules default {default_action}"
    if approved:
        return Check(True, f"{len(approved)} approved private endpoint{'s' if len(approved) > 1 else ''}", details, "")
    if public == "Disabled":
        impact = ("Its public endpoint is closed (here by an organization-wide Azure Policy) and it has no private endpoint, "
                  "so RequestHub cannot reach it: attachment uploads fail.")
    else:
        impact = ("RequestHub reaches it through its public endpoint, which accepts connections from the internet, so only "
                  "authentication stands between the internet and every attachment.")
    return Check(False, "no private endpoint", details, impact)


CONTROL = Control(
    key="storage-private-link",
    title="Storage accounts should use private link",
    policy_definition="6edd7eda-6dd8-40f7-810d-67160c639cd9",
    resource_type="Microsoft.Storage/storageAccounts",
    assignment="requesthub-storage-private-link",
    issue_title="Posture: attachment storage in {rg} has no private endpoint",
    bicep="`solutions/05-secure-microsoft/infra/resources.bicep`: the `storagePrivateEndpoint` value passed to "
    "`app/infra/requesthub.bicep`",
    fix="Turning it on adds a subnet, a private endpoint for Blob storage, and a private DNS zone linked to the app's virtual "
    "network, and closes the account's public endpoint. The API and worker already sign in with their managed identity, "
    "so only the network path changes.",
    evaluate=private_link,
)

LABEL = "posture"
OUT = SOLUTION / "out"
AZ = shutil.which("az") or "az"
ARG_URL = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
POSTURE_REQUEST_TITLE = "Posture check: attachment round trip"
# Readable names for initiatives that commonly include the control.
INITIATIVES = {"1f3afdf9-d0c9-4c3d-847f-89da613e70a8": "Microsoft cloud security benchmark"}
LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


class AzureError(RuntimeError):
    pass


# ---------- Azure ----------
def az(*args: str, parse: bool = True):
    command = [AZ, *args, "--only-show-errors"] + (["--output", "json"] if parse else [])
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AzureError(f"az {' '.join(args[:3])} failed: {proc.stderr.strip()[:600]}")
    return json.loads(proc.stdout) if parse and proc.stdout.strip() else proc.stdout


def resource_graph(query: str, subscription: str) -> list[dict]:
    # The body goes through a file: on Windows, az is a batch file and KQL pipes would reach cmd.exe.
    body = {"subscriptions": [subscription], "query": query, "options": {"resultFormat": "objectArray", "$top": 1000}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(body, handle)
    try:
        return az("rest", "--method", "post", "--url", ARG_URL, "--body", f"@{handle.name}").get("data", [])
    finally:
        os.unlink(handle.name)


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(value: str | None) -> str:
    if not value:
        return "never"
    try:
        return parse_time(value).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def short_id(resource_id: str, rg: str) -> str:
    """Resource group relative id: readable, and keeps subscription ids out of Issues and logs (output masks the name's token)."""
    return f"{rg}/{resource_id.rstrip('/').split('/')[-1]}"


def scope_label(scope: str | None, rg: str) -> str:
    scope = (scope or "").lower()
    if scope.endswith(f"/resourcegroups/{rg.lower()}"):
        return "this resource group"
    if "/managementgroups/" in scope:
        return "management group"
    if scope.startswith("/subscriptions/"):
        return "subscription"
    return "other scope"


class Posture:
    """Reads the control from each source for one resource group."""

    def __init__(self, control: Control) -> None:
        self.control = control
        self.subscription = setting("AZURE_SUBSCRIPTION_ID")
        self.rg = setting("AZURE_RESOURCE_GROUP")
        self.assignment = setting("POLICY_ASSIGNMENT_NAME", control.assignment)
        mask.learn(az("resource", "list", "--resource-group", self.rg, "--query", "[].name") or [])

    def resources(self) -> list[dict]:
        """Live configuration from Azure Resource Manager (not Resource Graph, which can lag behind a deployment)."""
        ids = az("resource", "list", "--resource-group", self.rg, "--resource-type", self.control.resource_type, "--query", "[].id")
        if not ids:
            return []
        shown = az("resource", "show", "--ids", *ids)
        rows = []
        for resource in shown if isinstance(shown, list) else [shown]:
            check = self.control.evaluate(resource.get("properties") or {})
            rows.append({"id": resource["id"], "name": resource["name"], "compliant": check.compliant, "summary": check.summary,
                         "details": check.details, "impact": check.impact, "readAt": now().isoformat()})
        return rows

    def policy_states(self) -> list[dict]:
        states = az("policy", "state", "list", "--resource-group", self.rg, "--top", "500",
                    "--filter", f"policyDefinitionName eq '{self.control.policy_definition}'")
        return [{"resourceId": s["resourceId"], "assignment": s.get("policyAssignmentName"),
                 "scope": scope_label(s.get("policyAssignmentScope"), self.rg), "initiative": s.get("policySetDefinitionName") or None,
                 "state": s.get("complianceState"), "evaluatedAt": s.get("timestamp"),
                 "definitionVersion": s.get("policyDefinitionVersion")} for s in states]

    def defender(self) -> list[dict]:
        return resource_graph(
            "securityresources | where type == 'microsoft.security/assessments' "
            f"| where resourceGroup =~ '{self.rg}' "
            f"| where tostring(properties.metadata.policyDefinitionId) endswith '/{self.control.policy_definition}' "
            "| project id, key = name, resourceId = tostring(properties.resourceDetails.Id), "
            "name = tostring(properties.displayName), state = tostring(properties.status.code), "
            "severity = tostring(properties.metadata.severity), firstEvaluated = tostring(properties.status.firstEvaluationDate), "
            "changedAt = tostring(properties.status.statusChangeDate)", self.subscription)

    def context(self) -> dict:
        """Other findings in the resource group, for perspective. Not tracked by this solution."""
        noncompliant = az("policy", "state", "list", "--resource-group", self.rg, "--top", "1000",
                          "--filter", "complianceState eq 'NonCompliant'")
        unhealthy = resource_graph(
            "securityresources | where type == 'microsoft.security/assessments' "
            f"| where resourceGroup =~ '{self.rg}' | where tostring(properties.status.code) == 'Unhealthy' "
            "| project name = tostring(properties.displayName), severity = tostring(properties.metadata.severity), "
            "resource = tostring(properties.resourceDetails.ResourceName)", self.subscription)
        return {"policyNonCompliant": len(noncompliant), "policyResources": len({s["resourceId"].lower() for s in noncompliant}),
                "defenderUnhealthy": sorted(unhealthy, key=lambda r: ({"High": 0, "Medium": 1, "Low": 2}.get(r["severity"], 3), r["name"]))}

    def trigger_evaluation(self) -> datetime:
        """Starts an Azure Policy evaluation of the resource group and returns when it was requested."""
        requested = now()
        az("policy", "state", "trigger-scan", "--resource-group", self.rg, "--no-wait", parse=False)
        return requested

    def wait_for_evaluation(self, requested: datetime, timeout: int, interval: int = 30) -> bool:
        """Polls until every Policy result for the control is newer than the request; False if the timeout passed first.
        Polling the results works the same on every platform and reports as soon as these resources are evaluated, usually
        minutes before the whole evaluation finishes."""
        deadline = time.monotonic() + timeout
        threshold = requested - timedelta(seconds=30)  # tolerate clock skew between this machine and Azure
        while time.monotonic() < deadline:
            time.sleep(interval)
            states = self.policy_states()
            fresh = [s for s in states if s["evaluatedAt"] and parse_time(s["evaluatedAt"]) >= threshold]
            if states and len(fresh) == len(states):
                return True
            print(f"  {now():%H:%M:%S}  {len(fresh)} of {len(states)} Policy results re-evaluated; checking again in {interval} s", flush=True)
        return False

    def findings(self) -> list[dict]:
        """The control, per resource, from each source."""
        policy, defender = self.policy_states(), self.defender()
        findings = []
        for resource in self.resources():
            rid = resource["id"].lower()
            states = sorted((s for s in policy if s["resourceId"].lower() == rid), key=lambda s: s["scope"] != "this resource group")
            assessment = next((d for d in defender if d["resourceId"].lower() == rid), None)
            own = next((s for s in states if s["assignment"] == self.assignment), None)
            reported = any(s["state"] == "NonCompliant" for s in states) or (assessment or {}).get("state") == "Unhealthy"
            findings.append({"control": self.control.key, "resource": resource, "policy": states, "ownAssignment": own,
                             "defender": assessment, "reported": reported})
        return findings


# ---------- Reporting ----------
# A row is (source, result, evidence) in Markdown. plain() turns it into console text.
Row = tuple[str, str, str]


def plain(text: str) -> str:
    return LINK.sub(r"\1", text).replace("`", "")


def config_row(finding: dict) -> Row:
    r = finding["resource"]
    return ("Resource configuration", f"{r['summary']} {'✅' if r['compliant'] else '❌'}",
            f"{r['details']}; read from Azure Resource Manager at {stamp(r['readAt'])}")


def policy_rows(finding: dict) -> list[Row]:
    rows = []
    for s in finding["policy"]:
        mark = "✅" if s["state"] == "Compliant" else "❌" if s["state"] == "NonCompliant" else "⏳"
        via = f", {INITIATIVES.get(s['initiative'], 'an inherited initiative')}" if s["initiative"] else ""
        rows.append((f"Azure Policy · `{s['assignment']}` ({s['scope']}{via})", f"{s['state']} {mark}",
                     f"evaluated {stamp(s['evaluatedAt'])}, definition version {s['definitionVersion'] or '?'}"))
    if not finding["policy"]:
        rows.append(("Azure Policy", "not evaluated yet ⏳", "new resources and assignments are evaluated within about 30 "
                     "minutes; `scan --refresh` starts an evaluation now"))
    return rows


def defender_row(finding: dict, after_fix: bool = False) -> Row:
    d = finding["defender"]
    if not d:
        return ("Microsoft Defender for Cloud", "not assessed yet ⏳", "Defender assesses new resources within about 24 hours")
    if d["state"] == "Healthy":
        mark = "✅"
    elif d["state"] == "Unhealthy":
        # The configuration is the ground truth: after a verified fix, Unhealthy means Defender has not caught up yet.
        mark = "⏳ not reassessed since the fix" if after_fix else "❌"
    else:
        mark = ""
    return (f"Microsoft Defender for Cloud · {d['name']}", f"{d['state']} {mark}".strip(),
            f"{d['severity'] or '-'} severity, status since {stamp(d['changedAt'])} (Defender for Cloud > Recommendations)")


def app_row(app: dict) -> Row:
    source = "App check · attachment upload and download through the RequestHub API"
    if app.get("ok"):
        return (source, "works ✅", f"`{app['file']}` on {app['request']} as {app['caller']} ({', '.join(app['roles'])}), "
                "SHA-256 matches")
    return (source, "fails ❌", app.get("error") or "the downloaded content did not match")


def rows_for(finding: dict, after_fix: bool = False, app: dict | None = None) -> list[Row]:
    return [config_row(finding), *policy_rows(finding), defender_row(finding, after_fix), *([app_row(app)] if app else [])]


def table(rows: list[Row]) -> list[str]:
    return ["| Source | Result | Evidence |", "|---|---|---|", *[f"| {a} | {b} | {c} |" for a, b, c in rows]]


def print_rows(title: str, rows: list[Row]) -> None:
    print(f"\n{title}")
    for source, result, evidence in rows:
        print(f"  {plain(source)}\n      {plain(result)}  ·  {plain(evidence)}")


def run_link() -> str:
    if os.environ.get("GITHUB_RUN_ID"):
        url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        return f"[workflow run]({url})"
    return "a local run"


def save(name: str, text: str) -> None:
    """Writes a result file under out/, masked: workflows upload these as run artifacts."""
    (OUT / name).write_text(mask(text), encoding="utf-8")


# ---------- GitHub Issues ----------
def gh(*args: str, stdin: str | None = None) -> str:
    """Runs the GitHub CLI. Arguments and input are masked: what this sends becomes Issue titles, bodies, and comments."""
    proc = subprocess.run(["gh", *map(mask, args)], input=mask(stdin) if stdin else None, capture_output=True, text=True,
                          encoding="utf-8", cwd=REPO)
    if proc.returncode != 0:
        raise AzureError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def marker(finding: dict, rg: str) -> str:
    """Identifies the finding's Issue without naming the resource: a short digest of its resource id."""
    digest = hashlib.sha256(finding["resource"]["id"].lower().encode()).hexdigest()[:12]
    return f"<!-- posture:{finding['control']}:{rg.lower()}:{digest} -->"


def find_issue(finding: dict, rg: str) -> dict | None:
    issues = json.loads(gh("issue", "list", "--label", LABEL, "--state", "open", "--limit", "100", "--json", "number,body,url"))
    return next((i for i in issues if marker(finding, rg) in (i.get("body") or "")), None)


def issue_body(finding: dict, posture: Posture, app: dict | None) -> str:
    c, r = posture.control, finding["resource"]
    return "\n".join([
        marker(finding, posture.rg),
        f"**{c.title}** · RequestHub's attachment storage account in resource group `{posture.rg}`",
        "",
        f"RequestHub keeps every attachment in this account. {r['impact']}",
        "",
        *table(rows_for(finding, app=app)),
        "",
        f"Azure Policy and Defender for Cloud evaluate the same built-in policy definition, *{c.title}*, on separate "
        "schedules, so their results can differ for a while. Neither proves on its own that the configuration changed: "
        "the resource configuration does.",
        "",
        "### Where to fix it",
        f"The setting lives in {c.bicep}. {c.fix} Fix it in Bicep, not in the portal, so the next deployment keeps it.",
        "",
        "### Done when",
        "- [ ] A pull request changes only that setting, and the **Secure · Microsoft · preview the infrastructure change** "
        "check shows changes to the storage account and its private networking only (virtual network, private endpoint, "
        "private DNS zone).",
        "- [ ] A person reviews and merges it, then applies it with `azd provision`.",
        "- [ ] **Secure · Microsoft · verify the remediation** (`gh workflow run secure-microsoft-verify.yml -f issue=<this issue>`) "
        "reports the private endpoint in place, Azure Policy compliant, and attachments working. Defender for Cloud "
        "confirms on its own schedule.",
        "",
        "Do not add a policy exemption, change the assignment's effect, or open the public endpoint to make the finding "
        "disappear. Keep host names, resource names, and ids out of this Issue and its pull request.",
        "",
        f"Detected by {run_link()} on {now():%Y-%m-%d %H:%M} UTC.",
    ])


def sync_issue(finding: dict, posture: Posture, app: dict | None) -> str:
    gh("label", "create", LABEL, "--color", "B60205", "--force",
       "--description", "Cloud posture finding from Azure Policy or Defender for Cloud")
    existing = find_issue(finding, posture.rg)
    if existing:
        comment = "\n".join([f"Still present at {now():%Y-%m-%d %H:%M} UTC ({run_link()}).", "", *table(rows_for(finding, app=app))])
        gh("issue", "comment", str(existing["number"]), "--body-file", "-", stdin=comment)
        return f"commented on #{existing['number']}, already open for this finding: {existing['url']}"
    title = posture.control.issue_title.format(rg=posture.rg)
    url = gh("issue", "create", "--title", title, "--label", LABEL, "--body-file", "-", stdin=issue_body(finding, posture, app)).strip()
    return f"opened {url}"


# ---------- App check ----------
class Api:
    """Minimal RequestHub API client with a Microsoft Entra token from the Azure CLI."""

    def __init__(self, base: str, identifier_uri: str) -> None:
        self.base = base.rstrip("/")
        account = az("account", "show")
        delegated = (account.get("user") or {}).get("type") == "user"
        scope = f"{identifier_uri}/user_impersonation" if delegated else f"{identifier_uri}/.default"
        # Who called, without names or ids: reports land in Issues.
        self.caller = ("you" if delegated else "the GitHub workflow identity" if os.environ.get("GITHUB_ACTIONS") == "true"
                       else "the signed-in app identity")
        self.token = az("account", "get-access-token", "--scope", scope)["accessToken"]

    def call(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/json")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def json(self, method: str, path: str, payload: dict | None = None, expect: int = 200) -> dict | list:
        status, data = self.call(method, path, json.dumps(payload).encode() if payload is not None else None,
                                 "application/json" if payload is not None else None)
        if status != expect:
            raise AzureError(f"{method} {path.split('?')[0]} returned HTTP {status}{problem(data)}")
        return json.loads(data)


def problem(data: bytes) -> str:
    """The title of an RFC 9457 problem response, if there is one."""
    try:
        return f" ({json.loads(data).get('title')})"
    except (ValueError, AttributeError):
        return ""


def app_check(api: Api) -> dict:
    """Uploads and downloads an attachment through the API, which stores it in Blob storage with its managed identity."""
    me = api.json("GET", "/api/me")
    mine = api.json("GET", "/api/requests?" + urllib.parse.urlencode({"scope": "mine", "q": "Posture check", "pageSize": 50}))
    target = None
    for item in mine["items"]:
        if item["title"] == POSTURE_REQUEST_TITLE and item["status"] in ("Submitted", "InReview"):
            detail = api.json("GET", f"/api/requests/{item['id']}")
            if len(detail["attachments"]) < 10:
                target = detail
                break
    if target is None:
        category = api.json("GET", "/api/categories")[0]["id"]
        department = api.json("GET", "/api/departments")[0]["id"]
        target = api.json("POST", "/api/requests", {
            "title": POSTURE_REQUEST_TITLE,
            "description": "Created by the Secure phase posture check to prove that attachments reach Blob storage.",
            "category": category, "departmentId": department, "priority": "Low"}, expect=201)

    content = f"RequestHub posture check {now().isoformat()}\n".encode()
    name = f"posture-check-{now():%Y%m%d-%H%M%S}.txt"
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: text/plain\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    status, data = api.call("POST", f"/api/requests/{target['id']}/attachments", body, f"multipart/form-data; boundary={boundary}")
    if status != 201:
        raise AzureError(f"upload to {target['id']} returned HTTP {status}{problem(data)}")
    uploaded = json.loads(data)
    status, downloaded = api.call("GET", uploaded["downloadUrl"])
    if status != 200:
        raise AzureError(f"download from {target['id']} returned HTTP {status}{problem(downloaded)}")
    expected = hashlib.sha256(content).hexdigest()
    return {"ok": hashlib.sha256(downloaded).hexdigest() == expected == uploaded["sha256"], "caller": api.caller,
            "roles": me["roles"], "request": target["id"], "file": name, "bytes": len(content), "sha256": expected}


def connect_api(skip: bool) -> Api | dict | None:
    """Gets the API token up front: in GitHub Actions the OIDC sign-in can only mint new tokens for about 5 minutes, and
    verify may wait longer than that for Azure Policy."""
    if skip:
        return None
    try:
        return Api(setting("API_URL"), setting("API_IDENTIFIER_URI"))
    except (AzureError, KeyError) as exc:
        return {"ok": False, "error": f"could not get a token for the RequestHub API: {exc}"}


def run_app_check(api: Api | dict | None) -> dict | None:
    if api is None or isinstance(api, dict):
        return api
    try:
        return app_check(api)
    except (AzureError, urllib.error.URLError, KeyError, IndexError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}


# ---------- Commands ----------
def scan(args: argparse.Namespace, posture: Posture) -> int:
    print(f"Cloud posture scan · resource group {posture.rg} · control: {posture.control.title}")
    api = connect_api(args.skip_app)
    if args.refresh:
        print("Starting an Azure Policy evaluation of the resource group; waiting until these resources are re-evaluated "
              f"(usually 2 to 10 minutes, at most {args.refresh_timeout // 60} min)...", flush=True)
        if not posture.wait_for_evaluation(posture.trigger_evaluation(), args.refresh_timeout):
            print("  not re-evaluated yet; showing the latest results (the evaluation keeps running)")
    findings = posture.findings()
    app = run_app_check(api)
    context = posture.context()
    if not findings:
        print(f"\nNo {posture.control.resource_type} resources in {posture.rg}.")
    for finding in findings:
        print_rows(f"{posture.control.title} · {short_id(finding['resource']['id'], posture.rg)}", rows_for(finding, app=app))

    print(f"\nOther findings in {posture.rg}, for context (this demo tracks one control):")
    print(f"  Azure Policy        {context['policyNonCompliant']} non-compliant results on {context['policyResources']} resources")
    print(f"  Defender for Cloud  {len(context['defenderUnhealthy'])} unhealthy recommendations")
    for item in context["defenderUnhealthy"][:10]:
        print(f"    [{item['severity'] or '-'}] {item['name']} ({item['resource']})")

    summary = [f"### Cloud posture scan: `{posture.rg}`", ""]
    print()
    for finding in findings:
        rid = short_id(finding["resource"]["id"], posture.rg)
        summary += [f"**{posture.control.title}** · `{rid}`", "", *table(rows_for(finding, app=app)), ""]
        if finding["resource"]["compliant"]:
            note = "configured correctly"
            if finding["reported"]:
                note += "; a service still reports the old state (it has not re-evaluated since the change)"
        elif not finding["reported"]:
            note = ("MISCONFIGURED, but neither Azure Policy nor Defender for Cloud has reported it yet: no Issue filed. "
                    "Run `scan --refresh` to evaluate Policy now.")
        elif args.issue:
            note = sync_issue(finding, posture, app)
        else:
            note = "MISCONFIGURED and reported; run with --issue to track it"
        print(f"{rid}: {note}")
        summary += [f"Result: {note}", ""]
    summary += [f"Other findings in the resource group: {context['policyNonCompliant']} non-compliant Azure Policy results, "
                f"{len(context['defenderUnhealthy'])} unhealthy Defender for Cloud recommendations."]
    OUT.mkdir(parents=True, exist_ok=True)
    save("scan.json", json.dumps({"scannedAt": now().isoformat(), "resourceGroup": posture.rg,
                                  "findings": findings, "app": app, "context": context}, indent=2, ensure_ascii=False))
    save("scan.md", "\n".join(summary) + "\n")
    return 0


def verify(args: argparse.Namespace, posture: Posture) -> int:
    print(f"Verifying the remediation · resource group {posture.rg} · control: {posture.control.title}")
    api = connect_api(args.skip_app)
    findings = posture.findings()
    if not findings:
        raise AzureError(f"no {posture.control.resource_type} resources in {posture.rg}")
    misconfigured = [f for f in findings if not f["resource"]["compliant"]]
    if misconfigured:
        print(f"FAIL {', '.join(f['resource']['name'] for f in misconfigured)}: {misconfigured[0]['resource']['summary']}. "
              "Merge the reviewed fix and apply it with `azd provision` first.")
    else:
        if args.timeout > 0 and not args.no_refresh:
            print("Configuration fixed. Starting an Azure Policy evaluation and waiting for this solution's assignment "
                  f"({posture.assignment}) to report Compliant (up to {args.timeout // 60} min)...", flush=True)
            posture.trigger_evaluation()
        deadline = time.monotonic() + args.timeout
        while True:
            pending = [f for f in findings if (f["ownAssignment"] or {}).get("state") != "Compliant"]
            if not pending or time.monotonic() >= deadline:
                break
            states = ", ".join(f"{f['resource']['name']}: {(f['ownAssignment'] or {}).get('state', 'not evaluated')}" for f in pending)
            print(f"  {now():%H:%M:%S}  Azure Policy reports {states}; checking again in {args.interval} s", flush=True)
            time.sleep(args.interval)
            findings = posture.findings()

    app = run_app_check(api)
    config_ok = all(f["resource"]["compliant"] for f in findings)
    policy_ok = all((f["ownAssignment"] or {}).get("state") == "Compliant" for f in findings)
    app_ok = args.skip_app or bool(app and app.get("ok"))
    defender_ok = all((f["defender"] or {}).get("state") == "Healthy" for f in findings)
    verified = config_ok and policy_ok and app_ok

    lines = [f"### Posture verification: `{posture.rg}`", ""]
    for f in findings:
        lines += [f"**{posture.control.title}** · `{short_id(f['resource']['id'], posture.rg)}`", "",
                  *table(rows_for(f, after_fix=f["resource"]["compliant"], app=app)), ""]
    if verified:
        lines.append("**Verified**: the configuration is fixed, Azure Policy reports Compliant, and attachments work.")
        if not defender_ok:
            lines.append("Microsoft Defender for Cloud has not reassessed yet; it does so on its own schedule, usually within "
                         "24 hours. Record its result later with `gh workflow run secure-microsoft-verify.yml -f issue=<number> "
                         "-f timeout=0`.")
    elif not config_ok:
        lines.append(f"**Not fixed**: {misconfigured[0]['resource']['summary'] if misconfigured else 'the configuration is not compliant'}.")
    elif not policy_ok:
        lines.append(f"**Pending**: Azure Policy has not reported Compliant within {args.timeout // 60} min. Run this again; "
                     "Policy evaluates changed resources within about 30 minutes.")
    else:
        lines.append("**Not verified**: the configuration and Azure Policy are fixed, but the app check failed. Investigate "
                     "before closing.")
    lines.append(f"\nChecked by {run_link()} at {now():%Y-%m-%d %H:%M} UTC.")
    report = "\n".join(lines)
    print("\n" + plain(report))

    OUT.mkdir(parents=True, exist_ok=True)
    save("verify.json", json.dumps({"checkedAt": now().isoformat(), "resourceGroup": posture.rg, "verified": verified,
                                    "findings": findings, "app": app}, indent=2, ensure_ascii=False))
    save("verify.md", report + "\n")

    if args.issue:
        state = json.loads(gh("issue", "view", str(args.issue), "--json", "state"))["state"]
        gh("issue", "comment", str(args.issue), "--body-file", "-", stdin=report)
        if verified and state == "OPEN":
            gh("issue", "close", str(args.issue), "--reason", "completed")
            print(f"closed #{args.issue}")
        elif not config_ok and state == "CLOSED":
            gh("issue", "reopen", str(args.issue))
            print(f"reopened #{args.issue}: the fix is not in place")
        else:
            print(f"commented on #{args.issue}")
    return 0 if verified else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="report the control by source and track a reported misconfiguration as an Issue")
    scan_parser.add_argument("--refresh", action="store_true",
                             help="start an Azure Policy evaluation of the resource group first, and wait until these "
                                  "resources are re-evaluated")
    scan_parser.add_argument("--refresh-timeout", type=int, default=900, metavar="SECONDS",
                             help="how long --refresh waits (default 900); the evaluation keeps running afterwards")
    scan_parser.add_argument("--issue", action="store_true",
                             help="open a GitHub Issue for each reported misconfiguration, or comment on the open one")
    scan_parser.add_argument("--skip-app", action="store_true", help="skip the attachment upload and download through the API")
    verify_parser = sub.add_parser("verify", help="confirm the remediation, requery compliance, and check the app")
    verify_parser.add_argument("--issue", type=int, metavar="NUMBER",
                               help="comment the evidence on this Issue; close it when verified, reopen it if the fix is missing")
    verify_parser.add_argument("--timeout", type=int, default=900, metavar="SECONDS",
                               help="how long to wait for Azure Policy to report Compliant (default 900; 0 checks once)")
    verify_parser.add_argument("--interval", type=int, default=30, metavar="SECONDS", help="polling interval (default 30)")
    verify_parser.add_argument("--no-refresh", action="store_true", help="do not start an Azure Policy evaluation")
    verify_parser.add_argument("--skip-app", action="store_true", help="skip the attachment upload and download through the API")
    args = parser.parse_args(argv)
    utf8_stdout()
    sys.stdout, sys.stderr = MaskedOutput(sys.stdout), MaskedOutput(sys.stderr)
    try:
        posture = Posture(CONTROL)
        return scan(args, posture) if args.command == "scan" else verify(args, posture)
    except AzureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
