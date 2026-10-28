---
name: standards-grounding
description: Keep the Azure AI Search "architecture-standards" index in sync with solutions/02-design-microsoft/standards (idempotent ingestion keyed by standard id, only approved standards, scope-filterable), and verify what each operating profile can retrieve. Use after editing a standard, before a Design demo, or when the advisor misses a standard.
---

# Standards grounding

## When to use
- A standard was added, changed, retired, or re-scoped.
- Before presenting the Design Microsoft demo, to prove the index matches the repository.
- An evaluation case fails with `did not cite X` and `run.json` shows X was never in `retrievedStandards`.

## Inputs
- `solutions/02-design-microsoft/standards/STD-*.md`. Front matter: `id` (must match the file name), `version`, `title`, `scope` (`all`, `small-team`, or `enterprise`), `category`, `keywords`, `status` (only `approved` is indexed).
- `solutions/02-design-microsoft/agent.yaml`: the index name and the scopes each profile may retrieve.
- `SEARCH_ENDPOINT` from the solution's azd environment (or the environment), and an identity with Search Index Data Contributor and Search Service Contributor on the search service.

## Procedure
1. Preview without Azure: `python solutions/02-design-microsoft/ingest_standards.py --dry-run`.
2. Sync: `python solutions/02-design-microsoft/ingest_standards.py`.
3. Prove idempotency: run it again. It must report `0 new, 0 changed` and the same document count.
4. Read the last lines: the search service itself lists what each profile can retrieve, using the agents' own filters.
5. Retrieval gap? Add the words people actually use to the standard's `keywords`, sync, and re-run the evaluation (architecture-evaluation skill).

In GitHub Actions, *Design · Microsoft · sync the standards and evaluate the advisor* runs the same sync before every evaluation, and on every push to `main` that changes the standards.

## Expected output
```
index architecture-standards: 12 approved standards, 0 new, 0 changed, 12 unchanged, 0 removed, 0 failed; documents in index: 12
  small-team  can retrieve  9: STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-001, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002
  enterprise  can retrieve 10: STD-AI-001, STD-AI-002, STD-API-001, STD-ARCH-001, STD-DATA-001, STD-OBS-001, STD-OBS-002, STD-OPS-002, STD-SEC-001, STD-SEC-002
```

## Failure handling
- `Forbidden` or `403`: the role assignment is missing or still propagating. Run `azd provision` in the solution folder, or wait a few minutes.
- `has scope '...', which no profile ... can retrieve`: fix the typo in the standard's front matter.
- Document count lower than expected right after a sync: the count is eventually consistent; the script waits up to 30 seconds.
- Never fix a retrieval gap by changing a standard's `scope`: scope is the access rule.
