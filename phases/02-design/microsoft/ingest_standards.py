#!/usr/bin/env python3
"""Ingest the approved architecture standards into Azure AI Search (Design phase, Microsoft track).

What this script does:
  1. Reads every phases/02-design/standards/STD-*.md file (YAML front matter: id, version, title, scope, category).
  2. Creates or updates the search index `architecture-standards` (keyword + semantic ranking; `scope` is filterable so
     retrieval can be restricted to what a team is allowed to see).
  3. Uploads one document per standard. The document key is the standard id, so re-running updates in place.
  4. Deletes documents whose standard file no longer exists, then reports the counts. A second run must report
     "0 new" and the same total, which proves ingestion is idempotent.

Configuration: SEARCH_ENDPOINT (from `azd env get-values`). Your identity needs "Search Index Data Contributor" and
"Search Service Contributor" on the search service (granted by infra/core.bicep).

Usage
  python phases/02-design/microsoft/ingest_standards.py
  python phases/02-design/microsoft/ingest_standards.py --index architecture-standards --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import yaml
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "common"))
from azd_env import REPO, setting, utf8_stdout  # noqa: E402

STANDARDS = REPO / "phases/02-design/standards"
INDEX = "architecture-standards"


def load_standards() -> list[dict]:
    docs = []
    for path in sorted(STANDARDS.glob("STD-*.md")):
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", path.read_text(encoding="utf-8").replace("\r\n", "\n"), re.DOTALL)
        if not match:
            raise SystemExit(f"error: {path} has no front matter")
        meta = yaml.safe_load(match.group(1))
        body = re.sub(r"^# .*\n", "", match.group(2).strip()).strip()
        docs.append({
            "id": meta["id"],
            "title": f"{meta['id']} · {meta['title']} (v{meta['version']})",
            "content": body,
            "keywords": meta.get("keywords", ""),
            "version": str(meta["version"]),
            "scope": meta["scope"],
            "category": meta["category"],
            "url": f"phases/02-design/standards/{path.name}",
        })
    return docs


def index_definition(name: str) -> SearchIndex:
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
        ],
        semantic_search=SemanticSearch(configurations=[SemanticConfiguration(
            name="default",
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="title"),
                content_fields=[SemanticField(field_name="content")],
                keywords_fields=[SemanticField(field_name="keywords")]),
        )], default_configuration_name="default"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", default=INDEX)
    parser.add_argument("--dry-run", action="store_true", help="Parse and print the documents without writing")
    args = parser.parse_args(argv)
    utf8_stdout()

    docs = load_standards()
    if args.dry_run:
        for doc in docs:
            print(f"{doc['id']:<14} v{doc['version']:<5} {doc['scope']:<11} {doc['title']}")
        return 0

    endpoint = setting("SEARCH_ENDPOINT")
    credential = DefaultAzureCredential()
    SearchIndexClient(endpoint, credential).create_or_update_index(index_definition(args.index))
    client = SearchClient(endpoint, args.index, credential)

    existing = {d["id"] for d in client.search(search_text="*", select=["id"], top=1000)}
    wanted = {d["id"] for d in docs}
    results = client.merge_or_upload_documents(documents=docs)
    failed = [r.key for r in results if not r.succeeded]
    stale = sorted(existing - wanted)
    if stale:
        client.delete_documents(documents=[{"id": key} for key in stale])

    for _ in range(10):  # the document count is eventually consistent
        total = client.get_document_count()
        if total == len(wanted):
            break
        time.sleep(2)
    new = len(wanted - existing)
    print(f"index {args.index}: {len(docs)} standards processed, {new} new, {len(docs) - new} updated, "
          f"{len(stale)} stale removed, {len(failed)} failed; documents in index: {total}")
    if failed:
        print(f"failed keys: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
