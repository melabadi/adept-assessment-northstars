---
name: verified-remediation
description: Prove the same SQL injection regression fails on the lab baseline and passes after Copilot's bounded repair.
---

# Verified remediation

## Triggers and inputs
Use after finding-triage accepts a real review/scan, before asking for review of a repair.
Inputs: lab base SHA, repair head SHA, supplied `SearchSecurityTests.cs`, PostgreSQL and .NET 10.

## Procedure
1. Copy the supplied test into `app/tests/RequestHub.Tests/`, run it, and commit tests ONLY before fixing.
   Use `dotnet test --project app/tests/RequestHub.Tests -- --filter-class '*SearchSecurityTests'`.
   Keep the failing assertions. Compilation, missing database, or zero tests is not a reproduced defect.
2. Fix the data access, not the test. Keep approval authority, authorization, public IDs, literal wildcard
   handling and the API contract unchanged. Commit the fix separately.
3. Run `python .github/skills/verified-remediation/verify_remediation.py --base BASE_SHA --head HEAD_SHA --out out/replay`.
   The checker requires both commits locally. It verifies the changed-file boundary, the unchanged supplied
   regression and a tests-only commit, then creates two isolated temporary worktrees under its output folder.
   It builds both, runs the same tests and records JUnit reports and logs. A real assertion failure on the
   original SQL/wildcard test and zero failures after repair are required. The full API/worker/contract suite
   also runs on the repaired snapshot. `ApiFixture` creates and drops a unique database per test class.
4. Prefer dispatching `secure-github-verify.yml` from `main` for trustworthy evidence: it loads the checker and
   reference test from `main`, not from the untrusted PR. The job has no cloud secrets or deploy permissions.
5. Link the JSON, JUnit, job URL, reviewed/scanned SHA, tests-only SHA and repair SHA. Have a person inspect the
   diff and request a new Copilot review. If licensed, also run CodeQL with `expect=absent` on the same head.

## Expected output
`PASS: regression failed before repair, passed after; full app suite passed`, with immutable SHAs and exit codes.
This proves the specified regression, not the absence of all vulnerabilities or regulatory compliance.

## Failure handling
Unexpected files, edited regression, missing tests-only commit, build failures, missing reports, test errors,
zero tests, no baseline failure or a repaired failure all return nonzero. Fix the code or report the blocker.
Never weaken a test or claim a passing review substitutes for deterministic execution.
