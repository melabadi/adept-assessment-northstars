# Evidence: the recorded run of 31 October 2026

What Azure recorded during [the run in See it work](../README.md#see-it-work), exported so that anyone can check it without signing in to Azure. Times are UTC.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-test`, with the commands shown in each section, run from `solutions/04-test-microsoft` after `azd env select ai-sdlc-test`. The exports keep only the fields that each command names, none of which identify the tenant: no e-mail addresses, resource URLs, or signed links.
- **Kept here because telemetry expires:** the Log Analytics workspace behind Application Insights keeps 30 days of data, so the queries in [the function's log](#the-functions-log) and [the API's telemetry](#the-apis-telemetry) return nothing after 30 November 2026. The tables keep their results.
- **On GitHub**, Issue [#215](https://github.com/melabadi/adept-assessment-northstars/issues/215) holds the function's two reports: the failure that opened it, and the [passing run that closed it](https://github.com/melabadi/adept-assessment-northstars/issues/215#issuecomment-6539313428).
- **Measured in the terminal:** a few times come from the terminal session that ran the steps, not from Azure. [The terminal](#the-terminal) lists them.

## The code that ran

- **The test:** [`loadtest/`](../loadtest/) as of commit [49e9cf0](https://github.com/melabadi/adept-assessment-northstars/commit/29a6873) (pull request [#166](https://github.com/melabadi/adept-assessment-northstars/pull/166), merged on 30 October), which `azd provision` had copied into Azure Load Testing. It hasn't changed since.
- **The reporting function:** the first version of pull request [#229](https://github.com/melabadi/adept-assessment-northstars/pull/229), which `azd deploy` deployed at 04:13, before that pull request's first commit. Before #229 merged the same day as [c3a533f](https://github.com/melabadi/adept-assessment-northstars/commit/c177953), the function's GitHub token moved from an app setting to Key Vault, the action group and the function came to share one function key, and only Issues and comments from the owner, members, and collaborators count. None of these changes what this run shows: every notification reached the function, and the Issue and its comments were the owner's.
- **The API:** the image that `azd deploy` built on 29 October at 20:29. `slowdown.py` changed only its settings, in new revisions (see [API revisions](#api-revisions)).

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 04:18:48 | The starting-state check timed the request list on API revision `0000021` | [Request list](#the-apis-telemetry) |
| 04:19:09 | `Baseline` was created | [Test runs](#the-test-runs) |
| 04:22:00 to 04:24:03 | `Baseline`'s load | [Test runs](#the-test-runs) |
| 04:27:48 | `Baseline`'s verdict, Passed, was in | [Terminal](#the-terminal) |
| 04:29:33 | Azure Load Testing notified the function about `Baseline` | [Function log](#the-functions-log) |
| 04:29:47 | The function's report: accepted; no Issue open, so nothing posted | [Function log](#the-functions-log) |
| 04:33:23 | `slowdown.py on` created revision `0000022`, with 1,500 ms on the request list | [Revisions](#api-revisions) |
| 04:34:16 | `slowdown.py on` finished: `0000022` serves all traffic | [Terminal](#the-terminal) |
| 04:34:45 | `After the slowdown` was created | [Test runs](#the-test-runs) |
| 04:37:40 to 04:39:46 | `After the slowdown`'s load | [Test runs](#the-test-runs) |
| 04:42:34 | The neutral question to the Observability Agent | [Terminal](#the-terminal) |
| 04:44:53 | The first wording of the hypothesis question, which checked the wrong operation | [Terminal](#the-terminal) |
| 04:45:43 | Azure Load Testing notified the function about `After the slowdown` | [Function log](#the-functions-log) |
| 04:45:58 | The function opened Issue #215 | [Function log](#the-functions-log), [#215](https://github.com/melabadi/adept-assessment-northstars/issues/215) |
| 04:46:47 | The hypothesis question, with the operation named exactly | [Terminal](#the-terminal) |
| 04:48:37 | `slowdown.py off` created revision `0000023` | [Revisions](#api-revisions) |
| 04:49:32 to 04:49:35 | `slowdown.py off` timed the request list on `0000023` | [Request list](#the-apis-telemetry) |
| 04:49:44 | `After the fix` was created | [Test runs](#the-test-runs) |
| 04:52:50 to 04:54:50 | `After the fix`'s load | [Test runs](#the-test-runs) |
| 04:58:36 | `After the fix`'s verdict, Passed, was in | [Terminal](#the-terminal) |
| 05:00:17 | Azure Load Testing notified the function about `After the fix` | [Function log](#the-functions-log) |
| 05:00:28 | The function commented the passing report on Issue #215 | [#215](https://github.com/melabadi/adept-assessment-northstars/issues/215#issuecomment-6539313428) |
| 05:00:29 | and closed the Issue | [#215](https://github.com/melabadi/adept-assessment-northstars/issues/215) |

## The test runs

The three runs as Azure Load Testing recorded them. `startDateTime` and `endDateTime` are the window of the load; `p90Ms`, `p95Ms`, and `p99Ms` are the 90th, 95th, and 99th percentiles of response time.

| Run | Display name | Created | Load | Result | Requests | p90 | Errors | Criteria failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline-20261031-001902` | Baseline | 04:19:09 | 04:22:00 to 04:24:03 | PASSED | 590 | 29 ms | 0 % | none |
| `slowdown-20261031-003441` | After the slowdown | 04:34:45 | 04:37:40 to 04:39:46 | FAILED | 576 | 1,510 ms | 0 % | my-requests p95 1,580 ms > 1,000 ms; team-queue p95 1,570 ms > 1,000 ms |
| `fix-20261031-004936` | After the fix | 04:49:44 | 04:52:50 to 04:54:50 | PASSED | 580 | 86 ms | 0 % | none |

```powershell
$lt = azd env get-value LOAD_TEST_NAME
$fields = '{testRunId: testRunId, displayName: displayName, testId: testId, status: status, testResult: testResult, createdDateTime: createdDateTime, startDateTime: startDateTime, endDateTime: endDateTime, durationMs: duration, virtualUsers: virtualUsers, virtualUserHours: virtualUserHours, passFailCriteria: passFailCriteria.passFailMetrics.*.{request: requestName, aggregate: aggregate, metric: clientMetric, condition: condition, value: value, actualValue: actualValue, result: result}, statistics: testRunStatistics.*.{request: transaction, requests: sampleCount, errors: errorCount, errorPct: errorPct, medianMs: medianResTime, p90Ms: pct1ResTime, p95Ms: pct2ResTime, p99Ms: pct3ResTime, maxMs: maxResTime, perSecond: throughput}}'
'baseline-20261031-001902', 'slowdown-20261031-003441', 'fix-20261031-004936' | ForEach-Object {
  az load test-run show --load-test-resource $lt -g rg-ai-sdlc-test --test-run-id $_ --query $fields -o json | ConvertFrom-Json
} | ConvertTo-Json -Depth 6
```

```json
[
  {
    "createdDateTime": "2026-10-31T04:19:09.074Z",
    "displayName": "Baseline",
    "durationMs": 123000,
    "endDateTime": "2026-10-31T04:24:03Z",
    "passFailCriteria": [
      {
        "actualValue": 25.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "decide",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 39.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "submit",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 14.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "my-requests",
        "result": "passed",
        "value": 1000.0
      },
      {
        "actualValue": 22.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "team-queue",
        "result": "passed",
        "value": 1000.0
      },
      {
        "actualValue": 0.0,
        "aggregate": "percentage",
        "condition": ">",
        "metric": "error",
        "request": null,
        "result": "passed",
        "value": 1.0
      }
    ],
    "startDateTime": "2026-10-31T04:22:00Z",
    "statistics": [
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 40.0,
        "medianMs": 15.0,
        "p90Ms": 18.0,
        "p95Ms": 20.0,
        "p99Ms": 27.0,
        "perSecond": 1.6178861788617886,
        "request": "open-request",
        "requests": 199.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 51.0,
        "medianMs": 15.0,
        "p90Ms": 19.0,
        "p95Ms": 23.0,
        "p99Ms": 51.0,
        "perSecond": 0.16260162601626016,
        "request": "denied-other-department",
        "requests": 20.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 300.0,
        "medianMs": 29.0,
        "p90Ms": 37.0,
        "p95Ms": 39.0,
        "p99Ms": 115.0,
        "perSecond": 0.8130081300813008,
        "request": "submit",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 279.0,
        "medianMs": 5.0,
        "p90Ms": 6.0,
        "p95Ms": 6.0,
        "p99Ms": 279.0,
        "perSecond": 0.16260162601626016,
        "request": "denied-invalid-token",
        "requests": 20.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 35.0,
        "medianMs": 14.0,
        "p90Ms": 18.0,
        "p95Ms": 22.0,
        "p99Ms": 28.0,
        "perSecond": 0.8130081300813008,
        "request": "team-queue",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 28.0,
        "medianMs": 21.0,
        "p90Ms": 25.0,
        "p95Ms": 25.0,
        "p99Ms": 28.0,
        "perSecond": 0.4146341463414634,
        "request": "decide",
        "requests": 51.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 300.0,
        "medianMs": 15.0,
        "p90Ms": 29.0,
        "p95Ms": 31.0,
        "p99Ms": 50.0,
        "perSecond": 4.796747967479675,
        "request": "Total",
        "requests": 590.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 16.0,
        "medianMs": 11.0,
        "p90Ms": 13.0,
        "p95Ms": 14.0,
        "p99Ms": 16.0,
        "perSecond": 0.8130081300813008,
        "request": "my-requests",
        "requests": 100.0
      }
    ],
    "status": "DONE",
    "testId": "requesthub-journey",
    "testResult": "PASSED",
    "testRunId": "baseline-20261031-001902",
    "virtualUserHours": 1.67,
    "virtualUsers": 10
  },
  {
    "createdDateTime": "2026-10-31T04:34:45.447Z",
    "displayName": "After the slowdown",
    "durationMs": 126000,
    "endDateTime": "2026-10-31T04:39:46Z",
    "passFailCriteria": [
      {
        "actualValue": 106.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "decide",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 171.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "submit",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 1580.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "my-requests",
        "result": "failed",
        "value": 1000.0
      },
      {
        "actualValue": 1570.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "team-queue",
        "result": "failed",
        "value": 1000.0
      },
      {
        "actualValue": 0.0,
        "aggregate": "percentage",
        "condition": ">",
        "metric": "error",
        "request": null,
        "result": "passed",
        "value": 1.0
      }
    ],
    "startDateTime": "2026-10-31T04:37:40Z",
    "statistics": [
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1780.0,
        "medianMs": 1510.0,
        "p90Ms": 1570.0,
        "p95Ms": 1570.0,
        "p99Ms": 1780.0,
        "perSecond": 0.7857142857142857,
        "request": "team-queue",
        "requests": 99.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 290.0,
        "medianMs": 5.0,
        "p90Ms": 20.0,
        "p95Ms": 290.0,
        "p99Ms": 290.0,
        "perSecond": 0.15873015873015872,
        "request": "denied-invalid-token",
        "requests": 20.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1600.0,
        "medianMs": 1510.0,
        "p90Ms": 1530.0,
        "p95Ms": 1580.0,
        "p99Ms": 1600.0,
        "perSecond": 0.7857142857142857,
        "request": "my-requests",
        "requests": 99.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 190.0,
        "medianMs": 17.0,
        "p90Ms": 56.0,
        "p95Ms": 99.0,
        "p99Ms": 190.0,
        "perSecond": 1.5555555555555556,
        "request": "open-request",
        "requests": 196.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 310.0,
        "medianMs": 25.0,
        "p90Ms": 84.0,
        "p95Ms": 106.0,
        "p99Ms": 310.0,
        "perSecond": 0.3333333333333333,
        "request": "decide",
        "requests": 42.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1020.0,
        "medianMs": 33.0,
        "p90Ms": 90.0,
        "p95Ms": 171.0,
        "p99Ms": 270.0,
        "perSecond": 0.7936507936507936,
        "request": "submit",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1780.0,
        "medianMs": 33.0,
        "p90Ms": 1510.0,
        "p95Ms": 1530.0,
        "p99Ms": 1580.0,
        "perSecond": 4.571428571428571,
        "request": "Total",
        "requests": 576.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 99.0,
        "medianMs": 17.0,
        "p90Ms": 97.0,
        "p95Ms": 98.0,
        "p99Ms": 99.0,
        "perSecond": 0.15873015873015872,
        "request": "denied-other-department",
        "requests": 20.0
      }
    ],
    "status": "DONE",
    "testId": "requesthub-journey",
    "testResult": "FAILED",
    "testRunId": "slowdown-20261031-003441",
    "virtualUserHours": 1.67,
    "virtualUsers": 10
  },
  {
    "createdDateTime": "2026-10-31T04:49:44.823Z",
    "displayName": "After the fix",
    "durationMs": 120000,
    "endDateTime": "2026-10-31T04:54:50Z",
    "passFailCriteria": [
      {
        "actualValue": 130.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "decide",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 256.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "submit",
        "result": "passed",
        "value": 1500.0
      },
      {
        "actualValue": 74.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "my-requests",
        "result": "passed",
        "value": 1000.0
      },
      {
        "actualValue": 73.0,
        "aggregate": "p95",
        "condition": ">",
        "metric": "response_time_ms",
        "request": "team-queue",
        "result": "passed",
        "value": 1000.0
      },
      {
        "actualValue": 0.0,
        "aggregate": "percentage",
        "condition": ">",
        "metric": "error",
        "request": null,
        "result": "passed",
        "value": 1.0
      }
    ],
    "startDateTime": "2026-10-31T04:52:50Z",
    "statistics": [
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 102.0,
        "medianMs": 13.0,
        "p90Ms": 32.0,
        "p95Ms": 74.0,
        "p99Ms": 99.0,
        "perSecond": 0.8333333333333334,
        "request": "my-requests",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 289.0,
        "medianMs": 24.0,
        "p90Ms": 108.0,
        "p95Ms": 130.0,
        "p99Ms": 289.0,
        "perSecond": 0.35,
        "request": "decide",
        "requests": 42.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 103.0,
        "medianMs": 18.0,
        "p90Ms": 89.0,
        "p95Ms": 101.0,
        "p99Ms": 103.0,
        "perSecond": 0.16666666666666666,
        "request": "denied-other-department",
        "requests": 20.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 159.0,
        "medianMs": 14.0,
        "p90Ms": 69.0,
        "p95Ms": 73.0,
        "p99Ms": 114.0,
        "perSecond": 0.8333333333333334,
        "request": "team-queue",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 109.0,
        "medianMs": 18.0,
        "p90Ms": 86.0,
        "p95Ms": 94.0,
        "p99Ms": 105.0,
        "perSecond": 1.65,
        "request": "open-request",
        "requests": 198.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1500.0,
        "medianMs": 34.0,
        "p90Ms": 160.0,
        "p95Ms": 256.0,
        "p99Ms": 660.0,
        "perSecond": 0.8333333333333334,
        "request": "submit",
        "requests": 100.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 1500.0,
        "medianMs": 18.0,
        "p90Ms": 86.0,
        "p95Ms": 99.0,
        "p99Ms": 258.0,
        "perSecond": 4.833333333333333,
        "request": "Total",
        "requests": 580.0
      },
      {
        "errorPct": 0.0,
        "errors": 0.0,
        "maxMs": 187.0,
        "medianMs": 6.0,
        "p90Ms": 9.0,
        "p95Ms": 187.0,
        "p99Ms": 187.0,
        "perSecond": 0.16666666666666666,
        "request": "denied-invalid-token",
        "requests": 20.0
      }
    ],
    "status": "DONE",
    "testId": "requesthub-journey",
    "testResult": "PASSED",
    "testRunId": "fix-20261031-004936",
    "virtualUserHours": 1.67,
    "virtualUsers": 10
  }
]
```

## The function's log

What the reporting function logged for each notification: the HTTP route's answer to Azure Load Testing's action group, the queued step, and the function's own messages. At 04:32:58, a test call with a made-up run id was refused, as every unknown run is.

```powershell
$appi = (azd env get-value FUNCTION_APP_NAME) -replace '^func-', 'appi-'
$kql = "union requests, traces | where timestamp between (datetime(2026-10-31T04:19:00Z) .. datetime(2026-10-31T05:01:00Z)) | where (itemType == 'request' and name in ('test_run_ended', 'report_run')) or (itemType == 'trace' and operation_Name in ('test_run_ended', 'report_run') and (message startswith 'Accepted' or message startswith 'Refused' or message has 'verdict' or message has 'Issue')) | project timestamp, ['function'] = coalesce(name, operation_Name), event = iff(itemType == 'request', strcat(iff(name == 'report_run', strcat('queue step ', iff(tostring(success) =~ 'true', 'succeeded', 'failed')), strcat('answered HTTP ', resultCode)), ' in ', tolong(duration), ' ms'), message) | order by timestamp asc"
az monitor app-insights query --app $appi -g rg-ai-sdlc-test --offset 30d --analytics-query $kql
```

| timestamp | function | event |
| --- | --- | --- |
| 2026-10-31T04:29:33.393Z | test_run_ended | answered HTTP 202 in 1192 ms |
| 2026-10-31T04:29:34.582Z | test_run_ended | Accepted Baseline (baseline-20261031-001902, ended 2026-10-31T04:24:03Z): queued for its report. |
| 2026-10-31T04:29:44.854Z | report_run | queue step succeeded in 2997 ms |
| 2026-10-31T04:29:47.284Z | report_run | Baseline: PASSED, verdict accepted (450 server requests, 0 with the injected delay). |
| 2026-10-31T04:29:47.836Z | report_run | Baseline: no change on GitHub: no Issue is open for this test. |
| 2026-10-31T04:32:58.614Z | test_run_ended | answered HTTP 404 in 693 ms |
| 2026-10-31T04:32:59.305Z | test_run_ended | Refused a notification (404): Azure Load Testing has no run with that id. |
| 2026-10-31T04:45:43.765Z | test_run_ended | answered HTTP 202 in 1115 ms |
| 2026-10-31T04:45:44.878Z | test_run_ended | Accepted After the slowdown (slowdown-20261031-003441, ended 2026-10-31T04:39:46Z): queued for its report. |
| 2026-10-31T04:45:55.637Z | report_run | queue step succeeded in 3115 ms |
| 2026-10-31T04:45:57.076Z | report_run | After the slowdown: FAILED, verdict expected-failure (468 server requests, 150 with the injected delay). |
| 2026-10-31T04:45:58.740Z | report_run | After the slowdown: opened Issue #215 (no Issue is open for this test). |
| 2026-10-31T05:00:17.805Z | test_run_ended | answered HTTP 202 in 1416 ms |
| 2026-10-31T05:00:19.218Z | test_run_ended | Accepted After the fix (fix-20261031-004936, ended 2026-10-31T04:54:50Z): queued for its report. |
| 2026-10-31T05:00:26.276Z | report_run | queue step succeeded in 3744 ms |
| 2026-10-31T05:00:27.342Z | report_run | After the fix: PASSED, verdict accepted (447 server requests, 0 with the injected delay). |
| 2026-10-31T05:00:30.008Z | report_run | After the fix: closed Issue #215 (the run passed and the report accepts it). |

## API revisions

The revisions that `slowdown.py` created: `on` rolled out `0000022` with the slowdown, and `off` rolled out `0000023` without it.

```powershell
az containerapp revision list -g rg-ai-sdlc-test -n (azd env get-value API_APP_NAME) --all `
  --query "[?ends_with(name, '0000022') || ends_with(name, '0000023')].[name, properties.createdTime]" -o tsv |
  ForEach-Object { $_ -replace '^\S*--', '' }
```

```text
0000022	2026-10-31T04:33:23+00:00
0000023	2026-10-31T04:48:37+00:00
```

## The API's telemetry

The API's own telemetry in Application Insights. The first three queries are about `GET /api/requests`, the request list that the slowdown delayed: the first two ask what the Observability Agent was asked, over the same 30 minutes, and every number matches the agent's answers in step 7; the third shows where each request came from. The fourth lists the server requests that failed during `After the slowdown`. Run each with:

```powershell
az monitor app-insights query --app (azd env get-value APPLICATIONINSIGHTS_NAME) -g rg-ai-sdlc-test --offset 30d --analytics-query $kql
```

**The neutral question** (asked at 04:42:34, so the 30 minutes from 04:12:34): the agent answered 326 requests, none failed, 725 ms on average, 1.51 seconds at the 95th percentile and 1.56 at the 99th, 155 over 1 second, 1 over 2 seconds, and the slowest at 2.41 seconds.

```kusto
requests | where timestamp between (datetime(2026-10-31T04:12:34Z) .. datetime(2026-10-31T04:42:34Z)) | where name == 'GET /api/requests' | summarize requests = sum(itemCount), failed = sumif(itemCount, success == false), avg_ms = round(avg(duration), 0), p95_ms = round(percentile(duration, 95), 0), p99_ms = round(percentile(duration, 99), 0), over_1s = sumif(itemCount, duration > 1000), over_2s = sumif(itemCount, duration > 2000), slowest_ms = round(max(duration), 0)
```

| requests | failed | avg_ms | p95_ms | p99_ms | over_1s | over_2s | slowest_ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 326 | 0 | 725 | 1515 | 1563 | 155 | 1 | 2415 |

**The hypothesis question** (asked at 04:46:47, so the 30 minutes from 04:16:47): the agent answered 155 requests with `requesthub.fault.queue_delay_ms`, averaging 1,518.1 ms with a 1,508.7 ms median and a 1,528.4 ms 95th percentile, and 171 without it, averaging 6.9 ms with a 6.5 ms median and a 9.9 ms 95th percentile.

```kusto
requests | where timestamp between (datetime(2026-10-31T04:16:47Z) .. datetime(2026-10-31T04:46:47Z)) | where name == 'GET /api/requests' | extend delayed = isnotempty(tostring(customDimensions['requesthub.fault.queue_delay_ms'])) | summarize requests = sum(itemCount), avg_ms = round(avg(duration), 1), p50_ms = round(percentile(duration, 50), 1), p95_ms = round(percentile(duration, 95), 1) by delayed | order by delayed desc
```

| delayed | requests | avg_ms | p50_ms | p95_ms |
| --- | --- | --- | --- | --- |
| True | 155 | 1518.1 | 1508.7 | 1528.4 |
| False | 171 | 6.9 | 6.5 | 9.9 |

**Where the requests came from**, by the windows in the [timeline](#timeline). The 171 without the property are the starting-state check's 4 timing calls and the `Baseline`'s 167. The 155 with it are `slowdown.py on`'s 4, the 150 that the report counted in `After the slowdown`'s window, and 1 that started less than a second after that window ended.

```kusto
requests | where timestamp between (datetime(2026-10-31T04:12:34Z) .. datetime(2026-10-31T04:52:50Z)) | where name == 'GET /api/requests' | extend delayed = isnotempty(tostring(customDimensions['requesthub.fault.queue_delay_ms'])) | extend phase = case(timestamp < datetime(2026-10-31T04:19:09Z), '1 starting-state check', timestamp between (datetime(2026-10-31T04:22:00Z) .. datetime(2026-10-31T04:24:03Z)), '2 Baseline', timestamp between (datetime(2026-10-31T04:33:00Z) .. datetime(2026-10-31T04:34:17Z)), '3 slowdown.py on', timestamp between (datetime(2026-10-31T04:37:40Z) .. datetime(2026-10-31T04:39:46Z)), '4 After the slowdown', timestamp between (datetime(2026-10-31T04:39:46Z) .. datetime(2026-10-31T04:46:47Z)), '5 after that run ended', timestamp between (datetime(2026-10-31T04:48:37Z) .. datetime(2026-10-31T04:49:44Z)), '6 slowdown.py off', 'other') | summarize requests = sum(itemCount), first_seen = min(timestamp), last_seen = max(timestamp) by phase, delayed | order by phase asc
```

| phase | delayed | requests | first_seen | last_seen |
| --- | --- | --- | --- | --- |
| 1 starting-state check | False | 4 | 2026-10-31T04:18:48.078Z | 2026-10-31T04:18:48.726Z |
| 2 Baseline | False | 167 | 2026-10-31T04:22:05.125Z | 2026-10-31T04:24:02.993Z |
| 3 slowdown.py on | True | 4 | 2026-10-31T04:34:08.063Z | 2026-10-31T04:34:14.207Z |
| 4 After the slowdown | True | 150 | 2026-10-31T04:37:48.638Z | 2026-10-31T04:39:45.377Z |
| 5 after that run ended | True | 1 | 2026-10-31T04:39:46.379Z | 2026-10-31T04:39:46.379Z |
| 6 slowdown.py off | False | 4 | 2026-10-31T04:49:32.531Z | 2026-10-31T04:49:34.969Z |

**The failed server requests** during `After the slowdown`'s load: all 10 were the journey's deliberate checks that a requester can't open another department's request (403). The checks with an invalid token get 401 from Container Apps authentication, before they reach the API.

```kusto
requests | where timestamp between (datetime(2026-10-31T04:37:40Z) .. datetime(2026-10-31T04:39:46Z)) | where toint(resultCode) >= 400 | summarize requests = sum(itemCount) by name, resultCode
```

| name | resultCode | requests |
| --- | --- | --- |
| GET /api/requests/{id} | 403 | 10 |

## The terminal

Times that the terminal session running the steps printed, in UTC. It polled the runs every 15 to 20 seconds, so a status or verdict was in up to that long before the time shown.

```text
04:19:10  run baseline-20261031-001902 started
04:22:17  EXECUTING
04:27:48  DONE PASSED
04:34:16  python slowdown.py on finished, 1 min 9.6 s after it started (output below)
04:34:47  run slowdown-20261031-003441 started
04:42:03  DONE
04:42:34  Observability Agent: the neutral question asked; answer captured at 04:44:29
04:44:53  Observability Agent: the hypothesis question, first wording, asked; answer captured at 04:45:53
04:46:47  Observability Agent: the hypothesis question, operation named exactly, asked; answer captured at 04:48:01
04:49:46  run fix-20261031-004936 started, right after python slowdown.py off (output below)
04:58:36  verdict PASSED
05:00:43  issue 215: CLOSED
```

The starting-state check, `slowdown.py on`, and `slowdown.py off`, as the screenshots of See it work's starting state, step 4, and step 8 show them:

```text
PS> azd env select ai-sdlc-test
PS> $pg = az postgres flexible-server list -g rg-ai-sdlc-test --query "[0].name" -o tsv
PS> az postgres flexible-server show -g rg-ai-sdlc-test -n $pg --query state -o tsv
Ready
PS> python slowdown.py status
API revision 0000021: no slowdown configured.
GET /api/requests now takes 215 ms (median of 3 calls).
PS> gh issue list --label load-test --state open --json number --jq length
0
PS> $lt = azd env get-value LOAD_TEST_NAME
PS> az load trigger schedule show --load-test-resource $lt -g rg-ai-sdlc-test --trigger-id weekday-evenings --query state -o tsv
WARNING: Command group 'load trigger schedule' is in preview and under development. Reference and support levels: https://aka.ms/CLI_refstatus
Paused

PS> python slowdown.py on
Injecting 1500 ms on the request list, expiring at 2026-10-31T05:03:12+00:00 ...
Waiting for API revision 0000022 to become ready and take all traffic ...
Deactivated the previous API revision 0000021.
API revision 0000022: 1500 ms on the request list until 2026-10-31T05:03:12Z (29 min left).
GET /api/requests now takes 1,727 ms (median of 3 calls).

PS> python slowdown.py off
Removing the slowdown ...
Waiting for API revision 0000023 to become ready and take all traffic ...
Deactivated the previous API revision 0000022.
API revision 0000023: no slowdown configured.
GET /api/requests now takes 296 ms (median of 3 calls).
```
