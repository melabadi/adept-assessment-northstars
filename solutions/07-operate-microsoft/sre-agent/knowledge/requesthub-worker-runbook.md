# Runbook: RequestHub notification backlog

Owner: RequestHub platform team (synthetic). Applies to resource group `{{AZURE_RESOURCE_GROUP}}`.

## How notifications work

1. The API (container app `{{API_APP_NAME}}`) writes a notification record in PostgreSQL whenever a request is
   submitted, commented on, rerouted, or decided. Submitting a request notifies the reviewers of its department,
   usually two people.
2. The notification worker (container app `{{WORKER_APP_NAME}}`, one replica) claims up to 20 pending notifications
   at a time, delivers them, and marks them sent. Several workers can run safely: each claims rows with
   `FOR UPDATE SKIP LOCKED`.
3. A failed delivery is retried with exponential backoff, up to five attempts, then marked failed.

A healthy worker delivers each notification within a few seconds of its creation.

## Signals

All app telemetry is in Application Insights `{{APPLICATIONINSIGHTS_NAME}}`. Its `cloud_RoleName` is the container
app's name: `{{API_APP_NAME}}` or `{{WORKER_APP_NAME}}`. Container logs are in Log Analytics `{{LOG_ANALYTICS_NAME}}`.

| Signal | Where | Healthy value |
| --- | --- | --- |
| `requesthub.notifications.pending` | `customMetrics`, after each batch | 0 to a few |
| `requesthub.notifications.oldest_pending_age_seconds` | `customMetrics`, after each batch | under 5 seconds |
| `requesthub.notifications.processed` with `outcome` | `customMetrics` | follows the load, outcome `sent` |
| `Notification backlog: pending=... workerDelayFaultActive=...` | `traces`, at most every 30 seconds | `workerDelayFaultActive=False` |
| `notification.deliver` span, tag `requesthub.fault.worker_delay_ms` | `dependencies` | milliseconds, no fault tag |
| Revisions, restarts, probe failures | `ContainerAppSystemLogs_CL` | one running revision |

The alert `{{BACKLOG_ALERT_NAME}}` (severity 2) fires when the oldest pending notification is older than
{{BACKLOG_ALERT_THRESHOLD_SECONDS}} seconds, and resolves a few minutes after it drops below.

## Known causes

1. **Delay fault left on.** Teams use fault injection for drills and tests. The settings `Faults__WorkerDelayMs`
   (extra milliseconds per delivery) and `Faults__ExpiresAtUtc` (when the fault switches itself off) on the worker
   slow every delivery. Changing them creates a new worker revision. Signs: `workerDelayFaultActive=True`, deliveries
   taking several seconds, `notification.deliver` spans tagged with the delay.
2. **Worker cannot reach the database.** Signs: "Notification worker iteration failed" warnings every few seconds,
   failed database dependencies, readiness probe failures.
3. **Worker not running.** Signs: no worker telemetry, no running revision, crash loops in the system logs.
4. **Load spike.** Signs: many more submitted requests than usual while deliveries stay fast. The backlog drains on
   its own.

## Mitigation

Every change needs approval from an SRE Agent Administrator (Review mode) and runs with that person's Azure
permissions. The agent's own identity can only read.

| Cause | Mitigation | Effect |
| --- | --- | --- |
| Delay fault | `az containerapp update -n {{WORKER_APP_NAME}} -g {{AZURE_RESOURCE_GROUP}} --remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc` | A new revision without the fault starts within about a minute and drains the backlog within seconds. |
| Database or worker failure | Escalate to the platform team with the evidence. | |
| Load spike | No change. Watch the backlog drain. | |

Do not delete notifications, change the database, restart or scale the API, or change identities and role
assignments. To roll back a mitigation, set the removed settings again.

## Verify recovery

1. The worker's active revision has no `Faults__` settings.
2. Pending notifications near 0 and the oldest pending age under the threshold, measured after the new revision
   became ready.
3. `notification.deliver` spans take milliseconds again.
4. The alert shows **Resolved**.

## Follow-ups after a fault-related incident

- Add an expiry check to the drill checklist, so a fault never outlives the drill.
- Measure the backlog independently of the worker, so a slow worker cannot delay its own alert.
