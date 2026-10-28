#!/usr/bin/env python3
"""Microsoft Foundry requirements analyst (Plan phase, Microsoft track).

What this script does, step by step:
  1. Connects to your Foundry project with Microsoft Entra ID (az login, managed identity, or GitHub OIDC).
  2. Uploads the stakeholder transcript and routing policies to a Foundry vector store. The store name includes a
     hash of the files, so an unchanged input set is reused instead of re-uploaded.
  3. Publishes the prompt agent defined in agent.yaml (model + instructions + file_search tool + strict JSON schema).
     A new agent version is created only when the definition changes; the definition hash is kept in version metadata.
  4. Calls the agent through the Responses API and receives the requirements package as schema-enforced JSON.
  5. Validates the package with the same deterministic validator as the GitHub track
     (.github/skills/requirements-traceability/validate_backlog.py) and renders brief.md.
  6. Writes evidence of the live call to run.json: response id, agent name/version, model, vector store, file-search
     calls, duration, and validation result.

Outputs (default folder brief/ next to this script): backlog.json, brief.md, run.json.

Configuration (environment variables, or read automatically from `azd env get-values` when azd is installed):
  FOUNDRY_PROJECT_ENDPOINT   https://<account>.services.ai.azure.com/api/projects/<project>
  FOUNDRY_MODEL_DEPLOYMENT   model deployment name, e.g. gpt-4.1
Your identity needs the "Foundry User" role (formerly Azure AI User) on the Foundry account (infra/resources.bicep grants it to whoever runs azd).

Usage
  python solutions/01-plan-microsoft/requirements_analyst.py
  python solutions/01-plan-microsoft/requirements_analyst.py --out solutions/01-plan-microsoft/out/run1

Exit codes: 0 valid package, 1 package produced but failed validation, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FileSearchTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    Reasoning,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent
SKILL = HERE / ".github/skills/requirements-traceability"
sys.path.insert(0, str(SKILL))
import render_brief  # noqa: E402
import validate_backlog  # noqa: E402

INPUTS = [HERE / "inputs/stakeholder-transcript.md", HERE / "inputs/routing-policies.md"]
UNSUPPORTED_STRICT_KEYS = {"$schema", "title", "pattern", "minItems", "maxItems", "format", "minLength", "maxLength"}


def azd_env() -> dict[str, str]:
    """Read values from the active azd environment, if azd is available."""
    if not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=HERE)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def setting(name: str, cache: dict[str, str]) -> str:
    value = os.environ.get(name) or cache.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set. Run `azd up` in solutions/01-plan-microsoft first, or export {name}.")
    return value


def last_json_document(text: str) -> dict:
    """The agent's answer as JSON. When a response holds more than one complete answer back to back (the model
    restated its package), the last one wins; the validator checks it either way."""
    decoder = json.JSONDecoder()
    position, document = 0, None
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        document, position = decoder.raw_decode(text, position)
    if not isinstance(document, dict):
        raise json.JSONDecodeError("no JSON object in the response", text, 0)
    return document


def strict_schema(node, in_properties: bool = False):
    """Structured outputs accept a subset of JSON Schema; the deterministic validator enforces the rest afterwards.
    Keys inside "properties" are property names, not keywords, so they are never removed."""
    if isinstance(node, dict):
        return {k: strict_schema(v, k == "properties") for k, v in node.items()
                if in_properties or k not in UNSUPPORTED_STRICT_KEYS}
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    return node


def ensure_vector_store(client, config: dict) -> tuple[str, bool]:
    # Line endings are normalized so Windows and Linux checkouts share one vector store (and one agent version).
    digest = hashlib.sha256(b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in INPUTS)).hexdigest()[:12]
    name = f"plan-inputs-{digest}"
    for store in client.vector_stores.list(limit=100):
        if store.name == name and store.status == "completed" and store.file_counts.completed == len(INPUTS):
            return store.id, True
    store = client.vector_stores.create(name=name, metadata={"purpose": "ai-sdlc-plan-demo"})
    chunking = {"type": "static", "static": {"max_chunk_size_tokens": config["chunk_size_tokens"],
                                              "chunk_overlap_tokens": config["chunk_overlap_tokens"]}}
    for path in INPUTS:
        with path.open("rb") as handle:
            client.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=handle, chunking_strategy=chunking)
    return store.id, False


def ensure_agent(project: AIProjectClient, spec: dict, model: str, vector_store_id: str):
    schema = strict_schema(json.loads((SKILL / "backlog.schema.json").read_text(encoding="utf-8")))
    # Reasoning models (such as gpt-5.1) take a reasoning effort and reject temperature; other models take temperature.
    settings = {}
    if spec.get("temperature") is not None:
        settings["temperature"] = spec["temperature"]
    if spec.get("reasoning_effort"):
        settings["reasoning"] = Reasoning(effort=spec["reasoning_effort"])
    definition = PromptAgentDefinition(
        model=model,
        instructions=spec["instructions"],
        tools=[FileSearchTool(vector_store_ids=[vector_store_id], max_num_results=spec["file_search"]["max_num_results"])],
        text=PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(name="requirements_package", schema=schema, strict=True)),
        **settings,
    )
    definition_hash = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    try:
        versions = list(project.agents.list_versions(agent_name=spec["name"]))
    except Exception:  # first run: the agent does not exist yet
        versions = []
    for version in versions:
        if (version.metadata or {}).get("definitionHash") == definition_hash:
            return version, True
    created = project.agents.create_version(
        agent_name=spec["name"],
        definition=definition,
        description=spec["description"],
        metadata={"definitionHash": definition_hash, "source": "solutions/01-plan-microsoft/agent.yaml"},
    )
    return created, False


def shown(path: Path) -> str:
    """A path relative to the current folder when it is inside it: short, and without the user's profile folder."""
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=HERE / "brief", help="Output folder (default: brief/ next to this script)")
    parser.add_argument("--max-repairs", type=int, default=1,
                        help="How many times validator findings are sent back to the agent for correction (default 1, 0 disables)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cache = {} if os.environ.get("FOUNDRY_PROJECT_ENDPOINT") else azd_env()
    endpoint = setting("FOUNDRY_PROJECT_ENDPOINT", cache)
    model = setting("FOUNDRY_MODEL_DEPLOYMENT", cache)
    spec = yaml.safe_load((HERE / "agent.yaml").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        openai_client = project.get_openai_client()
        store_id, store_reused = ensure_vector_store(openai_client, spec["file_search"])
        agent, agent_reused = ensure_agent(project, spec, model, store_id)
    except Exception as exc:  # surface service/auth errors clearly; there is no offline fallback
        print(f"error: Foundry setup failed: {exc}", file=sys.stderr)
        return 2
    print(f"agent {agent.name} v{agent.version} ({'reused' if agent_reused else 'new version'}), "
          f"vector store {store_id} ({'reused' if store_reused else 'uploaded'})")

    file_search_calls = 0
    response_ids: list[str] = []
    agent_ref = {"agent_reference": {"name": agent.name, "version": str(agent.version), "type": "agent_reference"}}
    request_input = spec["prompt"]
    previous_id = None
    for attempt in range(1 + max(0, args.max_repairs)):
        try:
            extra = {"previous_response_id": previous_id} if previous_id else {}
            response = openai_client.responses.create(input=request_input, extra_body=agent_ref, **extra)
        except Exception as exc:
            print(f"error: Foundry call failed: {exc}", file=sys.stderr)
            return 2
        response_ids.append(response.id)
        file_search_calls += sum(1 for item in response.output if getattr(item, "type", "") == "file_search_call")
        try:
            data = last_json_document(response.output_text)
        except json.JSONDecodeError as exc:
            print(f"error: agent did not return JSON ({exc}); response id {response.id}", file=sys.stderr)
            return 2
        problems = validate_backlog.validate(data, validate_backlog.source_ids(*INPUTS))
        print(f"attempt {attempt + 1}: response {response.id}: {'VALID' if not problems else f'{len(problems)} problem(s)'}")
        if not problems or attempt == args.max_repairs:
            break
        for problem in problems:
            print(f"  - {problem}")
        print("  sending the validator's findings back to the agent for one repair turn")
        # Repair turn: the deterministic validator's findings go back to the agent; the validator still decides.
        request_input = ("A deterministic validator rejected your requirements package. Fix every problem below, keep everything "
                         "else unchanged, and return the complete corrected package.\n" + "\n".join(f"- {p}" for p in problems))
        previous_id = response.id

    backlog_path = args.out / "backlog.json"
    backlog_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not problems:
        (args.out / "brief.md").write_text(
            render_brief.render(data, "Requirements brief: assisted request triage",
                                f"Microsoft Foundry agent {agent.name} v{agent.version}") + "\n", encoding="utf-8")

    run = {
        "track": "microsoft",
        "product": "Microsoft Foundry Agent Service",
        "startedAt": started_at,
        "durationSeconds": round(time.monotonic() - started, 1),
        "responseId": response.id,
        "responseIds": response_ids,
        "repairTurns": len(response_ids) - 1,
        "agent": {"name": agent.name, "version": str(agent.version)},
        "model": model,
        "vectorStoreId": store_id,
        "fileSearchCalls": file_search_calls,
        "usage": {"inputTokens": getattr(response.usage, "input_tokens", None), "outputTokens": getattr(response.usage, "output_tokens", None)},
        "valid": not problems,
        "problems": problems,
    }
    (args.out / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    status = "VALID" if not problems else f"INVALID ({len(problems)} problem(s))"
    print(f"response {response.id}: {status}; {len(data.get('tasks', []))} tasks, "
          f"{len(data.get('openQuestions', []))} open questions, file_search calls: {file_search_calls}")
    for problem in problems:
        print(f"  - {problem}")
    print(f"wrote {shown(backlog_path)}" + ("" if problems else f", {shown(args.out / 'brief.md')}") + f", {shown(args.out / 'run.json')}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
