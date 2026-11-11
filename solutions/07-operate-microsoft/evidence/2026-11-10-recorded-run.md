# Evidence: the recorded run of 10 November 2026

What Azure recorded during [the run in See it work](../README.md#see-it-work), exported so that anyone can check it without signing in to Azure. Times are UTC.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-operate`, with the commands shown in each section, run in PowerShell 7 from `solutions/07-operate-microsoft` after `azd env select ai-sdlc-operate`. The exports keep only the fields that each command names. Where a value would identify the tenant, it is replaced: the worker's name by `<worker>`, a revision by its number, the subscription by `<subscription>`, and the person who approved the change by *the approver*.
- **Kept here because the records expire:** Application Insights and Log Analytics keep 30 days of telemetry, so the queries in [the worker's telemetry](#the-workers-telemetry) and [container events](#container-events) return nothing after 10 December 2026. Azure Monitor lists an alert for 30 days, and the Activity Log keeps 90. The investigation thread stays in the agent's history, but only someone signed in to Azure can open it, so [the investigation](#the-investigation) quotes it.
- **On GitHub**, Issue [#301](https://github.com/melabadi/adept-assessment-northstars/issues/301) is the incident record that was filed from the agent's draft. Its body is the draft, character for character.
- **Not kept:** the terminal output of `python incident.py start`. The Activity Log, the revisions, and the telemetry record what it did.

## The configuration that ran

- **The agent:** [`sre-agent/`](../sre-agent/), applied by [`configure_sre_agent.py`](../configure_sre_agent.py), as pull request [#298](https://github.com/melabadi/adept-assessment-northstars/pull/298) merged them (commit [f4890b9](https://github.com/melabadi/adept-assessment-northstars/commit/40d748fc64c4d5bdec79661045e005d28eb7d08e)). Their last change before the run is that pull request's commit [7cb0756](https://github.com/melabadi/adept-assessment-northstars/commit/639b891758da4f6e5f3c61963358af825a05e174), at 18:37 on 10 November, two hours before the run: it made the record carry every field of the GitHub team's incident form. #298 says the live agent already used it. On 11 November, a read-only comparison of the live agent with these files, through the agent's API, found the three skills, the custom agent (instructions, tools, skills, and Stop hook), the guard hook, the response plan, and the tool policy (7 allowed, 2 asked, and 33 denied entries) the same as `configure_sre_agent.py` renders them. The service only adds default fields of its own.
- **The alert:** [`infra/monitoring.bicep`](../infra/monitoring.bicep), unchanged since 30 October. The rule as Azure has it:

  ```powershell
  az monitor metrics alert show -g rg-ai-sdlc-operate -n 'RequestHub notification backlog' `
    --query "{Severity: severity, Every: evaluationFrequency, Window: windowSize, Metric: criteria.allOf[0].metricName, Aggregation: criteria.allOf[0].timeAggregation, Operator: criteria.allOf[0].operator, Threshold: criteria.allOf[0].threshold, AutoResolve: autoMitigate}" -o table
  ```

  ```text
  Severity    Every    Window    Metric                                               Aggregation    Operator     Threshold    AutoResolve
  ----------  -------  --------  ---------------------------------------------------  -------------  -----------  -----------  -------------
  2           PT1M     PT1M      requesthub.notifications.oldest_pending_age_seconds  Maximum        GreaterThan  60.0         True
  ```

- **The worker:** the image that `azd deploy` built on 27 October 2026 (tag `azd-deploy-1793115984`). `incident.py` and the approved command changed only its settings, in new revisions (see [worker revisions](#worker-revisions)).

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 20:31:06 | A worker update removed the expired fault settings of the morning's drill; revision `0000017`, created at 20:31:13, has none | [Activity Log](#activity-log), [revisions](#worker-revisions) |
| 20:34:04 | The worker's last report before the drill: 0 pending, no fault | [Worker reports](#the-workers-backlog-reports) |
| 20:34:07 | `incident.py start` updated the worker: `Faults__WorkerDelayMs=10000`, expiring at 21:19:02 | [Activity Log](#activity-log), [revisions](#worker-revisions) |
| 20:34:14 | Revision `0000018` was created; its container started at 20:34:32 and reported the fault active at 20:34:34 | [Container events](#container-events), [worker reports](#the-workers-backlog-reports) |
| 20:35:26 to 20:35:34 | The synthetic requests reached the API: Application Insights recorded 41 of them, none failed | [The synthetic requests](#the-synthetic-requests) |
| 20:35:47 | The worker reported 358 pending, the oldest 21 seconds old | [Worker reports](#the-workers-backlog-reports) |
| 20:39:07 | 338 pending, the oldest 220.7 seconds old: the first report above the 60-second threshold | [Worker reports](#the-workers-backlog-reports) |
| 20:42:07 | Azure Monitor fired the alert, Sev2, on that value of 220.7 | [The alert](#the-alert) |
| 20:42:43 | Azure SRE Agent opened the investigation thread | [The investigation](#the-investigation) |
| 20:42:44 | The agent acknowledged the alert, with its own managed identity | [The alert](#the-alert), [Activity Log](#activity-log) |
| 20:42:54 | Its memory search found the runbook and 4 earlier incidents with similar symptoms | [The investigation](#the-investigation) |
| 20:42:59 to 20:44:15 | 10 read-only Azure CLI commands, run as the agent | [The investigation](#the-investigation) |
| 20:44:41 | The report, and the request to approve one command | [The report](#the-report), [the approvals](#the-approvals) |
| 20:47:23 | **Allow once**: the approver approved the command | [The approvals](#the-approvals) |
| 20:47:43 | **Grant permissions**: the command ran with the approver's permissions until 20:48:35 | [The approvals](#the-approvals) |
| 20:48:19 | The worker update began, by the approver's account | [Activity Log](#activity-log) |
| 20:48:26 | Revision `0000019` was created, without the fault settings | [Container events](#container-events), [revisions](#worker-revisions) |
| 20:49:07 | The faulted revision's last report: 278 pending, the oldest 819.7 seconds old | [Worker reports](#the-workers-backlog-reports) |
| 20:49:08 | The new worker container started | [Container events](#container-events) |
| 20:49:10 | The new revision's first report: no fault, 258 pending | [Worker reports](#the-workers-backlog-reports) |
| 20:49:40 | 20 pending; the oldest had waited 852.4 seconds, the most in the incident | [Worker reports](#the-workers-backlog-reports) |
| 20:50:08 | The backlog gauges reached 0 pending and 0 seconds | [Backlog gauges](#the-backlog-gauges-per-minute) |
| 20:50:26 | The agent reported the drain, then waited for Azure Monitor | [The investigation](#the-investigation) |
| 20:55:04 | Azure Monitor resolved the alert | [The alert](#the-alert) |
| 20:55:57 | The agent's last reply: the results before and after the change, and the incident record's draft | [The last reply](#the-last-reply) |
| 20:55:59 | The Stop hook allowed the reply | [The investigation](#the-investigation) |
| 20:57:33 | Issue #301 was filed from the draft | [On GitHub](#on-github) |

## The alert

The fired alert and its history in Azure Monitor. The agent acknowledged it when the investigation started. Azure Monitor resolved it on its own, after three healthy one-minute evaluations.

```powershell
$alerts = "https://management.azure.com/subscriptions/$(azd env get-value AZURE_SUBSCRIPTION_ID)/providers/Microsoft.AlertsManagement/alerts"
$pick = "value[?name=='RequestHub notification backlog' && starts_with(properties.essentials.startDateTime, '2026-11-10T20:42')] | [0]"
az rest --method get --url $alerts --uri-parameters api-version=2019-05-05-preview timeRange=30d `
  --query "$pick.properties.essentials.{Severity: severity, Fired: startDateTime, Condition: monitorCondition, Resolved: monitorConditionResolvedDateTime, State: alertState}" -o table
$alert = az rest --method get --url $alerts --uri-parameters api-version=2019-05-05-preview timeRange=30d --query "$pick.id" -o tsv
az rest --method get --url "https://management.azure.com$alert/history" --uri-parameters api-version=2019-05-05-preview `
  --query "properties.modifications[].[modifiedAt, modificationEvent, oldValue, newValue, comments]" -o tsv
```

```text
Severity    Fired                         Condition    Resolved                      State
----------  ----------------------------  -----------  ----------------------------  ------------
Sev2        2026-11-10T20:42:07.5655269Z  Resolved     2026-11-10T20:55:04.5028206Z  Acknowledged

2026-11-10T20:55:04.5028206Z	MonitorConditionChange	Fired	Resolved
2026-11-10T20:42:44.3202577+00:00	StateChange	New	Acknowledged	Acknowledged by SRE Agent
2026-11-10T20:42:07.5655269Z	AlertCreated
```

## Activity Log

Every change to the worker in the run's window, and the agent's acknowledgment of the alert, with who made it. The command compares each caller with the account signed in to the Azure CLI and with the agent's managed identity, so that no account name is printed. The approved command ran with the approver's permissions, so its update shows the approver's account, not the agent's identity.

```powershell
$worker = azd env get-value WORKER_APP_NAME
$me = az account show --query user.name -o tsv
$agent = az identity list -g rg-ai-sdlc-operate --query "[?starts_with(name, 'id-sre-')].principalId" -o tsv
az monitor activity-log list -g rg-ai-sdlc-operate --start-time 2026-11-10T20:25:00Z --end-time 2026-11-10T21:05:00Z -o json | ConvertFrom-Json |
  Where-Object { $_.resourceId -like "*/containerApps/$worker" -or $_.operationName.value -like '*alerts/changestate*' } |
  Sort-Object eventTimestamp | ForEach-Object {
    $who = switch ($_.caller) { $me { 'the account signed in to the Azure CLI' } $agent { "the agent's managed identity" } default { 'another identity' } }
    '{0:HH:mm:ss}  {1,-9}  {2,-52}  {3}' -f ([datetime]$_.eventTimestamp).ToUniversalTime(), $_.status.value, $_.operationName.value, $who
  }
```

```text
20:31:06  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
20:31:06  Accepted   Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
20:34:07  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
20:34:07  Accepted   Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
20:42:44  Started    Microsoft.AlertsManagement/alerts/changestate/action  the agent's managed identity
20:42:44  Succeeded  Microsoft.AlertsManagement/alerts/changestate/action  the agent's managed identity
20:48:19  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
20:48:19  Accepted   Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
```

The operator and the approver used the same account. No other change to the worker, and no change to the API, appears in the window.

## Worker revisions

The worker's revisions around the run, with their fault settings: `0000017` without a fault, `0000018` with the drill's, and `0000019`, created by the approved command, without it.

```powershell
az containerapp revision list -n (azd env get-value WORKER_APP_NAME) -g rg-ai-sdlc-operate --all `
  --query "[?ends_with(name, '0000017') || ends_with(name, '0000018') || ends_with(name, '0000019')].[name, properties.createdTime, properties.active, join(', ', properties.template.containers[0].env[?starts_with(name, 'Faults__')].join('=', [name, value]))]" -o tsv |
  ForEach-Object { $_ -replace '^\S*--', '' }
```

```text
0000017	2026-11-10T20:31:13+00:00	False
0000018	2026-11-10T20:34:14+00:00	False	Faults__WorkerDelayMs=10000, Faults__ExpiresAtUtc=2026-11-10T21:19:02Z
0000019	2026-11-10T20:48:25+00:00	True
```

## Container events

From the Container Apps system logs in Log Analytics: when each revision was created, and when its container started. In the query, `<worker>` stands for the worker's name, from `azd env get-value WORKER_APP_NAME`.

```powershell
$ws = az monitor log-analytics workspace show -g rg-ai-sdlc-operate -n (azd env get-value LOG_ANALYTICS_NAME) --query customerId -o tsv
az monitor log-analytics query -w $ws --analytics-query $kql --timespan P30D -o table
```

```kusto
ContainerAppSystemLogs_CL | where TimeGenerated between (datetime(2026-11-10T20:30:00Z) .. datetime(2026-11-10T20:52:00Z)) | where ContainerAppName_s == '<worker>' and Reason_s in ('RevisionCreation', 'ContainerStarted') | project TimeGenerated, Reason_s, Revision = iff(Reason_s == 'RevisionCreation', extract('--([0-9]+)$', 1, Log_s), extract('--([0-9]+)', 1, RevisionName_s)) | order by TimeGenerated asc
```

| TimeGenerated | Reason_s | Revision |
| --- | --- | --- |
| 2026-11-10T20:31:13.5370755Z | RevisionCreation | 0000017 |
| 2026-11-10T20:31:30.4609767Z | ContainerStarted | 0000017 |
| 2026-11-10T20:34:14.4954849Z | RevisionCreation | 0000018 |
| 2026-11-10T20:34:32.6212342Z | ContainerStarted | 0000018 |
| 2026-11-10T20:48:26.4039154Z | RevisionCreation | 0000019 |
| 2026-11-10T20:49:08.4029898Z | ContainerStarted | 0000019 |

## The worker's telemetry

The worker's own telemetry in Application Insights, with the queries of the agent's skill [`investigate-notification-backlog`](../sre-agent/skills/investigate-notification-backlog.md), limited to the run's window. Run each with:

```powershell
az monitor app-insights query --app (azd env get-value APPLICATIONINSIGHTS_NAME) -g rg-ai-sdlc-operate --offset 30d --analytics-query $kql
```

### The worker's backlog reports

The worker writes this report at most every 30 seconds, after a batch of up to 20 deliveries. At 10 seconds a delivery, a batch took 200 seconds, so the reports came 3 minutes 20 seconds apart. Twice, an old and a new revision ran side by side for about 30 seconds while one replaced the other: from 20:34:34 to 20:35:05, and from 20:49:07 to 20:49:37.

```kusto
traces | where timestamp between (datetime(2026-11-10T20:34:00Z) .. datetime(2026-11-10T20:51:00Z)) | where message startswith 'Notification backlog' | project timestamp, message | order by timestamp asc
```

| timestamp | message |
| --- | --- |
| 2026-11-10T20:34:04.8182178Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:34:34.6386492Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:34:35.1676254Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:35:05.1804593Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:35:05.509292Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:35:47.4535338Z | Notification backlog: pending=358 oldestPendingAgeSeconds=21 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:39:07.5145726Z | Notification backlog: pending=338 oldestPendingAgeSeconds=220.7 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:42:27.6428557Z | Notification backlog: pending=318 oldestPendingAgeSeconds=420.5 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:45:47.6932242Z | Notification backlog: pending=298 oldestPendingAgeSeconds=620 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:49:07.7347138Z | Notification backlog: pending=278 oldestPendingAgeSeconds=819.7 failed=0 workerDelayFaultActive=True |
| 2026-11-10T20:49:10.1545864Z | Notification backlog: pending=258 oldestPendingAgeSeconds=822.1 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:49:40.4215467Z | Notification backlog: pending=20 oldestPendingAgeSeconds=852.4 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:50:11.0714129Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=False |
| 2026-11-10T20:50:41.5058782Z | Notification backlog: pending=0 oldestPendingAgeSeconds=0 failed=0 workerDelayFaultActive=False |

### The backlog gauges, per minute

The two gauges that the worker sends to Application Insights, which the alert reads. A gauge keeps its last value until the next report, so a value repeats while deliveries are slow. The 20:50 values were sent at 20:50:08.

```kusto
customMetrics | where timestamp between (datetime(2026-11-10T20:33:00Z) .. datetime(2026-11-10T20:57:00Z)) | where name in ('requesthub.notifications.pending', 'requesthub.notifications.oldest_pending_age_seconds') | summarize pending = maxif(value, name == 'requesthub.notifications.pending'), oldest_seconds = maxif(value, name == 'requesthub.notifications.oldest_pending_age_seconds') by minute = bin(timestamp, 1m) | order by minute asc
```

| minute | pending | oldest_seconds |
| --- | --- | --- |
| 2026-11-10T20:33:00Z | 0 | 0 |
| 2026-11-10T20:34:00Z | 0 | 0 |
| 2026-11-10T20:35:00Z | 0 | 0 |
| 2026-11-10T20:36:00Z | 358 | 21 |
| 2026-11-10T20:37:00Z | 358 | 21 |
| 2026-11-10T20:38:00Z | 358 | 21 |
| 2026-11-10T20:39:00Z | 338 | 220.7 |
| 2026-11-10T20:40:00Z | 338 | 220.7 |
| 2026-11-10T20:41:00Z | 338 | 220.7 |
| 2026-11-10T20:42:00Z | 318 | 420.5 |
| 2026-11-10T20:43:00Z | 318 | 420.5 |
| 2026-11-10T20:44:00Z | 318 | 420.5 |
| 2026-11-10T20:45:00Z | 318 | 420.5 |
| 2026-11-10T20:46:00Z | 298 | 620 |
| 2026-11-10T20:47:00Z | 298 | 620 |
| 2026-11-10T20:48:00Z | 298 | 620 |
| 2026-11-10T20:49:00Z | 278 | 819.7 |
| 2026-11-10T20:50:00Z | 0 | 0 |
| 2026-11-10T20:51:00Z | 0 | 0 |
| 2026-11-10T20:52:00Z | 0 | 0 |
| 2026-11-10T20:53:00Z | 0 | 0 |
| 2026-11-10T20:54:00Z | 0 | 0 |
| 2026-11-10T20:55:00Z | 0 | 0 |
| 2026-11-10T20:56:00Z | 0 | 0 |

### Deliveries per minute

Notifications delivered, as the worker counts them. The counts are sent once a minute, so the 20:50 row's 278 are the notifications that were pending at 20:49:07, which the new revision delivered.

```kusto
customMetrics | where timestamp between (datetime(2026-11-10T20:33:00Z) .. datetime(2026-11-10T20:57:00Z)) | where name == 'requesthub.notifications.processed' | summarize sent = sumif(value, tostring(customDimensions.outcome) == 'sent'), retried_or_failed = sumif(value, tostring(customDimensions.outcome) != 'sent') by minute = bin(timestamp, 1m) | order by minute asc
```

| minute | sent | retried_or_failed |
| --- | --- | --- |
| 2026-11-10T20:36:00Z | 6 | 0 |
| 2026-11-10T20:37:00Z | 6 | 0 |
| 2026-11-10T20:38:00Z | 6 | 0 |
| 2026-11-10T20:39:00Z | 6 | 0 |
| 2026-11-10T20:40:00Z | 6 | 0 |
| 2026-11-10T20:41:00Z | 6 | 0 |
| 2026-11-10T20:42:00Z | 6 | 0 |
| 2026-11-10T20:43:00Z | 6 | 0 |
| 2026-11-10T20:44:00Z | 6 | 0 |
| 2026-11-10T20:45:00Z | 6 | 0 |
| 2026-11-10T20:46:00Z | 6 | 0 |
| 2026-11-10T20:47:00Z | 6 | 0 |
| 2026-11-10T20:48:00Z | 6 | 0 |
| 2026-11-10T20:49:00Z | 7 | 0 |
| 2026-11-10T20:50:00Z | 278 | 0 |

### How long each delivery took

Each delivery is a span, `notification.deliver`, and a span that the fault slowed carries the fault's delay. Application Insights keeps a sample of the spans under load, not all of them. Per minute, then, from the moment the change began, per revision:

```kusto
dependencies | where timestamp between (datetime(2026-11-10T20:33:00Z) .. datetime(2026-11-10T20:57:00Z)) | where name == 'notification.deliver' | summarize spans = count(), avg_ms = round(avg(duration), 3), fault_delay_ms = max(toint(customDimensions['requesthub.fault.worker_delay_ms'])) by minute = bin(timestamp, 1m) | order by minute asc
```

| minute | spans | avg_ms | fault_delay_ms |
| --- | --- | --- | --- |
| 2026-11-10T20:35:00Z | 4 | 10000.397 | 10000 |
| 2026-11-10T20:36:00Z | 6 | 10000.627 | 10000 |
| 2026-11-10T20:37:00Z | 6 | 10000.933 | 10000 |
| 2026-11-10T20:38:00Z | 6 | 10002.065 | 10000 |
| 2026-11-10T20:39:00Z | 6 | 10001.225 | 10000 |
| 2026-11-10T20:40:00Z | 6 | 10001.47 | 10000 |
| 2026-11-10T20:41:00Z | 6 | 10000.342 | 10000 |
| 2026-11-10T20:42:00Z | 6 | 10000.407 | 10000 |
| 2026-11-10T20:43:00Z | 6 | 10001.361 | 10000 |
| 2026-11-10T20:44:00Z | 6 | 9999.965 | 10000 |
| 2026-11-10T20:45:00Z | 5 | 9999.921 | 10000 |
| 2026-11-10T20:46:00Z | 6 | 10000.004 | 10000 |
| 2026-11-10T20:47:00Z | 6 | 10000.526 | 10000 |
| 2026-11-10T20:48:00Z | 6 | 10000.037 | 10000 |
| 2026-11-10T20:49:00Z | 22 | 1767.818 | 10000 |

```kusto
dependencies | where timestamp between (datetime(2026-11-10T20:48:19Z) .. datetime(2026-11-10T20:57:00Z)) | where name == 'notification.deliver' | extend revision = extract('--([0-9]+)-', 1, cloud_RoleInstance), fault_tag = isnotempty(tostring(customDimensions['requesthub.fault.worker_delay_ms'])) | summarize spans = count(), avg_ms = round(avg(duration), 3), first_seen = min(timestamp), last_seen = max(timestamp) by revision, fault_tag | order by first_seen asc
```

| revision | fault_tag | spans | avg_ms | first_seen | last_seen |
| --- | --- | --- | --- | --- | --- |
| 0000018 | True | 8 | 9861.381 | 2026-11-10T20:48:27.7145405Z | 2026-11-10T20:49:37.7507944Z |
| 0000019 | False | 18 | 0.059 | 2026-11-10T20:49:09.9278449Z | 2026-11-10T20:49:47.5195153Z |

### The synthetic requests

The requests that `incident.py start` submitted. Application Insights keeps a sample of requests under load, so it recorded 41 of them. `incident.py` submits 200 by default, which make about 360 notifications.

```kusto
requests | where timestamp between (datetime(2026-11-10T20:30:00Z) .. datetime(2026-11-10T21:00:00Z)) | where name == 'POST /api/requests' | summarize recorded = count(), failed = countif(success == false), first_seen = min(timestamp), last_seen = max(timestamp)
```

| recorded | failed | first_seen | last_seen |
| --- | --- | --- | --- |
| 41 | 0 | 2026-11-10T20:35:26.2448646Z | 2026-11-10T20:35:33.7191127Z |

## The investigation

The investigation thread in Azure SRE Agent: in the [SRE Agent portal](https://sre.azure.com), the agent › **Incidents** › the *RequestHub notification backlog* incident created at 20:42:07. This section was read on 11 November, with the operator's Azure CLI sign-in, from the agent's API that the portal uses (`GET <agent endpoint>/api/v1/threads/<thread>/messages` and `/api/v1/approvals/<thread>`).

The thread has 77 messages: 13 messages of text (the alert's card, the agent's replies, and the platform's review), 25 reasoning steps, 34 Azure CLI commands, 2 reads of the agent's memory, 1 memory search, 1 approval request, and 1 hook run. 33 of the commands ran as the agent, which can only read; the one change ran with the approver's permissions. The portal labels each command in its own words, which don't say whether it writes: it calls `az containerapp revision list` *Creating new Azure resource (Medium risk)*, `az containerapp show` *Starting Azure resource*, and `az monitor activity-log list` *Setting resource configuration*. The thread's messages don't list the telemetry queries that the agent runs through its Application Insights and Log Analytics connectors; its replies give their results, and [the worker's telemetry](#the-workers-telemetry) reproduces them.

| UTC | Message |
| --- | --- |
| 20:42:43 | The alert's card: Sev2, *RequestHub notification backlog*, fired, response plan `requesthub-notification-backlog` |
| 20:42:44 | "Alert received ✅ Initiating investigation to assess the situation and identify potential causes 🛠️" |
| 20:42:47 | "I'm checking the runbook and current alert state first, then I'll compare the worker's telemetry and revisions before proposing any change." |
| 20:42:50 | Read its memory: `logs.md` and `debugging.md` |
| 20:42:54 | Memory search: 5 relevant results, the team's runbook and 4 incidents from earlier drills with similar symptoms |
| 20:42:59 to 20:44:15 | 10 read-only commands, as the agent: `az monitor log-analytics workspace show`, `az resource show` (the alert, and Application Insights), `az monitor metrics alert show`, `az containerapp revision list`, `az containerapp show`, `az monitor activity-log list`, `az containerapp revision show` (the two latest revisions), and `az containerapp replica list` |
| 20:43:18 | "The Sev2 alert is still fired and acknowledged; its threshold is an oldest pending notification age over 60 seconds. I'm measuring the 20:12:07–20:42:07 UTC baseline against the post-alert period and checking the worker rollout." |
| 20:43:48 | "The active revision introduced a 10-second delay setting that the previous revision lacked. Deliveries are now about six per minute at 10 seconds each, while the worker reports 318 waiting and a 420.5-second oldest age; I'm checking for competing worker, database, API, or load failures before mitigation." |
| 20:44:41 | [The report](#the-report), and the [request to approve](#the-approvals) one command |
| 20:47:43 to 20:48:35 | `az containerapp update`, approved, run with the approver's permissions |
| 20:48:38 | "The approved worker-only update returned a new revision, but the response still showed the prior revision as ready. I'm checking rollout and fresh telemetry before calling the backlog recovered." |
| 20:48:52 to 20:55:36 | 23 read-only commands, as the agent: the alert's state (10 times), the worker, its revisions and replicas, and the Activity Log |
| 20:49:36 | "The new revision is running without the fault: its first backlog report says the delay is inactive, and nine observed post-change deliveries averaged **0.1 ms** with no fault tag. The backlog has not yet drained in that first report, so I'm waiting for fresh gauges and alert reevaluation." |
| 20:50:26 | "The backlog reached **0 pending / 0 seconds** at 20:50:08 UTC, about one minute after the new container started. The new revision processed 278 notifications in that measurement and its delivery spans averaged about **0.06 ms**; I'm waiting for Azure Monitor's healthy evaluations to resolve the alert." |
| 20:52:18 | "The queue remains empty in consecutive post-change measurements, but the alert is still marked fired at 20:52 UTC. I'm continuing verification through the alert's evaluation window; I won't report it resolved until Azure Monitor does." |
| 20:55:31 | "Azure Monitor marked the alert **Resolved at 20:55:04 UTC**. I'm making one final scoped check of the revision and post-change measurements, then I'll provide the before/after results and the incident draft." |
| 20:55:57 | [The last reply](#the-last-reply) |
| 20:55:59 | The Stop hook, [`evidence-checklist.md`](../sre-agent/hooks/evidence-checklist.md), allowed the reply after 2.2 seconds |
| 21:33:16 | The platform's *Session Insights*: the agent's own review of the thread |

### The report

At 20:44:41, 2 minutes 34 seconds after the alert fired:

> **Impact:** The Sev2 backlog alert fired at **20:42:07 UTC** and remains fired (acknowledged); it triggers when the oldest pending notification exceeds **60 seconds**. At 20:42:32, **318** were waiting and the oldest was **420.5 seconds** late. Deliveries are **6/minute**, each taking about **10 seconds**. Before the 20:34 update, the 20:12:07–20:34:07 baseline had **0 pending**, **0 seconds** oldest, and no deliveries because the queue was idle.
>
> **UTC timeline:** Worker updates started at 20:31:06 and 20:34:07; revision `--0000018` was created at 20:34:14. At 20:35:47 its report showed 358 pending; the alert fired at 20:42:07.
>
> **Confirmed facts:** The previous revision has no `Faults__` settings; the active, ready revision has `Faults__WorkerDelayMs=10000` and `Faults__ExpiresAtUtc=2026-11-10T21:19:02Z`. Worker reports say `workerDelayFaultActive=True`, and delivery spans carry a 10,000 ms fault tag. The replica is ready with **0 restarts**; 476 PostgreSQL dependencies and 41 request submissions show **0 failures**; 546 worker traces show **0 warnings/iteration failures**, with no worker exceptions observed. The 41 submissions at 20:35 contributed load, but the observed 10-second per-delivery delay explains the sustained backlog.
>
> **Hypothesis and gaps:** **High confidence** that the newly enabled delay fault is the primary cause. We cannot compare delivery duration with the idle pre-change baseline; brief rollout probe/scaling events occurred, but the healthy running replica and continuing successful deliveries contradict an ongoing crash or database outage. The precise human intent behind the update is unknown.
>
> **Mitigation:** Remove **only** the two fault settings with the exact scoped command below. Approval creates a new worker revision without the delay; expect the backlog to drain within about a minute after it becomes ready. Rollback, if necessary, is a separately approved restoration of the previous two settings/revision; doing so would restore the delay. Without intervention the fault is configured to switch itself off at **21:19:02 UTC**, but the settings would remain. The change briefly rolls the single worker replica; no API, database, identity, networking, alert, or scaling setting changes. Submitting it now for administrator approval.

### The approvals

The thread's two approvals: the tool policy's question for the one Azure CLI write, and the grant that ran it with the approver's permissions (on behalf of the approver).

| | Approval request | Grant |
| --- | --- | --- |
| Status | Approved (**Allow once**) | Authorized (**Grant permissions**) |
| Requested | 20:44:41.587 | 20:47:43.916 |
| Decided | 20:47:23.784, by the approver | 20:47:43.916, by the approver |
| Tool | `RunAzCliWriteCommands` | the same command |
| Why | *Permission rule requires approval for this tool.* | *CLI-in-ADC OBO grant*, with token scope `https://management.core.windows.net/.default` |
| Command | `az containerapp update -n <worker> -g rg-ai-sdlc-operate --subscription <subscription> --remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc` | |

The approved command first ran as the agent and got an authorization error, as designed: the agent's identity can't change the worker. After the grant it ran again, from 20:47:43.888 to 20:48:35.417, with the approver's permissions.

### The last reply

At 20:55:57, 53 seconds after the alert resolved. The record that follows the reply's text is the body of [#301](https://github.com/melabadi/adept-assessment-northstars/issues/301), character for character.

> **Recovered.** The approved worker-only change removed the two delay-fault settings. The new revision is ready, the backlog remains empty, and Azure Monitor resolved the alert at **20:55:04 UTC**. The alert was fired for **12 minutes 57 seconds**.
>
> | Measure | Before mitigation | After mitigation |
> | --- | --- | --- |
> | Pending / oldest age | 278 / 819.7 seconds at 20:49:07 UTC | 0 / 0 seconds at 20:50:08 UTC; still 0 / 0 at 20:55:08 UTC |
> | Delivery rate | About 6 per minute | 278 reported sent in the 20:50 UTC minute |
> | Delivery duration | About 10 seconds, with delay-fault tag | 18 observed spans averaged 0.059 ms, with no fault tag |
> | Alert condition | Fired | Resolved at 20:55:04 UTC |
>
> The backlog drained about **one minute after the new container started**. The active revision's 10-second delay fault explains the timing and slow deliveries; the previous revision lacked it. The running worker had no restarts, and the checked database dependencies and API submissions had no failures. A burst of submissions added load but does not explain the per-delivery delay.
>
> **Incident-update delivery:** I could not post an update to an incident system; no incident-posting capability is available. This chat response is not an incident update. A person should read and file the following single draft as a GitHub Issue in `melabadi/adept-assessment-northstars`.
>
> Title: Incident record: notification backlog, 2026-11-10
>
> Labels: ai-sdlc, phase:operate

## On GitHub

- **20:57:33:** [#301](https://github.com/melabadi/adept-assessment-northstars/issues/301) was filed under the repository owner's account, 1 minute 36 seconds after the agent's last reply, with the draft's title and body unchanged: its body and the draft's code block are the same 2,999 characters. It got the draft's two labels and `incident`, the label of the GitHub team's incident form, which starts [07-operate-github](../../07-operate-github/)'s triage.
- **21:02:51 and 21:02:54:** that triage opened the follow-up [#302](https://github.com/melabadi/adept-assessment-northstars/issues/302) and commented its triage on #301.
- **21:03:32:** the Copilot cloud agent opened pull request [#303](https://github.com/melabadi/adept-assessment-northstars/pull/303) for the follow-up.
- **21:29:02:** #301 was closed.
