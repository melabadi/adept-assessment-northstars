# Evidence: the recorded run of 31 October 2026

What Azure recorded during [the run in See it work](../README.md#see-it-work), exported so that anyone can check it without signing in to Azure. Times are UTC.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-secure`, with the commands shown in each section, run in PowerShell 7 from `solutions/05-secure-microsoft` after `azd env select ai-sdlc-secure`. Each table keeps only the fields that its command names. Resource names keep their prefix, with the random token that identifies the deployment replaced by `…`. Nothing here includes a GUID, a host name, or a URL.
- **Kept here because Azure's records expire:** Application Insights, which holds the Function's log and the API's requests, keeps them for 90 days, until 29 January 2027. The Logic App's run history and the Activity log also keep 90 days. The job's execution history keeps its last 100 executions.
- **On GitHub**, everything the automation wrote stays public: Issue [#223](https://github.com/melabadi/adept-assessment-northstars/issues/223) and pull request [#224](https://github.com/melabadi/adept-assessment-northstars/pull/224) from the run, Issue [#222](https://github.com/melabadi/adept-assessment-northstars/issues/222) from the first trigger, and pull request [#226](https://github.com/melabadi/adept-assessment-northstars/pull/226), which reverted the fix after the run. The fix's commit statuses, with their exact times, are in [GitHub's API](https://api.github.com/repos/melabadi/adept-assessment-northstars/commits/b1207ad/statuses).
- **Measured in the terminal:** a few times and results come from the operator's terminal, not from Azure. [The terminal](#the-terminal) lists them.

## The code that ran

- **The fix:** commit [b1207ad](https://github.com/melabadi/adept-assessment-northstars/commit/b1207ad), which the Function committed on branch `posture/issue-223-10310522`, created from `main` at [276ee2d](https://github.com/melabadi/adept-assessment-northstars/commit/b50abba). It merged as [0d03f96](https://github.com/melabadi/adept-assessment-northstars/commit/53d9015).
- **The posture automation:** an early version of pull request [#228](https://github.com/melabadi/adept-assessment-northstars/pull/228), deployed from the working copy that became it: the Function app, the three-step Logic App `posture-intake`, and the agent's instructions, published as version 6 at 05:18. Before #228 merged, the only change to that code was in `verify`'s result: it now also reports whether it started an Azure Policy evaluation, and logs its whole result, where this run logged `verify: verified`. Later, pull requests [#298](https://github.com/melabadi/adept-assessment-northstars/pull/298) and [#309](https://github.com/melabadi/adept-assessment-northstars/pull/309) changed how the Function starts the what-if job (the job now finds the pull requests waiting for a preview itself) and how `verify` reads Azure Policy's results. None of these changes affects what this run shows.
- **The what-if preview:** [`whatif.py`](../whatif.py) from `main` at 276ee2d, which the job downloads at each execution. It was last changed there by pull request [#204](https://github.com/melabadi/adept-assessment-northstars/pull/204).

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 05:10:04 | The tenant's automation stopped RequestHub's PostgreSQL server | [Activity log](#the-activity-log) |
| 05:12:17 | The operator's start of the server finished | [Activity log](#the-activity-log) |
| 05:12:44 | The starting-state check: database `Ready`, no private endpoint, Azure Policy `NonCompliant`, no open posture Issue | [Terminal](#the-terminal) |
| 05:13:31 | An attachment upload through RequestHub's API failed with HTTP 500 | [API's requests](#the-functions-log-and-the-apis-requests) |
| 05:14:08.9 to 05:14:25.5 | The first trigger: `posture-intake` ran for 16.5 seconds | [Logic App runs](#the-logic-app-runs) |
| 05:14:16 | Issue #222 was filed | GitHub |
| 05:14:25 | The Function refused the agent's answer and commented why on #222 | GitHub, [Function's log](#the-functions-log-and-the-apis-requests) |
| 05:19:26 | #222 was closed as not planned | GitHub |
| 05:22:25.7 | The trigger of the run shown: `posture-intake` started | [Logic App runs](#the-logic-app-runs) |
| 05:22:31 | Issue #223 was filed | GitHub |
| 05:22:42 | Draft pull request #224 was opened, with commit b1207ad | GitHub |
| 05:22:44 | `posture/what-if` was set to pending on b1207ad | GitHub's API |
| 05:22:45 | The `posture-whatif` job started | [Job executions](#the-what-if-jobs-executions) |
| 05:22:46 | The Function's comment on #223 linked #224 | GitHub |
| 05:22:47.0 | `posture-intake` ended, after 21.3 seconds | [Logic App runs](#the-logic-app-runs) |
| 05:23:58 | `posture/what-if` turned to success, *PASS: 4 expected change(s), nothing else*, and the preview comment was posted | GitHub |
| 05:24:01 | The job ended, after 76 seconds | [Job executions](#the-what-if-jobs-executions) |
| 05:35:05 | #224 was marked ready for review | GitHub |
| 05:35:09 | #224 was merged as 0d03f96 | GitHub |
| 05:35:36 | `azd provision` started | [Terminal](#the-terminal) |
| 05:36:39 | RequestHub's private endpoint `pe-blob-…` was created | [Activity log](#the-activity-log) |
| 05:37:27 | The blob private DNS zone was linked to RequestHub's virtual network (`vnet-link`) | [Activity log](#the-activity-log) |
| 05:38 | Azure Policy evaluated the storage account `Compliant` | The verification comment on #223 |
| 05:41:05 | `azd provision` ended, after 5 minutes 29 seconds | [Terminal](#the-terminal) |
| 05:42:05 | The operator started `verify` | [Terminal](#the-terminal) |
| 05:42:10 | `verify` started; it ran for 72 seconds | [Function's log](#the-functions-log-and-the-apis-requests) |
| 05:42:13 | `verify` started an Azure Policy evaluation | [Activity log](#the-activity-log) |
| 05:43:20 | `verify`'s evidence comment on #223 | GitHub |
| 05:43:21 | #223 was closed as completed | GitHub |
| 05:46:32 | An attachment upload through the API returned HTTP 201, and its download, a second later, HTTP 200 | [API's requests](#the-functions-log-and-the-apis-requests), [Terminal](#the-terminal) |
| 05:46:49 | The reset began: revert pull request #226 was opened | GitHub |
| 05:48:10 | #226's preview: *PASS: 1 expected change(s), nothing else* | GitHub |
| 05:48:51 | #226 was merged | GitHub |
| 05:50:16 | RequestHub's private endpoint was deleted | [Activity log](#the-activity-log) |
| 05:51:07 | `vnet-link` was deleted | [Activity log](#the-activity-log) |
| 05:57:15 to 06:04:53 | `az policy state trigger-scan` ran; Azure Policy then reported the account `NonCompliant` again | [Activity log](#the-activity-log), [Terminal](#the-terminal) |

## The Logic App runs

```powershell
$rg = azd env get-value AZURE_RESOURCE_GROUP
$runs = "/subscriptions/{subscriptionId}/resourceGroups/$rg/providers/Microsoft.Logic/workflows/posture-intake/runs"
az rest --method get --url $runs --url-parameters api-version=2019-05-01 --query "value[].{run:name, start:properties.startTime, end:properties.endTime, status:properties.status}" -o table
az rest --method get --url "$runs/<run>/actions" --url-parameters api-version=2019-05-01 --query "value[].{action:name, start:properties.startTime, end:properties.endTime, status:properties.status}" -o table
```

| Run | Started | Ended | Took | Status |
| --- | --- | --- | --- | --- |
| `08584081832364987435136581312CU08`, the first trigger | 05:14:08.9 | 05:14:25.5 | 16.5 s | Succeeded |
| `08584081827396975775796129199CU16`, the run shown | 05:22:25.7 | 05:22:47.0 | 21.3 s | Succeeded |

The run shown, step by step. Defender for Cloud's trigger is the run's start; the two actions follow:

| Action | Started | Ended | Status |
| --- | --- | --- | --- |
| `Keep_only_the_recommendation` | 05:22:25.941 | 05:22:25.942 | Succeeded |
| `Send_it_to_the_posture_Function` | 05:22:25.970 | 05:22:46.293 | Succeeded |

The Function's answer is the output of `Send_it_to_the_posture_Function`:

```powershell
$a = az rest --method get --url "$runs/<run>/actions/Send_it_to_the_posture_Function" --url-parameters api-version=2019-05-01 | ConvertFrom-Json
(Invoke-RestMethod $a.properties.outputsLink.uri).body | ConvertTo-Json -Compress
```

| Run | HTTP | The Function's answer |
| --- | --- | --- |
| The first trigger | 200 | `{"issue":222,"filed":true,"result":"the agent's proposal was not applied","problems":["it changes text outside the lines between the posture:editable markers"]}` |
| The run shown | 200 | `{"issue":223,"filed":true,"agentAttempts":1,"result":"drafted a fix","pullRequest":224,"previewStarted":true}` |

## The Function's log and the API's requests

From RequestHub's Application Insights, which the posture Function shares with the API:

```powershell
$ai = az resource list -g $rg --resource-type Microsoft.Insights/components --query "[0].id" -o tsv
az monitor app-insights query --ids $ai --start-time 2026-10-31T05:10:00Z --end-time 2026-10-31T05:50:00Z --analytics-query "traces | where message startswith 'intake' or message startswith 'preview' or message startswith 'verify' | project timestamp, message | order by timestamp asc" --query "tables[0].rows" -o tsv
az monitor app-insights query --ids $ai --start-time 2026-10-31T05:10:00Z --end-time 2026-10-31T05:50:00Z --analytics-query "requests | where name in ('intake', 'preview', 'verify') or name has 'attachments' | project timestamp, name, resultCode, duration | order by timestamp asc" --query "tables[0].rows" -o tsv
```

The Function's log:

| UTC | Message |
| --- | --- |
| 05:14:25 | `intake: the agent's proposal was not applied` |
| 05:22:46 | `preview of pull request #224 (pull_request.opened): already previewed` |
| 05:22:46 | `intake: drafted a fix` |
| 05:27:48 | `preview of pull request #212 (pull_request.closed): not previewed: the pull request is not open` |
| 05:35:10 | `preview of pull request #224 (pull_request.ready_for_review): not previewed: the pull request is not open` |
| 05:35:11 | `preview of pull request #224 (pull_request.closed): not previewed: the pull request is not open` |
| 05:43:22 | `verify: verified` |
| 05:46:59 | `preview of pull request #226 (pull_request.opened): preview started` |
| 05:48:53 | `preview of pull request #226 (pull_request.closed): not previewed: the pull request is not open` |

- The webhook's delivery for the new pull request #224 found the preview already started by `intake`, so the Function started nothing more.
- #212 was another pull request, closed during the run.
- The delivery for #224's *ready for review* arrived after the merge at 05:35:09: the Function reads each pull request again from GitHub, and found it no longer open.

The requests, by start time. The API's requests are RequestHub's attachment upload and download; `verify` is a timer function, which reports no HTTP result:

| UTC | Request | Result | Took |
| --- | --- | --- | --- |
| 05:13:31 | `POST /api/requests/{id}/attachments` | 500 | 430 ms |
| 05:14:11 | `intake` (the first trigger) | 200 | 14,369 ms |
| 05:22:27 | `intake` (the run shown) | 200 | 18,621 ms |
| 05:22:44 | `preview` (#224 opened) | 200 | 1,253 ms |
| 05:27:47 | `preview` (#212 closed) | 200 | 1,370 ms |
| 05:35:08 | `preview` (#224 ready for review) | 200 | 1,285 ms |
| 05:35:11 | `preview` (#224 closed) | 200 | 341 ms |
| 05:42:10 | `verify` | 0 | 72,468 ms |
| 05:46:32 | `POST /api/requests/{id}/attachments` | 201 | 438 ms |
| 05:46:33 | `GET /api/requests/{id}/attachments/{attachmentId:guid}/content` | 200 | 38 ms |
| 05:46:53 | `preview` (#226 opened) | 202 | 5,355 ms |
| 05:48:53 | `preview` (#226 closed) | 200 | 338 ms |

## The what-if job's executions

```powershell
az containerapp job execution list -g $rg -n posture-whatif --query "[].{execution:name, start:properties.startTime, end:properties.endTime, status:properties.status}" -o table
```

| Execution | Started | Ended | Status | Previewed |
| --- | --- | --- | --- | --- |
| `posture-whatif-vic5pmi` | 05:22:45 | 05:24:01 | Succeeded | #224, the fix: PASS, 4 expected changes |
| `posture-whatif-lh3yh4d` | 05:46:59 | 05:48:15 | Succeeded | #226, the revert: PASS, 1 expected change |

## The Activity log

The resource group's private endpoints, private DNS zone links, and Azure Policy evaluations, then the database's stop and start:

```powershell
az monitor activity-log list -g $rg --start-time 2026-10-31T05:30:00Z --end-time 2026-10-31T06:10:00Z --max-events 3000 --query "[?contains(operationName.value, 'privateEndpoints/') || contains(operationName.value, 'virtualNetworkLinks/') || contains(operationName.value, 'triggerEvaluation')].{time:eventTimestamp, operation:operationName.value, status:status.value, caller:claims.idtyp}" -o table
$pg = az postgres flexible-server list -g $rg --query "[0].id" -o tsv
az monitor activity-log list --resource-id $pg --start-time 2026-10-31T05:00:00Z --end-time 2026-10-31T05:15:00Z --query "[?status.value=='Succeeded'].{time:eventTimestamp, operation:operationName.value, caller:claims.idtyp}" -o table
```

The rows that concern the run. The caller is `user` for the operator's sign-in and `app` for an application's identity. The first command lists more rows: Azure records each operation's intermediate states, and each `azd provision` also rewrote private endpoints and DNS zone links that didn't change.

| UTC | Operation | Resource | Status | Caller |
| --- | --- | --- | --- | --- |
| 05:10:04 | `Microsoft.DBforPostgreSQL/flexibleServers/stop/action` | RequestHub's PostgreSQL server | Succeeded | `app`: the tenant's automation |
| 05:12:17 | `Microsoft.DBforPostgreSQL/flexibleServers/start/action` | RequestHub's PostgreSQL server | Succeeded | `user` |
| 05:36:39 | `Microsoft.Network/privateEndpoints/write` | `pe-blob-…`, RequestHub's | Succeeded | `user`: `azd provision` |
| 05:37:27 | `Microsoft.Network/privateDnsZones/virtualNetworkLinks/write` | `privatelink.blob.core.windows.net` / `vnet-link` | Succeeded | `user`: `azd provision` |
| 05:42:13 | `Microsoft.PolicyInsights/policyStates/triggerEvaluation/action` | the resource group | Accepted | `app`: the posture Function's identity, from `verify` |
| 05:50:16 | `Microsoft.Network/privateEndpoints/delete` | `pe-blob-…` | Succeeded | `user`: the reset |
| 05:51:07 | `Microsoft.Network/privateDnsZones/virtualNetworkLinks/delete` | `privatelink.blob.core.windows.net` / `vnet-link` | Succeeded | `user`: the reset |
| 05:57:15 | `Microsoft.PolicyInsights/policyStates/triggerEvaluation/action` | the resource group | Accepted | `user`: the reset's `az policy state trigger-scan` |
| 06:04:53 | `Microsoft.PolicyInsights/policyStates/triggerEvaluation/action` | the resource group | Succeeded | `user`: the same scan, finished |

## The terminal

What the operator's terminal recorded, in PowerShell 7 from `solutions/05-secure-microsoft`.

**05:12:44, the starting-state check**, as in the README's [Check the starting state](../README.md#check-the-starting-state). The last command listed no open posture Issue:

```text
PS> $rg = azd env get-value AZURE_RESOURCE_GROUP
PS> $st = az storage account show -g $rg -n (azd env get-value STORAGE_ACCOUNT_NAME) --query id -o tsv
PS> az postgres flexible-server list -g $rg --query "[0].state" -o tsv
Ready
PS> (az storage account show --ids $st --query privateEndpointConnections | ConvertFrom-Json).Count
0
PS> az policy state list --resource $st --filter "policyAssignmentName eq 'requesthub-storage-private-link'" --query "[0].complianceState" -o tsv
NonCompliant
PS> gh issue list --label posture --state open
```

**05:35:36, `azd provision`** on `main` at 0d03f96, the merged fix. It ended with:

```text
SUCCESS: Your application was provisioned in Azure in 5 minutes 29 seconds.
```

**05:42:05, `verify`**, started with the `az rest` command in the README's [step 7](../README.md#7-verify). It returns at once, without output.

**05:46:32, an attachment through RequestHub's API**, with the operator's own sign-in: a short text file uploaded to a request, then downloaded.

```text
upload: HTTP 201 in 0.6 s
download: HTTP 200, 58 bytes, same content and SHA-256 as uploaded: True
```

**The reset, after the run**, as in the README's [Reset the copy for another run](../README.md#reset-the-copy-for-another-run): `azd provision` on `main` after revert #226 took 5 minutes 23 seconds, and `az policy state trigger-scan -g $rg` took 7 minutes 38 seconds. Then the starting-state check returned `Ready`, `0`, `NonCompliant`, and no open posture Issue again, and Defender for Cloud still reported the account `Unhealthy`.
