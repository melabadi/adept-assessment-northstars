---
name: telemetry-investigation
description: Read RequestHub's notification backlog, delivery rate, alert state, and recent worker changes from the terminal with Azure CLI and KQL, to follow or double-check an Azure SRE Agent investigation. Use during the Operate drill, when an alert fires, or to collect numbers for an incident summary.
---

# Telemetry investigation

Azure SRE Agent investigates the alert in Azure. This skill gets the same evidence from a terminal, so a person can
follow along or check the agent's numbers. Every command is read-only.

## Inputs
Run from the repository root after `azd up` in `solutions/07-operate-microsoft`:

```powershell
$e = azd env get-values --cwd solutions/07-operate-microsoft --output json | ConvertFrom-Json
```

## Procedure
1. **One-line status** (backlog, fault settings, alert, SRE Agent thread):
   `python solutions/07-operate-microsoft/incident.py watch --once`
2. **The alert's signal**, one value per minute (the metric the alert evaluates):

   ```powershell
   az monitor app-insights metrics show --app $e.APPLICATIONINSIGHTS_NAME -g $e.AZURE_RESOURCE_GROUP `
     --metric "customMetrics/requesthub.notifications.oldest_pending_age_seconds" --aggregation max --interval PT1M --offset 1h
   ```

3. **Deliveries and their duration** from the logs (keep the query on one line: `az` on Windows cuts a multi-line
   argument at the first line break):

   ```powershell
   az monitor app-insights query --app $e.APPLICATIONINSIGHTS_NAME -g $e.AZURE_RESOURCE_GROUP --offset 1h -o tsv --query "tables[0].rows" --analytics-query "dependencies | where name == 'notification.deliver' | summarize deliveries = count(), avg_seconds = round(avg(duration) / 1000, 1), fault_delay_ms = max(toint(customDimensions['requesthub.fault.worker_delay_ms'])) by bin(timestamp, 5m) | order by timestamp asc"
   ```

   Each row is five minutes: deliveries, average seconds per delivery, and the injected delay if any.

4. **What changed on the worker** (shows only fault settings, never other environment values):

   ```powershell
   az containerapp revision list -n $e.WORKER_APP_NAME -g $e.AZURE_RESOURCE_GROUP --all `
     --query "[].{revision:name, created:properties.createdTime, active:properties.active}" -o table
   az containerapp show -n $e.WORKER_APP_NAME -g $e.AZURE_RESOURCE_GROUP `
     --query "properties.template.containers[0].env[?starts_with(name, 'Faults__')]" -o table
   ```

5. **Compare with the agent.** Open the investigation (`$e.SRE_AGENT_PORTAL_URL`, then **Incidents**) and check that
   its timeline, numbers, and cause match what you found.

## Reading the numbers
- Healthy: oldest pending age under 5 seconds, deliveries in milliseconds, no `fault_delay_ms`.
- During the drill: each delivery takes `Faults__WorkerDelayMs` milliseconds, the oldest pending age climbs past the
  alert threshold (`BACKLOG_ALERT_THRESHOLD_SECONDS`), and the worker's revision list shows the change that added the fault.
- The worker reports its gauges after each batch of up to 20 notifications. When deliveries are slow, the gauge
  updates every few minutes; flat steps are expected.
- Logs arrive two to five minutes after the fact; the metrics store about one minute.

## Failure handling
- `az monitor app-insights` needs the `application-insights` Azure CLI extension; accept the install prompt or run
  `az extension add -n application-insights`.
- No data at all for the worker: check that it runs (`az containerapp revision list`), then the
  **recovery-verification** skill.
