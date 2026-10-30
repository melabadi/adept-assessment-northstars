---
name: verify-worker-recovery
description: Confirm that RequestHub's notification worker recovered after a mitigation, with before and after evidence - fault settings gone, backlog drained, deliveries back to normal speed, alert resolved.
---

# Verify that the notification worker recovered

Run this after a mitigation, and again a few minutes later if telemetry is still arriving. Recovery needs fresh
evidence from after the change. Missing data is not proof of recovery.

## 1. The change is live

```bash
az containerapp show -n {{WORKER_APP_NAME}} -g {{AZURE_RESOURCE_GROUP}} \
  --query "{revision:properties.latestRevisionName, ready:properties.latestReadyRevisionName, faults:properties.template.containers[0].env[?starts_with(name, 'Faults__')].name}" -o json
```

Expect `revision` and `ready` to match and `faults` to be empty. Note the time the new revision became ready; it is
the start of the "after" window.

## 2. The backlog drained

```kusto
customMetrics
| where name in ("requesthub.notifications.pending", "requesthub.notifications.oldest_pending_age_seconds")
| where timestamp > ago(30m)
| summarize arg_max(timestamp, value) by name
```

Expect the latest pending count near 0 and the oldest pending age under {{BACKLOG_ALERT_THRESHOLD_SECONDS}} seconds,
with a timestamp after the new revision became ready.

## 3. Deliveries are fast again

```kusto
dependencies
| where name == "notification.deliver" and timestamp > ago(30m)
| summarize deliveries = count(), avg_ms = round(avg(duration), 0),
            with_fault = countif(isnotempty(customDimensions["requesthub.fault.worker_delay_ms"])) by bin(timestamp, 5m)
| order by timestamp asc
```

Expect deliveries after the change to take milliseconds and `with_fault` to be 0.

## 4. The alert resolved

Azure Monitor resolves `{{BACKLOG_ALERT_NAME}}` after three healthy one-minute evaluations, usually 3 to 6 minutes
after the backlog drains. Read its state with the alert id from the incident:

```bash
az resource show --ids <alert-id-from-the-incident> \
  --query "{condition:properties.essentials.monitorCondition, state:properties.essentials.alertState, resolved:properties.essentials.monitorConditionResolvedDateTime}"
```

Check it at most once a minute, for up to 10 minutes after the backlog drained. If it is still `Fired` then, report
that and stop: the team can follow it in Azure Monitor.

## Report

Give a before and after table with UTC timestamps: pending notifications, oldest pending age, deliveries per minute,
average delivery time, alert state. Say how long the incident lasted (alert fired to recovery) and how long the
backlog took to drain after the change. List anything you could not confirm.
