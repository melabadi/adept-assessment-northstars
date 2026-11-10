---
name: draft-incident-record
description: Draft the record of a RequestHub notification backlog incident in your last reply, after recovery is verified, with placeholders instead of identifiers, for a person to read and file as a GitHub Issue in {{GITHUB_REPOSITORY}}. Use it once per incident.
---

# Draft the incident record

The team keeps one GitHub Issue per incident as its record. People outside the team can read it, so it describes
resources by their role and never identifies the deployment. You draft it in your reply; a person reads it and files
it. You have no GitHub tool, and you never write to GitHub. The record states every fact the team's incident form asks
for (status, environment, detection time, impact, recent changes, and timeline), so the person who files it never has
to add one.

## Placeholders, never identifiers

Name resources only by role: "the worker", "the API", "the database", "the alert", "the resource group", "the previous
worker revision", "the new worker revision". Never write:

- a GUID or other id of any kind, with or without hyphens: subscription, tenant, alert, thread, revision, operation,
  trace, or request ids;
- a host name or URL of a deployed resource, or an Azure resource id (`/subscriptions/...`);
- a resource name, including the names in the Scope table of your instructions: they carry a random suffix;
- a subscription or tenant name, an account name, or an e-mail address. Say "an SRE Agent Administrator approved it",
  not who.

UTC times, durations, counts, metric values, setting names (`Faults__WorkerDelayMs`), the alert rule's display name
(`RequestHub notification backlog`), and the environment's name (`{{AZURE_ENV_NAME}}`) are fine.

## The record

End your last reply with the record, in this layout, with nothing after it:

- A line `Title: Incident record: notification backlog, <YYYY-MM-DD>` (the UTC date the alert fired).
- A line `Labels: ai-sdlc, phase:operate`. Nothing else: never `incident` or `incident-followup`, because those labels
  start another team's automation.
- The body, in one code block marked `markdown`, so the person can copy it exactly as written. Use inline code inside
  the body, never another code block:

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

## Recent changes
<Every deployment or configuration change to the worker or the API in the investigation window, with its UTC time and
evidence, for example a configuration change at <time> that created the new worker revision with
`Faults__WorkerDelayMs`. Name revisions by role, never by name. Write "None in the Activity Log" if there were none.>

## Root cause
<The confirmed cause and the evidence for it, for example the delay fault set on the worker at <time> by a
configuration change that created a new worker revision.>

## Mitigation
<What changed, with placeholders: `az containerapp update -n <worker> -g <resource group> --remove-env-vars
Faults__WorkerDelayMs Faults__ExpiresAtUtc`. Say that an SRE Agent Administrator approved it and that it ran with the
approver's permissions.>

## Follow-up
<One bounded change that would prevent a repeat or detect it sooner, with how to verify it.>

## Status
| Field | Value |
| --- | --- |
| Status | <Resolved once the alert resolved; Mitigated while it is still active> |
| Environment | `{{AZURE_ENV_NAME}}` (Azure) |
| Detected at (UTC) | <the time the alert fired, as YYYY-MM-DDTHH:MMZ> |

---
Drafted by Azure SRE Agent from its investigation of the alert, and filed by a person who read it. All data comes from
RequestHub's synthetic demo.
```

## Before you reply

1. Read the title and body once more against the list above.
2. Above the record, say in one sentence that a person reads it and files it as a GitHub Issue in
   `{{GITHUB_REPOSITORY}}`. Draft only this one record for the incident unless the team asks for another.
