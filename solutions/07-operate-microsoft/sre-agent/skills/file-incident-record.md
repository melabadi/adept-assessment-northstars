---
name: file-incident-record
description: File the record of a RequestHub notification backlog incident as one GitHub Issue in {{GITHUB_REPOSITORY}}, after recovery is verified, with placeholders instead of identifiers. Use it once per incident.
---

# File the incident record in GitHub

The team keeps one GitHub Issue per incident as its record. People outside the team can read it, so it describes
resources by their role and never identifies the deployment.

## Placeholders, never identifiers

Name resources only by role: "the worker", "the API", "the database", "the alert", "the resource group", "the previous
worker revision", "the new worker revision". Never write:

- a GUID or other id of any kind, with or without hyphens: subscription, tenant, alert, thread, revision, operation,
  trace, or request ids;
- a host name or URL of a deployed resource, or an Azure resource id (`/subscriptions/...`);
- a resource name, including the names in the Scope table of your instructions: they carry a random suffix;
- a subscription or tenant name, an account name, or an e-mail address. Say "an SRE Agent Administrator approved it",
  not who.

UTC times, durations, counts, metric values, setting names (`Faults__WorkerDelayMs`), and the alert rule's display
name (`RequestHub notification backlog`) are fine.

A guard hook checks every GitHub call before it runs, and blocks it if the text contains any of the identifiers above.
If it blocks yours, rewrite the text with placeholders and submit it once more. Never try to get around the guard.

## The Issue

- Repository: `{{GITHUB_REPOSITORY}}`
- Title: `Incident record: notification backlog, <YYYY-MM-DD>` (the UTC date the alert fired)
- Labels: `ai-sdlc` and `phase:operate`, nothing else. Never `incident` or `incident-followup`: those labels start
  another team's automation.
- Body, in Markdown:

```markdown
## Summary
<One or two sentences: what requesters and reviewers experienced, and for how long.>

## Impact
| Measure | Value |
| --- | --- |
| Alert fired (UTC) | <time> |
| Mitigation ran (UTC) | <time> |
| Backlog drained (UTC) | <time> |
| Alert resolved (UTC) | <time, or "not yet"> |
| Peak oldest pending notification | <seconds> |
| Peak pending notifications | <count> |

## Timeline (UTC)
| Time | Event | Evidence |
| --- | --- | --- |
| <time> | <event> | <the telemetry, log, or Activity Log entry that shows it> |

## Root cause
<The confirmed cause and the evidence for it, for example the delay fault set on the worker at <time> by a
configuration change that created a new worker revision.>

## Mitigation
<What changed, with placeholders: `az containerapp update -n <worker> -g <resource group> --remove-env-vars
Faults__WorkerDelayMs Faults__ExpiresAtUtc`. Say that an SRE Agent Administrator approved it and that it ran with the
approver's permissions.>

## Follow-up
<One bounded change that would prevent a repeat or detect it sooner, with how to verify it.>

---
Filed by Azure SRE Agent from its investigation of the alert. All data comes from RequestHub's synthetic demo.
```

## Filing it

1. Write the title and body, then read them once more against the list above.
2. Create the Issue with the GitHub tool. The platform holds the call until a person reviews the text and selects
   **Allow once**. If they cancel it, do not retry: put the title and body in your reply instead.
3. Reply with the Issue number. File only this one Issue for the incident unless the team asks for another.

If no GitHub tool is available (the GitHub connector is not connected), put the title, labels, and body in your reply,
say the connector is not connected, and stop.
