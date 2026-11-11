# Evidence: the evaluation of 10 November 2026

What Azure recorded when [`eval_reviewer.py`](../eval_reviewer.py) measured the reviewer, in [See it work, step 7](../README.md#7-an-evaluation-measured-the-reviewer), exported so that anyone can check it without signing in to Azure. Times are UTC, all on 10 November 2026.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-develop`, with the commands shown in each section, run in PowerShell 7 from `solutions/03-develop-microsoft` after `azd env select ai-sdlc-develop`. The exports keep only the fields that each command names: times, pull request numbers, review ids, the Function's own log lines, and pass counts. None of them identifies the tenant.
- **Kept here because telemetry expires:** Application Insights keeps 30 days of data, so [the dry runs' query](#the-dry-runs) returns nothing after 10 December 2026. Foundry keeps its evaluation runs until someone deletes them or the project.
- **On GitHub**, the ten closed pull requests that `python eval_reviewer.py --setup` made from 03:54:29 to 03:56:09, one per labelled case: [#268](https://github.com/melabadi/adept-assessment-northstars/pull/268) to [#277](https://github.com/melabadi/adept-assessment-northstars/pull/277). Each one's description names its case and the pull request of this repository that the change comes from. The evaluation was part of the rehearsal in pull request [#298](https://github.com/melabadi/adept-assessment-northstars/pull/298), whose description reports it.
- **The local scores** are in the terminal, [step 7's first screenshot](../README.md#7-an-evaluation-measured-the-reviewer): every check passed on every case.

## The code that ran

- **The evaluation:** `eval_reviewer.py`, its five checks in [`review_graders.py`](../review_graders.py), and the cases in [`eval_cases.jsonl`](../eval_cases.jsonl) and [`eval_changes/`](../eval_changes/), from the branch of pull request #298, before it merged as [f4890b9](https://github.com/melabadi/adept-assessment-northstars/commit/f4890b9). Its fixed reviews for `--check-graders` came from the same branch, after Copilot's review of #298 led to a stricter commentary check.
- **The Function, the rule checker, and the review's formatter:** the code on `main` at [c6eeb3c](https://github.com/melabadi/adept-assessment-northstars/commit/c6eeb3c) (pull request [#267](https://github.com/melabadi/adept-assessment-northstars/pull/267)), which hasn't changed since.
- **The agent:** `requesthub-pr-reviewer` version 4, on `gpt-5.4-mini`, the same version as on 31 October.

## The dry runs

The Function's log for each dry run: the same review as for a labelled pull request, with nothing posted. `eval_reviewer.py` started four at a time, then one more as each finished. The script measured each dry run from its start to its result, polling every 15 seconds, so its times (150 to 263 seconds) are a little longer than the Function's.

```powershell
$appi = azd env get-value APPLICATIONINSIGHTS_NAME
$kql = "traces | where timestamp between (datetime(2026-11-10T03:56:00Z) .. datetime(2026-11-10T04:08:00Z)) | where message startswith 'review ' | extend id = extract('^review ([0-9a-f]+):', 1, message), step = extract('^review [0-9a-f]+: (.*)', 1, message) | summarize queued = format_datetime(min(timestamp), 'HH:mm:ss'), pr = take_anyif(extract('dry run of #([0-9]+) queued', 1, step), step has 'queued'), rules = take_anyif(extract('in [0-9]+ s: (.*)', 1, step), step has 'rule checker'), tests = take_anyif(extract('build and tests: (.*)', 1, step), step startswith 'build and tests:'), agent = take_anyif(extract('answered in (.*)', 1, step), step has 'answered in'), done = take_anyif(extract('done in (.*); sessions', 1, step), step startswith 'done in') by id | order by pr asc"
(az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
```

| Case (kind) | Pull request | Review | Queued | Rules | Build and tests | Agent answered in | Done in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| confirm-routing (known-good) | [#268](https://github.com/melabadi/adept-assessment-northstars/pull/268) | `9fadee5fcfe1` | 03:56:35 | all 5 rules passed | API 63 of 63 passed, web 15 of 15 passed in 2 min 34 s | 6 s (completed, 1 sandbox command) | 2 min 50 s |
| first-decision-wins (flagged) | [#269](https://github.com/melabadi/adept-assessment-northstars/pull/269) | `c9990225d2a3` | 03:56:35 | 1 of 5 rules failed | API 58 of 58 passed, web 14 of 14 passed in 3 min 21 s | 7 s (completed, 0 sandbox commands) | 3 min 52 s |
| admins-decide (known-bad) | [#270](https://github.com/melabadi/adept-assessment-northstars/pull/270) | `2b5bdeaee2a4` | 03:56:37 | 2 of 5 rules failed | API 50 of 50 passed, web 14 of 14 passed in 2 min 31 s | 6 s (completed, 0 sandbox commands) | 2 min 50 s |
| literal-wildcards (known-good) | [#271](https://github.com/melabadi/adept-assessment-northstars/pull/271) | `ba635b0d9baf` | 03:56:35 | all 5 rules passed | API 52 of 52 passed, web 14 of 14 passed in 2 min 00 s | 6 s (completed, 0 sandbox commands) | 2 min 11 s |
| load-test-cleanup (flagged) | [#272](https://github.com/melabadi/adept-assessment-northstars/pull/272) | `bc2d9e89dc24` | 03:58:57 | 1 of 5 rules failed | API 60 of 60 passed, web 14 of 14 passed in 3 min 26 s | 6 s (completed, 0 sandbox commands) | 3 min 51 s |
| sql-concatenation (known-bad) | [#273](https://github.com/melabadi/adept-assessment-northstars/pull/273) | `c75750621609` | 03:59:40 | 1 of 5 rules failed | API 1 of 60 failed, web 14 of 14 passed in 2 min 10 s | 12 s (completed, 3 sandbox commands) | 2 min 37 s |
| parameterized-search (known-good) | [#274](https://github.com/melabadi/adept-assessment-northstars/pull/274) | `79d850fdf8c3` | 03:59:43 | all 5 rules passed | API 70 of 70 passed, web 14 of 14 passed in 2 min 08 s | 6 s (completed, 0 sandbox commands) | 2 min 31 s |
| delivery-timeout (known-good) | [#275](https://github.com/melabadi/adept-assessment-northstars/pull/275) | `77b25b78f543` | 04:00:41 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 2 min 02 s | 6 s (completed, 0 sandbox commands) | 2 min 32 s |
| token-reuse (known-good) | [#276](https://github.com/melabadi/adept-assessment-northstars/pull/276) | `6728ade5367f` | 04:02:29 | all 5 rules passed | API 63 of 63 passed, web 14 of 14 passed in 3 min 51 s | 7 s (completed, 0 sandbox commands) | 4 min 12 s |
| index-no-cache (known-good) | [#277](https://github.com/melabadi/adept-assessment-northstars/pull/277) | `8858a1cb812e` | 04:02:31 | all 5 rules passed | API 67 of 67 passed, web 14 of 14 passed in 2 min 01 s | 6 s (completed, 0 sandbox commands) | 2 min 33 s |

The last dry run ended at 04:06:42.

## The Foundry runs

Foundry graded the same results with the same five checks, registered as custom code-based evaluators. A check that Foundry couldn't grade on any item shows `0/0`: `eval_reviewer.py` then grades the same results once more and counts a check that was graded on every item in either grading.

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = azd env get-value FOUNDRY_PROJECT_ENDPOINT
$env:PYTHONIOENCODING = 'utf-8'
@'
import datetime as dt, os
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
client = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential()).get_openai_client()
utc = lambda t: dt.datetime.fromtimestamp(t, dt.UTC).strftime("%H:%M:%S")
shown = ("2026-11-10 04:07", "2026-11-10 04:11", "2026-11-10 19:")
runs = [r for e in client.evals.list(limit=100) for r in client.evals.runs.list(eval_id=e.id, limit=100) if any(s in r.name for s in shown)]
for r in sorted(runs, key=lambda r: r.created_at):
    checks = ", ".join(f"{c.testing_criteria.removeprefix('pr_review_')} {c.passed}/{c.passed + c.failed}" for c in r.per_testing_criteria_results or [])
    print(f"{r.name} | {utc(r.created_at)} to {utc(r.model_extra['modified_at'])} | {r.status} | {checks}")
'@ | python -
```

| Run | UTC | rule_verdicts | verdicts_verbatim | advisory_only | useful_commentary | sandbox_ran |
| --- | --- | --- | --- | --- | --- | --- |
| 10 labelled pull requests · agent v4 · 2026-11-10 04:07 UTC | 04:07:05 to 04:11:13 | 10/10 | 0/0 | 10/10 | 10/10 | 10/10 |
| 10 labelled pull requests · agent v4 · 2026-11-10 04:11 UTC | 04:11:22 to 04:13:00 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| 26 fixed reviews (grader checks) · run 1 · 2026-11-10 19:43 UTC | 19:43:28 to 19:51:34 | 0/0 | 26/26 | 26/26 | 13/26 | 26/26 |
| 26 fixed reviews (grader checks) · run 2 · 2026-11-10 19:51 UTC | 19:51:37 to 19:54:54 | 26/26 | 26/26 | 26/26 | 13/26 | 26/26 |
| 10 labelled pull requests · agent v4 · 2026-11-10 19:55 UTC | 19:55:20 to 19:59:22 | 10/10 | 0/0 | 10/10 | 10/10 | 10/10 |
| 10 labelled pull requests · agent v4 · 2026-11-10 19:59 UTC | 19:59:31 to 20:03:41 | 10/10 | 10/10 | 10/10 | 10/10 | 0/0 |

- **04:07 and 04:11:** `python eval_reviewer.py` graded the ten dry runs. Across the two gradings, every check passed on every item, as the local scores did.
- **19:43 and 19:51:** `python eval_reviewer.py --check-graders` graded 26 fixed reviews, a right and a wrong one per finding. Thirteen of them are labelled to fail `useful_commentary`, so the counts alone can't show whether the right ones failed: the terminal compared each review with its label. Paired, 13 of 13 were graded as labelled; held-out, 11 of 13, with the two misses listed as known; and Foundry graded all 26 the same way as the local checks.
- **19:55 and 19:59:** `python eval_reviewer.py --reuse` graded the same ten dry runs again with the stricter commentary check, without new dry runs. Across the two gradings, every check passed on every item.

The project holds other runs from the same rehearsal, for example `--check-graders` on the 17 fixed reviews of that morning; the command above lists only the runs that See it work shows.
