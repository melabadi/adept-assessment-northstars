# A fresh setup that followed only this README: 12 November 2026

On 12 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in the private copy that the fresh setups of [01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md), [02-design-microsoft](../../02-design-microsoft/evidence/2026-11-11-fresh-setup.md), [03-develop-microsoft](../../03-develop-microsoft/evidence/2026-11-11-fresh-setup.md), and [04-test-microsoft](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md) had used, and in a new azd environment, `ai-sdlc-release-fresh`, so in a new resource group, `rg-ai-sdlc-release-fresh`, in Central US. It ran the Quick start, the starting-state check, the seven steps, the copy's reset, and cleaned up. The owner created the GitHub token, and the coordinating session created the build task with it.

Times are UTC. The copy of the repository is private, so its pull requests and commits aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`. Host names, the subscription, and GUIDs are left out.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, Git 2.56.0, and Node.js 22.23.4 for the repository's screenshot tool.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. azd had no default subscription.
- The copy's `main` was at `d76cc2f`, which had already merged main at [e3c9b49](https://github.com/melabadi/adept-assessment-northstars/commit/e3c9b49). No file of this solution or of `app/` differed from e3c9b49.
- The token, `ai-sdlc-release-fresh`, for `<owner>/ai-sdlc` only, with Contents and Commit statuses read-only and Webhooks read and write, as [Let Azure build every commit of main](../README.md#3-let-azure-build-every-commit-of-main) says, and the Metadata read-only that GitHub adds, expiring on 28 February 2027. The owner created it on GitHub, and the coordinating session ran that step's block in this folder with the token in place of the `Read-Host` prompt.
- The session ran its commands without a terminal, so azd couldn't ask it questions. For the portal's steps it used the Azure CLI and the queries of [See it work's evidence](2026-11-01-recorded-run.md), and for Azure Copilot the repository's [`tools/screenshot.mjs`](../../../tools/screenshot.mjs) in the capture browser, signed in as the owner.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 03:58:41 | Clone the copy | `git clone` | 12 s | |
| 03:58:59 | Take later updates (root README) | `git pull --no-rebase --no-edit https://github.com/melabadi/adept-assessment-northstars.git main` | under a second: `Already up to date.` | |
| 03:58:59 | Push them (root README) | `git push` | under a second: `Everything up-to-date`, and no workflow ran | |
| 03:59:15 | A virtual environment (not in the README) | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 17 s | |
| 03:59:32 | Not in the Quick start | `pip install -r requirements.txt` | 3 s; nothing to install, as the file says | |
| 03:59:46 | Quick start | `azd env new ai-sdlc-release-fresh --location centralus` | 1 s; stored no subscription (finding 1) | |
| 04:00:01 | Not in the README | `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)` | 2 s | |
| 04:00:22 | Quick start | `azd up` | 15 min 34 s; azd counted 15 min 20 s: 10 min 33 s provisioning, 4 min 47 s deploying | about 25 minutes, the build task included |
| 04:16:43 | One-time setup, step 1 | `azd hooks run predeploy`, which the README offered to show the tests | 3 s: `Ran 89 tests in 0.179s`, `OK` | |
| 04:19:11 | One-time setup, step 2 | `python preflight.py` | 1 min 16 s: 18 passed, **Build** warned | |
| about 03:50, and again about 04:23 | 3. The token | on GitHub, by the owner | a few minutes, while the session went on ([also seen](#also-seen-and-left-as-they-are)) | |
| 04:24:24 | 3. The build task | the README's block, by the coordinating session | 6 s; the task's webhook appeared in the copy at 04:24:30 | a few minutes |
| 04:26:37 | Quick start | `python preflight.py` | 1 min 14 s: all 19 passed | |
| 04:28:00 | Check the starting state | the README's four lines | 1 min 21 s | about 2 minutes |
| 04:29:36 | 1. Build a commit of main | `python release.py watch`, in a second shell | until 05:05:38 | |
| 04:30:04 | 1. Build a commit of main | push a branch, `gh pr create`, wait for its checks, then `gh pr merge 22 --squash --delete-branch` | merged at 04:30:43; the build started at 04:30:45.8 and pushed the commit's image at 04:32:51, 2 min 5 s later | about 2 minutes to the push |
| 04:32:56 | 2. Watch Azure test the candidate | `az containerapp job execution list`, and the release records from Log Analytics, instead of the portal | the release job ran for 2 min 21 s; the gate passed at 04:35:11 | about 2½ minutes |
| 04:38:31 | 3. Read the record, then promote | `az containerapp job start -g $rg -n $job.promote --query name -o tsv` | 48 s | about 1 minute, plus your reading |
| 04:39:40 | 4. Rehearse a bad release | `az containerapp job start -g $rg -n $job.drill` | 2 min 20 s | about 2½ minutes |
| 04:42:12 | 5. Ask Azure Copilot | `python release.py status --limit 4` for the suffix, then `tools/screenshot.mjs` | the status took 7 s; the question wasn't asked ([why](#step-5-wasnt-run)) | about 2 minutes a question |
| 05:04:30 | 6. Roll back | `az containerapp job start -g $rg -n $job.rollback`, then the watch stopped | 49 s; the watch stopped at 05:05:38 | about 1 minute |
| 05:06:11 | 7. See who did what | `az monitor activity-log list` and `az graph query`, the queries of See it work's evidence, instead of the workbook | 19 s | about 1 minute |
| 05:07:23 | Pause the builds (One-time setup, step 3) | define `Update-BuildTask`, then call it with `Disabled` | 7 s: `commit trigger: Disabled` | |
| 05:09:14 | Not in the README: a check of the `azure.yaml` fix | `azd deploy release` | 1 min 51 s; azd counted 59 s | |
| 05:11:29 | Reset the copy | the README's two lines | no answer after 3 minutes: the database had been stopped ([also seen](#also-seen-and-left-as-they-are)); stopped by the session | |
| 05:14:50 | Check the starting state, **Database** says `Stopped` | `az postgres flexible-server start …` | 2 min 6 s, then `Ready` | 3 to 5 minutes, the preflight included |
| 05:17:06 | Reset the copy | the README's two lines | 5 s: `{"reset":true,"industry":"general","requests":24}` | |
| 05:18:43 | Clean up | delete the webhook the task created, with `gh api -X DELETE repos/<owner>/ai-sdlc/hooks/<id>` instead of the repository's settings | under a second | |
| 05:18:51 | Clean up | `$app = …`, then `$sp = …` (finding 3) | 5 s | |
| 05:18:57 | Clean up | `azd down --purge` | stopped after 14 s at its question (finding 4) | |
| 05:19:19 | Clean up | `azd down --purge --force` | 27 min 51 s; azd counted 27 min 47 s | |
| 05:47:17 | Clean up | `az ad app delete --id $app`, then `az rest --method delete` on `deletedItems/$app` and `deletedItems/$sp` | 6 s | |

**The Quick start took 17 minutes of commands**, from `azd env new` to the preflight that passed every check: 16 minutes 57 seconds, with the person's few minutes for the token alongside. The README said about 25 minutes. By the wall clock it took 28 minutes, 8 of them waiting for the build task, whose first try failed on this machine ([also seen](#also-seen-and-left-as-they-are)). **Every step but Azure Copilot's took 14 minutes**, from the watch's start to the records of step 7, reading the gate's record included: 12 minutes 27 seconds for steps 1 to 4, 1 minute 8 seconds for step 6, and 19 seconds for step 7. The README said about 15 minutes for the seven.

## What didn't match the README, and what changed

**1. `azd env new` stored no subscription.** As in the fresh setups of 01 to 04, `azd env new ai-sdlc-release-fresh --location centralus` stored only the environment's name and region, and azd has no default subscription here. `azd up` would then have asked which subscription to use, while `preflight.py` and the README's `az` commands find the resources in the subscription `az` uses. The session stored that subscription with `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)`. Both `azd env new` commands in the README now pass `--subscription (az account show --query id -o tsv)`, and [Deploy](../README.md#1-deploy) says why.

**2. `azd up` showed nothing that its hooks printed.** Its output went from the provisioned resources to `Running predeploy hook...` and the four services, and from them to `Running postdeploy hook...` and `SUCCESS`. The hooks did run: Event Grid's subscription `release-on-push` existed with the README's filter (each `ImagePushed` of `requesthub-api:`, except the tag `main`), and the preflight found it. The README said that azd doesn't print the hooks' output and that `azd hooks run predeploy` shows it, which it did. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds, and shows nothing without a terminal. [`azure.yaml`](../azure.yaml) now makes both hooks interactive, with a comment saying why: the tests' result, and the reason Event Grid isn't connected if the postdeploy hook fails. With that change, `azd deploy release` at 05:09:14 printed the tests' result before it deployed, and the postdeploy hook, which prints nothing when it succeeds, deployed `release-on-push` again at 05:10:45:

```text
----------------------------------------------------------------------
Ran 89 tests in 0.327s

OK

Deploying services (azd deploy)

  release: Packaging
  ...
  release: Done [59s]


SUCCESS: Your application was deployed to Azure in 59 seconds.
```

The clone went back to the copy's `azure.yaml` afterwards. [Deploy](../README.md#1-deploy) now says that the tests end with `OK` and that the postdeploy hook prints nothing unless it fails, and the README's Troubleshooting explains the pane, for copies made before this change.

**3. Clean up didn't purge RequestHub's service principal.** [04-test-microsoft's fresh setup](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md) found that deleting the app registration also moves its service principal to Entra's recycle bin, and this README's Clean up had the same lines, which don't purge it. [Clean up](../README.md#clean-up) now reads `$sp` with `$app`, before `azd down`, and purges it last, as 04-test-microsoft's does. Run that way here, it left neither object, active or in the recycle bin ([what is left](#the-clean-up-and-what-is-left)). The managed identities' principals that the group's deletion moves to the recycle bin can't be purged; Clean up now says so.

**4. `azd down --purge` stopped at its question.** Without a terminal, it listed the 19 resources it would delete, asked to confirm, got no answer, and stopped: `ERROR: deleting infrastructure: error deleting Azure resources: user denied delete confirmation`. Nothing had been deleted. `azd down --purge --force` then removed everything. [Clean up](../README.md#clean-up) now gives `--force` and says that azd asks without it.

**5. A fresh `azd up` leaves the API's revision without a label.** The starting-state check's comment expects `stable` with 100% of traffic. After `azd up`, the one revision, `frdn6h6`, served 100% with no label and build `local`, and the preflight said `frdn6h6 serves 100% (no stable label yet: the first release adds it)`, which the release did. [What azd up creates](../README.md#what-azd-up-creates) and [Check the starting state](../README.md#check-the-starting-state) now say so.

**6. Other solutions' workflows saw step 1's pull request.** In the copy, every solution's workflows are active. Pull request #22 started *Repository checks* (two jobs, 8 and 7 seconds) and *Develop · GitHub · feature bounds* (one job, 4 seconds), and its merge started *Repository checks* again (9 and 7 seconds), all green. No model ran. 05-secure-microsoft's posture Function, set up in the same copy by another session, received both pull request events through its webhook and ignored them: `preview of pull request #22 (pull_request.opened): not previewed: it does not change the solution's infra/`, at 04:30:12, and `… (pull_request.closed): not previewed: the pull request is not open`, at 04:30:45, both answered with HTTP 200, and neither commit got a status. [Try it first](../README.md#try-it-first-in-a-copy-of-this-repository) now says so.

**7. The README's estimates gave way to the times above,** in its summary, [One-time setup](../README.md#one-time-setup), [Use it the first time](../README.md#use-it-the-first-time), the Quick start, [Check the starting state](../README.md#check-the-starting-state), and [How long each step takes](../README.md#how-long-each-step-takes). [What it costs](../README.md#what-it-costs) now says that Azure Copilot's answers cost nothing extra: [Microsoft Learn](https://learn.microsoft.com/azure/copilot/overview#pricing-and-availability) says its capabilities are included at no extra cost, except the Observability Agent.

Checked and found right:

- **`azd up` ran its hooks and didn't stop at `missing required inputs`.** [`infra/main.bicep`](../infra/main.bicep) reads only `environmentName`, `location`, and `principalId`, which azd sets, and `principalType`, which has a default. `RELEASE_REPOSITORY` is an output of [`infra/release.bicep`](../infra/release.bicep), the image repository `requesthub-api`, not a parameter. Every parameter of the modules that azd deploys, in [`infra/jobs.parameters.json`](../infra/jobs.parameters.json), [`app/infra/api.parameters.json`](../../../app/infra/api.parameters.json), and [`worker.parameters.json`](../../../app/infra/worker.parameters.json), comes from `main.bicep`'s outputs or azd's image names, or has a default.
- **No `pip install`.** [`requirements.txt`](../requirements.txt) lists no package, and `preflight.py`, `release.py`, and both test files import only Python's standard library; [`test_trigger.py`](../test_trigger.py) reads `trigger/function_app.py` as text. The trigger's `azure-functions` is installed in Azure, by Flex Consumption's remote build. The Quick start now says that the solution needs no `pip install`.
- **No Foundry agent.** This solution publishes nothing to Microsoft Foundry. The Microsoft Entra objects it creates are RequestHub's app registration and its service principal, which Clean up deletes and purges, and the principals of three managed identities: `id-app-<token>`, `id-github-<token>` (the release identity), and the trigger function's.
- **`azd up` finished in one go.** The `BlobNotFound` that 05-secure-microsoft's `azd up` hit while publishing the API's image didn't happen.
- **The build task's commit trigger worked as step 3 says.** The merge started build `cj4` 2.6 seconds later, and `preflight.py` reported `build-api builds every commit to main`. `Update-BuildTask` turned the trigger off in 7 seconds. Until then the registry's only runs were azd's three builds and the merge's, and afterwards `azd deploy release` built the jobs' image once more: no build started that the session didn't start.
- **The root README's update command** found the copy's `main` up to date, and `git push` had nothing to send.

## Also seen, and left as they are

- **The first try at the build task failed on this machine, not in the README.** At 04:17:14, `az acr task create` failed with `InvalidUri: '.git#main'`: in the coordinating session's terminal, `gh` was signed in to an account that can't see the private copy, so `gh repo view` returned nothing and `$repo` was empty. The block's `Remove-Variable token` then cleared the token, which GitHub shows only once, so the owner regenerated it, with the same settings, at about 04:23, and the block succeeded at 04:24:24. A customer whose `gh` sees the repository, as the prerequisites ask, doesn't meet this.
- **A tenant policy stopped the database 2 seconds after the watch's last call.** A service principal, not the session, stopped the PostgreSQL server from 05:05:37 to 05:07:39, 15 seconds after the rollback job had ended. By 05:11 the API's readiness probe answered 503 (`Failed to connect to <address>:5432`), and the reset's `curl.exe` got no answer for 3 minutes, until the session stopped it. The README's command started the server in 2 minutes 6 seconds, and the reset then answered in under 2 seconds. Every step had ended before the stop: the watch's 1,630 calls all succeeded.
- **The tenant added a network security group to each subnet.** At 05:18:10, about 70 minutes after the virtual networks were created, a service principal created one for each of the five subnets, named after the subnet and tagged like the group (`azd-env-name` and `solution`). The template creates none. The group's deletion removed them.
- **`az acr task logs` stops with `UnicodeEncodeError` when its output goes to a file,** as the README's Troubleshooting says of `az acr build`. The session read the build's log through Azure Resource Manager's `listLogSasUrl` instead.
- **Resource Graph listed the rollback once.** See it work's evidence found it listed twice, a minute or more apart; here it was listed once, at 05:05:57, and still once at 05:17.
- **The watch's median was 314 milliseconds,** against 215 in See it work's second run, measured from the operator's machine both times.
- **The README's portal pointers name `rg-ai-sdlc-release`,** the group of the README's environment; the session used its own, `rg-ai-sdlc-release-fresh`.

## The run

**The starting state, at 04:28:00.** The preflight passed 19 checks. `python release.py status --limit 4` listed one revision, `frdn6h6`, with no label, 100% of traffic, running and healthy with one replica, build `local`, created at 04:13 by `azd up`, and `Release steps running now: none`.

### Step 1: the build

The session pushed a branch with one new Markdown file, `notes/06-release-fresh-setup.md`, opened pull request #22 at 04:30:06, waited for its checks, and merged it at 04:30:43 as `edb1fbf`. The build task's webhook delivered the push to Azure Container Registry, which created run `cj4` at 04:30:45.6. Its log, from Azure Resource Manager:

```text
2026/11/12 04:30:46 Downloading source code...
2026/11/12 04:30:52 Executing step ID: build. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/12 04:32:28 Successfully executed container: build
2026/11/12 04:32:28 Executing step ID: push. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/12 04:32:28 Pushing image: <registry>/requesthub-api:edb1fbfa38fb0b659a2d260f0e2cc1b4506bbe52, attempt 1
2026/11/12 04:32:51 Successfully pushed image: <registry>/requesthub-api:edb1fbfa38fb0b659a2d260f0e2cc1b4506bbe52
2026/11/12 04:32:51 Pushing image: <registry>/requesthub-api:main, attempt 1
2026/11/12 04:32:53 Successfully pushed image: <registry>/requesthub-api:main
2026/11/12 04:32:53 Step ID: build marked as successful (elapsed time in seconds: 95.722341)
2026/11/12 04:32:59 Step ID: push marked as successful (elapsed time in seconds: 25.251254)
Run ID: cj4 was successful after 2m14s
```

**The trigger function**, from Application Insights, with the query of [See it work's evidence](2026-11-01-recorded-run.md#the-trigger-function): an invocation at 04:32:55.131 that succeeded in 1,228 ms, and at 04:32:56.347 `Started release execution j0ec217 for build edb1fbf, image sha256:0e369f51256c, event "<id>"`. Event Grid delivered the push 4 seconds after it, and the release job started 5 seconds after it, against 2 seconds in See it work.

### Step 2: the release job

Execution `j0ec217` ran from 04:32:56 to 04:35:17. Its records, from Log Analytics:

- **release**, 04:33:19 to 04:33:22, **pass**: Releasing build edb1fbf.
- **deploy**, 04:33:22 to 04:33:35, **pass**: Candidate r1112043322 created with 0% of traffic; frdn6h6 still serves 100%. It took 12.9 seconds to create, and the traffic after it was `frdn6h6` 100% (`stable`) and `r1112043322` 0% (`candidate`).
- **gate**, 04:33:35 to 04:35:11, 95.9 s, **pass**: Candidate r1112043322 passed the gate and still has 0% of traffic. It waits for a person's go or no-go. The candidate was ready 33.9 seconds after it was created, and production answered 94 of 94 calls during the step, at a 95th percentile of 22 ms, all with build `local`.

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| candidate | ready | pass | /health/ready HTTP 200 |
| candidate | build | pass | build edb1fbfa38fb, contract requesthub.v1, auth EasyAuth (matches the release commit) |
| candidate | sign-in required | pass | /api/me without a token: HTTP 401 |
| candidate | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| candidate | submit | pass | HTTP 201: REQ-1025 |
| candidate | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1025 |
| candidate | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| candidate | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| candidate | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| candidate | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |
| candidate | bake | pass | 24/24 calls OK over 60 s |

The gate passed 4 minutes 28 seconds after the merge, and 4 minutes 25 seconds after the build started, against 4 minutes 10 seconds in See it work.

### Step 3: the promotion

The session read the gate's record above, then started the promote job at 04:38:31. Execution `vv91apf` ran from 04:38:34 to 04:39:22. Its record, 04:38:56 to 04:39:18, **pass**: r1112043322 is now stable with 100% of traffic, switched in 13 s and verified; frdn6h6 is previous, still running for an instant rollback. It ran the ten checks on the candidate's own URL first, then the same ten on production after the switch, all passed, and production answered 68 of 68 calls during the step, with build `edb1fbf` from 04:39:06.

### Step 4: the drill

The session started the drill job at 04:39:40. Execution `gaa1n5s` ran from 04:39:43 to 04:42:03 and succeeded, because the gate caught the fault. Its records:

- **drill**, 04:40:05 to 04:40:07, **pass**: Deploying the stable build again with a readiness probe that fails; the gate must catch it.
- **deploy**, 04:40:07 to 04:40:21, **pass**: Candidate d1112044007 created with 0% of traffic; r1112043322 still serves 100%.
- **gate**, 04:40:21 to 04:41:42, **fail**: Candidate d1112044007 failed the gate 78 s after it was created: readiness probe failing: container api started 60 s ago and is still not ready (Activating, health None, 1/2 container(s) ready). It never received traffic. Production answered 80 of 80 calls during the step. The evidence the gate read from the candidate's logs:
  - `Azure: Probe of Readiness failed with status code: 503 (x14)`
  - `Azure: Container api failed readiness probe`
  - `Azure: Readiness Probe of Readiness reached failure threshold 3, changing status to Failure.`
  - `App: Health check fault-injection with status Unhealthy with message 'Fault injection: readiness intentionally failing (Faults:FailReadiness).' (x13)`
- **abort**, 04:41:42 to 04:41:56, **pass**: Users stayed on r1112043322 and production passed the smoke test. The candidate was removed 102.5 seconds after it was created, and production passed all ten checks.
- **drill-result**, 04:41:56, **pass**: The gate blocked the bad candidate, which never received traffic, and it was removed.

In See it work, the gate failed 79 seconds after the candidate was created, and the job removed it after 104.

### Step 5 wasn't run

`python release.py status --limit 4` listed the drill's candidate, `d1112044007`, among the inactive revisions, as step 5 says. The session tried to ask Azure Copilot step 5's question with [`tools/screenshot.mjs`](../../../tools/screenshot.mjs), on the container app's **Revisions and replicas**, between 04:21 and 05:03, while the other steps ran, and with four more tries on the portal's home page at about 05:22. The tool opened the Copilot pane with the top bar's button, which showed *New Chat with Copilot* and its message box, but it couldn't type into that box: the tool finds elements in the page's own document, or in a frame named by part of its URL, and the pane's text wasn't in the page's document, nor in a frame under any of the 21 URL fragments the session tried. Reaching it otherwise would have needed a browser client of the session's own on the shared capture browser, which the repository's rules forbid ([CONTRIBUTING.md](../../../CONTRIBUTING.md), "Screenshots"). No question was sent, so Azure Copilot answered nothing. This is about how the session drives the portal: in a browser, a person selects **Copilot** and types the question, as step 5 says.

### Step 6: the rollback

The session started the rollback job at 05:04:30. Execution `7pn1ead` ran from 05:04:33 to 05:05:22. Its record, 05:04:52 to 05:05:18, **pass**: Rolled back in 13 s: frdn6h6 serves 100% of traffic and passed the smoke test. r1112043322 is kept as previous. Production passed all ten checks and answered 68 of 68 calls during the step, with build `local` again from 05:05:02.

**What users saw.** `python release.py watch` called the production URL every second from the session's machine, from 04:29:36. The session stopped it at 05:05:37 the way Ctrl+C does, with `_thread.interrupt_main()`, which raises the same `KeyboardInterrupt` that the watch catches before its summary: `1630/1630 calls succeeded (100.0%), median 314 ms`. Its 95th percentile was 344 ms. Its traffic lines:

```text
04:29:41  traffic → frdn6h6 100%
04:33:36  traffic → frdn6h6 100% [stable], r1112043322 0% [candidate]
04:39:08  traffic → r1112043322 100% [stable], frdn6h6 0% [previous]
04:40:16  traffic → r1112043322 100% [stable], frdn6h6 0% [previous], d1112044007 0% [candidate]
04:41:55  traffic → r1112043322 100% [stable], frdn6h6 0% [previous]
05:05:06  traffic → frdn6h6 100% [stable], r1112043322 0% [previous]
```

The build users got changed only at the promotion, from `local` to `edb1fbf` at 04:39:07, and at the rollback, back to `local` at 05:05:02. The jobs' own calls to production, in the records above, all succeeded too: 310 of 310.

### Step 7: who started each step

From the Activity log, with the query of [See it work's evidence](2026-11-01-recorded-run.md#who-started-each-step), read at 05:06:11, under 2 minutes after the rollback started:

| UTC | Job started | Started by |
| --- | --- | --- |
| 04:32:55.697 | release | the trigger function's managed identity |
| 04:38:33.809 | promote | the owner's account, used by the session |
| 04:39:43.287 | drill | the owner's account, used by the session |
| 05:04:33.280 | rollback | the owner's account, used by the session |

Resource Graph's change history of the API's container app, with the query of [See it work's evidence](2026-11-01-recorded-run.md#traffic-changes), recorded the traffic changes at 04:34:24 (the candidate added, and `frdn6h6` labelled `stable`), 04:39:17 (the promotion), 04:41:09 (the drill's candidate added), 04:42:43 (removed), and 05:05:57 (the rollback).

## The clean-up, and what is left

Before the clean-up, the app registration `RequestHub (ai-sdlc-release-fresh)`, created at 04:07:56, had seven app role assignments on its service principal: the four RequestHub roles of the person who ran `azd up`, and the three that the release identity's smoke test signs in with. The group held seven role assignments, all for the three managed identities: the release identity's Container Apps Contributor and Container Apps Jobs Reader on the group and AcrPull on the registry, the app identity's AcrPull and Storage Blob Data Contributor, and the trigger function's Storage Blob Data Owner on its storage and Container Apps Jobs Contributor on the release job.

The session deleted the build task's webhook from the copy first, as Clean up says, keeping the token, which the owner chose to keep. `azd down --purge --force` purged the Log Analytics workspace `log-<token>`, deleted the resource group, and ended with `SUCCESS: Your application was removed from Azure in 27 minutes 47 seconds.` From about 05:24 on, only the Container Apps environment, its virtual network, and one of the tenant's network security groups were left in the group, and the environment read `ScheduledForDelete`. The first `azd down --purge` is finding 4, and `$sp` and its purge are finding 3.

Checked between 05:47 and 05:52:

- `az group exists -n rg-ai-sdlc-release-fresh`: `false`, and no resource group named after the environment.
- No resource tagged `azd-env-name=ai-sdlc-release-fresh`, and none named with the setup's token, anywhere in the subscription.
- Nothing soft-deleted: no deleted Key Vault in the subscription (the solution creates none), and no deleted Log Analytics workspace, Cognitive Services account, or App Configuration store named with the token.
- No role assignment whose scope names the group, none for the three managed identities, and none of the subscription's, inherited ones included, created during the setup: 160, seven fewer than before the clean-up.
- In Microsoft Entra ID, no application `RequestHub (ai-sdlc-release-fresh)` and no service principal for its client id, active or in the recycle bin, and no app role assignment of the signed-in person on it.
- In Entra's recycle bin, the service principals of the group's three managed identities, deleted with it at 05:20:00 and 05:20:29: `id-github-<token>` (the release identity), `id-app-<token>`, and `func-release-<token>` (the trigger function's). Entra refused to purge each of them: `Authorization_RequestDenied`, *Insufficient privileges to complete the operation.*
- The copy's only webhook is 05-secure-microsoft's, for `pull_request` events: the build task's was deleted at 05:18:43.
- The live deployment, untouched: `rg-ai-sdlc-release` still exists, with its five jobs, its build task `build-api` with the commit trigger on, and its app registration, `RequestHub (ai-sdlc-release)`.
- The capture browser that the session started is closed.

What is left:

- **Two deployment records** at subscription scope, as for every azd deployment: that of `azd up`, and the empty one that `azd down` records. They cost nothing, and the template has no secure parameter.
- **The three managed identities' service principals,** in Entra's recycle bin until it removes them, 30 days after 05:20.
- **The GitHub token** `ai-sdlc-release-fresh`, which could only read the copy's contents and commit statuses and manage its webhooks, until it was deleted on 12 November 2026, after the seven fresh setups, as the owner asked. Nothing used it after the clean-up: the build task that held it was deleted with the registry, and its webhook was gone.
- **In the copy,** `main` at `edb1fbf` with the step's new note, `notes/06-release-fresh-setup.md`, and the merged pull request #22, whose branch was deleted. The copy was deleted on 12 November 2026, after the seven fresh setups, as the owner asked.
- **The local clone's azd environment,** which held no secret: the solution stores none there. The clone was deleted with the copy.

## What it cost

The resource group existed from 04:00 until azd deleted it at 05:47: 1 hour 47 minutes. At list prices:

- the copy's resource group, at the $120 a month that the [Quick start](../README.md#quick-start) measured: about 30 cents;
- the two private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1 if it bills each a whole month;
- five builds in the registry, about 8 minutes in all, and four release job executions, about 6 minutes at a quarter of a CPU: a few cents;
- the trigger function's one invocation and Event Grid's one event: inside their free grants;
- Azure Copilot: nothing, and no question was sent.

So between about 35 cents and about $1.35. In GitHub Actions, the copy ran 5 jobs for 35 seconds, 5 minutes as billed in a private repository, where each job counts as at least a minute: *Repository checks*' two jobs on the pull request and two after the merge, and the feature bounds check. No model ran.
