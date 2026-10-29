"""Apply this solution's Azure SRE Agent configuration (sre-agent/) to the live agent, or check it offline.

Bicep (infra/sre-agent.bicep) deploys the agent itself: its identity and read-only permissions, the Azure Monitor
incident platform, and the telemetry connectors. Everything else lives in the agent's data plane and is applied here
from the files in sre-agent/, described by sre-agent/agent.yaml:

  knowledge      knowledge/*.md, uploaded to the agent's knowledge base
  skills         skills/*.md, procedures with name and description front matter
  custom agent   instructions.md, its tools and skills, and a Stop hook (hooks/evidence-checklist.md)
  GitHub         the GitHub Issue tools, for the custom agent and the file-incident-record skill. A person connects
                 GitHub once in the agent's portal (Build + setup, Code access, with a token limited to Issues); until
                 then the agent has no GitHub tool. Run this
                 script again after connecting it
  guard hook     hooks/no-identifiers.py, a global PreToolUse hook that blocks a GitHub Issue call whose text contains
                 an identifier of this deployment (GUID, host name, resource id, suffixed name, e-mail address)
  tool policy    global allow, ask, and deny rules: Azure writes and GitHub Issue writes ask first; pull requests and
                 workflow runs are denied
  response plan  which Azure Monitor alerts go to the custom agent, in Review mode. The default quickstart plan is
                 removed so an alert is not investigated twice.

{{NAME}} placeholders in the files are filled from settings of the same name, plus GITHUB_REPOSITORY (this
repository, from the origin remote) and RESOURCE_SUFFIXES (the random suffixes in this deployment's resource names).

Usage
  python configure_sre_agent.py --check     validate the definitions and test the guard hook offline; no Azure access
  python configure_sre_agent.py             apply them to the agent, then read everything back
  python configure_sre_agent.py --dry-run   print what would be sent, without sending it

Settings come from environment variables first, then this solution's azd environment: AZURE_SUBSCRIPTION_ID,
AZURE_RESOURCE_GROUP, SRE_AGENT_NAME, WORKER_APP_NAME, and the names used in the placeholders. Signs in with the Azure
CLI (`az login`). Applying needs the SRE Agent Administrator role on the agent, which `azd up` gives the person who
runs it: only an Administrator can change the global tool policy and hooks.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

from azd_env import REPO, SOLUTION, setting, utf8_stdout

CONFIG_DIR = SOLUTION / "sre-agent"
ARM = "https://management.azure.com"
ARM_API_VERSION = "2026-01-01"
DATA_PLANE_SCOPE = "https://azuresre.dev/.default"
ARM_SCOPE = "https://management.azure.com/.default"
QUICKSTART_PLAN = "quickstart_handler"
PLACEHOLDERS = (
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "WORKER_APP_NAME",
    "API_APP_NAME",
    "APPLICATIONINSIGHTS_NAME",
    "LOG_ANALYTICS_NAME",
    "BACKLOG_ALERT_NAME",
    "BACKLOG_ALERT_THRESHOLD_SECONDS",
    "GITHUB_REPOSITORY",
    "RESOURCE_SUFFIXES",
)
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
# Tools that can change Azure resources or run arbitrary commands. None may run without a person's approval.
WRITE_TOOLS = {"RunAzCliWriteCommands", "RunKubectlWriteCommand", "RunShellCommand", "RunInTerminal", "Terminal",
               "bash", "shell", "execute_bash"}
# Names in the style of GitHub connector tools, to test the github patterns offline.
GITHUB_ISSUE_SAMPLES = ("CreateGitHubIssue", "AddCommentToGitHubIssue", "github_create_issue")
GITHUB_DENIED_SAMPLES = ("CreateGitHubPullRequest", "MergePullRequest", "TriggerGitHubWorkflow", "github_dispatch_workflow")


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    content: str
    github_issue_tools: bool


@dataclass
class Config:
    agent: dict
    instructions: str
    stop_hook: str
    skills: list[Skill]
    knowledge: dict[str, str]
    plan: dict
    policy: dict
    github: dict
    guard_script: str


def read(relative: str) -> str:
    path = CONFIG_DIR / relative
    if not path.is_file():
        raise SystemExit(f"error: {path.relative_to(SOLUTION)} not found (referenced in sre-agent/agent.yaml)")
    return path.read_text(encoding="utf-8")


def front_matter(text: str, source: str) -> dict:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise SystemExit(f"error: {source} must start with front matter (name, description)")
    return yaml.safe_load(match.group(1)) or {}


def load() -> Config:
    manifest = yaml.safe_load(read("agent.yaml"))
    agent = manifest["customAgent"]
    skills = []
    for entry in manifest.get("skills", []):
        text = read(entry["file"])
        meta = front_matter(text, entry["file"])
        skills.append(Skill(meta.get("name", ""), meta.get("description", ""), list(entry.get("tools", [])), text,
                            bool(entry.get("githubIssueTools"))))
    knowledge = {Path(rel).name: read(rel) for rel in manifest.get("knowledge", [])}
    github = manifest.get("github") or {}
    return Config(agent, read(agent["instructions"]), read(agent["stopHook"]), skills, knowledge,
                  manifest["responsePlan"], manifest["toolPolicy"], github, read(github["guardHook"]["script"]))


def glob_regex(patterns: list[str]) -> str:
    """A hook matcher (regex, anchored by the service as ^(...)$) for tool name globs where * is the only wildcard."""
    return "|".join(".*".join(re.escape(part) for part in pattern.split("*")) for pattern in patterns)


def run_guard(script: str, tool_input: object) -> dict | None:
    """Runs the guard hook locally the way the agent does: the tool call as JSON on stdin. Returns its decision."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "CreateGitHubIssue", "tool_input": tool_input}
    proc = subprocess.run([sys.executable, "-c", script], input=json.dumps(event), capture_output=True, text=True,
                          timeout=30)
    if proc.returncode != 0:
        return {"decision": "error", "reason": proc.stderr.strip()[-300:]}
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        return {"decision": "error", "reason": f"not JSON: {proc.stdout.strip()[:200]}"}


def guard_problems(script: str) -> list[str]:
    """Tests the guard hook with a clean incident record and with each kind of identifier it must block."""
    suffix = "q1w2e3r4t5y6u"
    script = script.replace("{{RESOURCE_SUFFIXES}}", suffix)
    clean = {
        "owner": "contoso", "repo": "requesthub", "labels": ["ai-sdlc", "phase:operate"],
        "title": "Incident record: notification backlog, 2026-10-29",
        "body": "The worker delivered notifications late from 14:03 to 14:31 UTC (peak oldest wait 1,020 s). Root cause: "
                "the delay fault on the worker. Mitigation: `az containerapp update -n <worker> -g <resource group> "
                "--remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc`, approved by an SRE Agent Administrator. "
                "Evidence: the RequestHub notification backlog alert in portal.azure.com; requesthub-notification-backlog.",
    }
    leaks = {
        "a GUID": "thread 12345678-1234-1234-1234-123456789abc",
        "an id without hyphens": "operation_Id 0123456789abcdef0123456789abcdef",
        "an Azure host name": "https://ca-api.politebeach-1a2b3c.centralus.azurecontainerapps.io/health",
        "an Azure resource id": "/subscriptions/sub/resourceGroups/rg-demo/providers/Microsoft.App/containerApps/worker",
        "an e-mail address": "approved by someone@example.com",
        "a tenant domain": "signed in to contoso.onmicrosoft.com",
        "this deployment's suffix": f"registry cr{suffix}",
        "a suffixed name": "worker ca-worker-z9y8x7w6v5u4t",
    }
    problems = []
    decision = run_guard(script, clean)
    if decision is not None:
        problems.append(f"guard hook must let a clean incident record through to the tool policy, got {decision}")
    for kind, leak in leaks.items():
        for tool_input in ({**clean, "body": clean["body"] + " " + leak}, json.dumps({**clean, "title": leak})):
            decision = run_guard(script, tool_input)
            if not decision or decision.get("decision") != "block":
                problems.append(f"guard hook must block {kind}, got {decision}")
                break
    return problems


def check(config: Config) -> list[str]:
    """The rules every change to sre-agent/ must keep. Returns the problems found."""
    problems = []
    agent, plan, policy = config.agent, config.plan, config.policy
    names = [agent.get("name", ""), plan.get("name", ""), *[s.name for s in config.skills]]
    problems += [f"name '{n}' must be lowercase letters, digits, and hyphens" for n in names if not NAME.match(n)]
    problems += [f"skill '{s.name}' needs a description" for s in config.skills if not s.description]
    known_skills = {s.name for s in config.skills}
    problems += [f"custom agent uses unknown skill '{s}'" for s in agent.get("skills", []) if s not in known_skills]

    texts = {"instructions.md": config.instructions, "stop hook": config.stop_hook, "guard hook": config.guard_script,
             **config.knowledge, **{s.name: s.content for s in config.skills}}
    for source, text in texts.items():
        problems += [f"{source}: unknown placeholder {{{{{p}}}}}" for p in PLACEHOLDER.findall(text) if p not in PLACEHOLDERS]

    if plan.get("agentMode") != "Review":
        problems.append("the response plan must use agentMode Review: a person approves every change")
    severities = plan.get("severities") or []
    if not severities or any(s not in {f"Sev{i}" for i in range(5)} for s in severities):
        problems.append("response plan severities must be a non-empty list of Sev0 to Sev4")
    if not plan.get("titleContains"):
        problems.append("the response plan needs titleContains, so it only takes this solution's alert")

    allow, ask, deny = (list(policy.get(k, [])) for k in ("allow", "ask", "deny"))
    for rule in allow:
        tool_glob = rule.split("(", 1)[0].strip()
        widened = sorted(t for t in WRITE_TOOLS | set(GITHUB_ISSUE_SAMPLES) if fnmatch.fnmatchcase(t, tool_glob))
        if widened:
            problems.append(f"tool policy must not allow '{rule}': it lets {', '.join(widened)} run without approval")
    used = set(agent.get("tools", [])) | {t for s in config.skills for t in s.tools}
    for tool in sorted(WRITE_TOOLS & used):
        if tool not in ask:
            problems.append(f"tool policy must ask before {tool}")
    problems += [f"custom agent tool {t} is denied by the tool policy" for t in agent.get("tools", []) if t in deny]
    if not any("delete" in rule for rule in deny):
        problems.append("tool policy must deny delete commands")

    github = config.github
    issue_tools, github_deny, guard = github.get("issueTools") or [], github.get("deny") or [], github.get("guardHook") or {}
    if not issue_tools:
        problems.append("github.issueTools must name the GitHub Issue tools the custom agent may use")
    for sample in GITHUB_ISSUE_SAMPLES:
        if not any(fnmatch.fnmatchcase(sample, p) for p in issue_tools):
            problems.append(f"github.issueTools must cover Issue tools such as {sample}")
    for sample in GITHUB_DENIED_SAMPLES:
        if not any(fnmatch.fnmatchcase(sample, p) for p in github_deny):
            problems.append(f"github.deny must deny pull request and workflow tools such as {sample}")
        if any(fnmatch.fnmatchcase(sample, p) for p in issue_tools):
            problems.append(f"github.issueTools must not cover {sample}")
    if guard.get("failMode") != "block":
        problems.append("the guard hook must use failMode block: if it cannot run, nothing reaches GitHub")
    if not NAME.match(str(guard.get("name", ""))):
        problems.append("the guard hook needs a name of lowercase letters, digits, and hyphens")
    matcher = re.compile(f"^({glob_regex(issue_tools)})$") if issue_tools else None
    if matcher:
        # The approved Azure CLI command carries a GUID and suffixed names; the guard must never see it.
        problems += [f"the guard hook's matcher must not match {t}" for t in sorted(used | WRITE_TOOLS) if matcher.match(t)]
    problems += guard_problems(config.guard_script)
    return problems


def render(text: str, extra: dict[str, str] | None = None) -> str:
    return PLACEHOLDER.sub(lambda m: (extra or {}).get(m.group(1)) or setting(m.group(1)), text)


def github_repository() -> str:
    """owner/name of this repository: GITHUB_REPOSITORY if set, otherwise the origin remote."""
    proc = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=REPO)
    match = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", proc.stdout.strip())
    return setting("GITHUB_REPOSITORY", match.group(1) if match else None)


class Client:
    """Minimal REST client for ARM and the agent's data plane, with Azure CLI credentials."""

    def __init__(self) -> None:
        from azure.identity import AzureCliCredential

        self.credential = AzureCliCredential(process_timeout=60)
        self.tokens: dict[str, tuple[str, float]] = {}

    def token(self, scope: str) -> str:
        cached = self.tokens.get(scope)
        if not cached or cached[1] - time.time() < 300:
            token = self.credential.get_token(scope)
            self.tokens[scope] = (token.token, token.expires_on)
        return self.tokens[scope][0]

    def call(self, method: str, url: str, scope: str, body: object = None, headers: dict | None = None,
             raw: bytes | None = None, attempts: int = 1, wait: int = 20) -> tuple[int, dict, object]:
        for attempt in range(1, attempts + 1):
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            request = urllib.request.Request(url, data=data, method=method)
            request.add_header("Authorization", f"Bearer {self.token(scope)}")
            if body is not None:
                request.add_header("Content-Type", "application/json")
            for key, value in (headers or {}).items():
                request.add_header(key, value)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    text = response.read().decode("utf-8", "replace")
                    try:
                        parsed = json.loads(text) if text.strip() else None
                    except json.JSONDecodeError:
                        parsed = text
                    return response.status, dict(response.headers), parsed
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", "replace")
                if attempt < attempts and (error.code in (404, 409, 429) or error.code >= 500):
                    print(f"    HTTP {error.code}, retrying in {wait}s ({attempt}/{attempts - 1})")
                    time.sleep(wait)
                    continue
                return error.code, dict(error.headers), text
        raise AssertionError("unreachable")


def agent_resource(client: Client, agent_id: str) -> dict:
    """Waits until the agent is provisioned and returns its ARM resource."""
    url = f"{ARM}{agent_id}?api-version={ARM_API_VERSION}"
    for _ in range(30):
        status, _, body = client.call("GET", url, ARM_SCOPE)
        if status != 200:
            raise SystemExit(f"error: cannot read the SRE Agent ({status}): {body}")
        props = body.get("properties", {})
        if props.get("provisioningState") == "Succeeded" and props.get("agentEndpoint"):
            return body
        print(f"  agent is {props.get('provisioningState')}; waiting")
        time.sleep(20)
    raise SystemExit("error: the SRE Agent did not finish provisioning in 10 minutes")


def resource_suffixes(agent: dict) -> str:
    """The random suffixes in this deployment's resource names: RequestHub's, and the SRE Agent module's own."""
    suffixes = {setting("WORKER_APP_NAME").rsplit("-", 1)[-1]}
    for identity_id in (agent.get("identity") or {}).get("userAssignedIdentities") or {}:
        suffixes.add(identity_id.rsplit("/", 1)[-1].rsplit("-", 1)[-1])
    return ",".join(sorted(s.lower() for s in suffixes if s))


def multipart(field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode()
    return head + content + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def items(body: object) -> list[dict]:
    if isinstance(body, dict):
        body = body.get("value", [])
    return body if isinstance(body, list) else []


def build(config: Config, extra: dict[str, str], github_tools: list[str]) -> dict:
    """The request bodies for everything this script applies, with placeholders filled in."""
    agent, plan, github = config.agent, config.plan, config.github
    guard, issue_patterns = github["guardHook"], list(github["issueTools"])
    ask, deny = list(config.policy.get("ask", [])), list(config.policy.get("deny", []))
    return {
        "knowledge": {name: render(text, extra) for name, text in config.knowledge.items()},
        "skills": [{
            "name": s.name, "type": "Skill", "tags": [],
            "properties": {"name": s.name, "description": render(s.description, extra),
                           "tools": s.tools + (github_tools if s.github_issue_tools else []),
                           "skillContent": render(s.content, extra), "additionalFiles": []},
        } for s in config.skills],
        "customAgent": {
            "name": agent["name"], "type": "ExtendedAgent", "tags": [],
            "properties": {
                "instructions": render(config.instructions, extra),
                "handoffDescription": agent["handoffDescription"],
                "handoffs": [],
                "tools": agent["tools"] + github_tools,
                "enableSkills": True,
                "allowedSkills": agent["skills"],
                "hooks": {"Stop": [{"type": "prompt", "prompt": render(config.stop_hook, extra), "timeout": 60,
                                    "maxRejections": 2}]},
            },
        },
        "toolPolicy": {
            "allow": list(config.policy.get("allow", [])),
            "ask": ask + [p for p in issue_patterns if p not in ask],
            "deny": deny + [p for p in github.get("deny", []) if p not in deny],
        },
        "guardHook": {
            "name": guard["name"], "type": "GlobalHook", "tags": [],
            "properties": {"eventType": "PreToolUse", "enabled": True, "hook": {
                "type": "command", "script": render(config.guard_script, extra), "matcher": glob_regex(issue_patterns),
                "timeout": int(guard.get("timeout", 30)), "failMode": guard["failMode"]}},
        },
        "responsePlan": {
            "name": plan["name"], "type": "IncidentFilter", "tags": [],
            "properties": {
                "incidentPlatform": "AzMonitor",
                "isEnabled": True,
                "priorities": plan["severities"],
                "titleContains": plan["titleContains"],
                "handlingAgent": agent["name"],
                "agentMode": plan["agentMode"],
                "maxAutomatedInvestigationAttempts": plan.get("maxAutomatedInvestigationAttempts", 3),
                "mergeEnabled": plan.get("mergeEnabled", False),
            },
        },
    }


def apply(config: Config, dry_run: bool) -> int:
    agent, plan, github = config.agent, config.plan, config.github
    issue_patterns = list(github["issueTools"])
    if dry_run:
        extra = {"GITHUB_REPOSITORY": github_repository(), "RESOURCE_SUFFIXES": "<read from the agent when applied>"}
        bodies = build(config, extra, ["<GitHub Issue tools from the agent's tool catalog>"])
        bodies["knowledge"] = list(bodies["knowledge"])
        print(json.dumps(bodies, indent=2))
        return 0

    agent_id = (f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
                f"/providers/Microsoft.App/agents/{setting('SRE_AGENT_NAME')}")
    client = Client()
    print(f"SRE Agent {setting('SRE_AGENT_NAME')} in {setting('AZURE_RESOURCE_GROUP')}")
    resource = agent_resource(client, agent_id)
    endpoint = resource["properties"]["agentEndpoint"].rstrip("/")
    extra = {"GITHUB_REPOSITORY": github_repository(), "RESOURCE_SUFFIXES": resource_suffixes(resource)}
    failures: list[str] = []

    def put(kind: str, name: str, body: dict, attempts: int = 3) -> None:
        status, _, response = client.call("PUT", f"{endpoint}/api/v2/extendedAgent/{kind}/{name}", DATA_PLANE_SCOPE,
                                          body, attempts=attempts, wait=30)
        ok = 200 <= status < 300
        print(f"  {'ok' if ok else 'FAILED'}  {kind}/{name}" + ("" if ok else f" (HTTP {status}): {str(response)[:300]}"))
        if not ok:
            failures.append(f"{kind}/{name}")

    print("Tools")
    status, _, body = client.call("GET", f"{endpoint}/api/v2/agent/tools", DATA_PLANE_SCOPE, attempts=3)
    listed = body.get("data") if isinstance(body, dict) else body
    catalog = {t.get("name") for t in listed or [] if isinstance(t, dict)}
    if status != 200 or not catalog:
        print(f"  FAILED  cannot read the agent's tool catalog (HTTP {status})")
        failures.append("tool catalog")
    named = set(agent["tools"]) | {t for s in config.skills for t in s.tools}
    for tool in sorted(named - catalog if catalog else set()):
        print(f"  FAILED  {tool} is not in the agent's tool catalog")
        failures.append(f"tool {tool}")
    github_tools = sorted(t for t in catalog if any(fnmatch.fnmatchcase(t, p) for p in issue_patterns))
    if github_tools:
        print(f"  ok      GitHub Issue tools: {', '.join(github_tools)}")
    else:
        print(f"  note    GitHub is not connected: no tool matches {', '.join(issue_patterns)}. Until a person connects "
              "it (README, Connect GitHub) and runs this script again, the agent puts the incident record in its reply.")
    bodies = build(config, extra, github_tools)

    print("Knowledge")
    for name, text in bodies["knowledge"].items():
        data, content_type = multipart("files", name, text.encode("utf-8"), "text/markdown")
        status, _, response = client.call("POST", f"{endpoint}/api/v1/agentmemory/upload?triggerIndexing=true",
                                          DATA_PLANE_SCOPE, raw=data, headers={"Content-Type": content_type}, attempts=3)
        ok = 200 <= status < 300
        print(f"  {'ok' if ok else 'FAILED'}  {name}" + ("" if ok else f" (HTTP {status}): {str(response)[:300]}"))
        if not ok:
            failures.append(f"knowledge/{name}")

    print("Skills")
    for skill in bodies["skills"]:
        put("skills", skill["name"], skill)

    print("Custom agent")
    put("agents", agent["name"], bodies["customAgent"])

    print("Tool policy")
    url = f"{endpoint}/api/v2/agent/settings/global"
    permissions = bodies["toolPolicy"]
    status, headers, settings = client.call("GET", url, DATA_PLANE_SCOPE, attempts=3)
    if status == 200:
        settings = settings if isinstance(settings, dict) else {}
        settings["permissions"] = permissions
        etag = headers.get("ETag") or headers.get("Etag") or "*"
        status, _, response = client.call("PUT", url, DATA_PLANE_SCOPE, settings, headers={"If-Match": etag})
    ok = 200 <= status < 300
    print(f"  {'ok' if ok else 'FAILED'}  allow {len(permissions['allow'])}, ask {len(permissions['ask'])}, deny "
          f"{len(permissions['deny'])}" + ("" if ok else f" (HTTP {status}); needs the SRE Agent Administrator role"))
    if not ok:
        failures.append("tool policy")

    print("Guard hook")
    hook = bodies["guardHook"]
    put("hooks", hook["name"], hook)
    status, _, hooks = client.call("GET", f"{endpoint}/api/v2/extendedAgent/hooks", DATA_PLANE_SCOPE)
    for other in items(hooks):
        if other.get("name") != hook["name"]:
            print(f"  note    other hook on this agent: {other.get('name')}")

    print("Response plan")
    put("incidentFilters", plan["name"], bodies["responsePlan"], attempts=5)
    status, _, plans = client.call("GET", f"{endpoint}/api/v2/extendedAgent/incidentFilters", DATA_PLANE_SCOPE)
    for other in items(plans):
        if other.get("name") == QUICKSTART_PLAN:
            status, _, _ = client.call("DELETE", f"{endpoint}/api/v2/extendedAgent/incidentFilters/{QUICKSTART_PLAN}",
                                       DATA_PLANE_SCOPE)
            print(f"  {'ok' if status < 300 else 'FAILED'}  removed the default {QUICKSTART_PLAN} plan")
        elif other.get("name") != plan["name"]:
            print(f"  note    other response plan on this agent: {other.get('name')}")

    print("Read back")
    base = f"{endpoint}/api/v2/extendedAgent"
    checks = {f"skills/{s['name']}": f"{base}/skills/{s['name']}" for s in bodies["skills"]} | {
        f"agents/{agent['name']}": f"{base}/agents/{agent['name']}",
        f"hooks/{hook['name']}": f"{base}/hooks/{hook['name']}",
        f"incidentFilters/{plan['name']}": f"{base}/incidentFilters/{plan['name']}",
        "tool policy": url,
    }
    for label, check_url in checks.items():
        status, _, body = client.call("GET", check_url, DATA_PLANE_SCOPE)
        props = body.get("properties", {}) if isinstance(body, dict) else {}
        ok = status == 200
        if ok and label.startswith("agents/"):
            wanted = bodies["customAgent"]["properties"]
            ok = set(wanted["tools"]) <= set(props.get("tools", [])) and set(agent["skills"]) <= set(props.get("allowedSkills", []))
        if ok and label.startswith("hooks/"):
            got, wanted = props.get("hook") or {}, hook["properties"]["hook"]
            ok = (props.get("eventType") == "PreToolUse" and props.get("enabled") is not False
                  and all(got.get(k) == wanted[k] for k in ("type", "matcher", "failMode")))
        if ok and label.startswith("incidentFilters/"):
            ok = props.get("handlingAgent") == agent["name"] and props.get("agentMode") == plan["agentMode"]
        if ok and label == "tool policy":
            # The service keeps one of two patterns that differ only in case (*Issue* and *issue*).
            got = (body or {}).get("permissions") or {}
            ok = all({p.lower() for p in permissions[k]} <= {p.lower() for p in got.get(k) or []}
                     for k in ("allow", "ask", "deny"))
        print(f"  {'ok' if ok else 'FAILED'}  {label}")
        if not ok:
            failures.append(f"read back {label}")

    if failures:
        print(f"\n{len(failures)} item(s) failed: {', '.join(failures)}")
        return 1
    print(f"\nSRE Agent configured. Response plan '{plan['name']}' sends {', '.join(plan['severities'])} alerts whose "
          f"title contains '{plan['titleContains']}' to '{agent['name']}' in {plan['agentMode']} mode. "
          + (f"It files the incident record in {extra['GITHUB_REPOSITORY']} after a person allows it."
             if github_tools else "GitHub is not connected yet."))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="validate sre-agent/ and test the guard hook offline, then exit; no Azure access")
    parser.add_argument("--dry-run", action="store_true", help="render everything and print it instead of applying it")
    args = parser.parse_args()
    utf8_stdout()
    config = load()
    problems = check(config)
    if problems:
        print("sre-agent/ does not meet the solution's rules:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if args.check:
        print(f"sre-agent/ is valid: custom agent '{config.agent['name']}', {len(config.skills)} skills, "
              f"{len(config.knowledge)} knowledge file(s), response plan '{config.plan['name']}' in "
              f"{config.plan['agentMode']} mode, Azure and GitHub writes need approval, deletes, pull requests, and "
              f"workflow runs denied, guard hook '{config.github['guardHook']['name']}' blocks identifiers.")
        return 0
    return apply(config, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())