# Evidence: the evaluation of 11 November 2026, after the move to gpt-6-luna

What Azure recorded when [`eval_reviewer.py`](../eval_reviewer.py) measured the reviewer after its agent moved from `gpt-5.4-mini` to `gpt-6-luna`, exported so that anyone can check it without signing in to Azure. It is the evaluation of [See it work, step 7](../README.md#7-an-evaluation-measured-the-reviewer): the same ten labelled cases, the same five checks, and the same closed pull requests, [#268](https://github.com/melabadi/adept-assessment-northstars/pull/268) to [#277](https://github.com/melabadi/adept-assessment-northstars/pull/277), which `python eval_reviewer.py --setup` reused. Times are UTC, all on 11 November 2026.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-develop`, with the commands shown in each section, run in PowerShell 7 from `solutions/03-develop-microsoft` after `azd env select ai-sdlc-develop`. The exports keep only the fields that each command names: times, pull request numbers, review ids, the Function's own log lines, pass counts, and token counts. None of them identifies the tenant.
- **Kept here because telemetry expires:** Application Insights keeps 30 days of data, and the Responses API keeps each response for [30 days by default](https://learn.microsoft.com/azure/foundry/openai/how-to/responses#delete-a-response), so the queries below return nothing after 11 December 2026, and nothing for 10 November after 10 December. Foundry keeps its evaluation runs until someone deletes them or the project.
- **The local scores** are quoted from the terminal.

## What changed, and the code that ran

- **The model:** `gpt-6-luna`, version 2026-09-22, GlobalStandard at 150K tokens per minute, from [`infra/main.bicep`](../infra/main.bicep). `azd provision` ran from 14:21:37 to 14:24:07 and created the deployment at 14:23:44, next to `gpt-5.4-mini`. Its postprovision hook published `requesthub-pr-reviewer` version 5 on it at 14:24:05, with the instructions unchanged.
- **The packages:** azure-ai-projects 2.10.0, azure-identity 1.27.0, and openai 3.45.0 in [`requirements.txt`](../requirements.txt); azure-functions 1.26.0 and azure-identity 1.27.0 in [`function/requirements.txt`](../function/requirements.txt).
- **The Function:** deployed from 15:51:27 to 15:52:11 (azd reported 24 seconds) from `main` at [33cda15](https://github.com/melabadi/adept-assessment-northstars/commit/33cda15) with the changes above. The postdeploy hook, run again at 15:52:18, found the label in place, GitHub accepting the token, and the Function refusing unsigned deliveries, and updated the webhook.
- **The sandbox, the rule checker, and the review's formatter:** read by the Function from `main` at 33cda15, as at every review: since pull request [#366](https://github.com/melabadi/adept-assessment-northstars/pull/366), PostgreSQL comes from Maven Central, and since [#330](https://github.com/melabadi/adept-assessment-northstars/pull/330), the sandbox installs Node 26.
- **The evaluation:** `eval_reviewer.py` from this change, which reuses a Foundry evaluation only when its criteria name the current model deployment. The checks in [`review_graders.py`](../review_graders.py) and the cases in [`eval_cases.jsonl`](../eval_cases.jsonl) are unchanged since 10 November.

A first attempt, at 14:28, ran on the sandbox script from before #366 and was stopped when Ubuntu's package archive couldn't be resolved: [the sandbox's setup on 11 November](2026-11-11-sandbox-setup.md).

## The dry runs

The Function's log for each dry run, as in [the evaluation of 10 November](2026-11-10-evaluation.md#the-dry-runs): the same review as for a labelled pull request, with nothing posted.

```powershell
$appi = azd env get-value APPLICATIONINSIGHTS_NAME
foreach ($w in @(@('2026-11-11T15:53:00Z', '2026-11-11T16:01:00Z'), @('2026-11-11T16:04:00Z', '2026-11-11T16:12:00Z'))) {
  $kql = "traces | where timestamp between (datetime($($w[0])) .. datetime($($w[1]))) | where message startswith 'review ' | extend id = extract('^review ([0-9a-f]+):', 1, message), step = extract('^review [0-9a-f]+: (.*)', 1, message) | summarize queued = format_datetime(min(timestamp), 'HH:mm:ss'), pr = take_anyif(extract('dry run of #([0-9]+) queued', 1, step), step has 'queued'), rules = take_anyif(extract('in [0-9]+ s: (.*)', 1, step), step has 'rule checker'), tests = take_anyif(extract('build and tests: (.*)', 1, step), step startswith 'build and tests:'), agent = take_anyif(extract('answered in (.*)', 1, step), step has 'answered in'), done = take_anyif(extract('done in (.*); sessions', 1, step), step startswith 'done in'), finished = format_datetime(max(timestamp), 'HH:mm:ss') by id | order by pr asc"
  "== $($w[0]) .. $($w[1])"
  (az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
}
```

### The first run: agent version 5

`python eval_reviewer.py` ran from 15:53:06 to 16:02:03. Four dry runs at a time, as on 10 November; the last one ended at 15:59:42.

| Case (kind) | Pull request | Review | Queued | Rules | Build and tests | Agent answered in | Done in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| confirm-routing (known-good) | #268 | `af42b37a00ba` | 15:53:18 | all 5 rules passed | API 63 of 63 passed, web 15 of 15 passed in 1 min 33 s | 11 s (completed, 1 sandbox command) | 1 min 57 s |
| first-decision-wins (flagged) | #269 | `766a401c0a4d` | 15:53:21 | 1 of 5 rules failed | API 58 of 58 passed, web 14 of 14 passed in 1 min 30 s | 19 s (completed, 4 sandbox commands) | 2 min 04 s |
| admins-decide (known-bad) | #270 | `630ed9c16254` | 15:53:19 | 2 of 5 rules failed | API 50 of 50 passed, web 14 of 14 passed in 1 min 35 s | 17 s (completed, 2 sandbox commands) | 2 min 02 s |
| literal-wildcards (known-good) | #271 | `f5f7690b9e36` | 15:53:20 | all 5 rules passed | API 52 of 52 passed, web 14 of 14 passed in 1 min 20 s | 12 s (completed, 2 sandbox commands) | 1 min 57 s |
| load-test-cleanup (flagged) | #272 | `40710ec0765d` | 15:55:25 | 1 of 5 rules failed | API 60 of 60 passed, web 14 of 14 passed in 1 min 27 s | 19 s (completed, 3 sandbox commands) | 2 min 04 s |
| sql-concatenation (known-bad) | #273 | `67b0c7c8fed0` | 15:55:27 | 1 of 5 rules failed | API 1 of 60 failed, web 14 of 14 passed in 1 min 30 s | 16 s (completed, 2 sandbox commands) | 2 min 01 s |
| parameterized-search (known-good) | #274 | `759428e84f71` | 15:55:40 | all 5 rules passed | API 70 of 70 passed, web 14 of 14 passed in 1 min 41 s | 12 s (completed, 4 sandbox commands) | 2 min 17 s |
| delivery-timeout (known-good) | #275 | `8b2336094116` | 15:55:40 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 1 min 28 s | 11 s (completed, 2 sandbox commands) | 1 min 57 s |
| token-reuse (known-good) | #276 | `e1160a1ed052` | 15:57:30 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 1 min 40 s | 17 s (completed, 2 sandbox commands) | 2 min 03 s |
| index-no-cache (known-good) | #277 | `d5624704c59e` | 15:57:44 | all 5 rules passed | API 67 of 67 passed, web 14 of 14 passed in 1 min 36 s | 11 s (completed, 2 sandbox commands) | 1 min 58 s |

The rule verdicts and the test counts are those of 10 November. The local scores, from the terminal:

```text
Case                  PR    Kind        rule_verdicts  verdicts_verbatim  advisory_only  useful_commentary  sandbox_ran  Dry run
sql-concatenation     #273  known-bad   pass           pass               pass           FAIL 0.50          pass         Succeeded
Passed                                  10/10          10/10              10/10          9/10               10/10
```

The nine other rows passed every check. The script exited with code 1, and Foundry graded the same: `useful_commentary` 9 of 10 ([the Foundry runs](#the-foundry-runs)).

**Why it failed.** On a known-bad case, `useful_commentary` gives half of a finding's credit for a concern that states the problem, in the words its labels accept, and half for pointing at the right file. Version 5's only concern on #273 pointed at the right file, `RequestWorkflow.cs`, line 47, but didn't state the problem:

> The search term is concatenated into `FromSqlRaw` instead of being passed as a parameter. A caller can supply SQL syntax through the search input; use parameterized SQL or EF query APIs.

Its summary said "This creates a SQL-injection risk", but the check reads the problem only in a concern, so the case scored 0.50, which fails. On 10 November, version 4 on `gpt-5.4-mini` passed this check on every case.

### One sentence added to the instructions: agent version 6

At 16:03:45, `python publish_reviewer_agent.py` published version 6, on the same model, from [`reviewer-agent.yaml`](../reviewer-agent.yaml) with one sentence added after the list of severities:

> Each observation must stand on its own: name the problem itself, as a reviewer would name it, then give the evidence. Don't leave that name to the summary.

No check, case, or label changed.

### The second run: agent version 6

`python eval_reviewer.py` ran from 16:04:02 to 16:12:47, 8 minutes 45 seconds; the last dry run ended at 16:10:32.

| Case (kind) | Pull request | Review | Queued | Rules | Build and tests | Agent answered in | Done in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| confirm-routing (known-good) | #268 | `3520f525238e` | 16:04:17 | all 5 rules passed | API 63 of 63 passed, web 15 of 15 passed in 1 min 27 s | 17 s (completed, 2 sandbox commands) | 2 min 03 s |
| first-decision-wins (flagged) | #269 | `371a7d6e6084` | 16:04:18 | 1 of 5 rules failed | API 58 of 58 passed, web 14 of 14 passed in 1 min 28 s | 17 s (completed, 4 sandbox commands) | 2 min 03 s |
| admins-decide (known-bad) | #270 | `d6dc3c4570fb` | 16:04:17 | 2 of 5 rules failed | API 50 of 50 passed, web 14 of 14 passed in 1 min 35 s | 12 s (completed, 1 sandbox command) | 1 min 57 s |
| literal-wildcards (known-good) | #271 | `80855a547c5d` | 16:04:17 | all 5 rules passed | API 52 of 52 passed, web 14 of 14 passed in 1 min 30 s | 12 s (completed, 3 sandbox commands) | 1 min 58 s |
| load-test-cleanup (flagged) | #272 | `d19ff61d0eed` | 16:06:25 | 1 of 5 rules failed | API 60 of 60 passed, web 14 of 14 passed in 1 min 31 s | 6 s (completed, 0 sandbox commands) | 1 min 51 s |
| sql-concatenation (known-bad) | #273 | `f2b01f51f8e1` | 16:06:26 | 1 of 5 rules failed | API 1 of 60 failed, web 14 of 14 passed in 1 min 28 s | 11 s (completed, 2 sandbox commands) | 1 min 56 s |
| parameterized-search (known-good) | #274 | `5251262744c2` | 16:06:36 | all 5 rules passed | API 70 of 70 passed, web 14 of 14 passed in 1 min 33 s | 22 s (completed, 2 sandbox commands) | 2 min 07 s |
| delivery-timeout (known-good) | #275 | `3bcb9453776a` | 16:06:37 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 1 min 28 s | 22 s (completed, 5 sandbox commands) | 2 min 07 s |
| token-reuse (known-good) | #276 | `96adccefc564` | 16:08:27 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 1 min 29 s | 16 s (completed, 1 sandbox command) | 2 min 02 s |
| index-no-cache (known-good) | #277 | `9bab471d800e` | 16:08:29 | all 5 rules passed | API 67 of 67 passed, web 14 of 14 passed in 1 min 40 s | 16 s (completed, 3 sandbox commands) | 2 min 03 s |

Every check passed on every case, locally and in Foundry:

```text
Passed                                  10/10          10/10              10/10          10/10              10/10
```

Version 6's concern on #273, at the same line: "Search terms are concatenated directly into `FromSqlRaw`; crafted input can alter the SQL and expose or affect requests beyond the intended search. Use parameterized SQL or the existing EF query." On every case, version 6 raised as many concerns as version 5: none on the six known-good cases.

On #274, the agent's first run failed in Foundry: its trace ends with HTTP 500 after 5.5 seconds and 4 sandbox commands. The Function asks the agent once more when an answer doesn't complete, and the second run, at 16:08:34, completed with 2 sandbox commands. The 22 seconds in the log include both runs.

### Three more runs of the case that had failed

From 16:13:12 to 16:20:28, `python eval_reviewer.py --cases sql-concatenation --local` ran three more times, scored on this machine only. Version 6 passed every check each time. Its concerns:

1. "Search term is concatenated directly into `FromSqlRaw`; crafted input can alter the SQL and potentially bypass search constraints. …"
2. "Search input is concatenated directly into `FromSqlRaw`. A term containing SQL syntax can alter the query, potentially bypassing intended search and scope filtering; …"
3. "Search-term SQL injection: `term` is interpolated by string concatenation into `FromSqlRaw`, so crafted input can alter the SQL. …"

## The sandbox

In all twenty dry runs, every setup step succeeded: Node 26 in 5 to 6 seconds, the .NET 10 SDK in 8 to 11, and PostgreSQL 16 from Maven Central in 4 to 6. The web UI's typecheck and unit tests ran on Node 26 in each. A whole run, from unpacking the code to the summary, took 80 to 101 seconds, against 2 to 4 minutes for the same builds on 10 November. Earlier that afternoon, in a separate session, `nvm install 26` installed Node v26.13.0 with npm 11.20.0.

## The agent's model use

Foundry traces every answer to Application Insights with its response's id. Each response's `usage`, read from the project's Responses API, is what the model deployment counts. The traces' `chat` spans give the same input tokens but fewer output tokens, so this export reads the responses.

```powershell
$appi = azd env get-value APPLICATIONINSIGHTS_NAME
$env:FOUNDRY_PROJECT_ENDPOINT = azd env get-value FOUNDRY_PROJECT_ENDPOINT
$env:PYTHONIOENCODING = 'utf-8'
$runs = [ordered]@{ 'v4 on 10 November' = '2026-11-10T03:56:00Z', '2026-11-10T04:07:00Z'; 'v5' = '2026-11-11T15:53:00Z', '2026-11-11T16:01:00Z'; 'v6' = '2026-11-11T16:04:00Z', '2026-11-11T16:11:00Z' }
$ids = foreach ($run in $runs.Keys) {
  $kql = "dependencies | where timestamp between (datetime($($runs[$run][0])) .. datetime($($runs[$run][1]))) | where name startswith 'invoke_agent' | project rid = tostring(customDimensions['gen_ai.response.id'])"
  (az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { "$run`t$($_[0])" }
}
$ids | Set-Content "$env:TEMP\response-ids.txt"
@'
import collections, os
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
client = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential()).get_openai_client()
total = collections.defaultdict(lambda: collections.Counter())
for line in open(os.path.join(os.environ["TEMP"], "response-ids.txt"), encoding="utf-8-sig"):
    run, response_id = line.rstrip("\n").split("\t")
    response = client.responses.retrieve(response_id)
    t = total[run]
    t[response.status] += 1
    if response.usage:
        t["in"] += response.usage.input_tokens
        t["cached"] += response.usage.input_tokens_details.cached_tokens or 0
        t["out"] += response.usage.output_tokens
for run, t in total.items():
    print(f"{run} | {t['completed']} completed, {t['failed']} failed | {t['in']} tokens in ({t['cached']} cached) | {t['out']} out")
'@ | python -
Remove-Item "$env:TEMP\response-ids.txt"
```

| Evaluation | Agent and model | Answers | Sandbox commands | Tokens in (cached) | Tokens out | At list prices |
| --- | --- | --- | --- | --- | --- | --- |
| [10 November, 03:56](2026-11-10-evaluation.md) | version 4, `gpt-5.4-mini` | 10 | 4 | 46,604 (0) | 6,670 | $0.065 |
| 11 November, 15:53 | version 5, `gpt-6-luna` | 10 | 24 | 62,815 (10,899) | 6,524 | $0.0095 |
| 11 November, 16:04 | version 6, `gpt-6-luna` | 10, and the failed run | 27 | 60,912 (12,154) | 6,150 | $0.0092 |

The list prices are those of the Azure Retail Prices API for Global Standard deployments, per million tokens: `gpt-5.4-mini` $0.75 in and $4.50 out, `gpt-6-luna` $0.10 in and $0.50 out. The table doesn't apply the discount on cached input tokens. The failed run reports no usage, and its 4 sandbox commands are in the count. On `gpt-6-luna`, the agent read more in the sandbox: 2.3 to 2.4 commands per answer instead of 0.4, and an average answer took 9 to 10 seconds in Foundry's traces instead of 3, yet ten answers cost about a seventh as much.

## The Foundry runs

Foundry graded the same results with the same five checks, registered as custom code-based evaluators. Because the model changed, `eval_reviewer.py` created a new evaluation for `gpt-6-luna` rather than adding these runs to the one of 10 November.

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = azd env get-value FOUNDRY_PROJECT_ENDPOINT
$env:PYTHONIOENCODING = 'utf-8'
@'
import datetime as dt, os
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
client = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential()).get_openai_client()
utc = lambda t: dt.datetime.fromtimestamp(t, dt.UTC).strftime("%H:%M:%S")
shown = ("2026-11-11 16:",)
runs = [r for e in client.evals.list(limit=100) for r in client.evals.runs.list(eval_id=e.id, limit=100) if any(s in r.name for s in shown)]
for r in sorted(runs, key=lambda r: r.created_at):
    checks = ", ".join(f"{c.testing_criteria.removeprefix('pr_review_')} {c.passed}/{c.passed + c.failed}" for c in r.per_testing_criteria_results or [])
    print(f"{r.name} | {utc(r.created_at)} to {utc(r.model_extra['modified_at'])} | {r.status} | {checks}")
'@ | python -
```

| Run | UTC | rule_verdicts | verdicts_verbatim | advisory_only | useful_commentary | sandbox_ran |
| --- | --- | --- | --- | --- | --- | --- |
| 10 labelled pull requests · agent v5 · 2026-11-11 16:00 UTC | 16:00:01 to 16:01:56 | 10/10 | 10/10 | 10/10 | 9/10 | 10/10 |
| 10 labelled pull requests · agent v6 · 2026-11-11 16:10 UTC | 16:10:58 to 16:12:44 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |

Both runs graded every check on every item the first time, and each agreed with the local scores.

## Afterwards

At 16:21:19, with no model call to it since 14:25 and no setting naming it, the `gpt-5.4-mini` deployment was deleted. The agent's versions 1 to 4 still name it, so only version 5 and later can answer.
