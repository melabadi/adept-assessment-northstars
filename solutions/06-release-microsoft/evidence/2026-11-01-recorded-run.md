# Evidence: the recorded run of 1 November 2026

What Azure recorded during [the run in See it work](../README.md#see-it-work), exported so that anyone can check it without signing in to Azure. Times are UTC: the run went from 23:58:49 on 31 October to 00:49:11 on 1 November.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-release`, with the commands shown in each section, run from `solutions/06-release-microsoft`. The exports keep only the fields that each section names. `<registry>` stands for the registry's host name, `<token>` for the unique part of the resource names, and `<id>` for an event id; e-mail addresses and principal ids are replaced by who they are.
- **Kept here because Azure's records expire:** Log Analytics keeps the release records and the function's log for 30 days, until about 1 December 2026; Resource Graph keeps its change history for 14 days, until about 15 November; and the Activity log keeps 90 days.
- **A second run** of steps 1 to 6, from 01:04 to 01:17 on build 786e099, gave the users' view in step 6 and the screenshot of who started each step in step 7. Its records are in [The second run](#the-second-run).
- **A release that a merge started**, at 03:05 the same night with the build task's commit trigger on, backs the example in *Use it the first time*: [A merge with the commit trigger on](#a-merge-with-the-commit-trigger-on).
- **Measured in the operator's terminal:** the starting state, and the times of Azure Copilot's answers. [The starting state](#the-starting-state) and [Azure Copilot](#azure-copilot) say so.

## The code that ran

- **The build:** commit [74e59ec](https://github.com/melabadi/adept-assessment-northstars/commit/74e59ec) of `main`, the merge of pull request [#238](https://github.com/melabadi/adept-assessment-northstars/pull/238), built by the registry's build task `build-api` ([`acr-build.yaml`](../acr-build.yaml)) as ACR run `cjm`.
- **The release jobs and the trigger function:** an early version of pull request [#248](https://github.com/melabadi/adept-assessment-northstars/pull/248), which moved the trigger from a Logic App to this Python Azure Function, deployed from the working tree before that pull request's first commit: the function at 23:29 and the jobs at 23:31, then Event Grid's subscription to the function at 23:33, as the Activity log records. At 01:03, between this run and the second, the jobs were deployed again with small fixes from a review, among them the wording of the message for a push that already started a release.
- **Since then:** #248's later commits made the function log the build and the execution's suffix instead of the registry's host and the job's name (the log lines below show the earlier format, masked). Pull request [#298](https://github.com/melabadi/adept-assessment-northstars/pull/298) gave the function Container Apps Jobs Contributor instead of Jobs Operator on the release job, because Azure began to require write permission on a job to start it with settings of its own. Neither changes what this run shows.

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 23:44:52 | The preflight: 18 checks passed; Build warned that the build task's commit trigger was off | [The starting state](#the-starting-state) |
| 23:44:59 | `release.py status`: r1029153655 (build 440297a) stable with 100% of traffic, r1029165021 previous, no candidate, no release step running | [The starting state](#the-starting-state) |
| 23:58:49 | The operator started the build task for commit 74e59ec: ACR run `cjm` | [The build](#the-build) |
| 23:58:55 | The build step started | [The build](#the-build) |
| 00:00:40 | `requesthub-api:74e59ec…` was pushed | [The build](#the-build) |
| 00:00:41 | Event Grid called the trigger function, which ran for 728 ms | [The trigger function](#the-trigger-function) |
| 00:00:42 | The function's identity started release execution `bqx6yca` | [Who started each step](#who-started-each-step) |
| 00:01:19 | Candidate r1101000111 was created with 0% of traffic | [The release](#the-release-execution-bqx6yca) |
| 00:01:50 | The candidate was ready, 31 seconds after it was created | [The release](#the-release-execution-bqx6yca) |
| 00:03:00 | The gate passed all 11 checks; the candidate waited for a person | [The release](#the-release-execution-bqx6yca) |
| 00:03:06 | Execution `bqx6yca` ended: 2 minutes 24 seconds | [The release jobs](#the-release-jobs) |
| 00:03:48 | The build's second tag, `:main`, was pushed; run `cjm` ended at 00:03:56 | [The build](#the-build) |
| 00:15:06 | The operator started promote execution `3axbvgs`, under the owner's account | [Who started each step](#who-started-each-step) |
| 00:15:45 | Production served build 74e59ec; traffic switched in 13 seconds | [The promotion](#the-promotion-execution-3axbvgs) |
| 00:16:04 | Execution `3axbvgs` ended: 58 seconds | [The release jobs](#the-release-jobs) |
| 00:17:29 | The operator started drill execution `htyg5y8`, under the owner's account | [Who started each step](#who-started-each-step) |
| 00:18:04 | Drill candidate d1101001758 was created with a readiness probe that fails | [The drill](#the-drill-execution-htyg5y8) |
| 00:19:23 | The gate failed, 79 seconds after the candidate was created | [The drill](#the-drill-execution-htyg5y8) |
| 00:19:48 | The candidate was removed, 104 seconds after it was created; production then passed all 10 checks | [The drill](#the-drill-execution-htyg5y8) |
| 00:19:51 | Execution `htyg5y8` ended: 2 minutes 22 seconds | [The release jobs](#the-release-jobs) |
| 00:44:40 | Azure Copilot's first answer, which asked for the error message, was on screen | [Azure Copilot](#azure-copilot) |
| 00:47:25 | Its second answer, the one in step 5, was on screen | [Azure Copilot](#azure-copilot) |
| 00:48:26 | The operator started rollback execution `efgfutt`, under the owner's account | [Who started each step](#who-started-each-step) |
| 00:48:58 | Production served build 440297a again; traffic switched in 16 seconds | [The rollback](#the-rollback-execution-efgfutt) |
| 00:49:11 | Execution `efgfutt` ended: 45 seconds | [The release jobs](#the-release-jobs) |

## The starting state

The operator's terminal, 14 minutes before the build: the preflight, then `release.py status` as the screenshot before step 1 shows it. The production, stable, and previous URLs, and the hint under the Build warning, are left out.

```text
PS> python preflight.py
PASS  Azure CLI  signed in as <account>
PASS  App        ca-api-<token>: activeRevisionsMode Multiple
PASS  App        ingress external
PASS  Traffic    r1029153655 serves 100% (label stable)
PASS  Probes     readiness /health/ready; startup and liveness present
PASS  Database   psql-<token> is Ready
PASS  Production /health/ready answers 200
PASS  Jobs       release jobs: release, promote, abort, rollback, drill
PASS  Jobs       all run as the release identity
PASS  Jobs       none running now
PASS  Identity   Container Apps Contributor on rg-ai-sdlc-release
PASS  Identity   Container Apps Jobs Reader on rg-ai-sdlc-release
PASS  Identity   AcrPull on cr<token>
PASS  Trigger    function release_on_push deployed, app running
PASS  Trigger    only the function may start the release job (Container Apps Jobs Operator)
PASS  Trigger    Event Grid topic evgt-registry-<token> watches registry cr<token>
PASS  Trigger    Event Grid sends the function each push of requesthub-api:<tag> except :main, one at a time
WARN  Build      build-api exists; its commit trigger is off
PASS  Workbook   RequestHub release records

18 passed, 1 warnings, 0 failed

PS> python release.py status --limit 4
RequestHub API ca-api-<token> in rg-ai-sdlc-release

REVISION                 LABEL      TRAFFIC  ACTIVE STATE      HEALTH    REPLICAS  BUILD     CREATED (UTC)
r1029165021              previous        0%  yes    Running    Healthy          1  41713b4   2026-10-29 16:50
r1029153655              stable        100%  yes    Running    Healthy          1  440297a   2026-10-29 15:37
r1031232109              -               0%  no     Stopped    Healthy          0  276ee2d   2026-10-31 23:21
r1031042306              -               0%  no     Stopped    Healthy          0  276ee2d   2026-10-31 04:23

Release steps running now: none
```

## The build

ACR run `cjm`, which the operator started for commit 74e59ec with `az acr task run --registry <registry> --name build-api --context <repository URL>.git#74e59ece58bf1450cd1d1f9e61332698e5d8503a --set commit=74e59ece58bf1450cd1d1f9e61332698e5d8503a`, because the task's commit trigger was off while other pull requests merged that evening.

```powershell
az acr task show-run --registry (azd env get-value AZURE_CONTAINER_REGISTRY_NAME) --run-id cjm --query "[status, createTime, startTime, finishTime]" -o tsv
```

```text
Succeeded
2026-10-31T23:58:49.850148+00:00
2026-10-31T23:58:50.046118+00:00
2026-11-01T00:03:56.298809+00:00
```

The run's log (in the portal: the registry › **Services** › **Tasks** › **Runs** › `cjm`), its step lines:

```text
2026/10/31 23:58:50 Downloading source code...
2026/10/31 23:58:55 Executing step ID: build. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/01 00:00:26 Successfully executed container: build
2026/11/01 00:00:26 Executing step ID: push. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/01 00:00:26 Pushing image: <registry>/requesthub-api:74e59ece58bf1450cd1d1f9e61332698e5d8503a, attempt 1
2026/11/01 00:00:40 Successfully pushed image: <registry>/requesthub-api:74e59ece58bf1450cd1d1f9e61332698e5d8503a
2026/11/01 00:00:40 Pushing image: <registry>/requesthub-api:main, attempt 1
2026/11/01 00:03:48 Successfully pushed image: <registry>/requesthub-api:main
2026/11/01 00:03:48 Step ID: build marked as successful (elapsed time in seconds: 91.043185)
2026/11/01 00:03:53 Step ID: push marked as successful (elapsed time in seconds: 202.039020)
Run ID: cjm was successful after 5m4s
```

The push of `requesthub-api:74e59ec…`, 1 minute 50 seconds after the run started, is what started the release; Event Grid's subscription leaves out `:main`. The second push, of the same image as `:main`, took 3 minutes 8 seconds this time (1 second in the second run), while the release was already under way.

## The trigger function

What the function `release_on_push` logged, from Application Insights, which keeps its data in the same Log Analytics workspace. Each pushed build is one invocation, and a successful one logs the execution it started. The function has logged the build and the execution's suffix since #248's later commits; these lines are in the earlier format, with the registry's host and the job's name masked.

```powershell
$kql = "union (AppRequests | where AppRoleName startswith 'func-release' | project TimeGenerated, what = strcat('invocation ', iff(Success, 'succeeded', 'failed'), ' in ', round(DurationMs), ' ms')), (AppTraces | where AppRoleName startswith 'func-release' and Message startswith 'Started release' | project TimeGenerated, what = Message), (AppExceptions | where AppRoleName startswith 'func-release' | summarize arg_min(TimeGenerated, *) by OperationId | project TimeGenerated, what = strcat('EventRejected: ', extract(@'No release was started: (.*?)\. Event Grid', 1, InnermostMessage))) | where TimeGenerated between (datetime(2026-10-31T23:30:00Z) .. datetime(2026-11-01T00:50:00Z)) | order by TimeGenerated asc"
az monitor log-analytics query --workspace (azd env get-value LOG_ANALYTICS_WORKSPACE_ID) --analytics-query $kql --query "[].[TimeGenerated, what]" -o tsv
```

During the run:

| UTC | What the function logged |
| --- | --- |
| 00:00:41.771 | invocation succeeded in 728 ms |
| 00:00:42.494 | Started release execution caj-release-<token>-bqx6yca for <registry>/requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269, tag "74e59ece58bf1450cd1d1f9e61332698e5d8503a", event "<id>" |

**Before the run**, from 23:34 to 23:39, the trigger was tested. Twelve events forged to look like Event Grid's, posted to the function's Event Grid endpoint, each failed with `EventRejected` and the checks it failed, and started nothing: another registry's topic, quotes in the repository, quotes in the digest, an uppercase digest, another event type, another host, a look-alike letter in the host, everything wrong at once, and four tags that aren't a commit (`main`, a short commit, an uppercase commit, and quotes after a commit). At 23:35:10 an image that had already been released was pushed again, and the release job it started skipped it. At 23:38:42, the release job started by hand with `COMMIT=main`, then with no `COMMIT`, refused to release anything. These are the errors in the screenshots of step 1.

| UTC | Invocation |
| --- | --- |
| 23:34:31.320 | failed in 56 ms: EventRejected, topic: the event does not come from this registry |
| 23:34:33.162 | failed in 56 ms: EventRejected, repository: the image is not requesthub-api |
| 23:34:34.951 | failed in 48 ms: EventRejected, digest: the image is not named by sha256 and 64 lowercase hexadecimal characters |
| 23:34:36.705 | failed in 52 ms: EventRejected, digest: the image is not named by sha256 and 64 lowercase hexadecimal characters |
| 23:34:37.025 | failed in 10 ms: EventRejected, eventType: the event is not an image push |
| 23:34:37.311 | failed in 8 ms: EventRejected, host: the image is not in this registry |
| 23:34:38.860 | failed in 55 ms: EventRejected, host: the image is not in this registry |
| 23:34:39.208 | failed in 8 ms: EventRejected, topic: the event does not come from this registry; eventType: the event is not an image push; host: the image is not in this registry; repository: the image is not requesthub-api; digest: the image is not named by sha256 and 64 lowercase hexadecimal characters |
| 23:34:39.471 | failed in 6 ms: EventRejected, tag: the image is not tagged with a commit, 40 lowercase hexadecimal characters |
| 23:34:41.126 | failed in 43 ms: EventRejected, tag: the image is not tagged with a commit, 40 lowercase hexadecimal characters |
| 23:34:41.523 | failed in 8 ms: EventRejected, tag: the image is not tagged with a commit, 40 lowercase hexadecimal characters |
| 23:34:41.780 | failed in 6 ms: EventRejected, tag: the image is not tagged with a commit, 40 lowercase hexadecimal characters |
| 23:35:10.292 | succeeded in 812 ms |
| 23:35:11.102 | Started release execution caj-release-<token>-whhrtt8 for <registry>/requesthub-api@sha256:c7cd86a85f06053453c15c2a26b9e0a3c599fddc4ef6e4412f284010cea2271a, tag "276ee2d5cffaf7ec4a6263e7ba946a5a36e8c9b3", event "<id>" |

The release records of those executions:

- 23:35:37, execution whhrtt8, skipped: Event Grid delivered the push of build 276ee2d again: execution caj-release-<token>-ny93d6s got it first (succeeded). Nothing to release; to release this build again, run the release job yourself.
- 23:39:07, execution lsx0k9o, fail: The pushed build's tag "main" is not a 40-character commit: not released.
- 23:39:08, execution 4eeahfp, fail: The pushed build's tag "" is not a 40-character commit: not released.

## The release jobs

Each step ran as one execution of its Container Apps job. The executions are named after the job, `caj-<step>-<token>-`, then the suffix shown here.

```powershell
$rg = azd env get-value AZURE_RESOURCE_GROUP
foreach ($step in 'release', 'promote', 'drill', 'rollback') {
  $job = (azd env get-value SERVICE_RELEASE_NAME) -replace '^caj-release-', "caj-$step-"
  az containerapp job execution list -g $rg -n $job `
    --query "[?properties.startTime >= '2026-10-31T23:58:00' && properties.startTime <= '2026-11-01T01:30:00'].[name, properties.status, properties.startTime, properties.endTime]" -o tsv |
    ForEach-Object { $_ -replace '^caj-\w+-[a-z0-9]+-', '' }
}
```

| Execution | Job | Status | Started | Ended | Took |
| --- | --- | --- | --- | --- | --- |
| bqx6yca | release | Succeeded | 00:00:42 | 00:03:06 | 2 min 24 s |
| 3axbvgs | promote | Succeeded | 00:15:06 | 00:16:04 | 58 s |
| htyg5y8 | drill | Succeeded | 00:17:29 | 00:19:51 | 2 min 22 s |
| efgfutt | rollback | Succeeded | 00:48:26 | 00:49:11 | 45 s |

## The release records

Each step of each job wrote one record to its log, the line `RELEASE-RECORD {...}`, which Log Analytics keeps and the workbook **RequestHub release records** shows. A job's first record comes 17 to 28 seconds after its execution starts, the time Azure takes to start its container.

```powershell
$kql = "ContainerAppConsoleLogs_CL | where TimeGenerated between (datetime(2026-10-31T23:58:00Z) .. datetime(2026-11-01T00:50:00Z)) | where ContainerName_s == 'release' and Log_s startswith 'RELEASE-RECORD ' | summarize by Log_s"
az monitor log-analytics query --workspace (azd env get-value LOG_ANALYTICS_WORKSPACE_ID) --analytics-query $kql --query "[].Log_s" -o tsv
```

### The release, execution bqx6yca

**release** (release job, execution bqx6yca), 00:01:08 to 00:01:10, 2.7 s, **pass**: Releasing build 74e59ec.

- `stable`: r1029153655, build 440297a, image requesthub-api@sha256:229ce4e54f81778527355f5472ffd8f9469fd7ae55cf88c7ddb59468d739138c

**deploy** (release job, execution bqx6yca), 00:01:10 to 00:01:27, 16.8 s, **pass**: Candidate r1101000111 created with 0% of traffic; r1029153655 still serves 100%.

- `secondsToCreate`: 15.9
- `candidate`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269, fault none
- `stable`: r1029153655, build 440297a, image requesthub-api@sha256:229ce4e54f81778527355f5472ffd8f9469fd7ae55cf88c7ddb59468d739138c
- traffic after: r1029153655 100% (stable), r1029165021 0% (previous), r1101000111 0% (candidate)

**gate** (release job, execution bqx6yca), 00:01:27 to 00:03:00, 93.0 s, **pass**: Candidate r1101000111 passed the gate and still has 0% of traffic. It waits for a person's go or no-go.

- `secondsToReady`: 31.1
- production, called about once a second during the step: 91 of 91 calls succeeded, 95th percentile 23 ms; builds served: 440297a from 00:01:28
- `candidate`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- `stable`: r1029153655, build 440297a, image requesthub-api@sha256:229ce4e54f81778527355f5472ffd8f9469fd7ae55cf88c7ddb59468d739138c

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| candidate | ready | pass | /health/ready HTTP 200 |
| candidate | build | pass | build 74e59ece58bf, contract requesthub.v1, auth EasyAuth (matches the release commit) |
| candidate | sign-in required | pass | /api/me without a token: HTTP 401 |
| candidate | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| candidate | submit | pass | HTTP 201: REQ-1029 |
| candidate | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1029 |
| candidate | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| candidate | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| candidate | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| candidate | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |
| candidate | bake | pass | 24/24 calls OK over 60 s |

### The promotion, execution 3axbvgs

**promote** (promote job, execution 3axbvgs), 00:15:34 to 00:15:56, 22.4 s, **pass**: r1101000111 is now stable with 100% of traffic, switched in 13 s and verified; r1029153655 is previous, still running for an instant rollback.

- `secondsToSwitch`: 13.1
- production, called about every quarter second during the step: 68 of 68 calls succeeded, 95th percentile 32 ms; builds served: 440297a from 00:15:36, 74e59ec from 00:15:45
- `candidate`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- `stable`: r1029153655, build 440297a, image requesthub-api@sha256:229ce4e54f81778527355f5472ffd8f9469fd7ae55cf88c7ddb59468d739138c
- traffic after: r1101000111 100% (stable), r1029153655 0% (previous)

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| candidate | ready | pass | /health/ready HTTP 200 |
| candidate | build | pass | build 74e59ece58bf, contract requesthub.v1, auth EasyAuth (matches r1101000111's commit) |
| candidate | sign-in required | pass | /api/me without a token: HTTP 401 |
| candidate | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| candidate | submit | pass | HTTP 201: REQ-1030 |
| candidate | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1030 |
| candidate | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| candidate | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| candidate | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| candidate | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |
| production | ready | pass | /health/ready HTTP 200 |
| production | build | pass | build 74e59ece58bf, contract requesthub.v1, auth EasyAuth (matches r1101000111's commit) |
| production | sign-in required | pass | /api/me without a token: HTTP 401 |
| production | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| production | submit | pass | HTTP 201: REQ-1031 |
| production | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1031 |
| production | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| production | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| production | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| production | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |

### The drill, execution htyg5y8

**drill** (drill job, execution htyg5y8), 00:17:54 to 00:17:57, 3.8 s, **pass**: Deploying the stable build again with a readiness probe that fails; the gate must catch it.

**deploy** (drill job, execution htyg5y8), 00:17:57 to 00:18:12, 14.8 s, **pass**: Candidate d1101001758 created with 0% of traffic; r1101000111 still serves 100%.

- `secondsToCreate`: 13.7
- `candidate`: d1101001758, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269, fault fail-readiness
- `stable`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- traffic after: r1101000111 100% (stable), r1029153655 0% (previous), d1101001758 0% (candidate)

**gate** (drill job, execution htyg5y8), 00:18:12 to 00:19:34, 81.5 s, **fail**: Candidate d1101001758 failed the gate 79 s after it was created: readiness probe failing: container api started 62 s ago and is still not ready (Activating, health None, 1/2 container(s) ready). It never received traffic.

- `secondsToDetectFailure`: 78.9
- production, called about once a second during the step: 80 of 80 calls succeeded, 95th percentile 22 ms; builds served: 74e59ec from 00:18:13
- `candidate`: d1101001758, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- `stable`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| candidate | ready | FAIL | readiness probe failing: container api started 62 s ago and is still not ready (Activating, health None, 1/2 container(s) ready) |

What the gate read from the candidate's live logs before removing it:

- Azure: Probe of Readiness failed with status code: 503 (x15)
- Azure: Container api failed readiness probe
- Azure: Readiness Probe of Readiness reached failure threshold 3, changing status to Failure.
- App: Health check fault-injection with status Unhealthy with message 'Fault injection: readiness intentionally failing (Faults:FailReadiness).' (x15)

**abort** (drill job, execution htyg5y8), 00:19:34 to 00:19:49, 15.4 s, **pass**: Users stayed on r1101000111 and production passed the smoke test.

- `secondsFromCandidateToRemoved`: 104.2
- `candidate`: d1101001758, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- `stable`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- traffic after: r1101000111 100% (stable), r1029153655 0% (previous)

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| production | ready | pass | /health/ready HTTP 200 |
| production | build | pass | build 74e59ece58bf, contract requesthub.v1, auth EasyAuth (matches r1101000111's commit) |
| production | sign-in required | pass | /api/me without a token: HTTP 401 |
| production | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| production | submit | pass | HTTP 201: REQ-1032 |
| production | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1032 |
| production | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| production | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| production | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| production | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |

**drill-result** (drill job, execution htyg5y8), 00:19:49 to 00:19:49, 0.0 s, **pass**: The gate blocked the bad candidate, which never received traffic, and it was removed.

### The rollback, execution efgfutt

**rollback** (rollback job, execution efgfutt), 00:48:43 to 00:49:09, 25.8 s, **pass**: Rolled back in 16 s: r1029153655 serves 100% of traffic and passed the smoke test. r1101000111 is kept as previous.

- `secondsToSwitch`: 16.0
- production, called about every quarter second during the step: 79 of 79 calls succeeded, 95th percentile 24 ms; builds served: 74e59ec from 00:48:47, 440297a from 00:48:58
- `stable`: r1101000111, build 74e59ec, image requesthub-api@sha256:0a6a960729ce5c1c9cc62a9c2db6cfb28778f419975783f7a344ffad8458c269
- `rolledBackTo`: r1029153655, build 440297a, image requesthub-api@sha256:229ce4e54f81778527355f5472ffd8f9469fd7ae55cf88c7ddb59468d739138c
- traffic after: r1029153655 100% (stable), r1101000111 0% (previous)

| Target | Check | Result | Detail |
| --- | --- | --- | --- |
| production | ready | pass | /health/ready HTTP 200 |
| production | build | pass | build 440297abda3f, contract requesthub.v1, auth EasyAuth (matches r1029153655's commit) |
| production | sign-in required | pass | /api/me without a token: HTTP 401 |
| production | signed in | pass | HTTP 200: roles Approver, Requester, Reviewer |
| production | submit | pass | HTTP 201: REQ-1033 |
| production | retry is safe | pass | same Idempotency-Key: HTTP 200, REQ-1033 |
| production | read | pass | HTTP 200: Submitted, canDecide=False (self_approval) |
| production | attachment | pass | upload HTTP 201, download HTTP 200, 50 bytes identical |
| production | approval guard | pass | self-approval: HTTP 403 decision.self_approval |
| production | history | pass | HTTP 200: 2 audit event(s): request.created, attachment.added |

## Who started each step

From the Activity log, which records every start of a job with its caller. The callers are replaced by who they are: the repository owner's account, which the operator used, or the trigger function's managed identity. In the same minutes, every entry for the API's container app (22 of them, for its revisions, traffic, labels, and deactivations) names the release identity, which the jobs run as.

```powershell
az monitor activity-log list -g (azd env get-value AZURE_RESOURCE_GROUP) --start-time 2026-10-31T23:58:00Z --end-time 2026-11-01T00:50:00Z --max-events 2000 `
  --query "[?operationName.value=='Microsoft.App/jobs/start/action' && status.value=='Started'].[eventTimestamp, resourceId, caller]" -o tsv
```

| UTC | Job started | Started by |
| --- | --- | --- |
| 00:00:42.227 | release | the trigger function's managed identity |
| 00:15:06.770 | promote | the owner's account, used by the operator |
| 00:17:29.746 | drill | the owner's account, used by the operator |
| 00:48:26.247 | rollback | the owner's account, used by the operator |

## Traffic changes

From Azure Resource Graph's change history of the API's container app, which the workbook also shows. Resource Graph records a change a few seconds to a minute after it happens, and compares the traffic list by position: the release records' *traffic after* lines above say the same in plain words. It lists the rollback twice, at 00:49:36 and at 00:58:49, although the Activity log has one rollback and no other change to the app in between, and the second run started from the rolled-back state.

```powershell
$app = azd env get-value API_APP_NAME
$q = "resourcechanges | where tostring(properties.targetResourceId) endswith '/containerApps/$app' | extend At = todatetime(properties.changeAttributes.timestamp) | where At between (datetime(2026-10-31T23:58:00Z) .. datetime(2026-11-01T01:00:00Z)) | mv-expand bagexpansion = array Change = properties.changes | extend Property = replace_string(tostring(Change[0]), 'properties.configuration.ingress.', ''), Before = tostring(Change[1].previousValue), After = tostring(Change[1].newValue) | where Property startswith 'traffic' | project At, Property, Before = iff(Property endswith 'revisionName', tostring(split(Before, '--')[1]), Before), After = iff(Property endswith 'revisionName', tostring(split(After, '--')[1]), After) | order by At asc, Property asc"
az graph query --first 100 -q $q --query "data[].[At, Property, Before, After]" -o tsv
```

| Recorded (UTC) | Property | Before | After |
| --- | --- | --- | --- |
| 00:02:15 | traffic[0].label |  | candidate |
| 00:02:15 | traffic[0].revisionName |  | r1101000111 |
| 00:02:15 | traffic[0].weight |  | 0 |
| 00:15:56 | traffic[0].label | stable | previous |
| 00:15:56 | traffic[0].weight | 100 | 0 |
| 00:15:56 | traffic[1].label | candidate | stable |
| 00:15:56 | traffic[1].revisionName | r1029165021 |  |
| 00:15:56 | traffic[1].weight | 0 | 100 |
| 00:18:59 | traffic[0].label |  | candidate |
| 00:18:59 | traffic[0].revisionName |  | d1101001758 |
| 00:18:59 | traffic[0].weight |  | 0 |
| 00:20:36 | traffic[0].label | candidate |  |
| 00:20:36 | traffic[0].revisionName | d1101001758 |  |
| 00:20:36 | traffic[0].weight | 0 |  |
| 00:49:36 | traffic[0].label | stable | previous |
| 00:49:36 | traffic[0].weight | 100 | 0 |
| 00:49:36 | traffic[1].label | previous | stable |
| 00:49:36 | traffic[1].weight | 0 | 100 |
| 00:58:49 | traffic[0].label | stable | previous |
| 00:58:49 | traffic[0].weight | 100 | 0 |
| 00:58:49 | traffic[1].label | previous | stable |
| 00:58:49 | traffic[1].weight | 0 | 100 |

## Azure Copilot

Azure Copilot's answers aren't kept anywhere a visitor can open; the screenshot in step 5 shows the second answer. The operator asked the same question twice, in the portal, on the container app: *In a few sentences: why did revision d1101001758 of my container app never become ready, and did it receive any traffic?*, and confirmed the resource group each time Copilot asked. Each answer was captured about a minute and a half after its question.

- **On screen at 00:44:40:** Copilot asked for more details about the specific error message or behavior, and suggested three follow-up questions about the revision's errors, its logs, and the troubleshooting steps tried.
- **On screen at 00:47:25:** Copilot answered from general knowledge: a revision that never became ready typically receives no traffic, which goes on to the last healthy revision; to investigate, check the revision's events and status, its container logs, and its ingress and readiness settings, and look at the deployment history for failed image pulls, crashes, or configuration errors.

Neither answer said what this revision's probes or logs had reported. The drill's record above did: HTTP 503 from the readiness probe, 15 times, and the app's health check naming the injected fault.

## The second run

The same steps from 1 to 6, from 01:04 to 01:17, on build [786e099](https://github.com/melabadi/adept-assessment-northstars/commit/786e099), the merge of pull request [#244](https://github.com/melabadi/adept-assessment-northstars/pull/244), while `python release.py watch` called the production URL every second from the operator's machine. During the first run, that machine lost its network for two minutes during the release and slept for eight minutes after the drill, so its own count of calls from then isn't usable; the release jobs' calls to production from Azure, in the records above, all succeeded. The second run's build, ACR run `cjp`, pushed its image at 01:06:39, 1 minute 49 seconds after the run started, and the release job started 2 seconds after the push. Its executions:

| Execution | Job | Status | Started | Ended | Took |
| --- | --- | --- | --- | --- | --- |
| 9mf335v | release | Succeeded | 01:06:41 | 01:08:56 | 2 min 15 s |
| 2pytan7 | promote | Succeeded | 01:09:02 | 01:09:58 | 56 s |
| rmy43j9 | drill | Succeeded | 01:10:04 | 01:12:32 | 2 min 28 s |
| 1fcbkdk | rollback | Succeeded | 01:12:39 | 01:13:23 | 44 s |

Its release records:

| Started | Job · step | Result | Seconds | Checks passed | Production calls OK | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 01:07:07 | release · release | pass | 2.7 |  |  | Releasing build 786e099. |
| 01:07:10 | release · deploy | pass | 13.8 |  |  | Candidate r1101010710 created with 0% of traffic; r1029153655 still serves 100%. |
| 01:07:23 | release · gate | pass | 90.2 | 11 of 11 | 88 of 88 | Candidate r1101010710 passed the gate and still has 0% of traffic. It waits for a person's go or no-go. |
| 01:09:31 | promote · promote | pass | 22.6 | 20 of 20 | 69 of 69 | r1101010710 is now stable with 100% of traffic, switched in 13 s and verified; r1029153655 is previous, still running for an instant rollback. |
| 01:10:31 | drill · drill | pass | 1.9 |  |  | Deploying the stable build again with a readiness probe that fails; the gate must catch it. |
| 01:10:32 | drill · deploy | pass | 14.4 |  |  | Candidate d1101011033 created with 0% of traffic; r1101010710 still serves 100%. |
| 01:10:47 | drill · gate | fail | 81.3 | 0 of 1 | 80 of 80 | Candidate d1101011033 failed the gate 78 s after it was created: readiness probe failing: container api started 61 s ago and is still not ready (Activating, health None, 1/2 container(s) ready). It never received traffic. |
| 01:12:08 | drill · abort | pass | 14.7 | 10 of 10 |  | Users stayed on r1101010710 and production passed the smoke test. |
| 01:12:23 | drill · drill-result | pass | 0.0 |  |  | The gate blocked the bad candidate, which never received traffic, and it was removed. |
| 01:12:59 | rollback · rollback | pass | 20.8 | 10 of 10 | 68 of 68 | Rolled back in 13 s: r1029153655 serves 100% of traffic and passed the smoke test. r1101010710 is kept as previous. |

Who started each step, and the traffic changes, as the workbook in step 7 shows them. Resource Graph again listed the rollback twice, at 01:13:11 and at 01:14:36:

| UTC | Job started | Started by |
| --- | --- | --- |
| 01:06:41.007 | release | the trigger function's managed identity |
| 01:09:02.531 | promote | the owner's account, used by the operator |
| 01:10:04.174 | drill | the owner's account, used by the operator |
| 01:12:39.262 | rollback | the owner's account, used by the operator |

| Recorded (UTC) | Property | Before | After |
| --- | --- | --- | --- |
| 01:08:12 | traffic[0].label |  | candidate |
| 01:08:12 | traffic[0].revisionName |  | r1101010710 |
| 01:08:12 | traffic[0].weight |  | 0 |
| 01:09:53 | traffic[0].label | stable | previous |
| 01:09:53 | traffic[0].weight | 100 | 0 |
| 01:09:53 | traffic[1].label | candidate | stable |
| 01:09:53 | traffic[1].revisionName | r1101000111 |  |
| 01:09:53 | traffic[1].weight | 0 | 100 |
| 01:11:35 | traffic[0].label |  | candidate |
| 01:11:35 | traffic[0].revisionName |  | d1101011033 |
| 01:11:35 | traffic[0].weight |  | 0 |
| 01:13:02 | traffic[0].label | candidate |  |
| 01:13:02 | traffic[0].revisionName | d1101011033 |  |
| 01:13:02 | traffic[0].weight | 0 |  |
| 01:13:11 | traffic[0].label | stable | previous |
| 01:13:11 | traffic[0].weight | 100 | 0 |
| 01:13:11 | traffic[1].label | previous | stable |
| 01:13:11 | traffic[1].weight | 0 | 100 |
| 01:14:36 | traffic[0].label | stable | previous |
| 01:14:36 | traffic[0].weight | 100 | 0 |
| 01:14:36 | traffic[1].label | previous | stable |
| 01:14:36 | traffic[1].weight | 0 | 100 |

**What users saw.** `python release.py watch --duration 780` ran from 01:04:37 to 01:17:36: 639 calls to the production URL, all HTTP 200, median 215 ms, the slowest 2,115 ms. It printed a line whenever Azure's traffic changed, and the build it got changed only at the promotion and the rollback. The screenshot in step 6 shows these lines and the calls around each build change:

```text
01:04:37  traffic → r1029153655 100% [stable], r1101000111 0% [previous]
01:04:37  200     214 ms  build 440297a
01:07:18  traffic → r1029153655 100% [stable], r1101000111 0% [previous], r1101010710 0% [candidate]
01:09:40  200     213 ms  build 440297a
01:09:41  200     232 ms  build 786e099
01:09:43  traffic → r1101010710 100% [stable], r1029153655 0% [previous]
01:10:41  traffic → r1101010710 100% [stable], r1029153655 0% [previous], d1101011033 0% [candidate]
01:12:21  traffic → r1101010710 100% [stable], r1029153655 0% [previous]
01:13:06  200     204 ms  build 786e099
01:13:08  200     226 ms  build 440297a
01:13:14  traffic → r1029153655 100% [stable], r1101010710 0% [previous]

639/639 calls succeeded (100.0%), median 215 ms
```

## A merge with the commit trigger on

What [Use it the first time](../README.md#use-it-the-first-time) describes: the release that a merge to `main` starts, with the build task's commit trigger on. Pull request [#251](https://github.com/melabadi/adept-assessment-northstars/pull/251) merged at 03:05:30 on 1 November 2026, as commit [584db4a](https://github.com/melabadi/adept-assessment-northstars/commit/584db4a). GitHub's webhook started ACR run `cjq` 2 seconds later. The candidate passed the gate at 03:09:35, 4 minutes 5 seconds after the merge, and waited for a person; the operator then ran the abort job, the no-go, and users stayed on the stable build. By then the function logged the build and the execution's suffix only. The commands of the sections above return these records with the times changed to 03:05 to 03:15.

The run's log, its step lines:

```text
2026/11/01 03:05:32 Downloading source code...
2026/11/01 03:05:38 Executing step ID: build. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/01 03:07:12 Executing step ID: push. Timeout(sec): 600, Working directory: '', Network: 'acb_default_network'
2026/11/01 03:07:24 Successfully pushed image: <registry>/requesthub-api:584db4aaf19151cd40e73d2b2827a0cdcf9888c0
2026/11/01 03:07:25 Successfully pushed image: <registry>/requesthub-api:main
2026/11/01 03:07:25 Step ID: build marked as successful (elapsed time in seconds: 94.274439)
2026/11/01 03:07:31 Step ID: push marked as successful (elapsed time in seconds: 13.485547)
Run ID: cjq was successful after 1m59s
```

The function's log:

| UTC | What the function logged |
| --- | --- |
| 03:07:25.900 | invocation succeeded in 1367 ms |
| 03:07:27.262 | Started release execution 67tmi1j for build 584db4a, image sha256:ac5b8f6f30a8, event "<id>" |

The executions:

| Execution | Job | Status | Started | Ended | Took |
| --- | --- | --- | --- | --- | --- |
| 67tmi1j | release | Succeeded | 03:07:27 | 03:09:38 | 2 min 11 s |
| 6kze35d | abort | Succeeded | 03:10:29 | 03:11:16 | 47 s |

The release records:

| Started | Job · step | Result | Seconds | Checks passed | Production calls OK | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 03:07:55 | release · release | pass | 3.4 |  |  | Releasing build 584db4a. |
| 03:07:59 | release · deploy | pass | 15.2 |  |  | Candidate r1101030759 created with 0% of traffic; r1029153655 still serves 100%. |
| 03:08:14 | release · gate | pass | 81.0 | 11 of 11 | 79 of 79 | Candidate r1101030759 passed the gate and still has 0% of traffic. It waits for a person's go or no-go. |
| 03:10:55 | abort · abort | pass | 17.4 | 10 of 10 |  | Users stayed on r1029153655 and production passed the smoke test. |