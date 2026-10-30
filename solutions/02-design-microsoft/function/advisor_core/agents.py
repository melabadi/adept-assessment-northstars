"""The architecture advisor agents in Foundry Agent Service: one prompt agent per operating profile, from agent.yaml.

publish() creates a new agent version only when the definition changes (its hash is kept in the version's metadata),
so running it twice changes nothing. Each version's metadata also records the profile and the scope filter its
knowledge tool applies, which the gate reads to know what that agent version was allowed to see.

agent.yaml chooses the knowledge tool:
  knowledge: foundry-iq       the profile's Foundry IQ knowledge base, through its MCP endpoint (default)
  knowledge: azure-ai-search  the Azure AI Search tool with a fixed filter on the index (the fallback)
"""
from __future__ import annotations

import hashlib
import json

import yaml

from . import knowledge, standards

SOURCE = "solutions/02-design-microsoft/agent.yaml"
TOOL_WORDING = {
    "foundry-iq": "the knowledge base tool (knowledge_base_retrieve)",
    "azure-ai-search": "the azure_ai_search tool",
}


def load_spec(text: str) -> dict:
    spec = yaml.safe_load(text)
    mode = spec.get("knowledge", "foundry-iq")
    if mode not in TOOL_WORDING:
        raise ValueError(f"agent.yaml: knowledge must be one of {', '.join(TOOL_WORDING)}, not {mode}")
    spec["knowledge"] = mode
    return spec


def agent_name(spec: dict, profile: str) -> str:
    return f"{spec['name']}-{profile}"


def definition(spec: dict, profile: str, model: str, search_endpoint: str, search_connection_id: str | None = None):
    from azure.ai.projects.models import (
        AISearchIndexResource,
        AzureAISearchTool,
        AzureAISearchToolResource,
        MCPTool,
        PromptAgentDefinition,
        PromptAgentDefinitionTextOptions,
        Reasoning,
        TextResponseFormatJsonSchema,
    )

    if spec["knowledge"] == "foundry-iq":
        tool = MCPTool(server_label="standards", server_url=knowledge.mcp_url(search_endpoint, profile),
                       require_approval="never", allowed_tools=["knowledge_base_retrieve"],
                       project_connection_id=knowledge.connection_name(profile))
    else:
        tool = AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(indexes=[AISearchIndexResource(
            project_connection_id=search_connection_id, index_name=spec["search"]["index"],
            query_type=spec["search"]["query_type"], filter=standards.scope_filter(spec, profile),
            top_k=spec["search"]["top_k"])]))
    # Reasoning models (gpt-5 family) take a reasoning effort and reject temperature; other models take temperature.
    sampling = {}
    if spec.get("temperature") is not None:
        sampling["temperature"] = spec["temperature"]
    if spec.get("reasoning_effort"):
        sampling["reasoning"] = Reasoning(effort=spec["reasoning_effort"])
    return PromptAgentDefinition(
        model=model,
        instructions=spec["instructions"].replace("{knowledge_tool}", TOOL_WORDING[spec["knowledge"]]),
        tools=[tool],
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name="architecture_recommendation", schema=spec["output_schema"], strict=True)),
        **sampling,
    )


def publish(project, spec: dict, model: str, search_endpoint: str) -> dict[str, dict]:
    """Publish every profile's agent. Returns {profile: {name, version, reused, scopeFilter}}."""
    connection_id = None
    if spec["knowledge"] == "azure-ai-search":
        connection_id = project.connections.get(spec["search"]["connection"]).id
    published = {}
    for profile in spec["profiles"]:
        name = agent_name(spec, profile)
        body = definition(spec, profile, model, search_endpoint, connection_id)
        digest = hashlib.sha256(json.dumps(body.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
        try:
            versions = list(project.agents.list_versions(agent_name=name))
        except Exception:  # first run: the agent does not exist yet
            versions = []
        agent = next((v for v in versions if (v.metadata or {}).get("definitionHash") == digest), None)
        reused = agent is not None
        if agent is None:
            agent = project.agents.create_version(
                agent_name=name, definition=body, description=spec["description"].format(profile=profile),
                metadata={"definitionHash": digest, "profile": profile, "knowledge": spec["knowledge"],
                          "scopeFilter": standards.scope_filter(spec, profile), "source": SOURCE})
        published[profile] = {"name": agent.name, "version": str(agent.version), "reused": reused,
                              "scopeFilter": standards.scope_filter(spec, profile)}
    return published


def scope_filter_of(project, name: str, version: str) -> tuple[str, str]:
    """(profile, scope filter) recorded on an agent version when it was published."""
    agent = project.agents.get_version(agent_name=name, agent_version=str(version))
    metadata = agent.metadata or {}
    if not metadata.get("scopeFilter") or not metadata.get("profile"):
        raise ValueError(f"agent {name} v{version} has no profile or scope filter in its metadata; publish it from agent.yaml")
    return metadata["profile"], metadata["scopeFilter"]
