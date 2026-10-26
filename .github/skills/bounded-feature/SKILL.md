---
name: bounded-feature
description: Implement a narrowly scoped feature from a GitHub Issue without crossing boundaries (approval authority, CI/CD, infrastructure, existing migrations, deleted tests, breaking API changes). Use when picking up a feature Issue, before opening a PR, and when reviewing an agent's PR.
---

# Bounded feature

## When to use
- You are assigned a feature Issue (for example "Reviewer confirms the recommended routing department").
- Before you open or update a PR, and when you review a PR that an agent opened.

## Inputs
- The Issue: problem, scope, numbered acceptance criteria, out of scope. Template: `.github/ISSUE_TEMPLATE/03-develop-feature.yml`.
- The base branch (normally `main`).

## Procedure
1. Restate each acceptance criterion as a test you will write. List the files you expect to touch.
2. Implement business rules in `RequestWorkflow` with a stable error `code` per refusal, map endpoints in `ApiEndpoints`,
   and keep UI strings in `app/web/src/i18n/messages.ts` (English and French).
3. Write the tests first or alongside: one integration test per criterion in `app/tests/RequestHub.Tests/`, including
   negative cases (wrong role, wrong department, stale, duplicate, closed request), and web unit tests for UI states.
4. If the API shape changed, regenerate the contract: `UPDATE_CONTRACT=1 dotnet test --solution app/RequestHub.slnx`.
5. Run the boundary check: `python .github/skills/bounded-feature/scope_check.py --base origin/main`.
6. Run the **regression-validation** skill. Open the PR with a criterion-by-criterion checklist that links each test.

## Expected output
```
compared with origin/main (merge base 1a2b3c4d5): 9 changed file(s)
PASS change stays within feature bounds
```

## Failure handling
- `out of scope for a feature`: revert that file. If the feature truly needs it, rerun with `--allow <path>` and say why in the PR.
- `approval authority changed`: stop. Approval rules change only through a separate, explicitly reviewed Issue.
- `tests removed`: restore the tests. Fix the code or explain in the PR why a test is wrong; never delete it to pass.
- `contract change is not additive`: add new fields or routes instead of renaming or removing existing ones.
