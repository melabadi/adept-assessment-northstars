#!/usr/bin/env python3
"""Publish the pull request reviewer agent to Microsoft Foundry (Develop phase, Microsoft track).

What this script does:
  1. Reads reviewer-agent.yaml: the instructions, the runInSandbox tool, and the strict JSON output schema.
  2. Builds the tool's OpenAPI description at publish time. It points at this deployment's sandbox session pool and
     authenticates through a Foundry project connection that uses the project's managed identity, so no secret, key,
     or endpoint is stored in the repository.
  3. Creates a new agent version only when the definition changed (a hash is stored in version metadata), so running it
     again is safe. azd runs it after every provision (postprovision hook).

Configuration (environment variables, or this solution's azd environment after `azd up`):
  FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT, RUN_POOL_ENDPOINT, SANDBOX_CONNECTION_ID.
Your identity needs the Foundry User role (formerly Azure AI User) on the Foundry account; `azd up` assigns it.

Usage
  python solutions/03-develop-microsoft/publish_reviewer_agent.py
  python solutions/03-develop-microsoft/publish_reviewer_agent.py --show            # print the definition, endpoint masked
  python solutions/03-develop-microsoft/publish_reviewer_agent.py --delete OTHER    # delete another agent, for example
                                                                                    # the retired requesthub-triage

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
    OpenApiFunctionDefinition,
    OpenApiProjectConnectionAuthDetails,
    OpenApiProjectConnectionSecurityScheme,
    OpenApiTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    Reasoning,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import setting, utf8_stdout  # noqa: E402

SESSIONS_API_VERSION = "2025-10-02-preview"


def sandbox_spec(endpoint: str, description: str) -> dict:
    """OpenAPI description of the one operation the agent may call: run a command in a session of the run pool."""
    return {
        "openapi": "3.0.1",
        "info": {"title": "Pull request sandbox", "version": "1.0"},
        "servers": [{"url": endpoint}],
        "paths": {
            "/executions": {
                "post": {
                    "operationId": "runInSandbox",
                    "description": description,
                    "parameters": [
                        {"name": "api-version", "in": "query", "required": True,
                         "schema": {"type": "string", "enum": [SESSIONS_API_VERSION]}},
                        {"name": "identifier", "in": "query", "required": True,
                         "description": "The run_session value from the request.", "schema": {"type": "string"}},
                    ],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object", "required": ["shellCommand", "timeoutInSeconds"],
                        "properties": {
                            "shellCommand": {"type": "string", "description": "A read-only bash command."},
                            "timeoutInSeconds": {"type": "integer", "minimum": 5, "maximum": 60},
                        }}}}},
                    "responses": {"200": {"description": "The command's exit status, stdout, and stderr.",
                                          "content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            }
        },
    }


def build_definition(spec: dict, model: str, endpoint: str, connection_id: str) -> PromptAgentDefinition:
    tool = spec["tools"][0]
    sandbox = OpenApiTool(openapi=OpenApiFunctionDefinition(
        name="sandbox",
        description=tool["description"],
        spec=sandbox_spec(endpoint, tool["description"]),
        auth=OpenApiProjectConnectionAuthDetails(
            security_scheme=OpenApiProjectConnectionSecurityScheme(project_connection_id=connection_id)),
    ))
    return PromptAgentDefinition(
        model=model,
        instructions=spec["instructions"],
        reasoning=Reasoning(effort=spec.get("reasoning_effort", "low")),
        tools=[sandbox],
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name="pr_review", schema=spec["output_schema"], strict=True)),
    )


def publish(project: AIProjectClient, spec: dict, definition: PromptAgentDefinition) -> tuple[object, bool]:
    digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    try:
        versions = list(project.agents.list_versions(agent_name=spec["name"]))
    except Exception:
        versions = []
    latest = max(versions, key=lambda v: int(v.version), default=None)
    if latest is not None and (latest.metadata or {}).get("definitionHash") == digest:
        return latest, False
    created = project.agents.create_version(
        agent_name=spec["name"], definition=definition, description=spec["description"],
        metadata={"definitionHash": digest, "source": "solutions/03-develop-microsoft/reviewer-agent.yaml"})
    return created, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="Print the agent definition (sandbox endpoint masked) and exit")
    parser.add_argument("--delete", metavar="NAME", help="Delete another agent and all its versions, then exit")
    args = parser.parse_args(argv)
    utf8_stdout()
    spec = yaml.safe_load((HERE / "reviewer-agent.yaml").read_text(encoding="utf-8"))
    project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    if args.delete:
        if args.delete == spec["name"]:
            parser.error("refusing to delete the reviewer itself; delete it in the Foundry portal if you mean it")
        try:
            project.agents.delete(agent_name=args.delete)
        except Exception as exc:
            print(f"error: deleting {args.delete} failed: {exc}", file=sys.stderr)
            return 2
        print(f"deleted: {args.delete}")
        return 0
    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    endpoint, connection = setting("RUN_POOL_ENDPOINT"), setting("SANDBOX_CONNECTION_ID")
    definition = build_definition(spec, model, endpoint, connection)
    if args.show:
        shown = json.dumps(definition.as_dict(), indent=2).replace(endpoint, "<run pool endpoint>").replace(connection, "<connection id>")
        print(shown)
        return 0
    try:
        agent, created = publish(project, spec, definition)
    except Exception as exc:
        print(f"error: publishing failed: {exc}", file=sys.stderr)
        return 2
    print(f"{'published new version' if created else 'unchanged'}: {agent.name} v{agent.version} (model {model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
