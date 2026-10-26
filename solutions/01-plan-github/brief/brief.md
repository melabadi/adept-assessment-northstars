# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **GitHub Copilot (plan-github agent)** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests can sit with the wrong team while staff identify and correct their routing; the reported reroute share is an unmeasured estimate. _(T01, T02)_

## Goals

- Reduce the time requests wait before reaching the right team. _(T01)_
- Measure the share of requests rerouted after triage, with a two-week baseline before the assistant is enabled. _(T23)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | For each new request, provide an advisory department and priority recommendation for a reviewer to confirm; a recommendation does not make the routing decision. | T03, T04, T19, POL-GOV-001 |
| R2 | must | Show a short rationale and the IDs and versions of the routing policies cited by a recommendation. | T08 |
| R3 | must | Send the AI service only the request title, description, category, approved routing policies, and requester department; do not send attachments or other personal data. | T09 |
| R4 | must | Clearly mark a recommendation stale if the request is rerouted after that recommendation was made. | T10 |
| R5 | must | Support the triage experience in English and French. | T11 |
| R6 | must | Audit every recommendation and every assistant lookup tool use with who requested it, when it occurred, and what was returned. | T13 |
| R7 | must | When the AI service is unavailable, clearly say so and let reviewers route requests manually. | T14 |
| R8 | should | If a confidence score is shown, do not use it to sort or filter recommendations. | T15 |
| R9 | must | A double-click while confirming routing must not create duplicate audit entries or notifications. | T16 |
| R10 | must | Measure the share of requests rerouted after triage; collect a two-week baseline before enabling the assistant. | T23 |

## Decisions

- **D1** The first release delivers recommendations plus reviewer confirmation; it does not automatically route requests without a person confirming. _(T19)_

## Conflicts

- **C1** The request for automatic routing when confidence is high conflicts with the requirement that recommendations remain advisory and be confirmed by a reviewer. _(T04, T05)_ → resolved: The first release provides recommendations plus reviewer confirmation; automatic routing without confirmation is deferred. (T19)
- **C2** Finance-first review for requests above 5,000 conflicts with IT ownership of all computing equipment, with no precedence specified for expensive computing equipment. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** What response-time target should define 'fast' for triage? _(T12)_
- **Q2** Who may override a recommendation: reviewers, approvers, or both? _(T21)_
- **Q3** How long should recommendations be retained? _(T22)_
- **Q4** What confidence threshold, if any, should hide a recommendation? _(T15)_
- **Q5** (blocking) Which routing policy takes precedence for computing equipment with an estimated cost above 5,000: IT ownership or Finance-first budget review? _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_
- **Q6** What data source and operational definition should be used to calculate the share of requests rerouted after triage for the two-week baseline? _(T23)_

## Out of scope

- Automatic approval of requests and email notifications to requesters are out of scope for this release. _(T20)_
- The assistant cannot approve or reject a request; only an authorized approver may do so. _(POL-GOV-001)_

## Success measures

- Track the share of requests rerouted after triage, using a two-week measurement period before enabling the assistant; no baseline value is yet available. _(T23)_

## Engineering backlog: Assisted request triage

Improve triage with advisory recommendations that reviewers can understand and act on, while respecting the stated data, audit, language, and governance requirements. _(T03, T04, T08, T09, T19)_

### TASK-1 · Present recommendation rationale and stale state

Update the reviewer triage experience to make the suggested department, priority, rationale, cited policy IDs and versions, and advisory status clear, and to identify recommendations made stale by rerouting. _(T03, T04, T08, T10, T19)_

- **Owner role:** Frontend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a request has a triage recommendation, When a reviewer opens its triage view, Then the suggested department and priority, short rationale, cited policy IDs and versions, and advisory status are visible.
  - [ ] Given a request is rerouted after a recommendation is made, When a reviewer views that recommendation, Then the screen clearly identifies it as stale.

### TASK-2 · Constrain AI inputs and audit assistant activity

Apply the agreed data boundary to AI-service requests and record recommendation and assistant lookup activity in the request audit history. _(T09, T13)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a request is prepared for the AI service, When its triage payload is sent, Then it contains only the request title, description, category, approved routing policies, and requester department, with no attachments or other personal data.
  - [ ] Given a recommendation is produced or an assistant lookup tool is used, When the activity is recorded, Then its audit record identifies who requested it, when it occurred, and what was returned.

### TASK-3 · Support both languages and unavailable-service fallback

Make the reviewer-facing triage experience usable in English and French, and communicate service unavailability while preserving manual routing. _(T11, T14, T15)_

- **Owner role:** Frontend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a reviewer uses the triage experience in English or French, When its interface is rendered, Then the triage interface supports both languages.
  - [ ] Given the AI service is unavailable, When a reviewer requests a recommendation, Then the screen clearly says the assistant is unavailable and the reviewer can continue routing manually instead of waiting indefinitely.
  - [ ] Given a recommendation includes a confidence score, When the reviewer views or works with recommendations, Then confidence is not used to sort or filter them.

### TASK-4 · Prevent duplicate effects from repeated routing confirmation

Make the reviewer confirmation interaction safe against a double-click so a repeated submission does not duplicate its routing side effects. _(T04, T16, T19, POL-GOV-001)_

- **Owner role:** Backend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a reviewer confirms routing, When the same confirmation is submitted twice by a double-click, Then it creates no more than one audit entry and no duplicate notification.
  - [ ] Given a reviewer confirms a recommendation, When the confirmation is processed, Then the request routing is changed only through that reviewer action and the request remains subject to the authorized approver's decision.

