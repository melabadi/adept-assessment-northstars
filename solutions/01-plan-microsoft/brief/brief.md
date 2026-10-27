# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **Microsoft Foundry agent requirements-analyst v10** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests are frequently routed to the wrong department, causing delays and manual rerouting by reviewers. There is no measurement of how often this occurs, and the process is inefficient. _(T01, T02)_

## Goals

- Reduce the time requests sit before reaching the correct team. _(T01)_
- Provide reviewers with advisory triage recommendations that cite the relevant routing policies. _(T03, T08)_
- Ensure all recommendations and assistant tool usage are auditable. _(T13)_
- Support both English and French for Montréal office users. _(T11)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | The assistant must provide advisory routing and priority suggestions for each new request, citing the relevant policy IDs and versions. | T03, T08 |
| R2 | must | Reviewers must confirm or reroute the assistant's suggestion; no automatic routing or approval is allowed. | T04, T19, POL-GOV-001 |
| R3 | must | Every recommendation and lookup by the assistant must be auditable, including who asked, when, and what was returned. | T13 |
| R4 | should | The system should support both English and French interfaces. | T11 |
| R5 | must | If a request is rerouted after a suggestion, the UI must indicate that the suggestion is stale. | T10 |

## Decisions

- **D1** The first release delivers recommendations plus reviewer confirmation; no automatic routing without a person confirming. _(T19)_

## Conflicts

- **C1** Ava wants automatic routing when the assistant is confident, but Priya and policy POL-GOV-001 require reviewer confirmation for all recommendations. _(T04, T05, POL-GOV-001)_ → resolved: The first release delivers recommendations plus reviewer confirmation; no automatic routing without a person confirming. (T19)
- **C2** POL-ROUTE-004 requires expensive requests to go to Finance, but Ben and POL-ROUTE-001 claim IT owns all computing equipment regardless of cost. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** Who is allowed to override a suggestion: only reviewers, or approvers as well? _(T21)_
- **Q2** How long should recommendations be retained in the audit log? _(T22)_
- **Q3** What is the baseline for request rerouting before the assistant is enabled? _(T23)_
- **Q4** What is the agreed definition of 'fast' for assistant response time? _(T12)_

## Out of scope

- Automatic approval or routing of requests without reviewer confirmation. _(T19, T20, POL-GOV-001)_
- Email notifications to requesters. _(T20)_

## Success measures

- The share of requests rerouted after triage, measured for two weeks before and after the assistant is enabled. _(T23)_

## Engineering backlog: Assisted Request Triage

Deliver an advisory assistant that recommends routing and priority for incoming requests, citing policies, supporting audit, and enabling reviewer confirmation in English and French. _(T03, T08, T10, T13, T14, T19, T11)_

### TASK-1 · Implement Policy-Based Triage Recommendation Engine

Develop the backend service to generate advisory routing and priority suggestions for new requests, citing relevant policy IDs and versions. _(T03, T08, POL-ROUTE-007, POL-ROUTE-001, POL-ROUTE-004)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a new request, When the engine processes it, Then it returns a suggested department, priority, rationale, and policy citations.
  - [ ] Given a request with missing information, When the engine cannot determine a department, Then it marks the request for human review and asks a clarifying question.
  - [ ] Given a request matches multiple policies, When a conflict exists, Then the engine returns all relevant policy citations in the rationale.

### TASK-2 · Reviewer Confirmation and Manual Rerouting UI

Build the frontend interface for reviewers to confirm or reroute suggestions, display rationales, and indicate when a suggestion is stale. _(T08, T10, T14, T16)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a reviewer opens a request, When a suggestion is available, Then the UI displays the suggested department, priority, rationale, and policy citations.
  - [ ] Given a reviewer reroutes a request after a suggestion, When the request is viewed again, Then the UI marks the suggestion as stale.
  - [ ] Given a reviewer double-clicks to confirm a suggestion, When the action is processed, Then only one audit entry and one notification are created.
  - [ ] Given the assistant is unavailable, When a reviewer opens a request, Then the UI shows an unavailable message and enables manual routing.

### TASK-3 · Audit Logging for Recommendations and Actions

Ensure all recommendations, lookups, and reviewer actions are logged with user, timestamp, and returned data for audit purposes. _(T13, T16)_

- **Owner role:** Full-stack engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a reviewer requests a recommendation, When the assistant responds, Then an audit entry is created with the user, time, and result.
  - [ ] Given a reviewer confirms or reroutes a suggestion, When the action is taken, Then an audit entry is created for the action.
  - [ ] Given a tool is used by the assistant to look up information, When the lookup occurs, Then the audit log records who, when, and what was returned.

### TASK-4 · Localization for English and French

Add support for English and French in the triage assistant UI and recommendation outputs. _(T11)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-2
- **Acceptance criteria:**
  - [ ] Given a reviewer in the Montréal office, When the UI is loaded, Then all triage assistant features are available in French.
  - [ ] Given a reviewer in another office, When the UI is loaded, Then all triage assistant features are available in English.
  - [ ] Given a reviewer switches language preference, When the UI reloads, Then all assistant outputs and labels appear in the selected language.

