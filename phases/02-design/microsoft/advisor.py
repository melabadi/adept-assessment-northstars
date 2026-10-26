#!/usr/bin/env python3
"""Microsoft Foundry architecture advisor grounded in Azure AI Search (Design phase, Microsoft track).

What this script does:
  1. Publishes a Foundry prompt agent per operating profile (architecture-advisor-small-team / -enterprise). Each agent's
     Azure AI Search tool carries a fixed filter (scope eq 'all' or scope eq '<profile>'), so the search service itself
     decides which standards a team can retrieve; the prompt is not the access control.
  2. Sends the architecture question. The agent searches the `architecture-standards` index and answers with a structured
     recommendation: options, constraints (standard id + version), conflicts, unknowns, or an explicit abstention.
  3. Applies deterministic checks: every cited standard must exist in the index, be inside the profile's scope, and match
     the indexed version; an abstention must not carry a recommendation.
  4. Writes run.json (response id, agent version, search tool calls, checks) and an ADR draft with Status "Proposed"
     for a human architect to accept or reject.

Configuration (environment or `azd env get-values`): FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT, SEARCH_ENDPOINT,
SEARCH_CONNECTION_NAME. Identity roles: Azure AI User (Foundry) and Search Index Data Reader or Contributor (search).

Usage
  python phases/02-design/microsoft/advisor.py --profile small-team --question "Should the live triage provider run in-process?"
  python phases/02-design/microsoft/advisor.py --profile enterprise --question-file question.md --out out/design-advisor
  ADVISOR_QUESTION="..." python phases/02-design/microsoft/advisor.py --profile enterprise   # used by the GitHub workflow

Exit codes: 0 checks passed, 1 a deterministic check failed, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "common"))
from azd_env import REPO, setting, utf8_stdout  # noqa: E402

INDEX = "architecture-standards"
PROFILES = ("small-team", "enterprise")
STANDARD_ID = re.compile(r"STD-[A-Z]+-\d{3}")

INSTRUCTIONS = """You are the architecture advisor for RequestHub, an internal request-and-approval app.
RequestHub today: ASP.NET Core API and React UI on Azure Container Apps, PostgreSQL, a notification worker, and a triage
extension point (ITriageProvider) that currently uses deterministic sample rules. A Microsoft Foundry project is available.

Answer only from the approved architecture standards returned by the azure_ai_search tool. Always search before answering,
and search several times with different words (architecture approach, new components, security, data handling,
observability, operations, AI) so you see every relevant standard before you recommend anything.
- Cite every constraint with the standard id and version exactly as shown in the result title, e.g. "STD-SEC-001" and "2.0".
- Before answering, go through every standard the search returned and add each one that applies to the question as a
  constraint, including general standards (observability, security, operations) that constrain the design indirectly.
- When the question asks how to design something, compare at least two concrete options and recommend one that satisfies the
  cited standards. Prefer the option the standards favour; say which standard tips the balance.
- Check every pair of retrieved standards for contradictions (for example one requires keeping data that another forbids
  storing). List each contradiction under conflicts, do not pick a winner, and do not present a contradicted rule as settled.
- If the standards do not answer the question, set answerable to false, recommendation to null, and explain what is missing
  in unknowns. Never invent policies, numbers, budgets, or standards.
- Your output is advisory. An architect reviews and decides."""

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answerable", "summary", "recommendation", "options", "constraints", "conflicts", "unknowns"],
    "properties": {
        "answerable": {"type": "boolean"},
        "summary": {"type": "string"},
        "recommendation": {"type": ["string", "null"]},
        "options": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "description", "pros", "cons", "standards"],
            "properties": {
                "name": {"type": "string"}, "description": {"type": "string"},
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}},
                "standards": {"type": "array", "items": {"type": "string"}},
            }}},
        "constraints": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["standardId", "version", "requirement"],
            "properties": {
                "standardId": {"type": "string", "description": "Standard id only, for example STD-SEC-001 (no version, no title)."},
                "version": {"type": "string", "description": "Version exactly as indexed, for example 2.0."},
                "requirement": {"type": "string"}}}},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["standards", "description"],
            "properties": {"standards": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string"}}}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
}


def scope_filter(profile: str) -> str:
    return f"scope eq 'all' or scope eq '{profile}'"


class Advisor:
    """Holds clients and published agents so evaluation can reuse them across questions."""

    def __init__(self) -> None:
        self.project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
        self.openai = self.project.get_openai_client()
        self.model = setting("FOUNDRY_MODEL_DEPLOYMENT")
        self.connection_id = self.project.connections.get(setting("SEARCH_CONNECTION_NAME", "standards-search")).id
        self.search = SearchClient(setting("SEARCH_ENDPOINT"), INDEX, DefaultAzureCredential())
        self.agents: dict[str, object] = {}

    def standards(self, profile: str | None = None) -> dict[str, str]:
        """id -> version of the standards visible to a profile (or all standards)."""
        results = self.search.search(search_text="*", select=["id", "version"], top=1000,
                                     filter=scope_filter(profile) if profile else None)
        return {doc["id"]: doc["version"] for doc in results}

    def agent(self, profile: str):
        if profile in self.agents:
            return self.agents[profile]
        name = f"architecture-advisor-{profile}"
        definition = PromptAgentDefinition(
            model=self.model,
            instructions=INSTRUCTIONS,
            temperature=0.1,
            tools=[AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(indexes=[AISearchIndexResource(
                project_connection_id=self.connection_id, index_name=INDEX, query_type=AzureAISearchQueryType.SEMANTIC,
                filter=scope_filter(profile), top_k=10)]))],
            text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
                name="architecture_recommendation", schema=OUTPUT_SCHEMA, strict=True)),
        )
        digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
        try:
            versions = list(self.project.agents.list_versions(agent_name=name))
        except Exception:
            versions = []
        agent = next((v for v in versions if (v.metadata or {}).get("definitionHash") == digest), None)
        if agent is None:
            agent = self.project.agents.create_version(
                agent_name=name, definition=definition,
                description=f"Architecture advisor grounded in approved standards ({profile} profile).",
                metadata={"definitionHash": digest, "profile": profile, "source": "phases/02-design/microsoft/advisor.py"})
        self.agents[profile] = agent
        return agent

    def ask(self, question: str, profile: str) -> dict:
        agent = self.agent(profile)
        started = time.monotonic()
        response = self.openai.responses.create(
            input=question,
            extra_body={"agent_reference": {"name": agent.name, "version": str(agent.version), "type": "agent_reference"}})
        data = json.loads(response.output_text)
        tool_calls = [getattr(item, "type", "") for item in response.output if getattr(item, "type", "") not in ("message", "reasoning")]
        checks = self.check(data, profile)
        return {
            "question": question,
            "profile": profile,
            "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "durationSeconds": round(time.monotonic() - started, 1),
            "responseId": response.id,
            "agent": {"name": agent.name, "version": str(agent.version)},
            "model": self.model,
            "toolCalls": tool_calls,
            "result": data,
            "checks": checks,
        }

    def check(self, data: dict, profile: str) -> list[str]:
        """Deterministic gates. A model cannot talk its way past these."""
        everything, permitted = self.standards(), self.standards(profile)
        problems = []
        cited: dict[str, str] = {}
        for constraint in data["constraints"]:
            match = STANDARD_ID.search(constraint["standardId"])
            if match:
                cited[match.group(0)] = constraint["version"].lstrip("vV")
            else:
                problems.append(f"citation: '{constraint['standardId']}' is not a standard id")
        cited_ids = set(cited) | {s for o in data["options"] for s in STANDARD_ID.findall(" ".join(o["standards"]))}
        cited_ids |= {s for c in data["conflicts"] for s in STANDARD_ID.findall(" ".join(c["standards"]))}
        cited_ids |= set(STANDARD_ID.findall(json.dumps(data)))
        for standard in sorted(cited_ids):
            if standard not in everything:
                problems.append(f"citation: {standard} does not exist in the standards index (invented)")
            elif standard not in permitted:
                problems.append(f"access: {standard} is outside the '{profile}' scope and must not be used")
        for standard, version in cited.items():
            if standard in everything and everything[standard] != version:
                problems.append(f"version: {standard} cited as v{version}, index has v{everything[standard]}")
        if not data["answerable"] and data["recommendation"]:
            problems.append("abstention: answerable is false but a recommendation was given")
        if not data["answerable"] and not data["unknowns"]:
            problems.append("abstention: answerable is false but unknowns is empty")
        if data["answerable"] and not data["constraints"]:
            problems.append("grounding: an answer must cite at least one standard")
        return problems


def adr_draft(run: dict) -> str:
    data = run["result"]
    title = run["question"].strip().splitlines()[0][:90]
    lines = [
        f"# ADR draft: {title}",
        "",
        f"- **Status:** Proposed — advisory draft from Microsoft Foundry agent `{run['agent']['name']}` v{run['agent']['version']} "
        f"(response `{run['responseId']}`). An architect must accept or reject it.",
        f"- **Operating profile:** {run['profile']} · **Standards index:** `{INDEX}`",
        "",
        "## Context", "", run["question"].strip(), "",
        "## Summary", "", data["summary"], "",
    ]
    if data["options"]:
        lines += ["## Options considered", ""]
        for option in data["options"]:
            lines += [f"### {option['name']}", "", option["description"], ""]
            lines += [f"- ✅ {p}" for p in option["pros"]] + [f"- ⚠️ {c}" for c in option["cons"]]
            lines += [f"- Standards: {', '.join(option['standards']) or 'none'}", ""]
    lines += ["## Recommendation", "", data["recommendation"] or "_No recommendation: the approved standards do not answer this question._", ""]
    lines += ["## Constraints from approved standards", "", "| Standard | Version | Requirement |", "| --- | --- | --- |"]
    lines += [f"| {c['standardId']} | {c['version']} | {c['requirement']} |" for c in data["constraints"]] or ["| — | — | none cited |"]
    lines += ["", "## Conflicts needing a decision", ""]
    lines += [f"- {', '.join(c['standards'])}: {c['description']}" for c in data["conflicts"]] or ["- None found."]
    lines += ["", "## Unknowns", ""] + ([f"- {u}" for u in data["unknowns"]] or ["- None."])
    lines += ["", "## Review", "", "- [ ] Citations checked against the standards", "- [ ] Decision: Accept / Reject (architect)", ""]
    return "\n".join(lines)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "question"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=PROFILES, default="enterprise", help="Operating profile; controls which standards can be retrieved")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--question", help="Architecture question")
    source.add_argument("--question-file", type=Path, help="File containing the question (e.g. an issue body)")
    parser.add_argument("--out", type=Path, default=REPO / "phases/02-design/output/microsoft", help="Output folder")
    parser.add_argument("--adr-dir", type=Path, help="Also write the ADR draft here (e.g. docs/adr/drafts)")
    args = parser.parse_args(argv)
    utf8_stdout()

    question = args.question or (args.question_file.read_text(encoding="utf-8") if args.question_file else os.environ.get("ADVISOR_QUESTION"))
    if not question or not question.strip():
        parser.error("provide --question, --question-file, or ADVISOR_QUESTION")
    try:
        run = Advisor().ask(question, args.profile)
    except Exception as exc:
        print(f"error: advisor call failed: {exc}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    draft = adr_draft(run)
    (args.out / "adr-draft.md").write_text(draft, encoding="utf-8")
    if args.adr_dir:
        args.adr_dir.mkdir(parents=True, exist_ok=True)
        (args.adr_dir / f"{slug(question.splitlines()[0])}.md").write_text(draft, encoding="utf-8")

    data = run["result"]
    print(f"agent {run['agent']['name']} v{run['agent']['version']} · response {run['responseId']} · tools: {', '.join(run['toolCalls']) or 'none'}")
    print(f"answerable={data['answerable']} · constraints: {', '.join(c['standardId'] for c in data['constraints']) or 'none'} · "
          f"conflicts: {len(data['conflicts'])} · unknowns: {len(data['unknowns'])}")
    print("checks: " + ("PASS" if not run["checks"] else "FAIL"))
    for problem in run["checks"]:
        print(f"  - {problem}")
    print(f"wrote {args.out / 'run.json'} and {args.out / 'adr-draft.md'}")
    return 0 if not run["checks"] else 1


if __name__ == "__main__":
    sys.exit(main())
