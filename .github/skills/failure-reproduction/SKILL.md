---
name: failure-reproduction
description: Reproduce a reported RequestHub defect against a running API with a data-driven scenario, then turn it into a failing automated regression test (API or Playwright, including concurrent and double-click cases) before any fix. Use when a bug Issue arrives, or when a reviewer suspects a regression.
---

# Failure reproduction

Fix nothing until a test fails for the right reason. This skill gets you there in two steps: reproduce with a scenario file,
then encode the same steps as a regression test.

## When to use
- A bug Issue describes observed behavior (for example "a request can be decided twice").
- You want to apply the same procedure to a second small defect.

## Inputs
- The Issue's observed and expected behavior.
- A local API with development sign-in: `dotnet run --project app/src/RequestHub.Api` (http://localhost:5080, PostgreSQL on 5432).
- Scenario files in `phases/04-test/github/repro/` (format documented in `repro.py --help`).

## Procedure
1. Write or reuse a scenario JSON: each step names a persona, a call, and the **correct** expected result.
   Use `"parallel": 8` for double-click and retry races.
2. Run it: `python .github/skills/failure-reproduction/repro.py <scenario.json>`. Exit code 1 and FAIL lines mean the defect
   reproduces; note which expectations break.
3. Encode each failing expectation as an integration test in `app/tests/RequestHub.Tests/` (xUnit v3 + `ApiFixture` personas).
   For races, fire the calls together with `Task.WhenAll` and assert the outcome counts and the audit history, not just a helper.
4. Run only the new tests and confirm they fail for the reported reason:
   `dotnet test --solution app/RequestHub.slnx --filter-method "*Decision*"`.
   Commit the tests alone (message: `Add failing regression tests for #<issue>`), so the failure is visible at a known SHA.
5. Fix the code, rerun the same filter, then the full suite (regression-validation skill). Commit the fix separately.
6. Rerun the scenario: it must print `Not reproduced`.

## Expected output
```
 4. FAIL Dan rejects the already approved request  ->  HTTP 201
REPRODUCED: 6 step(s) did not behave as expected.        (before the fix)
Not reproduced: every step behaved as expected.          (after the fix)
```

## Failure handling
- `cannot reach`: start the API, or pass `--api`.
- The scenario passes but the Issue says it fails: check you are on the lab branch and the database was not reused from another branch.
- A race test passes before the fix: make it stronger (more parallel calls, assert audit counts) rather than adding sleeps.
- Never write a test that mirrors the implementation; assert the behavior the Issue describes.
