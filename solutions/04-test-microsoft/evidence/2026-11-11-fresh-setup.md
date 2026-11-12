# A fresh setup that followed only this README: 11 November 2026

On 11 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in the private copy that the fresh setups of [01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md), [02-design-microsoft](../../02-design-microsoft/evidence/2026-11-11-fresh-setup.md), and [03-develop-microsoft](../../03-develop-microsoft/evidence/2026-11-11-fresh-setup.md) had used, and in a new azd environment, `ai-sdlc-test-fresh`, so in a new resource group, `rg-ai-sdlc-test-fresh`, in Central US. It ran the Quick start, the starting-state check, the eight steps, reset the copy, and cleaned up. The owner created the GitHub token.

Times are UTC; those after midnight are on 12 November. The copy of the repository is private, so its Issues aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`. Host names, the subscription, and GUIDs are left out.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0 with its `load` extension 2.1.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, and Git 2.56.0.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. The Azure account sees 87 subscriptions, and azd had no default subscription.
- The copy's `main` was at `334a6df`. The session took later updates with the root README's command, which merged main at [93033b0](https://github.com/melabadi/adept-assessment-northstars/commit/93033b0), and pushed them, before deploying anything. No file of this solution changed between the two.
- The token, created by the owner on GitHub at about 22:30, as [Let Azure post to GitHub](../README.md#3-let-azure-post-to-github) says, through the coordinating session: `ai-sdlc-test-fresh`, for `<owner>/ai-sdlc` only, with Issues read and write and the Metadata read-only that GitHub adds, expiring on 28 February 2027. The coordinating session stored it at 22:49:04, once `azd up` had ended, with `azd env set GITHUB_ISSUES_TOKEN`: the README's command, with the masked prompt answered earlier.
- The session ran its commands without a terminal, so azd couldn't ask it questions. For the portal's steps it used the Azure CLI, and for the Observability Agent the repository's [`tools/screenshot.mjs`](../../../tools/screenshot.mjs) in the capture browser, signed in as the owner.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 22:26:45 | Clone the copy | `git clone` | 9 s | |
| 22:27:00 | Take later updates (root README) | `git pull --no-rebase --no-edit https://github.com/melabadi/adept-assessment-northstars.git main` | 5 s; a merge commit with git's default message | |
| 22:27:21 | Push them to the copy (root README) | `git push` | 2 s; started *Repository checks*, which passed in 10 s | |
| 22:28:04 | A virtual environment (not in the README) | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 17 s | |
| 22:28:32 | Quick start | `pip install -r requirements.txt` | 1 min 25 s | |
| 22:30:02 | Quick start | `az extension add --name load --upgrade` | 3 s; 2.1.0 was already installed | |
| about 22:30 | 3. Create the GitHub token | on GitHub, by the owner | a few minutes, while the session went on | |
| 22:30:12 | Quick start | `azd env new ai-sdlc-test-fresh --location centralus` | 1 s; stored no subscription (finding 1) | |
| 22:30:40 | Not in the README | `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)` | 2 s | |
| 22:30:58 | Quick start | `azd up` | 17 min 29 s; azd counted 17 min 14 s: 14 min provisioning, 3 min 13 s deploying | about 20 minutes |
| 22:49:04 | Quick start | `azd env set GITHUB_ISSUES_TOKEN …`, by the coordinating session | | |
| 22:49:30 | Quick start, with the `azure.yaml` fix of finding 2 | `azd provision` | 6 min 31 s; azd counted 5 min 41 s | 5 min 45 s |
| 22:56:29 | Check the starting state | the README's lines | 27 s | about 5 minutes |
| 22:57:29 | 1. Open the test in Azure | `az load test show`, `az load notification-rule show`, and `az load trigger schedule show`, instead of the portal | 10 s | about 2 minutes |
| 22:57:44 | 2. Run the baseline | `az load test-run create … --display-name "Baseline"` | verdict at 23:06:14, 8 min 26 s after the run was created | 7 to 9 minutes |
| 23:06:14 | 3. Read the baseline | `az load test-run show`, and the function's log from Application Insights instead of the portal | the function's report at 23:08:24, 2 min 10 s after the verdict | about 1 minute, and the report about 2 minutes later |
| 23:12:57 | 4. Ship a slowdown | `python slowdown.py on` | 1 min 12 s | 1 to 3 minutes |
| 23:14:16 | 5. Run again | `az load test-run create … --display-name "After the slowdown"` | verdict at 23:23:05, 8 min 42 s after the run was created | 7 to 9 minutes |
| 23:23:05 | 6. Azure tells the team | `gh issue list --label load-test --state open`, and the function's log | Issue #21 at 23:25:22, 2 min 17 s after the verdict | 2 to 4 minutes |
| 23:23:18 | 7. AI explains, people verify | the run's AI insights through Azure Load Testing's REST API; the Observability Agent through `tools/screenshot.mjs` | the insights by 23:25:52, without anyone asking; two questions, after a first try that asked nothing ([also seen](#also-seen-and-left-as-they-are)), the answers in by 23:30:11 | about 5 minutes |
| 23:30:51 | 8. Fix and confirm | `python slowdown.py off`, then `az load test-run create … --display-name "After the fix"` | 1 min 12 s; verdict at 23:40:38, 8 min 31 s after the run was created; the Issue closed at 23:42:40 | about 12 minutes |
| 23:44:07 | Reset the copy | the README's three lines | 14 s | |
| 23:44:36 | Not in the README: a check of the `azure.yaml` fix | `azd deploy reporter` | 55 s; azd counted 32 s | |
| 23:46:03 | Clean up | `$app = az ad app show --id (azd env get-value API_CLIENT_ID) --query id -o tsv` | 4 s | |
| 23:46:07 | Clean up | `azd down --purge` | stopped after 14 s at its question (finding 3) | |
| 23:46:29 | Clean up | `azd down --purge --force` | 27 min 14 s; azd counted 27 min 11 s | about half an hour: 31 min 45 s once |
| 00:13:55 | Clean up | `az ad app delete --id $app`, then `az rest --method delete --url "https://graph.microsoft.com/v1.0/directory/deletedItems/$app"` | 4 s | |
| 00:13:59 | Not in the README | `azd env set GITHUB_ISSUES_TOKEN ''` | 1 s | |
| 00:16:46 | Not in the README | `az rest --method delete` on the app's service principal in `deletedItems` (finding 5) | under a second | |

**The Quick start took 27 minutes 29 seconds**, from `pip install` to the end of the provision that stored the token, 1 minute 3 seconds of it between `azd up` and that provision, while the token was stored. The README said about 30 minutes. **The eight steps took 46 minutes 11 seconds** from the starting-state check to the closed Issue, the way See it work measured its 41 minutes 41 seconds, with the portal's steps run from the terminal. The README said about 45 minutes.

## What didn't match the README, and what changed

**1. `azd env new` stored no subscription.** As in [01-plan-microsoft's fresh setup](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md), `azd env new ai-sdlc-test-fresh --location centralus` stored only the environment's name and region, and azd has no default subscription here. `azd up` would then have asked which of the account's 87 subscriptions to use, and this solution's scripts and the README's commands find the resources with `az`, in the subscription `az` uses. The session stored that subscription with `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)`. Both `azd env new` commands in the README now pass `--subscription (az account show --query id -o tsv)`, and [Deploy](../README.md#1-deploy) says why.

**2. `azd up` showed nothing that its hooks printed.** Its output went from the provisioned resources straight to `Running predeploy hook...` and the deployment: not the repository line of the preprovision hook, not the guardrails' `PASS`, the test, the notification rule, and the schedule that [What azd up creates](../README.md#what-azd-up-creates) quotes, and not the unit tests. The hooks did run: the environment held `GITHUB_REPOSITORY`, and Azure Load Testing had the test from 22:44:44, the notification rule from 22:44:59, and the schedule, paused, from 22:45:07. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds. [`azure.yaml`](../azure.yaml) now makes all three hooks interactive, with a comment saying why. The provision that stored the token, at 22:49, ran with that change and printed what the postprovision hook does on a second run:

```text
  (✓) Done: Function App: func-loadtest-<token> (3.258s)
PASS loadtest/requesthub-journey.yaml: criteria name real requests, thresholds and workload within guardrails, every setting read, Python 3.9 compatible, no secrets
Test 'requesthub-journey': updated from loadtest/ (rendered to out/loadtest.yaml).
Notification rule 'runs-to-github': updated; every finished run goes to the reporting function, which reports it to GitHub.
Schedule 'weekday-evenings': unchanged (paused).

SUCCESS: Your application was provisioned in Azure in 5 minutes 41 seconds.
```

The preprovision hook printed nothing there, as it should: it names the repository only when the environment doesn't have one yet. `azd deploy reporter`, at 23:44, showed the predeploy hook's tests:

```text
----------------------------------------------------------------------
Ran 85 tests in 14.316s

OK
```

[Deploy](../README.md#1-deploy) now says that the unit tests end with `OK`, and the README's Troubleshooting explains the pane.

**3. `azd down --purge` stopped at its question.** Without a terminal, it listed the 18 resources it would delete, asked to confirm, got no answer, and stopped: `ERROR: deleting infrastructure: error deleting Azure resources: user denied delete confirmation`. Nothing had been deleted, and this solution has no predown hook. `azd down --purge --force` then removed everything. [Clean up](../README.md#clean-up) now gives `--force` and says that azd asks without it.

**4. Clean up left the token in the local azd environment.** After `azd down`, the environment still held `GITHUB_ISSUES_TOKEN`. Clean up now removes it with `azd env set GITHUB_ISSUES_TOKEN ''`, as 01-plan-microsoft's and 03-develop-microsoft's do.

**5. Clean up left RequestHub's service principal in Entra's recycle bin.** The README's lines deleted the app registration `RequestHub (ai-sdlc-test-fresh)` and purged it, but deleting the app also moved its service principal to the recycle bin, at the same second, 00:13:55, and the README didn't purge it. The session read its object id from the snapshot it had taken before the clean-up, and `az rest --method delete --url "https://graph.microsoft.com/v1.0/directory/deletedItems/<id>"` purged it at 00:16:46. To check the order Clean up now gives, the session created a throwaway app registration and its service principal, read both object ids, deleted the app, and purged the app and then the principal at once: all four calls succeeded in 5.5 seconds, and neither object was left, active or in the recycle bin. [Clean up](../README.md#clean-up) now reads `$sp` with `$app`, before `azd down`, and purges it last. The six managed identities' principals that the group's deletion moved to the recycle bin can't be purged ([what is left](#the-clean-up-and-what-is-left)); Clean up now says so.

**6. Other solutions' workflows saw this run's Issue.** In the copy, every solution's workflows are active. Opening Issue #21, with its `load-test` label, started *Operate · GitHub · agentic incident triage*, which skipped all six of its jobs in 2 seconds, and the comment that closed it started *Design · GitHub · agentic design review*, whose `pre_activation` job stopped it after 15 seconds. No model ran in GitHub. [Try it first](../README.md#try-it-first-in-a-copy-of-this-repository) now says so.

**7. The README's estimates gave way to the times above,** in its summary, [One-time setup](../README.md#one-time-setup), the Quick start, [Check the starting state](../README.md#check-the-starting-state), [How long each step takes](../README.md#how-long-each-step-takes), and [Clean up](../README.md#clean-up). The root README's update now says what the update took here.

**8. What it costs left out the Observability Agent.** Step 7 asks it questions, and Microsoft Learn says it has billed them since 1 July 2026, in Azure Agent Credits; Azure's retail price list gives $0.01 a credit, effective that day. [What it costs](../README.md#what-it-costs) now says so.

Checked and found right:

- **`azd up` ran its hooks and didn't stop at `missing required inputs`.** [`infra/main.bicep`](../infra/main.bicep) already gives `githubRepository` and `githubIssuesToken` empty defaults, and every parameter of the app's modules that azd deploys, in [`app/infra/api.parameters.json`](../../../app/infra/api.parameters.json) and [`worker.parameters.json`](../../../app/infra/worker.parameters.json), comes from the azd environment, from `main.bicep`'s outputs, or from azd's image names, or has a default.
- **No Foundry agent.** This solution publishes nothing to Microsoft Foundry, so no agent identity or blueprint appears in Microsoft Entra ID. The Entra objects it creates are RequestHub's app registration and its service principal, which Clean up deletes and purges, and the managed identities' principals, which go with the resource group.
- **The root README's command for later updates** merged main into the copy, whose `main` had a commit of its own, and `git push` sent it to the copy.

## Also seen, and left as they are

- **The engines ran a newer Locust than the one the README pins.** The engine's log said `Starting Locust 2.46.7`. [`requirements.txt`](../requirements.txt) pins `locust==2.33.2`, and the locustfile's docstring says the engines run Locust 2.33.2 on Python 3.9, as [Microsoft Learn](https://learn.microsoft.com/azure/app-testing/load-testing/concept-load-testing-concepts#azure-load-testing-components) says. Every run worked with it; the local version matters only for [the optional local run](../README.md#optional-change-the-journey-on-your-machine), which the session didn't run.
- **A run reads `DONE` before it has a verdict.** The Baseline's status was `DONE` from 23:04:52 with the result `NOT_APPLICABLE`, no statistics, and no criteria results, and `PASSED` only from 23:06:14; the other two runs did the same for 1 to 2 minutes. A script that waits for a run should wait for `PASSED` or `FAILED`, as the portal's verdict does.
- **The AI insights have a REST API.** Azure Load Testing's data plane serves a run's insights at `GET https://<data-plane URI>/test-runs/<run id>/insights/latest?api-version=2025-03-01-preview`, for the scope `https://cnt-prod.loadtesting.azure.com`; it answered `TestRunInsightsNotFound` for the Baseline, which passed, and returned the failed run's insights by 23:25:52, under 3 minutes after its verdict, without anyone asking or opening the run in the portal, as step 7 says the portal shows them.
- **The README's step commands name `rg-ai-sdlc-test`,** the group of the README's environment; the session used its own, `rg-ai-sdlc-test-fresh`.
- **The list requests were slower at the baseline than in See it work,** 98 and 166 ms at the 95th percentile for my-requests and team-queue, against 14 and 22 ms, on a new database; every criterion still passed with room. After the fix, they took 65 and 69 ms.
- **The session's first try at the Observability Agent asked nothing.** At 23:23:18 it waited for the agent's empty input to show its placeholder, *I want to…*, which it didn't find within two minutes. The second try, at 23:26:49, waited for the agent's greeting instead and asked the question. This is about how the session drove the portal, not about the README.

## The run

**The starting state, at 22:56:29.** The database was `Ready`; `python slowdown.py status` printed `API revision <revision>: no slowdown configured.` and `GET /api/requests now takes 201 ms (median of 3 calls).`, the revision being the one `azd up` deployed; no `load-test` Issue was open; and the weekday schedule was `Paused`.

**Step 1.** The test `requesthub-journey`, *RequestHub request-and-approval journey*, kind Locust, on one engine, with five criteria; the notification rule *Report finished runs to GitHub*, for `requesthub-journey` and the event `run-ended`; and the schedule *Weekday evenings*, `Paused`.

**Steps 2 and 3.** The three runs, as Azure Load Testing recorded them, with the verdict's time from the run's `lastModifiedDateTime`:

| Run | Display name | Created | Load | Verdict | Result | Requests | p90 | Errors | Criteria failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline-20261111-175745` | Baseline | 22:57:49 | 23:00:30 to 23:02:33 | 23:06:14 | PASSED | 590 | 97 ms | 0 % | none |
| `slowdown-20261111-181417` | After the slowdown | 23:14:22 | 23:17:20 to 23:19:23 | 23:23:05 | FAILED | 578 | 1,510 ms | 0 % | my-requests p95 1,570 ms > 1,000 ms; team-queue p95 1,560 ms > 1,000 ms |
| `fix-20261111-183203` | After the fix | 23:32:06 | 23:35:00 to 23:36:58 | 23:40:38 | PASSED | 584 | 65 ms | 0 % | none |

The 95th percentiles of the five criteria, in milliseconds:

| Run | my-requests (fails above 1,000) | team-queue (1,000) | decide (1,500) | submit (1,500) | Errors (1 %) |
| --- | --- | --- | --- | --- | --- |
| Baseline | 98 | 166 | 194 | 265 | 0 % |
| After the slowdown | 1,570 | 1,560 | 173 | 164 | 0 % |
| After the fix | 65 | 69 | 200 | 253 | 0 % |

The engine's log for the Baseline: `Starting Locust 2.46.7`, `Cleanup: deleted 0 requests owned by aad-<id>` before the load, 10 users, `{"Approver": 5, "Requester": 5}`, and `Cleanup: deleted 100 requests owned by aad-<id>` after it.

**The function's log**, from Application Insights (the query of [See it work's evidence](2026-10-31-recorded-run.md#the-functions-log), which reads what the portal's **Invocations** show):

| UTC | Function | Event |
| --- | --- | --- |
| 23:08:05 | test_run_ended | answered HTTP 202 in 2201 ms |
| 23:08:07 | test_run_ended | Accepted Baseline (baseline-20261111-175745, ended 2026-11-11T23:02:33Z): queued for its report. |
| 23:08:14 | report_run | queue step succeeded in 11637 ms |
| 23:08:24 | report_run | Baseline: PASSED, verdict accepted (454 server requests, 0 with the injected delay). |
| 23:08:25 | report_run | Baseline: no change on GitHub: no Issue is open for this test. |
| 23:25:17 | test_run_ended | answered HTTP 202 in 1585 ms |
| 23:25:19 | test_run_ended | Accepted After the slowdown (slowdown-20261111-181417, ended 2026-11-11T23:19:23Z): queued for its report. |
| 23:25:20 | report_run | queue step succeeded in 2492 ms |
| 23:25:21 | report_run | After the slowdown: FAILED, verdict expected-failure (479 server requests, 154 with the injected delay). |
| 23:25:23 | report_run | After the slowdown: opened Issue #21 (no Issue is open for this test). |
| 23:42:30 | test_run_ended | answered HTTP 202 in 1417 ms |
| 23:42:31 | test_run_ended | Accepted After the fix (fix-20261111-183203, ended 2026-11-11T23:36:58Z): queued for its report. |
| 23:42:36 | report_run | queue step succeeded in 5049 ms |
| 23:42:38 | report_run | After the fix: PASSED, verdict accepted (464 server requests, 0 with the injected delay). |
| 23:42:41 | report_run | After the fix: closed Issue #21 (the run passed and the report accepts it). |

Azure Load Testing's notification reached the function 1 min 51 s, 2 min 13 s, and 1 min 52 s after each verdict.

**Step 4.** `python slowdown.py on`, from 23:12:57:

```text
Injecting 1500 ms on the request list, expiring at 2026-11-11T23:43:02+00:00 ...
Waiting for API revision 0000001 to become ready and take all traffic ...
Deactivated the previous API revision <revision>.
API revision 0000001: 1500 ms on the request list until 2026-11-11T23:43:02Z (29 min left).
GET /api/requests now takes 1,612 ms (median of 3 calls).
```

**Step 6.** Issue #21, *[load-test requesthub-journey] RequestHub journey missed its performance criteria*, opened at 23:25:22 by the token's owner, with the `load-test` label: 11 minutes 12 seconds after `slowdown.py on` ended, against 11 minutes 42 seconds in See it work. Its report: `After the slowdown` FAILED with 10 virtual users for 123 s; *Expected failure*, because 154 server requests carried `requesthub.fault.queue_delay_ms`; the server requests in the run's window came from revision `0000001`; my-requests at 1,570 ms and team-queue at 1,560 ms failed their 1,000 ms limit, while the error rate, decide, and submit passed. On the server, `GET /api/requests` counted 154 requests at a 1,521 ms 95th percentile, every one with the injected delay, and `GET /api/requests/{id}` 12 denied requests, the journey's deliberate checks.

**Step 7.** The run's AI insights, read at 23:25:52 through the REST API above, version 1, status `Succeeded`. The summary: *Load test (2 min, 5 VUs) failed due to 2 test criteria failures. Client response times remained high and plateaued above acceptable thresholds, with persistent latency spikes, while backend metrics showed rising request duration and increased failed HTTP requests.* Its four insights: *Consistently High Response Latency* (my-requests and team-queue between 1,510 and 1,590 ms, which failed the criteria), *Backend Load Correlation Evident*, *RPS and Virtual User Plateau*, and *Failed HTTP Requests Spike*. As in See it work, it counted 5 virtual users where the run had 10, read the journey's deliberate 403 checks as failed requests, and didn't name the injected delay.

The Observability Agent, in Application Insights › Logs with the **Agent** toggle on, asked the README's two questions in two conversations:

- *Why was GET /api/requests slow in the last 30 minutes?*, asked at about 23:27:03. It reasoned for 1.72 minutes: 325 requests, a 1.51 second 95th percentile, 752 ms on average, and no failures; the slow requests clustered from 23:14 to 23:18, with no exceptions, no warning or error traces, and no sign of CPU saturation. It pointed to *application-side work inside GET /api/requests* and suggested a deeper investigation, without finding the injected delay.
- *In the last 30 minutes, how many requests named exactly GET /api/requests (the list, not GET /api/requests/{id}) carried the custom dimension requesthub.fault.queue_delay_ms, and how did their duration compare with the GET /api/requests requests that did not?*, asked at about 23:29:43. It reasoned for 0.42 minutes: 159 requests with the property, averaging 1,520.5 ms with a 1,522.0 ms 95th percentile, and 166 without it, averaging 16.1 ms with a 19.2 ms 95th percentile, *about 95x* slower.

The session's own KQL, the queries of [See it work's evidence](2026-10-31-recorded-run.md#the-apis-telemetry) over the same 30 minutes, gave the agent's numbers exactly: 325 requests, none failed, 752 ms on average, a 1,515 ms 95th percentile; then 159 with the property at 1,520.5 ms on average and a 1,522 ms 95th percentile, and 166 without it at 16.1 and 19.2 ms. The 159 are `slowdown.py on`'s 4 timing calls, the 154 in the failed run's window, and 1 in the second after it; the 166 are the Baseline's.

**Step 8.** `python slowdown.py off`, from 23:30:51, printed `API revision 0000002: no slowdown configured.` and `GET /api/requests now takes 118 ms (median of 3 calls).` The function commented the passing report on Issue #21 at 23:42:39, *`After the fix` passed every criterion. Closing.*, with *Accepted* and revision `0000002`, and closed it at 23:42:40 as completed: 10 minutes 34 seconds after `After the fix` started, against 10 minutes 44 seconds in See it work, and 17 minutes 18 seconds after it opened.

**The reset**, at 23:44:07: `API revision 0000002: no slowdown configured.`, `GET /api/requests now takes 97 ms`, `API revision 0000002 runs the normal image. Nothing to restore.`, and no open `load-test` Issue.

## The clean-up, and what is left

Before the clean-up, the app registration `RequestHub (ai-sdlc-test-fresh)`, created at 22:37:45, had six app role assignments on its service principal: the four RequestHub roles of the person who ran `azd up`, and one each for `id-lt-requester-<token>` and `id-lt-approver-<token>`.

`azd down --purge --force` purged the Log Analytics workspace `log-<token>`, deleted the resource group, then purged the Key Vault `kv-<token>`, and ended with `SUCCESS: Your application was removed from Azure in 27 minutes 11 seconds.` From 23:57 on, only the Container Apps environment and its virtual network were left in the group; at 00:10 the environment read `ScheduledForDelete`. The first `azd down --purge` is finding 3, and the Entra lines and the purge of the service principal are finding 5.

Checked between 00:14 and 00:18:

- `az group exists -n rg-ai-sdlc-test-fresh`: `false`.
- `az keyvault list-deleted`: empty. `az monitor log-analytics workspace list-deleted-workspaces`, `az cognitiveservices account list-deleted`, and `az appconfig list-deleted`: nothing named with the setup's token.
- No resource tagged `azd-env-name=ai-sdlc-test-fresh`, none named with the setup's token, and no resource group named after the environment, anywhere in the subscription.
- No role assignment whose scope names the group, and none of the subscription's 149, inherited ones included, created during the setup. The template assigns every role inside the group.
- In Microsoft Entra ID, no application `RequestHub (ai-sdlc-test-fresh)` and no service principal for its client id, active or in the recycle bin, and no app role assignment of the signed-in person on it; the identities' assignments went with it. No active application or service principal named with the setup's token.
- In Entra's recycle bin, the service principals of the group's six managed identities, deleted with it at 23:47: `id-lt-requester-<token>`, `id-lt-approver-<token>`, `id-app-<token>`, `id-github-<token>`, `lt-<token>` (the Load Testing resource's), and `func-loadtest-<token>` (the function's). Entra refused to purge each of them: `Authorization_RequestDenied`, *Insufficient privileges to complete the operation.*
- The live deployment, untouched: `rg-ai-sdlc-test` still exists, and so does its app registration, `RequestHub (ai-sdlc-test)`, created on 27 October.
- The local azd environment no longer holds the token, and the capture browser that the session started for step 7 is closed.

What is left:

- **Three deployment records** at subscription scope, as for every azd deployment: those of `azd up` and `azd provision`, and the empty one that `azd down` records. They cost nothing. Their `githubIssuesToken` parameter keeps only its type, `SecureString`, and no value.
- **The six managed identities' service principals,** in Entra's recycle bin until it removes them, 30 days after 23:47.
- **The GitHub token** `ai-sdlc-test-fresh`, which could only read and write the copy's Issues, until it was deleted on 12 November 2026, after the seven fresh setups, as the owner asked. Nothing used it after the clean-up: the Key Vault that held it was purged, and the azd environment no longer had it.
- **In the copy,** `main` at `62d2667`, the closed Issue #21, and the `load-test` label, which GitHub created when the function opened the Issue with it. The copy was deleted on 12 November 2026, after the seven fresh setups, as the owner asked.

## What it cost

The resource group existed from 22:31 until azd deleted it at 00:13: 1 hour 42 minutes. At list prices:

- the copy's resource group, at the $2 to $3 a day that the [Quick start](../README.md#quick-start) gives: about 14 to 21 cents;
- the three test runs, at about $0.25 each, as [What it costs](../README.md#what-it-costs) counts them: about $0.75;
- the three private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1.50 if it bills each a whole month;
- the function on Flex Consumption: three notifications and their report steps, inside the monthly free grant;
- the image builds in the registry, storage, Key Vault, Application Insights, and Log Analytics: cents at most;
- the Observability Agent's two answers: since 1 July 2026 it bills its work in Azure Agent Credits, at $0.01 a credit ([its billing](https://learn.microsoft.com/azure/azure-monitor/aiops/observability-agent-billing)), and chat is its lowest-cost use; the session couldn't see how many credits the two answers used, which Microsoft Cost Management shows later. The session found no price for the run's AI insights, a preview feature.

So between about 90 cents and about $2.50, plus the agent's credits. In GitHub Actions, the copy ran 3 jobs for 29 seconds, 3 minutes as billed in a private repository, where each job counts as at least a minute: *Repository checks*' two jobs after the update's push, and the design review's `pre_activation` job; the incident triage skipped every job.
