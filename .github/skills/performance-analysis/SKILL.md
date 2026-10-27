---
name: performance-analysis
description: Read and act on a RequestHub load test result from Azure Load Testing (pass/fail criteria, client-side percentiles, server-side telemetry from Application Insights) and decide whether it is an acceptance run, an expected failure from the slowdown rehearsal, or a regression. Use after a load test run, when the load-test workflow fails, or when a load-test Issue opens.
---

# Performance analysis

A load test result only means something next to the load, data, region, and compute it ran on, and next to what the
server saw. `solutions/04-test-microsoft/load_test.py report` puts all of that in one report.

## When to use
- After `python solutions/04-test-microsoft/load_test.py run`, or when the **Test · Microsoft · load test RequestHub**
  workflow finishes.
- When an Issue labelled `load-test` opens or gets a new comment.

## Inputs
- The test run id: printed by `load_test.py run`, shown in the workflow log, or listed with
  `az load test-run list --load-test-resource <LOAD_TEST_NAME> --resource-group <AZURE_RESOURCE_GROUP> --test-id requesthub-journey`.
- Reader access to Application Insights for the server-side part (azd grants it to you and to the workflow identity).

## Procedure
1. `python solutions/04-test-microsoft/load_test.py report --run-id <id>`. It writes `out/report.md` and `out/run.json`.
2. Read the **verdict** first:
   - **Accepted**: every criterion met, no injected slowdown. This is an acceptance run.
   - **Expected failure**: the rehearsal slowdown was active (server requests carry `requesthub.fault.queue_delay_ms`)
     and the criteria caught it. It proves the gate works. It is never acceptance evidence.
   - **Regression**: a criterion failed without any injected fault. Investigate before releasing.
   - **Warning: slowdown not caught**: the gate is too lax. Tighten the criteria (with the **load-scenario** skill).
3. Read the **criteria** table: which request and which statistic failed, by how much.
4. Compare **client side** (Azure Load Testing) with **server side** (Application Insights) for the failing request:
   - server p95 close to client p95: the time is spent in RequestHub. Use query 2 in
     `.github/skills/performance-analysis/queries.kql` to split it between the database and the app.
   - client p95 much higher than server p95: the time is spent before the app (network, the Container Apps
     authentication layer, scaling). Check the replica count and CPU on the test run's dashboard in the Azure portal.
   - errors on the client but none on the server: requests were refused before the app, usually sign-in (401) or the
     engines' identities missing an app role.
5. Decide and record it: in the pull request or on the `load-test` Issue, state the verdict, the failing criterion with
   its actual value, the server-side evidence, and the fix. A passing run closes the Issue automatically.

## Expected output
```
**FAILED** · test `requesthub-journey` · run `run-20260101-120000` · 10 virtual users · 120 s load
**Expected failure:** the API ran with the rehearsal slowdown (412 server requests carried `requesthub.fault.queue_delay_ms`) ...
| team-queue p95(response_time_ms) | > 1000 ms | 1,612 ms | failed |
| GET /api/requests | 412 | 0 | 1,534 | 412 |
```

## Failure handling
- `No server-side telemetry for this window yet`: Application Insights receives data a minute or two late. Run the
  report again with the same run id.
- `could not read Application Insights`: the signed-in identity needs Reader or Monitoring Reader on the resource group.
- The run status is `FAILED` or `CANCELLED` (not the test result): the engines could not run the script. Download the
  logs with `az load test-run download-files --test-run-id <id> --path out/logs --log` and read `locust.log`.
- Never change a threshold, the request mix, or the pacing to turn a failed run into a pass. Fix the app, or explain in
  the pull request why the criterion itself was wrong.
