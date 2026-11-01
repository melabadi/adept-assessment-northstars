"""Apply this solution's Azure SRE Agent configuration (sre-agent/) to the live agent, or check it offline.

Bicep (infra/sre-agent.bicep) deploys the agent itself: its identity and read-only permissions, the Azure Monitor
incident platform, and the telemetry connectors. Everything else lives in the agent's data plane and is applied here
from the files in sre-agent/, described by sre-agent/agent.yaml:

  knowledge      knowledge/*.md, uploaded to the agent's knowledge base
  skills         skills/*.md, procedures with name and description front matter. The skill earlier versions used to
                 file the record (file-incident-record) is removed
  custom agent   instructions.md, its tools and skills, and a Stop hook (hooks/evidence-checklist.md)
  GitHub         nothing to apply. A person connects this repository once under Build + setup, Code access, with a
                 read-only fine-grained token, so the agent can read its code. The agent gets no GitHub tool: it
                 drafts the incident record in its reply (skills/draft-incident-record.md), and a person reads it and
                 files it. This script reports whether the repository is connected
  guard hook     hooks/no-identifiers.py, a global PreToolUse hook on every GitHub Issue tool, kept as a backstop: it
                 blocks the GitHub write tools the policy denies and any call whose text contains an identifier of
                 this deployment (GUID, trace id, host name, resource id, suffixed name, e-mail address), and otherwise
                 asks a person
  tool policy    global allow, ask, and deny rules: Azure writes ask first, and every GitHub write tool is denied,
                 Issue writes included, by pattern and by the exact names found in the agent's tool catalog. So are
                 the command tools that could use the token: the terminal, shell commands, and Python.
                 CreateGithubIssue stays denied by name: after a person allows it, it appends a footer that names the
                 agent instance and links the thread with the subscription ID and thread GUID, which neither the
                 guard hook nor the approval card shows
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
    "GITHUB_DENIED_TOOLS",
)
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
# Tools that can change Azure resources or run arbitrary commands. None may run without a person's approval.
WRITE_TOOLS = {"RunAzCliWriteCommands", "RunKubectlWriteCommand", "RunShellCommand", "RunInTerminal", "Terminal",
               "bash", "shell", "execute_bash"}
# Command tools that must be denied outright: with GitHub connected, the agent's terminal can use gh and git with the
# connection's token, and nothing in this solution needs a terminal, shell commands, or Python.
COMMAND_TOOLS = ("RunInTerminal", "Terminal", "RunShellCommand", "ExecutePythonCode")
# Skills that earlier versions of this solution applied; removed from the agent when found.
RETIRED_SKILLS = ("file-incident-record",)
# After a person allows it, this tool appends a footer that names the agent instance and links the thread with the
# subscription ID and thread GUID. Neither the guard hook nor the approval card shows it, so it must stay denied.
FOOTER_TOOL = "CreateGithubIssue"
# GitHub tool names to test the github patterns offline: the agent's real runtime tools, names in their style, and
# tools of GitHub's MCP server as a connector would name them.
GITHUB_ISSUE_SAMPLES = ("CreateGithubIssue", "FetchGithubIssue", "FetchGithubIssuesLimited", "CreateGitHubIssue",
                        "AddCommentToGitHubIssue", "github_create_issue", "github_issue_write")
GITHUB_WRITE_SAMPLES = ("CreateGithubIssue", "CreateGitHubIssue", "UpdateGithubIssue", "CloseGithubIssue",
                        "AddCommentToGitHubIssue", "github_create_issue", "github_issue_write", "github_add_issue_comment",
                        "github_update_issue", "CreateGithubPullRequest", "MergePullRequest", "TriggerGitHubWorkflow",
                        "github_dispatch_workflow", "CreateGithubBranch", "PushGithubCommit", "CreateGithubCommitStatus",
                        "CreateGithubWebhook", "github_create_pull_request", "github_merge_pull_request",
                        "github_push_files", "github_create_or_update_file", "github_delete_file",
                        "github_create_repository", "github_fork_repository")


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
        skills.append(Skill(meta.get("name", ""), meta.get("description", ""), list(entry.get("tools", [])), text))
    knowledge = {Path(rel).name: read(rel) for rel in manifest.get("knowledge", [])}
    github = manifest.get("github") or {}
    return Config(agent, read(agent["instructions"]), read(agent["stopHook"]), skills, knowledge,
                  manifest["responsePlan"], manifest["toolPolicy"], github, read(github["guardHook"]["script"]))


def matches(name: str, patterns: list[str]) -> bool:
    """Tool name globs (* is the only wildcard), matched case-insensitively."""
    return any(fnmatch.fnmatchcase(name.lower(), pattern.lower()) for pattern in patterns)


def glob_regex(patterns: list[str]) -> str:
    """A hook matcher for tool name globs. The service anchors it as ^(...)$ and matches case-sensitively, so every
    letter becomes a [xX] class: the matcher then works the same in any regex engine, without flags."""
    def literal(text: str) -> str:
        return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else re.escape(c) for c in text)
    return "|".join(".*".join(literal(part) for part in pattern.split("*")) for pattern in patterns)


def run_guard(script: str, stdin: str) -> tuple[str, str]:
    """Runs the guard hook locally the way the agent does, with this text on stdin. Returns its verdict (ask, block,
    allow, no objection, or error) and a detail, read the way the platform reads hook output."""
    proc = subprocess.run([sys.executable, "-c", script], input=stdin, capture_output=True, text=True, timeout=30)
    out = proc.stdout.strip()
    if proc.returncode == 2:
        return "block", proc.stderr.strip()[-200:]
    if proc.returncode != 0:
        return "error", f"exit code {proc.returncode}: {proc.stderr.strip()[-200:]}"
    if not out:
        return "no objection", "no output"
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        return "error", f"not JSON: {out[:200]}"
    decision = str(result.get("decision") or "").lower() if isinstance(result, dict) else ""
    specific = (result.get("hookSpecificOutput") or {}) if isinstance(result, dict) else {}
    permission = str(specific.get("permissionDecision") or "").lower()
    if decision == "block" or permission == "deny":
        return "block", str(result.get("reason") or specific.get("permissionDecisionReason") or "")[:200]
    if decision in ("allow", "approve") or permission == "allow":
        return "allow", out[:200]
    if permission == "ask":
        return "ask", ""
    return "error", f"unexpected output: {out[:200]}"


def guard_problems(script: str, deny_patterns: list[str]) -> list[str]:
    """Tests the guard hook, the backstop for GitHub Issue tools. Every denied write tool, CreateGithubIssue and an MCP
    server's Issue tool included, must be blocked even with clean text. On an Issue tool the policy does not deny (a
    read), a clean record must wait for a person (ask) and every kind of identifier, hidden or not, must be blocked.
    Every malformed or oversized call must be blocked too. Nothing may come back as allow or as no objection, nothing
    may fail open, and long input must be decided quickly."""
    suffix = "q1w2e3r4t5y6u"
    script = script.replace("{{RESOURCE_SUFFIXES}}", suffix).replace("{{GITHUB_DENIED_TOOLS}}", glob_regex(deny_patterns))
    clean = {
        "owner": "contoso", "repo": "requesthub", "labels": ["ai-sdlc", "phase:operate"],
        "title": "Incident record: notification backlog, 2026-10-29",
        "body": "The worker delivered notifications late from 14:03 to 14:31 UTC (peak oldest wait 1,020 s). Root cause: "
                "the delay fault on the worker. Mitigation: `az containerapp update -n <worker> -g <resource group> "
                "--remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc`, approved by an SRE Agent Administrator. "
                "Evidence: the RequestHub notification backlog alert in portal.azure.com; requesthub-notification-backlog.",
    }
    # An Issue tool the policy does not deny takes the hook's ask path. If every Issue tool were denied, none would.
    open_tool = next((t for t in GITHUB_ISSUE_SAMPLES if not matches(t, deny_patterns)), None)

    def call(tool_input: object, tool: str = open_tool or FOOTER_TOOL) -> str:
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input})

    leaks = {
        "a GUID": "thread 12345678-1234-1234-1234-123456789abc",
        "an id without hyphens": "operation_Id 0123456789abcdef0123456789abcdef",
        "an Azure host name": "https://ca-api.politebeach-1a2b3c.centralus.azurecontainerapps.io/health",
        "an Azure resource id": "/subscriptions/sub/resourceGroups/rg-demo/providers/Microsoft.App/containerApps/worker",
        "an e-mail address": "approved by someone@example.com",
        "a tenant domain": "signed in to contoso.onmicrosoft.com",
        "this deployment's suffix": f"registry cr{suffix}",
        "a suffixed name": "worker ca-worker-z9y8x7w6v5u4t",
        "a GUID split by a zero-width space": "thread 12345678-1234\u200b-1234-1234-123456789abc",
        "a suffix split by a soft hyphen": f"registry cr{suffix[:6]}\u00ad{suffix[6:]}",
        "a GUID in fullwidth digits": "thread \uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18-1234-1234-1234-123456789abc",
        "a name split by an HTML comment": "worker ca-worker-z9y8x7<!-- -->w6v5u4t",
        "a name with an HTML entity": "worker ca-worker-z9y8&#120;7w6v5u4t",
        "a host name with a zero-width space": "https://ca-api.example.centralus.azure\u200bcontainerapps.io",
        "an e-mail address with a URL escape": "approved by someone%40example.com",
        "a name split by an empty HTML tag": "worker ca-worker-z9y8x7<b></b>w6v5u4t",
        "a name split by Markdown bold": "worker ca-worker-z9y8x7**w6v5u4t",
        "a name split by Markdown code": "worker ca-worker-z9y8x7`w6v5u4t",
        "a name split by Markdown strikethrough": "worker ca-worker-z9y8x7~~w6v5u4t",
        "a name split by an underscore": "worker ca-worker-z9y8x7_w6v5u4t",
        "a GUID split by Markdown bold": "thread 12345678**-1234-1234-1234-123456789abc",
    }
    cases: list[tuple[str, str, str]] = []  # (what, stdin, expected verdict)
    if open_tool:
        cases += [
            (f"a clean incident record on {open_tool}", call(clean), "ask"),
            (f"a clean incident record on {open_tool}, sent as a JSON string", call(json.dumps(clean)), "ask"),
        ]
    for kind, leak in leaks.items():
        cases.append((f"{kind} in the body", call({**clean, "body": clean["body"] + " " + leak}), "block"))
        cases.append((f"{kind} in the title, sent as a JSON string", call(json.dumps({**clean, "title": leak})), "block"))
    cases += [(f"the denied tool {p.replace('*', 'Issue')}", call(clean, p.replace("*", "Issue")), "block")
              for p in deny_patterns]
    cases += [
        (f"{FOOTER_TOOL} with a clean incident record", call(clean, FOOTER_TOOL), "block"),
        ("an MCP server's github_create_issue with a clean incident record", call(clean, "github_create_issue"), "block"),
        ("a GUID as a key", call({**clean, "fields": {"12345678-1234-1234-1234-123456789abc": "x"}}), "block"),
        ("a pull request tool", call(clean, "LinkGitHubPullRequestToIssue"), "block"),
        ("a workflow tool", call(clean, "TriggerWorkflowForIssue"), "block"),
        ("a call without tool_input", json.dumps({"hook_event_name": "PreToolUse", "toolInput": clean}), "block"),
        ("a call whose tool_input is null", call(None), "block"),
        ("a call whose tool_input is a number", call(42), "block"),
        ("input that is not JSON", "not json", "block"),
        ("empty input", "", "block"),
        ("text longer than 65,536 characters", call({**clean, "body": "a" * 70_000}), "block"),
    ]
    problems = []
    for what, stdin, expected in cases:
        verdict, detail = run_guard(script, stdin)
        if verdict != expected:
            problems.append(f"guard hook must {'ask a person for' if expected == 'ask' else 'block'} {what}, got "
                            f"{verdict}" + (f" ({detail})" if detail else ""))
    # The agent gives a hook 30 seconds; a slow scan would time out and block every Issue. 60,000 characters with
    # long unbroken runs must be decided in a few seconds.
    for what, body in (("60,000 unbroken letters", "a" * 60_000), ("60,000 characters of a.b.", "a." * 30_000),
                       ("60,000 characters of a-b-", "a-" * 30_000), ("60,000 characters of <!--", "<!--" * 15_000)):
        started = time.monotonic()
        verdict, detail = run_guard(script, call({**clean, "body": body}))
        elapsed = time.monotonic() - started
        if elapsed > 5 or verdict not in ("ask", "block"):
            problems.append(f"guard hook must decide {what} in under 5 seconds, took {elapsed:.1f} s ({verdict})")
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
        widened = sorted(t for t in WRITE_TOOLS | set(GITHUB_ISSUE_SAMPLES) | set(GITHUB_WRITE_SAMPLES)
                         if matches(t, [tool_glob]))
        if widened:
            problems.append(f"tool policy must not allow '{rule}': it lets {', '.join(widened)} run without approval")
    used = set(agent.get("tools", [])) | {t for s in config.skills for t in s.tools}
    for tool in sorted(WRITE_TOOLS & used):
        if tool not in ask:
            problems.append(f"tool policy must ask before {tool}")
    problems += [f"custom agent tool {t} is denied by the tool policy" for t in agent.get("tools", []) if t in deny]
    if not any("delete" in rule for rule in deny):
        problems.append("tool policy must deny delete commands")
    if "RunAzCliWriteCommands(az monitor *)" not in deny:
        problems.append("tool policy must deny az monitor writes: the platform gives the agent's identity Monitoring "
                        "Contributor on the whole subscription, so an approved az monitor command would run with it")
    problems += [f"tool policy must deny {t}: with GitHub connected, a command tool could use the connection's token"
                 for t in COMMAND_TOOLS if t not in deny]

    github = config.github
    issue_tools, github_deny, guard = github.get("issueTools") or [], github.get("deny") or [], github.get("guardHook") or {}
    if "customAgentTools" in github:
        problems.append("github.customAgentTools is not supported: the agent gets no GitHub tool and drafts the "
                        "incident record in its reply, for a person to file")
    if not issue_tools:
        problems.append("github.issueTools must name the GitHub Issue tools, so the guard hook sees every one of them")
    for sample in GITHUB_ISSUE_SAMPLES:
        if not matches(sample, issue_tools):
            problems.append(f"github.issueTools must cover Issue tools such as {sample}")
    for sample in GITHUB_WRITE_SAMPLES:
        if not matches(sample, github_deny):
            problems.append(f"github.deny must deny every GitHub write tool, Issue writes included, such as {sample}")
    if FOOTER_TOOL not in github_deny:
        problems.append(f"github.deny must name {FOOTER_TOOL}: after a person allows it, it appends a footer that names "
                        "the agent instance and links the thread with the subscription ID and thread GUID, which "
                        "neither the guard hook nor the approval card shows")
    problems += [f"the custom agent and its skills must not use the GitHub tool {t}: the agent drafts the incident "
                 "record in its reply, and a person files it"
                 for t in sorted(used) if "github" in t.lower() or matches(t, issue_tools) or matches(t, github_deny)]
    if guard.get("failMode") != "block":
        problems.append("the guard hook must use failMode block: if it cannot run, nothing reaches GitHub")
    if not NAME.match(str(guard.get("name", ""))):
        problems.append("the guard hook needs a name of lowercase letters, digits, and hyphens")
    problems += [f"github pattern '{p}' may use only letters, digits, '_', '-', and '*'"
                 for p in issue_tools + github_deny if not re.fullmatch(r"[A-Za-z0-9_*-]+", p)]
    if issue_tools:
        matcher = re.compile(f"^({glob_regex(issue_tools)})$")
        problems += [f"the guard hook's matcher must match {t}" for t in GITHUB_ISSUE_SAMPLES if not matcher.match(t)]
        # The approved Azure CLI command carries a GUID and suffixed names; the guard must never see it.
        problems += [f"the guard hook's matcher must not match {t}" for t in sorted(used | WRITE_TOOLS) if matcher.match(t)]
    problems += guard_problems(config.guard_script, github_deny)
    return problems


def render(text: str, extra: dict[str, str] | None = None) -> str:
    return PLACEHOLDER.sub(lambda m: (extra or {}).get(m.group(1)) or setting(m.group(1)), text)


def github_repository() -> str:
    """owner/name of this repository: GITHUB_REPOSITORY if set, otherwise the origin remote."""
    proc = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=REPO)
    match = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", proc.stdout.strip())
    return setting("GITHUB_REPOSITORY", match.group(1) if match else None)


def github_connection(client: "Client", endpoint: str, repository: str) -> tuple[bool, str]:
    """Whether this repository is connected under Build + setup, Code access, with a healthy credential: the condition
    for the agent's runtime GitHub tools. Returns the answer and what was found, without any credential detail."""
    status, _, body = client.call("GET", f"{endpoint}/api/v2/repos", DATA_PLANE_SCOPE, attempts=3)
    if status != 200:
        return False, f"cannot read the connected repositories (HTTP {status})"
    wanted = f"https://github.com/{repository}".lower()
    for repo in items(body):
        props = repo.get("properties") or {}
        url = str(props.get("url") or "").lower().removesuffix(".git").rstrip("/")
        if url == wanted:
            healthy = bool((props.get("connection") or {}).get("isHealthy"))
            return healthy, (f"{repository} is connected, credential {'healthy' if healthy else 'not healthy'}, code "
                             f"{str(props.get('cloneStatus') or 'not cloned').lower()}")
    return False, f"{repository} is not connected under Build + setup, Code access"


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


def unique(entries: list[str]) -> list[str]:
    """Entries without repeats, ignoring case: the service keeps only one of two entries that differ only in case."""
    seen: set[str] = set()
    return [e for e in entries if not (e.lower() in seen or seen.add(e.lower()))]


def build(config: Config, extra: dict[str, str], github_denied: list[str]) -> dict:
    """The request bodies for everything this script applies, with placeholders filled in. github_denied are the tools
    in the agent's catalog that github.deny covers, denied by their exact names too."""
    agent, plan, github = config.agent, config.plan, config.github
    guard, issue_patterns = github["guardHook"], list(github["issueTools"])
    ask, deny = list(config.policy.get("ask", [])), list(config.policy.get("deny", []))
    return {
        "knowledge": {name: render(text, extra) for name, text in config.knowledge.items()},
        "skills": [{
            "name": s.name, "type": "Skill", "tags": [],
            "properties": {"name": s.name, "description": render(s.description, extra), "tools": s.tools,
                           "skillContent": render(s.content, extra), "additionalFiles": []},
        } for s in config.skills],
        "customAgent": {
            "name": agent["name"], "type": "ExtendedAgent", "tags": [],
            "properties": {
                "instructions": render(config.instructions, extra),
                "handoffDescription": agent["handoffDescription"],
                "handoffs": [],
                "tools": agent["tools"],
                "enableSkills": True,
                "allowedSkills": agent["skills"],
                "hooks": {"Stop": [{"type": "prompt", "prompt": render(config.stop_hook, extra), "timeout": 60,
                                    "maxRejections": 2}]},
            },
        },
        "toolPolicy": {
            # Patterns cover tools the catalog adds later; exact names do not depend on how the service compares case.
            "allow": unique(list(config.policy.get("allow", []))),
            "ask": unique(ask + issue_patterns),
            "deny": unique(deny + list(github.get("deny", [])) + github_denied),
        },
        "guardHook": {
            "name": guard["name"], "type": "GlobalHook", "tags": [],
            "properties": {"eventType": "PreToolUse", "enabled": True, "description": guard.get("description", ""),
                           "hook": {
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
    deny_patterns = list(github.get("deny", []))
    if dry_run:
        extra = {"GITHUB_REPOSITORY": github_repository(), "RESOURCE_SUFFIXES": "<read from the agent when applied>",
                 "GITHUB_DENIED_TOOLS": glob_regex(deny_patterns)}
        bodies = build(config, extra, ["<GitHub tools in the agent's tool catalog that github.deny covers>"])
        bodies["knowledge"] = list(bodies["knowledge"])
        print(json.dumps(bodies, indent=2))
        return 0

    agent_id = (f"/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{setting('AZURE_RESOURCE_GROUP')}"
                f"/providers/Microsoft.App/agents/{setting('SRE_AGENT_NAME')}")
    client = Client()
    print(f"SRE Agent {setting('SRE_AGENT_NAME')} in {setting('AZURE_RESOURCE_GROUP')}")
    resource = agent_resource(client, agent_id)
    endpoint = resource["properties"]["agentEndpoint"].rstrip("/")
    extra = {"GITHUB_REPOSITORY": github_repository(), "RESOURCE_SUFFIXES": resource_suffixes(resource),
             "GITHUB_DENIED_TOOLS": glob_regex(deny_patterns)}
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
    github_denied = sorted(t for t in catalog if matches(t, deny_patterns))
    connected, detail = github_connection(client, endpoint, extra["GITHUB_REPOSITORY"])
    if connected:
        print(f"  ok      GitHub: {detail}; the agent can read its code and has no GitHub tool that writes")
    else:
        print(f"  note    GitHub: {detail}. The agent works without the repository's code until a person connects it "
              "(README, Connect GitHub); it has no GitHub tool that writes either way.")
    print(f"  ok      GitHub write tools denied by pattern: {', '.join(deny_patterns)}"
          + (f"; in the catalog: {', '.join(github_denied)}" if github_denied else ""))
    bodies = build(config, extra, github_denied)

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
    status, _, existing = client.call("GET", f"{endpoint}/api/v2/extendedAgent/skills", DATA_PLANE_SCOPE)
    for retired in (s.get("name") for s in items(existing)):
        if retired in RETIRED_SKILLS:
            status, _, _ = client.call("DELETE", f"{endpoint}/api/v2/extendedAgent/skills/{retired}", DATA_PLANE_SCOPE)
            print(f"  {'ok' if status < 300 else 'FAILED'}  removed the retired skill {retired}")
            if status >= 300:
                failures.append(f"remove skills/{retired}")

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
            wanted, got_tools = bodies["customAgent"]["properties"], props.get("tools", [])
            github_tools = [t for t in got_tools if "github" in t.lower() or matches(t, deny_patterns)]
            ok = (set(wanted["tools"]) <= set(got_tools) and set(agent["skills"]) <= set(props.get("allowedSkills", []))
                  and not github_tools and not set(RETIRED_SKILLS) & set(props.get("allowedSkills", [])))
            if github_tools:
                print(f"  the custom agent still has GitHub tools: {', '.join(github_tools)}")
        if ok and label.startswith("hooks/"):
            got, wanted = props.get("hook") or {}, hook["properties"]["hook"]
            ok = (props.get("eventType") == "PreToolUse" and props.get("enabled") is not False
                  and all(got.get(k) == wanted[k] for k in ("type", "matcher", "failMode")))
        if ok and label.startswith("incidentFilters/"):
            ok = props.get("handlingAgent") == agent["name"] and props.get("agentMode") == plan["agentMode"]
        if ok and label == "tool policy":
            # Exact comparison: every entry sent, by name and case, must be in the service's policy.
            got = (body or {}).get("permissions") or {}
            missing = [f"{k} {e}" for k in ("allow", "ask", "deny") for e in permissions[k] if e not in (got.get(k) or [])]
            ok = not missing
            if missing:
                print(f"  missing from the tool policy: {', '.join(missing)}")
        print(f"  {'ok' if ok else 'FAILED'}  {label}")
        if not ok:
            failures.append(f"read back {label}")

    if failures:
        print(f"\n{len(failures)} item(s) failed: {', '.join(failures)}")
        return 1
    print(f"\nSRE Agent configured. Response plan '{plan['name']}' sends {', '.join(plan['severities'])} alerts whose "
          f"title contains '{plan['titleContains']}' to '{agent['name']}' in {plan['agentMode']} mode. It drafts the "
          f"incident record in its reply for a person to file in {extra['GITHUB_REPOSITORY']}; every GitHub write tool "
          "is denied.")
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
              f"{config.plan['agentMode']} mode, no GitHub tool for the agent and every GitHub write tool denied "
              f"(Issue writes included), Azure writes need approval, deletes denied, guard hook "
              f"'{config.github['guardHook']['name']}' as a backstop.")
        return 0
    return apply(config, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())