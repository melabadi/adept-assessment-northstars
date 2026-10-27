---
name: bounded-feature
description: Implement a narrowly scoped feature from a GitHub Issue without crossing boundaries (approval authority, CI/CD, infrastructure, existing migrations, deleted or skipped tests, breaking API changes). Use when picking up a feature Issue, before opening or updating a PR, and when reviewing an agent's PR.
---

# Bounded feature

## When to use
- You are assigned a feature Issue (for example "Reviewer confirms the recommended routing department").
- Before you open or update a PR, and when you review a PR that an agent opened.

## Inputs
- The Issue: problem, scope, numbered acceptance criteria, out of scope. Template: `.github/ISSUE_TEMPLATE/03-develop-github-feature.yml`.
- The base branch, normally `origin/main`. If git cannot find it, run `git fetch origin main` first.

## Procedure
1. Restate each acceptance criterion as a test you will write. List the files you expect to touch. They should all be under `app/`.
2. Implement business rules in `RequestWorkflow` with a stable error `code` per refusal, map endpoints in `ApiEndpoints`,
   and keep UI strings in `app/web/src/i18n/messages.ts` (English and French).
3. Write the tests first or alongside: one integration test per criterion in `app/tests/RequestHub.Tests/`, including
   negative cases (wrong role, wrong department, stale, duplicate, closed request), and web unit tests for UI states.
4. Schema change: add a new migration, never edit an existing one. In `app/`: `dotnet tool restore`, then `dotnet ef migrations add <Name> --project src/RequestHub.Core`.
5. If the API shape changed, regenerate the contract: `UPDATE_CONTRACT=1 dotnet test --solution app/RequestHub.slnx`.
6. Run the boundary check: `python .github/skills/bounded-feature/scope_check.py --base origin/main`.
7. Run the **regression-validation** skill. Open the PR with a criterion-by-criterion checklist that names each test.

To review someone else's branch without checking it out: `python .github/skills/bounded-feature/scope_check.py --head origin/<branch>`.
CI runs the same check on every pull request that closes an Issue labeled `phase:develop`, using the checker from the base branch.

## Expected output
```
compared working tree with origin/main (merge base 1a2b3c4d5): 18 changed file(s)
  M app/src/RequestHub.Core/Services/RequestWorkflow.cs
  A app/tests/RequestHub.Tests/RecommendationConfirmationTests.cs
  ...
PASS change stays within feature bounds
```

## Failure handling
- `out of scope (...)`: revert that file. A feature changes `app/` only. If it truly needs more, rerun with `--allow <path>`,
  say why in the PR, and expect the CI check to stay red until a person accepts it.
- `existing migration changed or deleted`: restore it and add a new migration instead.
- `approval authority changed`: stop. Approval rules change only through a separate, explicitly reviewed Issue.
- `tests removed` or `tests skipped or focused`: restore the tests. Fix the code, or explain in the PR why a test is wrong; never delete or skip it to pass.
- `no tests changed`: add the tests that prove the acceptance criteria.
- `contract change is not additive`: add new fields or routes instead of renaming or removing existing ones.
