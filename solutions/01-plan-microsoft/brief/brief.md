# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **Microsoft Foundry agent requirements-analyst v10** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests are often routed to the wrong department, causing delays and manual rerouting by reviewers. There is no measurement of how often this occurs, and the process is inefficient. _(T01, T02)_

## Goals

- Reduce the time requests sit before reaching the correct team. _(T01)_
- Provide reviewers with advisory triage recommendations that include the rationale and cited policy IDs. _(T03, T08)_
- Ensure all recommendations and lookups are auditable. _(T13)_
- Support both English and French for Montréal office users. _(T11)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | The assistant must provide advisory routing and priority suggestions for each new request, including a rationale and the policy IDs and versions cited. | T03, T08 |
| R2 | must | Reviewers must confirm or override the assistant's suggestion; automatic routing without confirmation is not allowed. | T04, T19, POL-GOV-001 |
| R3 | must | The system must audit every recommendation and lookup, recording who asked, when, and what was returned. | T13 |
| R4 | should | If a request is rerouted after a suggestion, the UI must indicate that the suggestion is stale. | T10 |
| R5 | must | The assistant must support both English and French. | T11 |

## Decisions

- **D1** The first release delivers recommendations plus reviewer confirmation; no automatic routing without a person confirming. _(T19)_

## Conflicts

- **C1** Ava wants automatic routing when the assistant is confident, but Priya and policy POL-GOV-001 require reviewer confirmation for all suggestions. _(T05, T04, POL-GOV-001)_ → resolved: Automatic routing is out of scope for this release; only recommendations with reviewer confirmation are allowed. (T19)
- **C2** POL-ROUTE-004 requires expensive requests to go to Finance, but Ben and POL-ROUTE-001 state that IT owns all computing equipment regardless of cost. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** What is the agreed definition of 'fast' for assistant response time? _(T12)_
- **Q2** Who is allowed to override a suggestion: only reviewers, or approvers as well? _(T21)_
- **Q3** How long should recommendations (not decisions) be retained in the audit log? _(T22)_
- **Q4** What confidence score threshold, if any, should hide a suggestion from reviewers? _(T15)_

## Out of scope

- Automatic approval or routing of requests without reviewer confirmation. _(T19, T20, POL-GOV-001)_
- Email notifications to requesters. _(T20)_

## Success measures

- The share of requests rerouted after triage, measured for two weeks before and after the assistant is enabled. _(T23)_

## Engineering backlog: Assisted Request Triage

Implement an advisory assistant that recommends routing and priority for incoming requests, with rationale and policy citations, supporting audit, reviewer confirmation, and bilingual operation. _(T03, T08, T10, T13, T14, T19, T11)_

### TASK-1 · Implement Assistant Recommendation Engine

Develop the backend logic to generate advisory routing and priority suggestions for new requests, including rationale and policy citations. _(T03, T08, POL-ROUTE-007, POL-ROUTE-001, POL-ROUTE-004)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a new request, When the backend receives the request data, Then it returns a suggested department, priority, rationale, and policy IDs.
  - [ ] Given a request with missing or unclear information, When the assistant cannot determine a department, Then it marks the request for human review and asks a clarifying question.
  - [ ] Given a request that matches multiple policies, When the assistant generates a suggestion, Then it cites all relevant policy IDs and versions.

### TASK-2 · Reviewer Confirmation and Override UI

Build the frontend panel for reviewers to confirm or override assistant suggestions, with rationale and policy citations visible. _(T08, T10, T16)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a reviewer opens a request, When a suggestion is available, Then the panel displays the suggested department, priority, rationale, and policy IDs.
  - [ ] Given a reviewer confirms a suggestion, When the action is taken, Then only one audit entry and one notification are created even if the button is double-clicked.
  - [ ] Given a reviewer overrides a suggestion, When the override is submitted, Then the UI updates to show the new routing and marks the suggestion as stale.

### TASK-3 · Audit Logging for Recommendations and Lookups

Extend the audit history to record every recommendation and lookup, including who asked, when, and what was returned. _(T13, T16)_

- **Owner role:** Full-stack engineer
- **Depends on:** TASK-1, TASK-2
- **Acceptance criteria:**
  - [ ] Given a reviewer requests a recommendation, When the assistant responds, Then the audit log records the user, timestamp, and recommendation details.
  - [ ] Given a reviewer confirms or overrides a suggestion, When the action is taken, Then the audit log records the event with user and timestamp.
  - [ ] Given an audit entry is created, When a reviewer double-clicks the confirmation, Then only one entry is recorded.

### TASK-4 · Bilingual Support and Assistant Availability Handling

Ensure the assistant and UI support both English and French, and clearly indicate when the assistant is unavailable. _(T11, T14)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1, TASK-2
- **Acceptance criteria:**
  - [ ] Given a reviewer opens a request, When the assistant is available, Then the UI displays all suggestions and rationale in the user's preferred language.
  - [ ] Given a reviewer opens a request, When the assistant is unavailable, Then the panel shows an unavailable message and allows manual routing.
  - [ ] Given a reviewer uses the Montréal office locale, When the assistant generates a suggestion, Then the suggestion and rationale are shown in French.

