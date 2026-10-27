#!/usr/bin/env python3
"""Sync the approved architecture standards into Azure AI Search (Design phase, Microsoft track).

What this script does, step by step:
  1. Reads every standards/STD-*.md file in this folder. The YAML front matter gives the stable id, version, title,
     scope (all, small-team, or enterprise), category, keywords, and status. The script stops if a file has no front
     matter, an id that does not match its file name, or a scope that no operating profile in agent.yaml uses.
  2. Creates or updates the search index `architecture-standards` (keyword search with a semantic configuration;
     `scope` is filterable so retrieval can be restricted to what a team may see).
  3. Uploads one document per approved standard, keyed by the standard id, with a hash of its content. Unchanged
     standards are not rewritten, standards that are no longer approved or no longer exist are deleted, so running it
     twice reports "0 new, 0 changed" and the same document count: ingestion is idempotent.
  4. Queries the index with each operating profile's filter, the same filter the advisor agents use, and prints which
     standards each profile can retrieve.

Configuration (environment variable, or read automatically from `azd env get-values` in this folder):
  SEARCH_ENDPOINT   https://<search-service>.search.windows.net
Your identity needs Search Index Data Contributor and Search Service Contributor on the search service
(infra/resources.bicep grants both to whoever runs azd and to the GitHub Actions identity).

Usage
  python solutions/02-design-microsoft/ingest_standards.py
  python solutions/02-design-microsoft/ingest_standards.py --dry-run

Exit codes: 0 index in sync, 1 a document failed to upload, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import credential, setting, utf8_stdout  # noqa: E402

STANDARDS = HERE / "standards"
SPEC = yaml.safe_load((HERE / "agent.yaml").read_text(encoding="utf-8"))
INDEX = SPEC["search"]["index"]
FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
REQUIRED = ("id", "version", "title", "scope", "category", "status")


def scope_filter(profile: str) -> str:
    """OData filter that limits retrieval to the scopes a profile may see, for example
    "scope eq 'all' or scope eq 'small-team'". The advisor agents' search tool uses the same filter."""
    return " or ".join(f"scope eq '{scope}'" for scope in SPEC["profiles"][profile])


def load_standards() -> tuple[list[dict], list[str]]:
    """Parse the standards folder into index documents. Returns (approved documents, skipped file names)."""
    known_scopes = {scope for scopes in SPEC["profiles"].values() for scope in scopes}
    docs, skipped = [], []
    for path in sorted(STANDARDS.glob("STD-*.md")):
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        if not match:
            raise SystemExit(f"error: {path.name} has no YAML front matter")
        meta = yaml.safe_load(match.group(1))
        missing = [key for key in REQUIRED if not meta.get(key)]
        if missing:
            raise SystemExit(f"error: {path.name} front matter lacks {', '.join(missing)}")
        if meta["id"] != path.stem:
            raise SystemExit(f"error: {path.name} declares id {meta['id']}; the id must match the file name")
        if meta["scope"] not in known_scopes:
            raise SystemExit(f"error: {path.name} has scope '{meta['scope']}', which no profile in agent.yaml can "
                             f"retrieve ({', '.join(sorted(known_scopes))})")
        if meta["status"] != "approved":
            skipped.append(f"{path.name} (status {meta['status']})")
            continue
        doc = {
            "id": meta["id"],
            "title": f"{meta['id']} · {meta['title']} (v{meta['version']})",
            "content": re.sub(r"^# .*\n", "", match.group(2).strip()).strip(),
            "keywords": meta.get("keywords", ""),
            "version": str(meta["version"]),
            "scope": meta["scope"],
            "category": meta["category"],
            "url": f"solutions/02-design-microsoft/standards/{path.name}",
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


def sync(endpoint: str, name: str, docs: list[dict]) -> int:
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    signed_in = credential()
    SearchIndexClient(endpoint, signed_in).create_or_update_index(index_definition(name))
    client = SearchClient(endpoint, name, signed_in)

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
    print(f"index {name}: {len(docs)} approved standards, {len(new)} new, {len(changed)} changed, "
          f"{len(docs) - len(new) - len(changed)} unchanged, {len(stale)} removed, {len(failed)} failed; "
          f"documents in index: {total}")
    for label, items in (("new", new), ("changed", changed)):
        if items:
            print(f"  {label}: {', '.join(d['id'] + ' v' + d['version'] for d in items)}")
    if stale:
        print(f"  removed: {', '.join(stale)}")

    # Ask the search service itself what each profile can retrieve, with the agents' own filter.
    for profile in SPEC["profiles"]:
        visible = sorted(d["id"] for d in client.search(search_text="*", filter=scope_filter(profile), select=["id"], top=1000))
        print(f"  {profile:<11} can retrieve {len(visible):>2}: {', '.join(visible)}")
    if failed:
        print(f"error: failed to upload {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog="Reads SEARCH_ENDPOINT from the environment or from this folder's azd environment.")
    parser.add_argument("--index", default=INDEX, help=f"Search index name (default from agent.yaml: {INDEX})")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print the documents without connecting to Azure")
    args = parser.parse_args(argv)
    utf8_stdout()

    docs, skipped = load_standards()
    for name in skipped:
        print(f"skipped {name}: only approved standards are indexed")
    if args.dry_run:
        for doc in docs:
            print(f"{doc['id']:<13} v{doc['version']:<5} {doc['scope']:<11} {doc['category']:<14} {doc['title']}")
        print(f"{len(docs)} approved standards parsed (dry run, nothing written)")
        return 0
    endpoint = setting("SEARCH_ENDPOINT")
    try:
        return sync(endpoint, args.index, docs)
    except Exception as exc:  # surface auth and service errors clearly; there is no offline fallback
        print(f"error: Azure AI Search sync failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
