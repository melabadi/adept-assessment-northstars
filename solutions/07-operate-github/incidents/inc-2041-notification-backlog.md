### Status

Mitigated

### Environment

staging

### Detected at (UTC)

2026-10-20T14:05Z

### Impact

Reviewers and approvers in IT and Facilities received RequestHub notifications up to 35 minutes late, and some received the same notification many times. Submitting, reviewing, and deciding requests kept working: every decision was still made by a person with the Approver role. No request or decision data was lost.

### Recent changes

- 2026-10-20 13:46 UTC: configuration change in staging. Notification delivery switched from RequestHub's built-in log-only sender to the platform team's webhook relay adapter (pilot, maintained outside this repository, HTTP timeout 10 seconds).
- 2026-10-20 13:52 UTC: worker revision `requesthub-worker--0000418` (image `requesthub-worker:2026.10.20.3`) became active with the relay adapter.
- 2026-10-19 16:30 UTC: API revision `requesthub-api--0000231` deployed. It made no notification changes.

### Timeline (UTC)

- 13:52 Worker revision 0000418 active.
- 13:58 First "Notification worker iteration failed" warning in the worker log. It then repeats about every 15 seconds.
- 13:58 Last "Notification backlog" line from the worker (pending=3). The line stops appearing after this.
- 14:05 Synthetic check alert: `GET /api/admin/notifications/backlog` reports oldestPendingAgeSeconds above the 300-second threshold.
- 14:09 Ben Okafor (u-ben) and Chloé Dubois (u-chloe) report late notifications, some received repeatedly.
- 14:12 Relay team: the same notification ids arrive about every 15 seconds, and requests for one notification never complete.
- 14:20 Backlog endpoint: 212 pending, failed 0. The worker metric `requesthub.notifications.pending` still shows 3.
- 14:31 Mitigation started: traffic moved back to worker revision `requesthub-worker--0000417` (built-in log-only sender).
- 14:33 Backlog endpoint: 0 pending. Mitigated.

### Signals and logs (sanitized)

```text
2026-10-20T13:58:12Z info NotificationWorker: Notification backlog: pending=3 oldestPendingAgeSeconds=4.1 failed=0
  workerDelayFaultActive=False
2026-10-20T13:58:29Z warn NotificationWorker: Notification worker iteration failed; retrying in 5 seconds
  System.Threading.Tasks.TaskCanceledException: The request was canceled due to the configured HttpClient.Timeout
    of 10 seconds elapsing.
   ---> System.TimeoutException: A task was canceled.
     at RelayPilot.WebhookNotificationSender.SendAsync(Notification notification, CancellationToken cancellationToken)
     at RequestHub.Core.Notifications.NotificationProcessor.ProcessBatchAsync(CancellationToken ct)
     at NotificationWorker.ExecuteAsync(CancellationToken stoppingToken)
2026-10-20T13:58:44Z warn NotificationWorker: Notification worker iteration failed; retrying in 5 seconds
  System.Threading.Tasks.TaskCanceledException: (same exception and stack trace)
  (the warning repeats about every 15 seconds until 14:31)

GET /api/admin/notifications/backlog
  14:05:00Z  {"pending":97,"oldestPendingAgeSeconds":412.0,"failed":0}
  14:20:00Z  {"pending":212,"oldestPendingAgeSeconds":1312.0,"failed":0}
  14:33:10Z  {"pending":0,"oldestPendingAgeSeconds":0,"failed":0}

Worker metric requesthub.notifications.pending: 3 from 13:58 to 14:31 (flat)
Relay receiver summary (from the relay team): 6 notification ids received about 130 times each between 13:58 and 14:31;
  requests for notification 7c1e9b2a never complete and the client gives up after 10 seconds.
```

### Mitigation so far

Rolled the worker back to revision `requesthub-worker--0000417`, which uses the built-in log-only sender. The backlog drained within two minutes. The relay adapter stays disabled in staging until the follow-up is done.

### Evidence links

- Worker log excerpts and backlog responses: pasted above (sanitized).
- Relay receiver log: summary from the relay team above. The full log was requested and is not available yet.
- Dashboards: not attached.

_Synthetic demo incident: every name, time, and identifier is invented._
