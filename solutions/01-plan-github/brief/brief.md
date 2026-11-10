# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **GitHub Copilot (plan-github agent)** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests can sit with the wrong team while reviewers reroute them manually, delaying work before it reaches the right team. _(T01, T02)_

## Goals

- Reduce the time requests wait before reaching the right team by assisting reviewers with routing. _(T01, T03)_
- Measure the share of requests rerouted after triage, with a two-week baseline before enabling the assistant. _(T23)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | For each new request, provide advisory recommendations for department and priority using approved routing policies. | T03, T04, POL-GOV-001 |
| R2 | must | Show a short rationale and the IDs and versions of policies cited by each recommendation. | T08 |
| R3 | must | Send to the AI service only the request title, description, category, requester's department, and approved routing policies; do not send attachments or other personal data. | T09 |
| R4 | must | When a request is rerouted after a recommendation, show reviewers that the recommendation is stale. | T10 |
| R5 | must | Support the assisted-triage experience in English and French. | T11 |
| R6 | must | Audit every recommendation and every assistant lookup, including who requested it, when, and what was returned. | T13 |
| R7 | must | If the AI service is unavailable, clearly indicate that it is unavailable and allow reviewers to continue routing manually. | T14 |
| R8 | could | A confidence score may be displayed, but must not be used to sort or filter recommendations; the threshold for hiding suggestions remains undecided. | T15 |
| R9 | must | A double-click on routing confirmation must not create duplicate audit entries or notifications. | T16 |
| R10 | must | A reported safety hazard is Urgent and routes to Facilities regardless of the requester's selected category. | T17, POL-ROUTE-006 |
| R11 | must | Only an authorized approver may approve or reject a request; recommendation and reviewer confirmation do not approve or reject it. | T04, T19, POL-GOV-001 |

## Decisions

- **D1** The first release uses advisory recommendations with reviewer confirmation; it does not route automatically without a person confirming. _(T19)_
- **D2** Automatic request approval and requester email notifications are excluded from this release. _(T20)_

## Conflicts

- **C1** The spend-threshold policy says requests above 5,000 route to Finance, while the stakeholder says IT owns computing equipment regardless of cost; neither source resolves which routing takes precedence for expensive computing equipment. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**
- **C2** A request for automatic routing when confidence is high conflicts with the advisory recommendation and reviewer confirmation requirement. _(T04, T05, POL-GOV-001)_ → resolved: The first release provides recommendations plus reviewer confirmation; routing is not automatic without a person confirming. (T19)

## Open questions

- **Q1** What response-time target defines 'fast' for the assistant? _(T12)_
- **Q2** Should recommendations below a confidence threshold be hidden, and what is that threshold? _(T15)_
- **Q3** (blocking) Which roles may override a recommendation: reviewers, approvers, or both? _(T21)_
- **Q4** (blocking) How long should recommendations be retained? _(T22)_

## Out of scope

- Automatic approval of requests is out of scope for this release. _(T20)_
- Email notifications to requesters are out of scope for this release. _(T20)_

## Success measures

- The share of requests rerouted after triage, with a two-week measurement before the assistant is enabled. _(T23)_

## Engineering backlog: Assisted request triage

Extend RequestHub's existing advisory triage capability so reviewers receive explainable, auditable routing recommendations and can confirm routing while preserving human approval. _(T03, T08, T19, T23, POL-GOV-001)_

### TASK-1 · Extend policy-grounded recommendation generation

Build on the existing recommendation capability to produce department and priority suggestions from approved routing policies, with traceable explanations and constrained AI inputs. _(T03, T08, T09, T17, POL-ROUTE-006, POL-ROUTE-007)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a request with the information required to determine its department, When a recommendation is generated, Then it includes a suggested department and priority with a short rationale and the cited policy IDs and versions.
  - [ ] Given a request reports a safety hazard and its selected category is not Facilities, When a recommendation is generated, Then the recommendation is Urgent and routes to Facilities.
  - [ ] Given a request lacks the information needed to determine its owning department, When a recommendation is generated, Then its current department is kept, it is marked for human review, and one clarifying question is asked.
  - [ ] Given data is prepared for the AI service, When the request is sent, Then it contains only the title, description, category, requester's department, and approved routing policies, with no attachments or other personal data.

### TASK-2 · Audit recommendation and confirmation activity

Extend the existing audited request workflow so recommendation and assistant lookup activity is recorded, and routing confirmation remains advisory and safe against repeated submissions. _(T04, T13, T16, T19, POL-GOV-001)_

- **Owner role:** Backend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a recommendation or assistant lookup is requested, When the operation completes, Then its audit record includes who requested it, when it occurred, and what was returned.
  - [ ] Given a reviewer double-clicks routing confirmation, When both submissions are handled, Then only one audit entry and one notification are created.
  - [ ] Given a reviewer confirms a recommendation, When the routing is updated, Then no approval or rejection is made and only an authorized approver can approve or reject the request.

### TASK-3 · Present recommendations in the reviewer experience

Update the existing reviewer experience to explain recommendations, show stale and unavailable states, and support the agreed languages without removing manual routing. _(T08, T10, T11, T14)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1, TASK-2
- **Acceptance criteria:**
  - [ ] Given a recommendation is available, When a reviewer views it, Then the rationale and cited policy IDs and versions are visible.
  - [ ] Given a request is rerouted after its recommendation was made, When a reviewer views the request, Then the recommendation is clearly marked stale.
  - [ ] Given the AI service is unavailable, When a reviewer opens the triage experience, Then the screen clearly says the assistant is unavailable and manual routing remains available.
  - [ ] Given a user selects English or French, When the assisted-triage experience is displayed, Then its user-facing content is available in that language.

### TASK-4 · Verify triage outcomes and establish the reroute baseline

Add regression coverage for the advisory workflow and measure the agreed reroute success measure for the two weeks before enabling the assistant. _(T04, T16, T19, T23, POL-GOV-001)_

- **Owner role:** QA engineer
- **Depends on:** TASK-2, TASK-3
- **Acceptance criteria:**
  - [ ] Given the assistant has not been enabled, When the baseline period is completed, Then the share of requests rerouted after triage is measured for the two weeks before enablement.
  - [ ] Given recommendation and reviewer-confirmation flows are available, When the regression suite runs, Then it verifies that recommendations do not approve or reject requests and a double-click does not duplicate audit entries or notifications.
