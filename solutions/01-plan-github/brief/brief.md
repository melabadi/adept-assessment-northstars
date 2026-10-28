# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **GitHub Copilot (plan-github agent)** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests can sit with the wrong department while reviewers reroute them manually; the estimated share rerouted has not been measured. _(T01, T02)_

## Goals

- Reduce the time requests wait before reaching the right team by assisting reviewers with department and priority recommendations. _(T01, T03)_
- Measure the share of requests rerouted after triage, with a two-week baseline before enabling the assistant. _(T23)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | For a new request, provide advisory department and priority recommendations with a short rationale and the policy IDs and versions relied on. | T03, T08, POL-GOV-001 |
| R2 | must | Send only the request title, description, category, and approved routing policies to the AI service; do not send attachments or personal data beyond the requester's department. | T09 |
| R3 | must | Keep recommendations advisory: a reviewer confirms routing, and only an authorized approver may approve or reject a request. | T04, T19, POL-GOV-001 |
| R4 | must | Show when a recommendation is stale after routing changes, support English and French, and show confidence without confidence-based sorting or filtering; no hiding threshold is defined. | T10, T11, T15 |
| R5 | must | Audit every recommendation and every assistant lookup, including who asked, when, and what was returned. | T13 |
| R6 | must | When the AI service is unavailable, clearly communicate that status and allow reviewers to continue routing manually. | T14 |
| R7 | must | A double confirmation of a routing suggestion must not create duplicate audit entries or notifications. | T16 |
| R8 | must | Apply the approved safety-hazard routing rule: reported hazards are Urgent and route to Facilities regardless of category. | T17, POL-ROUTE-006 |

## Decisions

- **D1** The first release provides advisory recommendations with reviewer confirmation; automatic routing without a person confirming is deferred. _(T19)_

## Conflicts

- **C1** The request for automatic routing without review conflicts with the requirement for advisory recommendations and human confirmation. _(T04, T05)_ → resolved: For the first release, recommendations require reviewer confirmation; there is no automatic routing without a person confirming. (T19)
- **C2** For computing equipment above 5,000, T06 requires Finance first while T07 says IT owns all computing equipment; the policies do not specify which route takes precedence. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** What response-time target should define 'fast' for the triage experience? _(T12)_
- **Q2** Should there be a confidence threshold below which a recommendation is hidden, and if so, what is it? _(T15)_
- **Q3** (blocking) Which roles may override a suggestion: reviewers, approvers, or both? _(T21)_
- **Q4** (blocking) How long should recommendations be retained? The seven-year audit period for decisions does not specify recommendation retention. _(T22)_
- **Q5** (blocking) For computing equipment above 5,000, should routing go to IT Services or to Finance first, and which policy takes precedence? _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_

## Out of scope

- Automatic approval of any kind and email notifications to requesters are outside this release. _(T20)_
- Automatic routing without a person confirming it is not part of this release. _(T19)_

## Success measures

- Measure the share of requests rerouted after triage; collect a two-week baseline before enabling the assistant. No target value is specified. _(T23)_

## Engineering backlog: Assisted request triage

Extend RequestHub's existing advisory triage recommendation, routing, policy, and audit-history capabilities with policy-grounded recommendations and a safe reviewer workflow. _(T03, T08, T10, T14, T19, POL-GOV-001)_

### TASK-1 · Constrain triage inputs and ground recommendations in policies

Build on the existing advisory triage recommendation and approved-policy APIs. Enforce the allowed AI input boundary and use approved policy references for department and priority suggestions, including the safety-hazard rule. Do not encode a precedence rule for expensive computing equipment while the policy conflict remains unresolved. _(T03, T08, T09, T17, T19, POL-GOV-001, POL-ROUTE-006)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a reviewer requests a recommendation for a new request, When the triage provider receives the request, Then its inputs contain only the title, description, category, and approved routing policies, with no attachments or personal data beyond the requester's department.
  - [ ] Given a request reports a safety hazard, When the recommendation is generated, Then it recommends Urgent priority and Facilities regardless of the request category.
  - [ ] Given a recommendation is returned, When the response is presented, Then it remains advisory and includes the suggested department, priority, a short rationale, and the cited policy IDs and versions.

### TASK-2 · Present recommendations with rationale, freshness, and localization

Extend the request review experience to display the recommendation data already exposed by RequestHub, make stale recommendations visible after a route change, and support the agreed English and French experience. _(T08, T10, T11, T15)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a request has a recommendation, When a reviewer views its triage details, Then the suggested department, priority, rationale, policy IDs and versions, and confidence are displayed, with no confidence-based sorting or filtering.
  - [ ] Given a request's routed department changes after its recommendation was created, When a reviewer views the recommendation, Then the interface identifies it as stale.
  - [ ] Given a reviewer uses the English or French interface, When recommendation and stale-state content is displayed, Then that content is available in the selected language.

### TASK-3 · Complete recommendation and assistant-lookup audit coverage

Extend the existing request audit history so recommendation generation and assistant lookups are traceable with the actor, time, and returned information. _(T13)_

- **Owner role:** Backend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a recommendation is generated, When the operation completes, Then its audit record captures who requested it, when it occurred, and what was returned.
  - [ ] Given the assistant uses a tool or lookup to obtain information, When the lookup completes, Then its audit record captures who requested it, when it occurred, and what was returned.
  - [ ] Given an authorized caller reads the request audit history, When recommendation or lookup events have occurred, Then those events are available in that history.

### TASK-4 · Keep reviewer confirmation safe and provide a manual fallback

Connect reviewer confirmation to RequestHub's existing audited routing operation, prevent duplicate effects from repeated confirmation, and preserve manual routing when the triage service is unavailable. Routing remains a human-confirmed action. _(T04, T14, T16, T19, POL-GOV-001)_

- **Owner role:** Full-stack engineer
- **Depends on:** TASK-2, TASK-3
- **Acceptance criteria:**
  - [ ] Given a reviewer confirms a routing suggestion twice through a double click, When the confirmation is processed, Then it creates no more than one audit entry and one notification for that confirmation.
  - [ ] Given the triage service is unavailable, When a reviewer opens the request, Then the interface clearly says the assistant is unavailable and permits manual routing without waiting indefinitely.
  - [ ] Given a recommendation is available, When no reviewer has confirmed it, Then the routed department is not changed automatically.

