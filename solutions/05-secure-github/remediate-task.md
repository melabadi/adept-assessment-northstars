## Problem

Defensive training only. An undeployed `lab/secure-*` branch replaces safe search with SQL string
concatenation in `RequestWorkflow.ListAsync`. Copilot code review (or, where licensed, CodeQL) identified it.

Before assigning, append the real **review comment URL**, **reviewed SHA**, and **lab PR URL** here.
For CodeQL instead, append the successful run URL, scanned SHA, `cs/sql-injection` source location and artifact.
Missing detection evidence is a blocker, not permission to invent it.

## Acceptance criteria

1. Use agent `secure-github` and skills `finding-triage` and `verified-remediation`.
2. Copy `solutions/05-secure-github/regression/SearchSecurityTests.cs` unchanged into
   `app/tests/RequestHub.Tests/SearchSecurityTests.cs`. Commit tests ONLY first. Show real failed assertions.
3. Fix SQL parameterization and literal LIKE wildcard behavior in `ListAsync` only. Keep role/department
   scope, public IDs, filters, ordering and pagination unchanged. Prefer the existing safe LINQ/EF pattern.
4. The identical regression passes after repair, and the full API/worker/contract suite passes.
5. Commit the fix separately and put both SHAs and commands in the PR description. Target the original
   unsafe lab branch, never `main`. A person runs the trusted replay and requests a fresh review/rescan.

## Out of scope

No deploy, merge, credentials, active secrets, approval-rule changes, migrations, UI or API contract changes.
Do not edit workflows, skills, agent files or the supplied regression. No skipped, weakened or deleted tests.
AI review is not code scanning. This is Copilot-assisted remediation, not Copilot Autofix.
