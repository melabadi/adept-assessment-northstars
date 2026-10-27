---
name: regression-validation
description: Select and run the deterministic regression suites that cover a change (API integration tests on PostgreSQL, web typecheck and unit tests, additive contract check, optional Playwright browser tests) and diagnose the first failure. Use before claiming a change is done, when CI fails on a PR, or when a reviewer adds a regression test.
---

# Regression validation

## When to use
- Before you say a change is done or ask for review.
- When CI fails on a PR, or a reviewer adds a regression test that fails.

## Inputs
- A branch with changes, and the base branch (normally `origin/main`).
- PostgreSQL on `localhost:5432` (user `requesthub`, password `devpass`). The Copilot cloud agent environment starts one.

## Procedure
1. Run the suites that cover your change:
   `python .github/skills/regression-validation/run_regression.py --base origin/main`
   Add `--e2e` when UI behavior changed, `--all` to run everything.
2. For each FAIL, reproduce the single test before changing code:
   - API: `dotnet test --solution app/RequestHub.slnx --filter-method "*Confirm*"`
   - Web unit: `npm test --prefix app/web -- TriagePanel`
   - Browser: `npx playwright test e2e/confirm-routing.spec.ts` in `app/web` (API running on port 5080).
3. Decide whether the code or the test is wrong. Use the acceptance criteria in the Issue as the source of truth.
4. Fix, rerun the single test, then rerun step 1. Commit with a message that names the failing test and the cause.

## Expected output
```
## Regression summary
PASS  API and worker tests
PASS  Web typecheck
PASS  Web unit tests
PASS  Browser tests
```

## Failure handling
- `Connection refused` on 5432: start PostgreSQL (`docker compose -f app/docker-compose.yml up -d db`).
- Contract test fails: if the shape change is intended, regenerate with `UPDATE_CONTRACT=1` and run the contract check.
- A test fails only in CI: compare runtime versions in the job log with `global.json` and `app/web/package.json`.
- Never skip, delete, or loosen a failing test to get a green summary.
