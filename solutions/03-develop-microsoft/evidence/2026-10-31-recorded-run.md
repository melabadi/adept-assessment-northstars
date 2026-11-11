# Evidence: the recorded run of 31 October 2026

What Azure and GitHub recorded during steps 1 to 6 of [the run in See it work](../README.md#see-it-work), exported so that anyone can check it without signing in to Azure. Times are UTC, all on 31 October 2026.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-develop`, with the commands shown in each section, run in PowerShell 7 from `solutions/03-develop-microsoft` after `azd env select ai-sdlc-develop`. The exports keep only the fields that each command names: times, function names, result codes, durations, the Function's own log lines, and token counts. None of them identifies the tenant.
- **Kept here because telemetry expires:** Application Insights keeps 30 days of data, so the queries return nothing after 30 November 2026. The tables keep their results.
- **On GitHub**, pull request [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) holds both commits, both reviews ([the first](https://github.com/melabadi/adept-assessment-northstars/pull/212#pullrequestreview-5721199287) and [the second](https://github.com/melabadi/adept-assessment-northstars/pull/212#pullrequestreview-5721247811)), and [the closing comment](https://github.com/melabadi/adept-assessment-northstars/pull/212#issuecomment-6539558976). GitHub keeps only a webhook's recent deliveries, and this run's are gone; [the Function's requests](#the-functions-requests) show how the Function answered them.

## The code that ran

- **The Function:** an early version of pull request [#227](https://github.com/melabadi/adept-assessment-northstars/pull/227), deployed at 04:10, before that pull request's first commit. Its review steps are those of that commit, [4e0cd62](https://github.com/melabadi/adept-assessment-northstars/commit/4e0cd62). Two parts of #227 came after this run: the GitHub token and the webhook secret moved from app settings to Key Vault ([cf2d6d1](https://github.com/melabadi/adept-assessment-northstars/commit/cf2d6d1)), and the queue settings in `function/host.json` changed. Neither changes what this run shows. #227 merged the same day as [1e74ae8](https://github.com/melabadi/adept-assessment-northstars/commit/a0fabea).
- **The rule checker and the review's formatter** ([`sandbox/`](../sandbox/)), which the Function reads from `main` at every review: `main` was [276ee2d](https://github.com/melabadi/adept-assessment-northstars/commit/b50abba) (pull request [#205](https://github.com/melabadi/adept-assessment-northstars/pull/205)) throughout the run.
- **The agent:** `requesthub-pr-reviewer` version 4, on `gpt-5.4-mini`, published on 30 October from [`reviewer-agent.yaml`](../reviewer-agent.yaml).
- **The change under review:** branch `demo/fast-track` from 276ee2d, with [`demo/fast-track.patch`](../demo/fast-track.patch) as commit [4f351a5](https://github.com/melabadi/adept-assessment-northstars/commit/4f351a5), then [`demo/keep-the-guard.patch`](../demo/keep-the-guard.patch) as commit [bd49ff7](https://github.com/melabadi/adept-assessment-northstars/commit/bd49ff7).

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 04:18:08 | Commit 4f351a5: approvers may approve their own low-priority requests | [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) |
| 04:18:13 | Pull request #212 opened | [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) |
| 04:18:16 | The `opened` event reached the Function, which ignored it: the pull request had no label yet | [Requests](#the-functions-requests) |
| 04:18:23 | The `review:azure` label added | [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) |
| 04:18:27 | The `labeled` event reached the Function, which queued review `a50187b57774` and answered 202 | [Requests](#the-functions-requests), [log](#the-functions-log) |
| 04:18:34 | The rule checker's verdicts: 1 of 5 rules failed. Only then did the build start | [Log](#the-functions-log) |
| 04:20:35 | Build and tests done: API 67 of 67, web 14 of 14 | [Log](#the-functions-log) |
| 04:20:36 to 04:20:41 | The agent's answer | [Agent](#the-agents-traces), [log](#the-functions-log) |
| 04:20:43 | The first review, a COMMENT on 4f351a5 | [Review](https://github.com/melabadi/adept-assessment-northstars/pull/212#pullrequestreview-5721199287) |
| 04:28:22 | Commit bd49ff7: keep the guard and pin it with a test | [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) |
| 04:28:28 | The `synchronize` event reached the Function, which queued review `d115e71e51b1` and answered 202 | [Requests](#the-functions-requests), [log](#the-functions-log) |
| 04:28:38 | The rule checker's verdicts: all 5 rules passed | [Log](#the-functions-log) |
| 04:30:39 | Build and tests done: API 68 of 68, web 14 of 14 | [Log](#the-functions-log) |
| 04:30:40 to 04:30:51 | The agent's answer, with one command in the sandbox | [Agent](#the-agents-traces), [log](#the-functions-log) |
| 04:30:52 | The second review, a COMMENT on bd49ff7 | [Review](https://github.com/melabadi/adept-assessment-northstars/pull/212#pullrequestreview-5721247811) |
| 05:27:43 | Comment: "Demo finished; closing without merging." | [Comment](https://github.com/melabadi/adept-assessment-northstars/pull/212#issuecomment-6539558976) |
| 05:27:44 | Pull request #212 closed without merging; its branch deleted at 05:27:46 | [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) |

## The Function's requests

Every call to the Function's two functions during the run: `github_webhook`, which GitHub's webhook calls, and `review`, which takes one review from the queue. A queue trigger has no HTTP status, so its result is `0`. Durations are in milliseconds, as the Functions host measured them.

```powershell
$appi = azd env get-value APPLICATIONINSIGHTS_NAME
$kql = "requests | where timestamp between (datetime(2026-10-31T04:18:00Z) .. datetime(2026-10-31T04:31:00Z)) | where name in ('github_webhook', 'review') | order by timestamp asc | project utc = format_datetime(timestamp, 'HH:mm:ss.fff'), ['function'] = name, result = resultCode, duration_ms = tolong(duration)"
(az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
```

| UTC | function | result | duration_ms | What it was |
| --- | --- | --- | --- | --- |
| 04:18:16.094 | github_webhook | 200 | 8 | `opened`: ignored, no label yet |
| 04:18:27.188 | github_webhook | 202 | 1502 | `labeled`: review `a50187b57774` queued |
| 04:18:28.889 | review | 0 | 134986 | review `a50187b57774` |
| 04:28:28.545 | github_webhook | 202 | 1078 | `synchronize`: review `d115e71e51b1` queued |
| 04:28:32.778 | review | 0 | 139854 | review `d115e71e51b1` |

## The Function's log

The Function logs one line per step of a review, starting with the review's id. Each review's footer on GitHub names the same id.

```powershell
$kql = "traces | where timestamp between (datetime(2026-10-31T04:18:00Z) .. datetime(2026-10-31T04:31:00Z)) | where message startswith 'review ' | order by timestamp asc | project utc = format_datetime(timestamp, 'HH:mm:ss.fff'), message"
(az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
```

| UTC | message |
| --- | --- |
| 04:18:27.832 | review a50187b57774: #212 queued (pull_request.labeled) |
| 04:18:29.188 | review a50187b57774: #212 at 4f351a5 |
| 04:18:34.092 | review a50187b57774: the rule checker from main read both trees in the judge's session in 2 s: 1 of 5 rules failed |
| 04:18:34.811 | review a50187b57774: the pull request's code runs only now, in its own session: build and tests started |
| 04:20:35.475 | review a50187b57774: build and tests: API 67 of 67 passed, web 14 of 14 passed in 1 min 50 s |
| 04:20:41.888 | review a50187b57774: agent requesthub-pr-reviewer v4 answered in 6 s (completed, 0 sandbox commands) |
| 04:20:43.444 | review a50187b57774: posted a COMMENT review on 4f351a5 |
| 04:20:43.875 | review a50187b57774: done in 2 min 15 s; sessions deleted |
| 04:28:29.082 | review d115e71e51b1: #212 queued (pull_request.synchronize) |
| 04:28:33.103 | review d115e71e51b1: #212 at bd49ff7 |
| 04:28:38.112 | review d115e71e51b1: the rule checker from main read both trees in the judge's session in 2 s: all 5 rules passed |
| 04:28:38.582 | review d115e71e51b1: the pull request's code runs only now, in its own session: build and tests started |
| 04:30:39.097 | review d115e71e51b1: build and tests: API 68 of 68 passed, web 14 of 14 passed in 1 min 49 s |
| 04:30:51.014 | review d115e71e51b1: agent requesthub-pr-reviewer v4 answered in 12 s (completed, 1 sandbox command) |
| 04:30:52.274 | review d115e71e51b1: posted a COMMENT review on bd49ff7 |
| 04:30:52.630 | review d115e71e51b1: done in 2 min 20 s; sessions deleted |

## The agent's traces

Foundry traces every answer of the agent to the same Application Insights resource: `invoke_agent` is the whole answer, `chat` a call to the model with its tokens, and `execute_tool` a command the agent ran in the sandbox. The agent's **Traces** tab in the Foundry portal shows the same answers ([step 5's screenshot](../README.md#5-foundry-kept-the-agents-definition-and-traces)), with Foundry's estimate of their cost: about $0.002 and $0.003. An `invoke_agent` span times the agent's run itself; [the Function's log](#the-functions-log) says 6 and 12 seconds for the same answers, because it counts from its request to the answer it polled for, and it polls every 5 seconds.

```powershell
$kql = "dependencies | where timestamp between (datetime(2026-10-31T04:18:00Z) .. datetime(2026-10-31T04:31:00Z)) | where name startswith 'invoke_agent' or name startswith 'chat ' or name startswith 'execute_tool' | order by timestamp asc | project utc = format_datetime(timestamp, 'HH:mm:ss.fff'), span = name, duration_ms = tolong(duration), tokens_in = tolong(customDimensions['gen_ai.usage.input_tokens']), tokens_out = tolong(customDimensions['gen_ai.usage.output_tokens'])"
(az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
```

| UTC | span | duration_ms | tokens_in | tokens_out |
| --- | --- | --- | --- | --- |
| 04:20:36.576 | invoke_agent requesthub-pr-reviewer:4 | 4244 | | |
| 04:20:37.714 | chat gpt-5.4-mini-2026-03-17 | 2799 | 2373 | 494 |
| 04:30:40.803 | invoke_agent requesthub-pr-reviewer:4 | 6885 | | |
| 04:30:42.678 | execute_tool remote_openapi.sandbox_runInSandbox | 209 | | |
| 04:30:45.944 | chat gpt-5.4-mini-2026-03-17 | 1567 | 2881 | 623 |
