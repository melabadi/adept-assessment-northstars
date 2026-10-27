#!/usr/bin/env python3
"""Publish the RequestHub triage agent to Microsoft Foundry (Develop phase, Microsoft track).

What this script does:
  1. Reads triage-agent.yaml: instructions, two function tools (get_request, get_routing_policies), and a strict JSON output schema.
  2. Creates a new agent version in your Foundry project only when the definition changed (a hash is stored in version metadata),
     so re-running is safe and versions stay meaningful.
  3. Prints the agent name and version. The RequestHub API calls the agent by name (setting Foundry:AgentName) and executes the
     tools itself, with the caller's permissions and an audit entry per call. The agent has no tool that can approve anything.

Configuration: FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_DEPLOYMENT (environment variables, or this solution's azd
environment after `azd up`); identity with the Foundry User role (formerly Azure AI User) on the Foundry account.

Usage
  python solutions/03-develop-microsoft/publish_triage_agent.py
  python solutions/03-develop-microsoft/publish_triage_agent.py --show     # print the definition without publishing
  python solutions/03-develop-microsoft/publish_triage_agent.py --name requesthub-triage-pr-42
      # publish a candidate under another name, so an unmerged change never becomes the version the app uses
  python solutions/03-develop-microsoft/publish_triage_agent.py --name requesthub-triage-pr-42 --delete
      # remove that candidate afterwards

Exit codes: 0 published, unchanged, or deleted; 2 configuration or service error.
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
sys.path.insert(0, str(HERE))
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


def project_client() -> AIProjectClient:
    return AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())


def publish(spec: dict, model: str, name: str) -> tuple[object, bool]:
    project = project_client()
    definition = build_definition(spec, model)
    digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    try:
        versions = list(project.agents.list_versions(agent_name=name))
    except Exception:
        versions = []
    # The API uses the latest version, so only the latest one counts as "unchanged" (a revert publishes a new version).
    latest = max(versions, key=lambda v: int(v.version), default=None)
    if latest is not None and (latest.metadata or {}).get("definitionHash") == digest:
        return latest, False
    created = project.agents.create_version(
        agent_name=name, definition=definition, description=spec["description"],
        metadata={"definitionHash": digest, "source": "solutions/03-develop-microsoft/triage-agent.yaml"})
    return created, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="Print the agent definition and exit")
    parser.add_argument("--name", help="Agent name (default: the name in triage-agent.yaml, which the app calls)")
    parser.add_argument("--delete", action="store_true", help="Delete the named agent and all its versions instead of publishing")
    args = parser.parse_args(argv)
    utf8_stdout()
    spec = yaml.safe_load((HERE / "triage-agent.yaml").read_text(encoding="utf-8"))
    name = args.name or spec["name"]
    if args.delete:
        if name == spec["name"]:
            parser.error(f"refusing to delete {name}: the app calls it. --delete is for candidate agents published with --name.")
        try:
            project_client().agents.delete(agent_name=name)
        except Exception as exc:
            print(f"error: deleting {name} failed: {exc}", file=sys.stderr)
            return 2
        print(f"deleted: {name}")
        return 0
    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    if args.show:
        print(json.dumps(build_definition(spec, model).as_dict(), indent=2))
        return 0
    try:
        agent, created = publish(spec, model, name)
    except Exception as exc:
        print(f"error: publishing failed: {exc}", file=sys.stderr)
        return 2
    print(f"{'published new version' if created else 'unchanged'}: {agent.name} v{agent.version} (model {model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
