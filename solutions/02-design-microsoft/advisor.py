#!/usr/bin/env python3
"""Ask the Microsoft Foundry architecture advisor a design question (Design phase, Microsoft track).

What this script does, step by step:
  1. Reads the agent definition in agent.yaml and publishes one Foundry prompt agent per operating profile
     (architecture-advisor-small-team, architecture-advisor-enterprise). Each agent's Azure AI Search tool carries a
     fixed filter on the standards' `scope` field, so the search service decides which standards a team can retrieve;
     the prompt is not the access control. A new agent version is created only when the definition changes (its hash
     is kept in the version's metadata).
  2. Sends the question through the Responses API. The agent searches the `architecture-standards` index and answers in
     a strict JSON schema: options, constraints (standard id, version, and a word-for-word excerpt), conflicts between
     standards, unknowns, or an explicit abstention when the standards do not answer the question.
  3. Applies deterministic checks against the index: every cited standard exists, is inside the profile's scope, and
     has the indexed version; every excerpt appears word for word in the cited standard; an abstention carries no
     recommendation; an answer cites at least one standard. The model cannot talk its way past them.
  4. Writes, under --out: run.json (response id, agent version, search calls, tokens, timing, checks), summary.md
     (a short Markdown answer for an issue comment), and adr-draft.md, an architecture decision record with status
     "Proposed" for an architect to accept or reject.

Configuration (environment variables, or read automatically from `azd env get-values` in this folder):
  FOUNDRY_PROJECT_ENDPOINT   https://<account>.services.ai.azure.com/api/projects/<project>
  FOUNDRY_MODEL_DEPLOYMENT   model deployment name, for example gpt-4.1-mini
  SEARCH_ENDPOINT            https://<search-service>.search.windows.net
  SEARCH_CONNECTION_NAME     the Foundry project connection to the search service (default standards-search)
Your identity needs Foundry User on the Foundry account and Search Index Data Reader (or Contributor) on the search
service. infra/resources.bicep grants them to whoever runs azd and to the GitHub Actions identity.

Usage
  python solutions/02-design-microsoft/advisor.py --profile small-team --question "Should the triage provider run in-process?"
  python solutions/02-design-microsoft/advisor.py --profile enterprise --question-file question.md --adr-file adr/triage.md
  ADVISOR_QUESTION="..." python solutions/02-design-microsoft/advisor.py --profile enterprise

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

from openai import RateLimitError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import credential, setting, utf8_stdout  # noqa: E402
from ingest_standards import INDEX, SPEC, scope_filter  # noqa: E402

PROFILES = tuple(SPEC["profiles"])
STANDARD_ID = re.compile(r"STD-[A-Z]+-\d{3}")
SEARCH_MARKER = re.compile(r"\s*【[^】]*】")
RATE_LIMIT_RETRIES = 3


def normalize(text: str) -> str:
    """Lowercase words only, so an excerpt matches the standard regardless of punctuation, quotes, or line breaks."""
    return " ".join(re.findall(r"[a-z0-9%]+", text.lower()))


def bare_version(text: str) -> str:
    """Versions compare without a leading v, so v2.0 and 2.0 are the same."""
    return text.strip().lstrip("vV")


def excerpt_found(excerpt: str, source: str) -> bool:
    """True when every part of the excerpt (split on an ellipsis) appears word for word in the source."""
    parts = [normalize(part) for part in re.split(r"\.\.\.|…", excerpt)]
    parts = [part for part in parts if part]
    return bool(parts) and all(part in normalize(source) for part in parts)


def strip_markers(node):
    """Remove the search tool's inline citation markers, such as 【5:0†source】, from every text in the answer.
    The structured fields already carry the citations."""
    if isinstance(node, str):
        return SEARCH_MARKER.sub("", node)
    if isinstance(node, list):
        return [strip_markers(value) for value in node]
    if isinstance(node, dict):
        return {key: strip_markers(value) for key, value in node.items()}
    return node


class Advisor:
    """Holds the clients and the published agents, so the evaluation can reuse them across questions."""

    def __init__(self) -> None:
        from azure.ai.projects import AIProjectClient
        from azure.search.documents import SearchClient

        signed_in = credential()
        self.project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=signed_in)
        self.openai = self.project.get_openai_client()
        self.model = setting("FOUNDRY_MODEL_DEPLOYMENT")
        self.connection_id = self.project.connections.get(setting("SEARCH_CONNECTION_NAME", "standards-search")).id
        self.search = SearchClient(setting("SEARCH_ENDPOINT"), INDEX, signed_in)
        self.agents: dict[str, object] = {}
        self._standards: dict[str | None, dict[str, dict]] = {}

    def standards(self, profile: str | None = None) -> dict[str, dict]:
        """id -> {version, text} of the standards a profile may retrieve (all standards when profile is None),
        as reported by the search service itself."""
        if profile not in self._standards:
            results = self.search.search(search_text="*", select=["id", "version", "title", "content"], top=1000,
                                         filter=scope_filter(profile) if profile else None)
            self._standards[profile] = {d["id"]: {"version": d["version"], "text": f"{d['title']}\n{d['content']}"}
                                        for d in results}
        return self._standards[profile]

    def definition(self, profile: str):
        from azure.ai.projects.models import (
            AISearchIndexResource,
            AzureAISearchTool,
            AzureAISearchToolResource,
            PromptAgentDefinition,
            PromptAgentDefinitionTextOptions,
            Reasoning,
            TextResponseFormatJsonSchema,
        )

        # Reasoning models (gpt-5 family) take a reasoning effort and reject temperature; other models take temperature.
        sampling = {}
        if SPEC.get("temperature") is not None:
            sampling["temperature"] = SPEC["temperature"]
        if SPEC.get("reasoning_effort"):
            sampling["reasoning"] = Reasoning(effort=SPEC["reasoning_effort"])
        return PromptAgentDefinition(
            model=self.model,
            instructions=SPEC["instructions"],
            tools=[AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(indexes=[AISearchIndexResource(
                project_connection_id=self.connection_id, index_name=INDEX, query_type=SPEC["search"]["query_type"],
                filter=scope_filter(profile), top_k=SPEC["search"]["top_k"])]))],
            text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
                name="architecture_recommendation", schema=SPEC["output_schema"], strict=True)),
            **sampling,
        )

    def agent(self, profile: str):
        """The published agent version for a profile: reused while the definition is unchanged, otherwise created."""
        if profile in self.agents:
            return self.agents[profile]
        name = f"{SPEC['name']}-{profile}"
        definition = self.definition(profile)
        digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
        try:
            versions = list(self.project.agents.list_versions(agent_name=name))
        except Exception:  # first run: the agent does not exist yet
            versions = []
        agent = next((v for v in versions if (v.metadata or {}).get("definitionHash") == digest), None)
        reused = agent is not None
        if agent is None:
            agent = self.project.agents.create_version(
                agent_name=name, definition=definition, description=SPEC["description"].format(profile=profile),
                metadata={"definitionHash": digest, "profile": profile, "source": "solutions/02-design-microsoft/agent.yaml"})
        self.agents[profile] = agent
        print(f"agent {agent.name} v{agent.version} ({'reused' if reused else 'new version'}), model {self.model}, "
              f"search filter: {scope_filter(profile)}")
        return agent

    def ask(self, question: str, profile: str) -> dict:
        agent = self.agent(profile)
        limits = {"max_output_tokens": SPEC["max_output_tokens"]} if SPEC.get("max_output_tokens") else {}
        for attempt in range(1, RATE_LIMIT_RETRIES + 2):
            started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            started = time.monotonic()
            try:
                response = self.openai.responses.create(
                    input=question,
                    extra_body={"agent_reference": {"name": agent.name, "version": str(agent.version), "type": "agent_reference"}},
                    **limits)
                break
            except RateLimitError:
                # Throttled (HTTP 429) for the rest of the minute: wait longer than the client's own short retries.
                if attempt > RATE_LIMIT_RETRIES:
                    raise
                time.sleep(20 * attempt)
        duration = round(time.monotonic() - started, 1)
        if response.status != "completed":
            raise RuntimeError(f"response {response.id} ended with status {response.status}: {response.error or response.incomplete_details}")
        data = strip_markers(json.loads(response.output_text))
        searches = [item for item in response.output if getattr(item, "type", "") == "azure_ai_search_call"]
        retrieved = sorted({doc_id for item in response.output if getattr(item, "type", "") == "azure_ai_search_call_output"
                            for doc_id in retrieved_ids(item)})
        return {
            "question": question,
            "profile": profile,
            "startedAt": started_at,
            "durationSeconds": duration,
            "responseId": response.id,
            "agent": {"name": agent.name, "version": str(agent.version)},
            "model": self.model,
            "searchCalls": len(searches),
            "searchQueries": [query for item in searches for query in search_queries(item)],
            "retrievedStandards": retrieved,
            "usage": {"inputTokens": getattr(response.usage, "input_tokens", None),
                      "outputTokens": getattr(response.usage, "output_tokens", None)},
            "result": data,
            "checks": self.check(data, profile, question, retrieved),
        }

    def check(self, data: dict, profile: str, question: str, retrieved: list[str]) -> list[str]:
        """Deterministic gates. The index, not the model, decides whether a citation is real and allowed."""
        everything, permitted = self.standards(), self.standards(profile)
        problems: list[str] = []
        flagged: set[str] = set()

        # Negative access test on every call: the search service must never return a standard outside the profile.
        for standard in retrieved:
            if standard not in permitted:
                problems.append(f"access: the search returned {standard}, which is outside the '{profile}' scope")

        def verify(standard: str, where: str) -> bool:
            if standard not in everything:
                problems.append(f"citation: {standard} in {where} does not exist in the standards index (invented)")
            elif standard not in permitted:
                problems.append(f"access: {standard} in {where} is outside the '{profile}' scope and must not be used")
            else:
                return True
            flagged.add(standard)
            return False

        for constraint in data["constraints"]:
            ids = STANDARD_ID.findall(constraint["standardId"])
            if len(ids) != 1:
                problems.append(f"citation: '{constraint['standardId']}' is not exactly one standard id")
                continue
            standard = ids[0]
            if not verify(standard, "constraints"):
                continue
            cited, indexed = bare_version(constraint["version"]), everything[standard]["version"]
            if cited != indexed:
                problems.append(f"version: {standard} cited as v{cited}, the index has v{indexed}")
            if not excerpt_found(constraint["excerpt"], everything[standard]["text"]):
                problems.append(f"excerpt: the quote attributed to {standard} is not in the standard: \"{constraint['excerpt'][:80]}\"")
        for option in data["options"]:
            for standard in sorted(set(STANDARD_ID.findall(" ".join(option["standards"])))):
                verify(standard, f"option '{option['name'][:40]}'")
        for conflict in data["conflicts"]:
            for standard in sorted(set(STANDARD_ID.findall(" ".join(conflict["standards"])))):
                verify(standard, "conflicts")
        # Anywhere else in the answer, an id is only allowed if it is real and in scope (or the question named it).
        for standard in sorted(set(STANDARD_ID.findall(json.dumps(data))) - flagged - set(STANDARD_ID.findall(question))):
            verify(standard, "the answer text")

        if not data["answerable"] and data["recommendation"]:
            problems.append("abstention: answerable is false but a recommendation was given")
        if not data["answerable"] and not data["unknowns"]:
            problems.append("abstention: answerable is false but unknowns is empty")
        if data["answerable"] and not data["constraints"]:
            problems.append("grounding: an answer must cite at least one standard")
        return problems


def search_queries(item) -> list[str]:
    """The query text of an azure_ai_search_call output item, when the service reports it."""
    raw = getattr(item, "arguments", None)
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return [raw]
    query = arguments.get("query") if isinstance(arguments, dict) else None
    return [query] if query else []


def retrieved_ids(item) -> list[str]:
    """Standard ids in an azure_ai_search_call_output item: the documents the search service returned to the agent."""
    try:
        documents = json.loads(getattr(item, "output", None) or "{}").get("documents", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [doc["id"] for doc in documents if isinstance(doc, dict) and STANDARD_ID.fullmatch(str(doc.get("id", "")))]


def cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def checks_line(run: dict) -> str:
    if not run["checks"]:
        return (f"✅ Deterministic checks passed: every citation exists in the index, is inside the {run['profile']} scope, "
                "matches the indexed version, and quotes the standard word for word.")
    return "❌ Deterministic checks failed:\n" + "\n".join(f"- {problem}" for problem in run["checks"])


def evidence_line(run: dict) -> str:
    return (f"Agent `{run['agent']['name']}` v{run['agent']['version']} · model `{run['model']}` · response "
            f"`{run['responseId']}` · {run['searchCalls']} search call(s) · {run['durationSeconds']} s")


def summary_markdown(run: dict) -> str:
    """Short answer for an issue comment or a workflow summary."""
    data = run["result"]
    lines = [f"### Foundry architecture advisor · {run['profile']} profile", ""]
    if data["answerable"]:
        lines += [f"**Recommendation:** {data['recommendation'] or '_none_'}", ""]
    else:
        lines += ["**Abstained:** the approved standards do not answer this question.", ""]
    lines += [data["summary"], ""]
    if data["constraints"]:
        if not data["answerable"]:
            lines += ["Related standards it found, none of which answers the question:", ""]
        lines += ["| Standard | Version | Requirement |", "| --- | --- | --- |"]
        lines += [f"| {cell(c['standardId'])} | {cell(bare_version(c['version']))} | {cell(c['requirement'])} |" for c in data["constraints"]]
        lines += [""]
    if data["conflicts"]:
        lines += ["**Conflicts needing a decision:**", ""]
        lines += [f"- {', '.join(c['standards'])}: {c['description']}" for c in data["conflicts"]] + [""]
    if data["unknowns"]:
        lines += ["**Unknowns:**", ""] + [f"- {u}" for u in data["unknowns"]] + [""]
    lines += [checks_line(run), "", f"<sub>{evidence_line(run)}. Advisory only: an architect accepts or rejects the "
                                    "ADR draft.</sub>", ""]
    return "\n".join(lines)


def adr_draft(run: dict) -> str:
    """Architecture decision record with status Proposed, for an architect to accept or reject."""
    data = run["result"]
    first_line = run["question"].strip().splitlines()[0]
    title = first_line if len(first_line) <= 90 else first_line[:90].rsplit(" ", 1)[0] + "…"
    scopes = ", ".join(SPEC["profiles"][run["profile"]])
    lines = [
        f"# ADR draft: {title}",
        "",
        "| | |",
        "| --- | --- |",
        "| Status | **Proposed**. An architect accepts or rejects it in review. |",
        f"| Drafted by | Microsoft Foundry agent `{run['agent']['name']}` v{run['agent']['version']}, model `{run['model']}` |",
        f"| Evidence | Response `{run['responseId']}`, {run['searchCalls']} search call(s) that retrieved "
        f"{', '.join(run['retrievedStandards']) or 'nothing'}, {run['startedAt']} |",
        f"| Operating profile | {run['profile']}: standards with scope {scopes} in the `{INDEX}` index |",
        f"| Deterministic checks | {'Passed' if not run['checks'] else 'Failed: ' + cell('; '.join(run['checks']))} |",
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
    lines += ["## Recommendation", "",
              data["recommendation"] or "_No recommendation: the approved standards do not answer this question._", ""]
    lines += ["## Constraints from approved standards", "",
              "| Standard | Version | Requirement | Source excerpt |", "| --- | --- | --- | --- |"]
    lines += [f"| {cell(c['standardId'])} | {cell(bare_version(c['version']))} | {cell(c['requirement'])} | \"{cell(c['excerpt'])}\" |"
              for c in data["constraints"]] or ["| none | | | |"]
    lines += ["", "## Conflicts needing a decision", ""]
    lines += [f"- {', '.join(c['standards'])}: {c['description']}" for c in data["conflicts"]] or ["- None found."]
    lines += ["", "## Unknowns", ""] + ([f"- {u}" for u in data["unknowns"]] or ["- None."])
    lines += ["", "## Review", "",
              "- [ ] Citations, versions, and excerpts checked against the standards",
              "- [ ] Each conflict and unknown has an owner",
              "- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Settings come from the environment or from this folder's azd environment; see the module docstring.")
    parser.add_argument("--profile", choices=PROFILES, default="enterprise",
                        help="Operating profile; decides which standards the agent can retrieve (default enterprise)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--question", help="The architecture question")
    source.add_argument("--question-file", type=Path, help="File that contains the question, for example an issue body")
    parser.add_argument("--out", type=Path, default=HERE / "out",
                        help="Folder for run.json, summary.md, and adr-draft.md (default out/ next to this script)")
    parser.add_argument("--adr-file", type=Path, help="Also write the ADR draft to this path, for example adr/issue-12.md")
    args = parser.parse_args(argv)
    utf8_stdout()

    question = args.question or (args.question_file.read_text(encoding="utf-8") if args.question_file else os.environ.get("ADVISOR_QUESTION"))
    if not question or not question.strip():
        parser.error("provide --question, --question-file, or the ADVISOR_QUESTION environment variable")
    try:
        run = Advisor().ask(question.strip(), args.profile)
    except Exception as exc:  # surface service and auth errors clearly; there is no offline fallback
        print(f"error: advisor call failed: {exc}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "summary.md").write_text(summary_markdown(run), encoding="utf-8")
    draft = adr_draft(run)
    (args.out / "adr-draft.md").write_text(draft, encoding="utf-8")
    if args.adr_file:
        args.adr_file.parent.mkdir(parents=True, exist_ok=True)
        args.adr_file.write_text(draft, encoding="utf-8")

    data = run["result"]
    print(f"response {run['responseId']} in {run['durationSeconds']} s · {run['searchCalls']} search call(s) · "
          f"retrieved {len(run['retrievedStandards'])}: {', '.join(run['retrievedStandards']) or 'nothing'}")
    for query in run["searchQueries"]:
        print(f"  searched: {query}")
    cited = dict.fromkeys(f"{c['standardId']} v{bare_version(c['version'])}" for c in data["constraints"])
    print(f"answerable: {data['answerable']} · cites: {', '.join(cited) or 'none'} · "
          f"conflicts: {len(data['conflicts'])} · unknowns: {len(data['unknowns'])}")
    print(f"recommendation: {data['recommendation'] or '(abstained)'}")
    print("checks: " + ("PASS" if not run["checks"] else "FAIL"))
    for problem in run["checks"]:
        print(f"  - {problem}")
    written = [args.out / name for name in ("run.json", "summary.md", "adr-draft.md")] + ([args.adr_file] if args.adr_file else [])
    print("wrote " + ", ".join(str(path) for path in written))
    return 0 if not run["checks"] else 1


if __name__ == "__main__":
    sys.exit(main())
