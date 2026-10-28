---
name: load-scenario
description: Change and run the RequestHub load test (the Locust journey, its workload settings, and its pass/fail criteria) safely, locally against a development API and live in Azure Load Testing. Use when adding a step to the journey, changing users, duration, pacing, dataset, cleanup, or thresholds, or before running the test in a new environment.
---

# Load scenario

The load test is two files. Everything that depends on a deployment (API URL, identities, monitored resources) is added
at run time by `solutions/04-test-microsoft/load_test.py`, so both files are safe to commit and to review.

| Piece | File |
|---|---|
| The journey: virtual users, requests, sign-in, cleanup | `solutions/04-test-microsoft/loadtest/locustfile.py` |
| Workload settings, pass/fail criteria, auto-stop | `solutions/04-test-microsoft/loadtest/requesthub-journey.yaml` |
| Run, report, Issue sync, cleanup | `solutions/04-test-microsoft/load_test.py` |
| Guardrail check (this skill) | `.github/skills/load-scenario/check_scenario.py` |

## When to use
- Adding or changing a step of the journey, or a request name that a criterion refers to.
- Changing users, spawn rate, duration, pacing, decide share, dataset size, cleanup, or a threshold.
- Before the first run against a new environment.

## Inputs
- The change, for example "add the comment step" or "run 20 users for 3 minutes".
- For a local run: RequestHub running locally with `Demo__LoadTestRequesterIds=u-ben` (see the solution README).
- For a live run: the solution deployed with `azd up` and the Load Test Contributor role (azd grants it).

## Procedure
1. Edit the journey or the settings. Keep these rules:
   - **Synthetic data only.** The journey creates its own requests; approvers only decide requests this run submitted.
   - **Two identities.** Requesters and approvers sign in as different identities, so nobody decides their own request.
     Never add a step that approves as the requester or reaches the API without signing in (except the 401 check).
   - **Python 3.9 and no extra packages.** The engines run Locust 2.33.2 on Python 3.9 with locust and gevent only.
   - **Name every request** with `name="..."`; criteria refer to these names.
   - **Never raise a threshold to make a run pass.** Fix the app, or explain in the pull request why the criterion was wrong.
2. Check it: `python .github/skills/load-scenario/check_scenario.py`.
3. Run it locally (from `solutions/04-test-microsoft`, API on http://localhost:5080):
   `locust -f loadtest/locustfile.py --headless -u 4 -r 2 -t 1m -H http://localhost:5080`
4. Run it live: `python load_test.py run` (add `--users` or `--duration` for a one-off override), or open a pull request:
   the **Test · Microsoft · load test RequestHub** workflow runs it and comments the report.
5. Read the result with the **performance-analysis** skill.

## Expected output
```
PASS requesthub-journey.yaml: criteria name real requests, thresholds and workload within guardrails, every setting read, Python 3.9 compatible, no secrets
...
Cleanup: deleted 0 requests owned by u-ben
All users spawned: {"Approver": 2, "Requester": 2} (4 total users)
Aggregated   81   0(0.00%)
```

## Failure handling
- `names request '...', which the locustfile never makes`: the criterion would never be evaluated. Fix the name on either side.
- `exceeds ... the rehearsal limit`: the demo environment runs one small API replica set and a burstable database. Raise the
  limit in `check_scenario.py` only for an environment sized for it, and say so in the pull request.
- `is not valid Python 3.9`: remove newer syntax such as `match` or `X | Y` outside annotations.
- Locally, `Cleanup refused (HTTP 403)`: start the API with `Demo__LoadTestRequesterIds` set to the requester persona.
- Live, every request fails with 401: the identities are missing from the API's accepted client applications. Run
  `azd deploy api` so `app/infra/api.bicep` picks up `LOAD_TEST_CLIENT_IDS`.
