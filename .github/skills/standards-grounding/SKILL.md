---
name: standards-grounding
description: Keep the Azure AI Search "architecture-standards" index in sync with phases/02-design/standards (idempotent ingestion keyed by standard id, scope-filterable), and verify what each operating profile can retrieve. Use after editing a standard, before a Design demo, or when the advisor misses a standard.
---

# Standards grounding

## When to use
- A standard was added, changed, or removed.
- Before presenting the Design Microsoft track (prove the index is current).
- An evaluation case fails because a relevant standard was never retrieved.

## Inputs
- `phases/02-design/standards/STD-*.md`: front matter `id`, `version`, `title`, `scope` (`all`, `small-team`, `enterprise`), `category`, `keywords`.
- `SEARCH_ENDPOINT` (from `azd env get-values`); identity with Search Index Data Contributor + Search Service Contributor.

## Procedure
1. Preview: `python phases/02-design/microsoft/ingest_standards.py --dry-run`.
2. Ingest: `python phases/02-design/microsoft/ingest_standards.py`.
3. Prove idempotency: run it again; it must report `0 new` and the same document count.
4. Check what a profile can see (Azure CLI, Entra auth):
   `az rest --method post --url "$SEARCH_ENDPOINT/indexes/architecture-standards/docs/search?api-version=2024-07-01" --resource https://search.azure.com --body "{\"search\":\"*\",\"filter\":\"scope eq 'all' or scope eq 'small-team'\",\"select\":\"id,version,scope\"}"`
5. Retrieval gap? Improve the standard's `keywords` (words people actually use), re-ingest, and re-run the evaluation.

## Expected output
```
index architecture-standards: 12 standards processed, 0 new, 12 updated, 0 stale removed, 0 failed; documents in index: 12
```

## Failure handling
- `Forbidden`: role assignment missing or not yet propagated; re-run `azd provision`, wait a few minutes.
- Count lower than expected right after ingestion: the count is eventually consistent; the script waits up to 20 seconds.
- Never fix a retrieval gap by changing a standard's scope; scope is the access rule.
