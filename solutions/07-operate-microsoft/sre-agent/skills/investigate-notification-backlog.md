---
name: investigate-notification-backlog
description: Measure RequestHub's notification backlog and find what changed on the notification worker, with Application Insights, Log Analytics, and read-only Azure CLI commands.
---

# Investigate the notification backlog

Use the investigation window you set from the alert (UTC). Query Application Insights `{{APPLICATIONINSIGHTS_NAME}}`
for app telemetry and Log Analytics `{{LOG_ANALYTICS_NAME}}` for container logs. Return at most 30 rows per query.

## 1. Measure the backlog

How the signal works: after each batch of up to 20 notifications, the worker publishes two gauges, the number of
pending notifications and the age of the oldest one. When deliveries are slow, a batch takes longer, so the gauges
update less often. A flat line between updates is expected, not missing data.

```kusto
customMetrics
| where name in ("requesthub.notifications.pending", "requesthub.notifications.oldest_pending_age_seconds")
| summarize value = max(value) by name, bin(timestamp, 1m)
| order by timestamp asc
```

Deliveries per minute (`outcome` is `sent`, `retry`, or `failed`):

```kusto
customMetrics
| where name == "requesthub.notifications.processed"
| summarize delivered = sum(value) by outcome = tostring(customDimensions.outcome), bin(timestamp, 1m)
| order by timestamp asc
```

How long each delivery takes, and whether a delay fault was applied to it:

```kusto
dependencies
| where name == "notification.deliver"
| summarize deliveries = count(), avg_seconds = round(avg(duration) / 1000, 1),
            fault_delay_ms = max(toint(customDimensions["requesthub.fault.worker_delay_ms"])) by bin(timestamp, 5m)
| order by timestamp asc
```

The worker's own backlog report, written at most every 30 seconds after a batch:

```kusto
traces
| where message startswith "Notification backlog"
| project timestamp, message
| order by timestamp desc
| take 20
```

Incoming load. Each submitted request creates about two notifications:

```kusto
requests
| where name == "POST /api/requests"
| summarize submitted = count(), failed = countif(success == false) by bin(timestamp, 5m)
| order by timestamp asc
```

## 2. Find what changed

Read-only commands. Show only `Faults__` settings, never other environment values.

```bash
az containerapp revision list -n {{WORKER_APP_NAME}} -g {{AZURE_RESOURCE_GROUP}} --all \
  --query "[].{revision:name, created:properties.createdTime, active:properties.active, state:properties.runningState}" -o table

az containerapp show -n {{WORKER_APP_NAME}} -g {{AZURE_RESOURCE_GROUP}} \
  --query "properties.template.containers[0].env[?starts_with(name, 'Faults__')]" -o table

az containerapp revision show -n {{WORKER_APP_NAME}} -g {{AZURE_RESOURCE_GROUP}} --revision <previous-revision> \
  --query "properties.template.containers[0].env[?starts_with(name, 'Faults__')]" -o table

az monitor activity-log list -g {{AZURE_RESOURCE_GROUP}} --offset 3h \
  --query "[?contains(resourceId, '{{WORKER_APP_NAME}}')].{time:eventTimestamp, operation:operationName.localizedValue, status:status.value, caller:caller}" -o table
```

Container events for the worker, including new revisions:

```kusto
ContainerAppSystemLogs_CL
| where ContainerAppName_s == "{{WORKER_APP_NAME}}"
| project TimeGenerated, RevisionName_s, Reason_s, Log_s
| order by TimeGenerated desc
| take 30
```

## 3. Rule out other causes

- **Worker errors or restarts:** `traces` with `severityLevel >= 2` and `exceptions` where `cloud_RoleName == "{{WORKER_APP_NAME}}"`; restarts
  and probe failures in `ContainerAppSystemLogs_CL`.
- **Database:** `dependencies` for the worker with `success == false`.
- **API:** failed `requests` where `cloud_RoleName == "{{API_APP_NAME}}"`.
- **A load spike:** compare submitted requests with the 30 minutes before the alert. A healthy worker clears a spike
  of a few hundred notifications within a minute.

## What the evidence means

| Evidence | Points to |
| --- | --- |
| `workerDelayFaultActive=True`, `fault_delay_ms` set, deliveries of several seconds each, a new revision with `Faults__WorkerDelayMs` | The delay fault slows every delivery. Remove the two fault settings. |
| Worker exceptions, "Notification worker iteration failed" warnings, failed database calls | The worker cannot reach the database or crashes. Escalate; do not change settings. |
| Deliveries fast but submitted requests far above normal | A load spike. The backlog drains on its own; keep watching. |
| No worker telemetry at all | The worker is not running. Check its revision and replica state. |
