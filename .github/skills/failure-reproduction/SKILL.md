---
name: failure-reproduction
description: Reproduce a reported RequestHub defect against a running API with a data-driven scenario, then turn it into a failing automated regression test (API or Playwright, including concurrent and double-click cases) before any fix. Use when a bug Issue arrives, or when a reviewer suspects a regression.
---

# Failure reproduction

Fix nothing until a test fails for the right reason. This skill gets you there in two steps: reproduce the defect with a
scenario file, then encode the same expectations as regression tests and commit them before the fix.

## When to use
- A bug Issue describes observed behavior, for example "a request can be decided twice".
- A reviewer suspects a regression and wants to see it happen.
- You want to apply the same procedure to another small defect: write a new scenario, the steps do not change.

## Inputs
- The Issue's observed and expected behavior.
- A running API with development sign-in: `dotnet run --project app/src/RequestHub.Api`
  (http://localhost:5080, PostgreSQL on localhost:5432).
- A scenario file. In this repository they live in `solutions/04-test-github/scenarios/`; the format is documented in
  `python .github/skills/failure-reproduction/repro.py --help`.

## Procedure
1. Write or reuse a scenario: each step names a persona, a call, and the **correct** expected result. Use
   `"parallel": 8` for double-click and retry races.
2. Run it: `python .github/skills/failure-reproduction/repro.py <scenario.json>` (add `--api <url>` for another port).
   Exit code 1 and `FAIL` lines mean the defect reproduces. Note which expectations break.
3. Encode each broken expectation as an integration test in `app/tests/RequestHub.Tests/` (xUnit v3, `ApiFixture`,
   personas). For races, fire the calls together with `Task.WhenAll` and assert the outcome counts and the audit
   history, not a helper's return value.
4. Run only the new tests and confirm they fail for the reported reason:
   `dotnet test --solution app/RequestHub.slnx --filter-method "*.<TestName>"` (repeat `--filter-method` per test).
   Commit the tests alone, with only files under `app/tests/`: `Add failing regression tests for #<issue>`. The failure
   is now visible at a known SHA.
5. Fix the code, rerun the same tests, then the full suite (regression-validation skill). Commit the fix separately.
6. Rerun the scenario: it must print `Not reproduced`.

## Expected output
Against the defective build:
```
 4. FAIL Dan rejects the already approved request  ->  HTTP 201
          HTTP 201, expected 409
          code None, expected decision.already_decided
 8. FAIL Chloé double-clicks Approve: eight requests at once  ->  HTTP 201 x3, HTTP 500 x5
          status counts {'201': 3, '500': 5}, expected {'201': 1, '409': 7}

REPRODUCED: 6 step(s) did not behave as expected.
```
After the fix: `Not reproduced: every step behaved as expected.`

## Failure handling
- `error: cannot reach`: start the API, or pass `--api` with the right URL.
- The scenario passes but the Issue says it fails: check that the API runs the defective code (the right branch, rebuilt).
- A race test passes before the fix: make it stronger (more parallel calls, assert audit counts) rather than adding sleeps.
- Never write a test that mirrors the implementation; assert the behavior the Issue describes.
