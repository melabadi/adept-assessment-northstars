# Severity and area rubric for RequestHub incidents

Pick the **highest** severity whose description matches the impact in the report. Judge by what users experienced, not by how alarming a log looks.

| Severity | Label | Impact on RequestHub | Examples |
| --- | --- | --- | --- |
| 1 | `severity:1` | Approval integrity, data, or access at risk; or RequestHub unavailable for everyone. | A decision recorded without a person with the Approver role. Requests lost or visible to the wrong department. The portal down for all users. |
| 2 | `severity:2` | A core flow (submit, review, decide) unavailable or badly degraded for at least one department, with no workaround. | Reviewers in a department cannot open their queue. Decisions fail with errors. |
| 3 | `severity:3` | A supporting function degraded, delayed, or duplicated. Core flows still work, or a workaround exists. No data loss. | Notifications late or sent several times. Triage recommendations unavailable, so reviewers route requests by hand. |
| 4 | `severity:4` | Cosmetic or limited to one person, with no business impact. | A wrong label in the French UI. One user's slow page load. |

Approval-integrity impact is always severity 1. A person cannot be bypassed, even briefly.

## Areas

Pick one or two areas, matching the component where the failure showed up.

| Label | Component | Code |
| --- | --- | --- |
| `area:worker` | Notification worker: delivery, retries, backlog | `app/src/RequestHub.Worker/`, `app/src/RequestHub.Core/Notifications/` |
| `area:api` | API endpoints, authorization, business rules, triage providers | `app/src/RequestHub.Api/`, `app/src/RequestHub.Core/Services/` |
| `area:web` | Web UI | `app/web/` |
| `area:database` | PostgreSQL schema, migrations, data | `app/src/RequestHub.Core/Data/` |
| `area:infrastructure` | Hosting, networking, identity, configuration | `app/infra/` |

Use `needs-info` when the report does not support a classification yet.
