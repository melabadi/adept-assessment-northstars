"""The approved architecture standards: parse them from Markdown and keep the Azure AI Search index in sync.

The standards are code: solutions/02-design-microsoft/standards/STD-*.md, reviewed in pull requests. This module
turns a set of those files (read from the local checkout by the azd hook, or from a merged commit by the Function)
into one search document per approved standard, and syncs the index idempotently: unchanged standards are not
rewritten, and standards that are no longer approved or no longer exist are removed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import yaml

SOURCE_DIR = "solutions/02-design-microsoft/standards"
FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
REQUIRED = ("id", "version", "title", "scope", "category", "status")


class StandardsError(ValueError):
    """A standard file is malformed. The sync stops rather than index a partial set."""


def scope_filter(spec: dict, profile: str) -> str:
    """OData filter that limits retrieval to the scopes a profile may see, for example
    "scope eq 'all' or scope eq 'small-team'". The profile's knowledge source stores the same filter."""
    return " or ".join(f"scope eq '{scope}'" for scope in spec["profiles"][profile])


def parse(files: dict[str, str], spec: dict) -> tuple[list[dict], list[str]]:
    """Index documents from {file name: Markdown text} for every STD-*.md file. Returns (approved documents,
    skipped file names). Raises StandardsError for a file without front matter, a missing field, an id that does
    not match the file name, or a scope that no operating profile can retrieve."""
    known_scopes = {scope for scopes in spec["profiles"].values() for scope in scopes}
    docs, skipped = [], []
    for name in sorted(files):
        if not re.fullmatch(r"STD-[A-Z]+-\d{3}\.md", name):
            continue
        match = FRONT_MATTER.match(files[name].replace("\r\n", "\n"))
        if not match:
            raise StandardsError(f"{name} has no YAML front matter")
        meta = yaml.safe_load(match.group(1))
        missing = [key for key in REQUIRED if not meta.get(key)]
        if missing:
            raise StandardsError(f"{name} front matter lacks {', '.join(missing)}")
        if f"{meta['id']}.md" != name:
            raise StandardsError(f"{name} declares id {meta['id']}; the id must match the file name")
        if meta["scope"] not in known_scopes:
            raise StandardsError(f"{name} has scope '{meta['scope']}', which no profile in agent.yaml can retrieve "
                                 f"({', '.join(sorted(known_scopes))})")
        if meta["status"] != "approved":
            skipped.append(f"{name} (status {meta['status']})")
            continue
        doc = {
            "id": meta["id"],
            "title": f"{meta['id']} · {meta['title']} (v{meta['version']})",
            "content": re.sub(r"^# .*\n", "", match.group(2).strip()).strip(),
            "keywords": meta.get("keywords", ""),
            "version": str(meta["version"]),
            "scope": meta["scope"],
            "category": meta["category"],
            "url": f"{SOURCE_DIR}/{name}",
        }
        doc["contentHash"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]
        docs.append(doc)
    return docs, skipped


def index_definition(name: str):
    from azure.search.documents.indexes.models import (
        SearchableField,
        SearchFieldDataType,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
    )

    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SearchableField(name="keywords", type=SearchFieldDataType.String),
            SimpleField(name="version", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="scope", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="category", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="url", type=SearchFieldDataType.String),
            SimpleField(name="contentHash", type=SearchFieldDataType.String),
        ],
        semantic_search=SemanticSearch(configurations=[SemanticConfiguration(
            name="default",
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="title"),
                content_fields=[SemanticField(field_name="content")],
                keywords_fields=[SemanticField(field_name="keywords")]),
        )], default_configuration_name="default"),
    )


def sync(endpoint: str, credential, index: str, docs: list[dict], spec: dict) -> dict:
    """Create or update the index, upload new and changed standards, delete stale ones. Returns a summary with the
    counts and, for each profile, the standards its scope filter retrieves (asked of the search service itself)."""
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    SearchIndexClient(endpoint, credential).create_or_update_index(index_definition(index))
    client = SearchClient(endpoint, index, credential)
    existing = {d["id"]: d.get("contentHash") for d in client.search(search_text="*", select=["id", "contentHash"], top=1000)}
    new = [d for d in docs if d["id"] not in existing]
    changed = [d for d in docs if d["id"] in existing and existing[d["id"]] != d["contentHash"]]
    stale = sorted(set(existing) - {d["id"] for d in docs})
    failed = []
    if new or changed:
        failed = [r.key for r in client.merge_or_upload_documents(documents=new + changed) if not r.succeeded]
    if stale:
        client.delete_documents(documents=[{"id": key} for key in stale])
    total = None
    for _ in range(15):  # the document count is eventually consistent
        total = client.get_document_count()
        if total == len(docs):
            break
        time.sleep(2)
    visible = {profile: sorted(d["id"] for d in client.search(search_text="*", filter=scope_filter(spec, profile),
                                                               select=["id"], top=1000))
               for profile in spec["profiles"]}
    return {"index": index, "approved": len(docs), "new": [f"{d['id']} v{d['version']}" for d in new],
            "changed": [f"{d['id']} v{d['version']}" for d in changed], "removed": stale, "failed": failed,
            "unchanged": len(docs) - len(new) - len(changed), "documents": total, "visible": visible}


def summary_lines(result: dict) -> list[str]:
    """The sync result as the presenter reads it: the counts, then what sets each profile apart."""
    lines = [f"index {result['index']}: {result['approved']} standards ({len(result['new'])} new, {len(result['changed'])} "
             f"changed, {len(result['removed'])} removed, {len(result['failed'])} failed), {result['documents']} in the index"]
    for label in ("new", "changed", "removed"):
        if result[label]:
            lines.append(f"  {label}: {', '.join(result[label])}")
    visible = result["visible"]
    for profile, ids in visible.items():
        others = set().union(*(set(v) for p, v in visible.items() if p != profile))
        only = sorted(set(ids) - others)
        lines.append(f"  {profile:<11} can retrieve {len(ids):>2}; only this profile sees {', '.join(only) or 'none'}")
    return lines


def snapshot(endpoint: str, credential, index: str, search_filter: str | None = None) -> dict[str, dict]:
    """id -> {version, text} of the indexed standards (only those matching the filter, when one is given), as the
    search service reports them. The gate and the evaluation compare answers against this, never against the model."""
    from azure.search.documents import SearchClient

    client = SearchClient(endpoint, index, credential)
    results = client.search(search_text="*", select=["id", "version", "title", "content"], top=1000, filter=search_filter)
    return {d["id"]: {"version": d["version"], "text": f"{d['title']}\n{d['content']}"} for d in results}
