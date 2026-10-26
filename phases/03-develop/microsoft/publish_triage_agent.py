#!/usr/bin/env python3
"""Publish the RequestHub triage agent to Microsoft Foundry (Develop phase, Microsoft track).

What this script does:
  1. Reads triage-agent.yaml: instructions, two function tools (get_request, get_routing_policies), and a strict JSON output schema.
  2. Creates a new agent version in your Foundry project only when the definition changed (a hash is stored in version metadata),
     so re-running is safe and versions stay meaningful.
  3. Prints the agent name and version. The RequestHub API calls the agent by name (setting Foundry:AgentName) and executes the
     tools itself, with the caller's permissions and an audit entry per call. The agent has no tool that can approve anything.

Configuration: FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_DEPLOYMENT (environment or `azd env get-values`); identity with the
Azure AI User role on the Foundry account.

Usage
  python phases/03-develop/microsoft/publish_triage_agent.py
  python phases/03-develop/microsoft/publish_triage_agent.py --show     # print the definition without publishing

Exit codes: 0 published or unchanged, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FunctionTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "common"))
from azd_env import setting, utf8_stdout  # noqa: E402


def build_definition(spec: dict, model: str) -> PromptAgentDefinition:
    tools = [FunctionTool(name=t["name"], description=t["description"], parameters=t["parameters"], strict=True) for t in spec["tools"]]
    return PromptAgentDefinition(
        model=model,
        instructions=spec["instructions"],
        temperature=spec.get("temperature", 0.1),
        tools=tools,
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name="triage_recommendation", schema=spec["output_schema"], strict=True)),
    )


def publish(spec: dict, model: str) -> tuple[object, bool]:
    project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    definition = build_definition(spec, model)
    digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    try:
        versions = list(project.agents.list_versions(agent_name=spec["name"]))
    except Exception:
        versions = []
    # The API uses the latest version, so only the latest one counts as "unchanged" (a revert publishes a new version).
    latest = max(versions, key=lambda v: int(v.version), default=None)
    if latest is not None and (latest.metadata or {}).get("definitionHash") == digest:
        return latest, False
    created = project.agents.create_version(
        agent_name=spec["name"], definition=definition, description=spec["description"],
        metadata={"definitionHash": digest, "source": "phases/03-develop/microsoft/triage-agent.yaml"})
    return created, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="Print the agent definition and exit")
    args = parser.parse_args(argv)
    utf8_stdout()
    spec = yaml.safe_load((HERE / "triage-agent.yaml").read_text(encoding="utf-8"))
    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    if args.show:
        print(json.dumps(build_definition(spec, model).as_dict(), indent=2))
        return 0
    try:
        agent, created = publish(spec, model)
    except Exception as exc:
        print(f"error: publishing failed: {exc}", file=sys.stderr)
        return 2
    print(f"{'published new version' if created else 'unchanged'}: {agent.name} v{agent.version} (model {model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
