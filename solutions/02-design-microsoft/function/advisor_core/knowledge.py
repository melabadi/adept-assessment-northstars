"""Foundry IQ knowledge for the advisor: one knowledge base per operating profile over the standards index.

Each profile gets a knowledge source on the `architecture-standards` index with a stored base filter (for example
"scope eq 'all' or scope eq 'small-team'") and a knowledge base over that source. Azure AI Search applies the base
filter to every retrieval, and a request can only narrow it, never widen it: the search service enforces what a team
may see, not the prompt. The agent reaches its knowledge base through the knowledge base's MCP endpoint and a
Foundry project connection (RemoteTool, project managed identity) that infra/resources.bicep creates.

Retrieval uses minimal reasoning and extractive output: no model runs inside the knowledge base, and the agent gets
the standards' own text to cite.
"""
from __future__ import annotations

import requests

from . import standards

API_VERSION = "2026-08-01-preview"  # baseFilter on a search index knowledge source is a preview property


def name(profile: str) -> str:
    """Name of a profile's knowledge source and knowledge base."""
    return f"standards-{profile}"


def connection_name(profile: str) -> str:
    """Name of the Foundry project connection to a profile's knowledge base (created in infra/resources.bicep)."""
    return f"standards-kb-{profile}"


def mcp_url(search_endpoint: str, profile: str) -> str:
    return f"{search_endpoint.rstrip('/')}/knowledgebases/{name(profile)}/mcp?api-version={API_VERSION}"


def definitions(spec: dict, profile: str, index: str) -> tuple[dict, dict]:
    """The knowledge source and knowledge base for one profile."""
    source = {
        "name": name(profile),
        "kind": "searchIndex",
        "description": f"Approved architecture standards the {profile} profile may retrieve.",
        "searchIndexParameters": {
            "searchIndexName": index,
            "semanticConfigurationName": "default",
            "baseFilter": standards.scope_filter(spec, profile),
            "sourceDataFields": [{"name": "id"}, {"name": "version"}, {"name": "scope"}],
        },
    }
    base = {
        "name": name(profile),
        "description": f"Architecture standards for the {profile} operating profile.",
        "knowledgeSources": [{"name": name(profile)}],
        "outputMode": "extractiveData",
        "retrievalReasoningEffort": {"kind": "minimal"},
        "retrieveDefaults": {"maxOutputDocuments": spec["search"].get("top_k", 10)},
    }
    return source, base


def sync(search_endpoint: str, credential, spec: dict, index: str) -> list[str]:
    """Create or update every profile's knowledge source and knowledge base (PUT is idempotent)."""
    token = credential.get_token("https://search.azure.com/.default").token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    lines = []
    for profile in spec["profiles"]:
        source, base = definitions(spec, profile, index)
        for kind, body in (("knowledgesources", source), ("knowledgebases", base)):
            url = f"{search_endpoint.rstrip('/')}/{kind}/{body['name']}?api-version={API_VERSION}"
            response = requests.put(url, headers=headers, json=body, timeout=60)
            if response.status_code >= 300:
                raise RuntimeError(f"{kind} {body['name']}: HTTP {response.status_code} {response.text[:300]}")
        lines.append(f"  knowledge base {name(profile)}: base filter {source['searchIndexParameters']['baseFilter']}")
    return lines
