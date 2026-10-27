"""Apply this solution's Azure SRE Agent configuration (sre-agent/) to the live agent, or check it offline.

Bicep (infra/sre-agent.bicep) deploys the agent itself: its identity and read-only permissions, the Azure Monitor
incident platform, and the telemetry connectors. Everything else lives in the agent's data plane and is applied here
from the files in sre-agent/, described by sre-agent/agent.yaml:

  knowledge      knowledge/*.md, uploaded to the agent's knowledge base
  skills         skills/*.md, procedures with name and description front matter
  custom agent   instructions.md, its tools and skills, and a Stop hook (hooks/evidence-checklist.md)
  tool policy    global allow, ask, and deny rules
  response plan  which Azure Monitor alerts go to the custom agent, in Review mode. The default quickstart plan is
                 removed so an alert is not investigated twice.

{{NAME}} placeholders in the files are filled from settings of the same name.

Usage
  python configure_sre_agent.py --check     validate the definitions offline; no Azure access (pull request check)
  python configure_sre_agent.py             apply them to the agent, then read everything back
  python configure_sre_agent.py --dry-run   print what would be sent, without sending it

Settings come from environment variables first, then this solution's azd environment: AZURE_SUBSCRIPTION_ID,
AZURE_RESOURCE_GROUP, SRE_AGENT_NAME, and the names used in the placeholders. Signs in with the Azure CLI (`az login`
locally, azure/login in GitHub Actions). Applying needs the SRE Agent Administrator role on the agent; with SRE Agent
Author plus Standard User everything but the global tool policy is applied (use --skip-tool-policy).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

from azd_env import SOLUTION, setting, utf8_stdout

CONFIG_DIR = SOLUTION / "sre-agent"
ARM = "https://management.azure.com"
ARM_API_VERSION = "2026-01-01"
DATA_PLANE_SCOPE = "https://azuresre.dev/.default"
ARM_SCOPE = "https://management.azure.com/.default"
QUICKSTART_PLAN = "quickstart_handler"
PLACEHOLDERS = (
    "AZURE_RESOURCE_GROUP",
    "WORKER_APP_NAME",
    "API_APP_NAME",
    "APPLICATIONINSIGHTS_NAME",
    "LOG_ANALYTICS_NAME",
    "BACKLOG_ALERT_NAME",
    "BACKLOG_ALERT_THRESHOLD_SECONDS",
)
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
WRITE_TOOLS = {"RunAzCliWriteCommands", "RunKubectlWriteCommand"}


@dataclass
class Skill:
    name: str
    description: str
    tools: list[str]
    content: str


@dataclass
class Config:
    agent: dict
    instructions: str
    stop_hook: str
    skills: list[Skill]
    knowledge: dict[str, str]
    plan: dict
    policy: dict


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
        skills.append(Skill(meta.get("name", ""), meta.get("description", ""), list(entry.get("tools", [])), text))
    knowledge = {Path(rel).name: read(rel) for rel in manifest.get("knowledge", [])}
    return Config(agent, read(agent["instructions"]), read(agent["stopHook"]), skills, knowledge,
                  manifest["responsePlan"], manifest["toolPolicy"])


def check(config: Config) -> list[str]:
    """The rules every change to sre-agent/ must keep. Returns the problems found."""
    problems = []
    agent, plan, policy = config.agent, config.plan, config.policy
    names = [agent.get("name", ""), plan.get("name", ""), *[s.name for s in config.skills]]
    problems += [f"name '{n}' must be lowercase letters, digits, and hyphens" for n in names if not NAME.match(n)]
    problems += [f"skill '{s.name}' needs a description" for s in config.skills if not s.description]
    known_skills = {s.name for s in config.skills}
    problems += [f"custom agent uses unknown skill '{s}'" for s in agent.get("skills", []) if s not in known_skills]

    texts = {"instructions.md": config.instructions, "stop hook": config.stop_hook, **config.knowledge,
             **{s.name: s.content for s in config.skills}}
    for source, text in texts.items():
        problems += [f"{source}: unknown placeholder {{{{{p}}}}}" for p in PLACEHOLDER.findall(text) if p not in PLACEHOLDERS]

    if plan.get("agentMode") != "Review":
        problems.append("the response plan must use agentMode Review: a person approves every change")
    severities = plan.get("severities") or []
    if not severities or any(s not in {f"Sev{i}" for i in range(5)} for s in severities):
        problems.append("response plan severities must be a non-empty list of Sev0 to Sev4")
    if not plan.get("titleContains"):
        problems.append("the response plan needs titleContains, so it only takes this solution's alert")

    allow, ask, deny = (set(policy.get(k, [])) for k in ("allow", "ask", "deny"))
    for tool in WRITE_TOOLS & set(agent.get("tools", [])):
        if tool in allow:
            problems.append(f"tool policy must not allow {tool} without approval")
        if tool not in ask:
            problems.append(f"tool policy must ask before {tool}")
    problems += [f"custom agent tool {t} is denied by the tool policy" for t in agent.get("tools", []) if t in deny]
    if not any("delete" in rule for rule in deny):
        problems.append("tool policy must deny delete commands")
    return problems


def render(text: str) -> str:
    return PLACEHOLDER.sub(lambda m: setting(m.group(1)), text)


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


def agent_endpoint(client: Client, agent_id: str) -> str:
    """Waits until the agent is provisioned and returns its data-plane endpoint."""
    url = f"{ARM}{agent_id}?api-version={ARM_API_VERSION}"
    for _ in range(30):
        status, _, body = client.call("GET", url, ARM_SCOPE)
        if status != 200:
            raise SystemExit(f"error: cannot read the SRE Agent ({status}): {body}")
        props = body.get("properties", {})
        if props.get("provisioningState") == "Succeeded" and props.get("agentEndpoint"):
            return props["agentEndpoint"].rstrip("/")
        print(f"  agent is {props.get('provisioningState')}; waiting")
        time.sleep(20)
    raise SystemExit("error: the SRE Agent did not finish provisioning in 10 minutes")


def multipart(field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode()
    return head + content + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def items(body: object) -> list[dict]:
    if isinstance(body, dict):
        body = body.get("value", [])
    return body if isinstance(body, list) else []


def apply(config: Config, dry_run: bool, skip_tool_policy: bool) -> int:
    agent, plan = config.agent, config.plan
    agent_body = {
        "name": agent["name"],
        "type": "ExtendedAgent",
        "tags": [],
        "properties": {
            "instructions": render(config.instructions),
            "handoffDescription": agent["handoffDescription"],
            "handoffs": [],
            "tools": agent["tools"],
            "enableSkills": True,
            "allowedSkills": agent["skills"],
            "hooks": {"Stop": [{"type": "prompt", "prompt": render(config.stop_hook), "timeout": 60, "maxRejections": 2}]},
        },
    }
    plan_body = {
        "name": plan["name"],
        "type": "IncidentFilter",
        "tags": [],
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
    }
    skill_bodies = [{
        "name": s.name, "type": "Skill", "tags": [],
        "properties": {"name": s.name, "description": s.description, "tools": s.tools,
                       "skillContent": render(s.content), "additionalFiles": []},
    } for s in config.skills]
    knowledge = {name: render(text) for name, text in config.knowledge.items()}
    if dry_run:
        print(json.dumps({"knowledge": list(knowledge), "skills": skill_bodies, "customAgent": agent_body,
                          "toolPolicy": config.policy, "responsePlan": plan_body}, indent=2))
        return 0

    agent_id = (f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
                f"/providers/Microsoft.App/agents/{setting('SRE_AGENT_NAME')}")
    client = Client()
    print(f"SRE Agent {setting('SRE_AGENT_NAME')} in {setting('AZURE_RESOURCE_GROUP')}")
    endpoint = agent_endpoint(client, agent_id)
    failures: list[str] = []

    def put(kind: str, name: str, body: dict, attempts: int = 3) -> None:
        status, _, response = client.call("PUT", f"{endpoint}/api/v2/extendedAgent/{kind}/{name}", DATA_PLANE_SCOPE,
                                          body, attempts=attempts, wait=30)
        ok = 200 <= status < 300
        print(f"  {'ok' if ok else 'FAILED'}  {kind}/{name}" + ("" if ok else f" (HTTP {status}): {str(response)[:300]}"))
        if not ok:
            failures.append(f"{kind}/{name}")

    print("Knowledge")
    for name, text in knowledge.items():
        data, content_type = multipart("files", name, text.encode("utf-8"), "text/markdown")
        status, _, response = client.call("POST", f"{endpoint}/api/v1/agentmemory/upload?triggerIndexing=true",
                                          DATA_PLANE_SCOPE, raw=data, headers={"Content-Type": content_type}, attempts=3)
        ok = 200 <= status < 300
        print(f"  {'ok' if ok else 'FAILED'}  {name}" + ("" if ok else f" (HTTP {status}): {str(response)[:300]}"))
        if not ok:
            failures.append(f"knowledge/{name}")

    print("Skills")
    for body in skill_bodies:
        put("skills", body["name"], body)

    print("Custom agent")
    put("agents", agent["name"], agent_body)

    print("Tool policy")
    if skip_tool_policy:
        print("  skipped (--skip-tool-policy)")
    else:
        url = f"{endpoint}/api/v2/agent/settings/global"
        status, headers, settings = client.call("GET", url, DATA_PLANE_SCOPE, attempts=3)
        if status == 200:
            settings = settings if isinstance(settings, dict) else {}
            settings["permissions"] = {k: config.policy.get(k, []) for k in ("allow", "ask", "deny")}
            etag = headers.get("ETag") or headers.get("Etag") or "*"
            status, _, response = client.call("PUT", url, DATA_PLANE_SCOPE, settings, headers={"If-Match": etag})
        ok = 200 <= status < 300
        print(f"  {'ok' if ok else 'FAILED'}  allow {len(config.policy.get('allow', []))}, ask "
              f"{len(config.policy.get('ask', []))}, deny {len(config.policy.get('deny', []))}"
              + ("" if ok else f" (HTTP {status}); needs the SRE Agent Administrator role"))
        if not ok:
            failures.append("tool policy")

    print("Response plan")
    put("incidentFilters", plan["name"], plan_body, attempts=5)
    status, _, plans = client.call("GET", f"{endpoint}/api/v2/extendedAgent/incidentFilters", DATA_PLANE_SCOPE)
    for other in items(plans):
        if other.get("name") == QUICKSTART_PLAN:
            status, _, _ = client.call("DELETE", f"{endpoint}/api/v2/extendedAgent/incidentFilters/{QUICKSTART_PLAN}",
                                       DATA_PLANE_SCOPE)
            print(f"  {'ok' if status < 300 else 'FAILED'}  removed the default {QUICKSTART_PLAN} plan")
        elif other.get("name") != plan["name"]:
            print(f"  note    other response plan on this agent: {other.get('name')}")

    print("Read back")
    checks = {
        f"skills/{s.name}": f"{endpoint}/api/v2/extendedAgent/skills/{s.name}" for s in config.skills
    } | {
        f"agents/{agent['name']}": f"{endpoint}/api/v2/extendedAgent/agents/{agent['name']}",
        f"incidentFilters/{plan['name']}": f"{endpoint}/api/v2/extendedAgent/incidentFilters/{plan['name']}",
    }
    for label, url in checks.items():
        status, _, body = client.call("GET", url, DATA_PLANE_SCOPE)
        props = body.get("properties", {}) if isinstance(body, dict) else {}
        ok = status == 200
        if ok and label.startswith("agents/"):
            ok = set(agent["tools"]) <= set(props.get("tools", [])) and set(agent["skills"]) <= set(props.get("allowedSkills", []))
        if ok and label.startswith("incidentFilters/"):
            ok = props.get("handlingAgent") == agent["name"] and props.get("agentMode") == plan["agentMode"]
        print(f"  {'ok' if ok else 'FAILED'}  {label}")
        if not ok:
            failures.append(f"read back {label}")

    if failures:
        print(f"\n{len(failures)} item(s) failed: {', '.join(failures)}")
        return 1
    print(f"\nSRE Agent configured. Response plan '{plan['name']}' sends {', '.join(plan['severities'])} alerts whose "
          f"title contains '{plan['titleContains']}' to '{agent['name']}' in {plan['agentMode']} mode.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate sre-agent/ offline and exit; no Azure access")
    parser.add_argument("--dry-run", action="store_true", help="render everything and print it instead of applying it")
    parser.add_argument("--skip-tool-policy", action="store_true",
                        help="do not change the global tool policy (for identities without SRE Agent Administrator)")
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
              f"{config.plan['agentMode']} mode, writes need approval, deletes denied.")
        return 0
    return apply(config, args.dry_run, args.skip_tool_policy)


if __name__ == "__main__":
    sys.exit(main())
