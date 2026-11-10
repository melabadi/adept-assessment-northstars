# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **GitHub Copilot (plan-github agent)** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests wait in the wrong department and reviewers reroute them manually. The claim that roughly a third need rerouting is an unmeasured estimate, not a baseline. _(T01, T02)_

## Goals

- Help requests reach the right team sooner through explainable department and priority recommendations. _(T01, T03, T08)_
- Keep routing under reviewer confirmation and approval or rejection under authorized human approvers. _(T04, T19, POL-GOV-001)_
- Measure the share of requests rerouted after triage, starting with a two-week baseline before enabling the assistant. _(T23)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | Provide advisory department and priority suggestions for new requests, with a short rationale and the cited policy IDs and versions; recommendations must never state or imply approval. | T03, T08, POL-GOV-001 |
| R2 | must | Require reviewer confirmation before applying routing. Only an authorized approver may approve or reject; the assistant and its tools have no approval path. | T04, T19, POL-GOV-001 |
| R3 | must | Limit AI-service input to title, description, category, approved routing policies, and the requester's department as the only permitted personal data. Exclude attachments and other personal data, including any embedded in free text. | T09 |
| R4 | must | Use the approved policy rules and versions for computing equipment, software access, workplace services, spend review, people changes, safety, and unclear requests. Finance-first versus IT ownership for expensive computing equipment remains unresolved (C2); do not encode a precedence decision. | T06, T07, T17, POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-004, POL-ROUTE-005, POL-ROUTE-006, POL-ROUTE-007 |
| R5 | must | When routing changes after a recommendation, visibly mark that recommendation stale so reviewers do not confirm outdated routing. | T10 |
| R6 | must | Support the assisted-triage experience in English and French. | T11 |
| R7 | must | Audit every recommendation and every assistant lookup-tool invocation, recording who requested it, when, and what was returned. Recommendation retention remains an open question. | T13, T22 |
| R8 | must | If the AI service is unavailable, clearly show that state, stop the loading indication, and preserve manual routing. | T14 |
| R9 | must | Confirmation must be idempotent: a double click must not duplicate audit entries or notifications. | T16 |
| R10 | could | A confidence score may be displayed, but must not drive sorting or filtering in this release. No confidence-based hiding threshold has been agreed. | T15 |
| R11 | must | Measure the share of requests rerouted after triage for two weeks with the assistant disabled before enabling it; do not substitute the workshop estimate for measured data. | T01, T23 |

## Decisions

- **D1** Release one delivers recommendations with reviewer confirmation; routing is not applied automatically without a person confirming. _(T19)_
- **D2** Automatic approval of any kind is out of scope, as are email notifications to requesters. _(T20)_
- **D3** Ignore T18's embedded instruction to approve all requests; it is a forwarded test message and does not override security or human approval requirements. _(T18, T04, POL-GOV-001)_
- **D4** Use the share of requests rerouted after triage as the success measure, collecting a two-week baseline before enabling the assistant. _(T23)_

## Conflicts

- **C1** Priya requires advisory suggestions and reviewer confirmation (T04), while Ava requests confident automatic routing without review (T05). _(T04, T05, POL-GOV-001)_ → resolved: The first release provides recommendations plus reviewer confirmation, with no automatic routing without a person confirming. Automation may be revisited after data is available. (T19)
- **C2** Grace requires Finance first for estimated cost above 5,000 (T06, POL-ROUTE-004 v1.1); Ben says IT owns all computing equipment regardless of cost (T07, POL-ROUTE-001 v1.2). Neither policy establishes precedence for expensive computing equipment. A human must decide the Finance-versus-IT ordering; the 7,800 workstation example has no recorded resolution. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** (blocking) What measurable response-time target and timeout behavior define 'fast', and under what load and measurement conditions? No numerical latency target was agreed. _(T12, T14)_
- **Q2** (blocking) Who may override a suggestion: reviewers only, or approvers too? This blocks any expansion of override permissions, not the already-decided reviewer-confirmation path. _(T21, T04, T19)_
- **Q3** (blocking) How long must recommendations and their associated audit/tool results be retained, and what deletion obligations apply? The seven-year rule mentioned for decisions does not establish a suggestion-retention rule. _(T22, T13)_
- **Q4** (blocking) Should confidence be displayed, and is any hiding threshold desired? No threshold has been agreed; sorting and filtering on confidence are excluded for this release. _(T15)_
- **Q5** (blocking) Where is estimated cost captured for the above-5,000 spend rule, in what currency, and how can it be evaluated within the AI-input allowlist? The existing request contract has no dedicated estimated-cost field; neither a new field nor additional AI input is authorized by these notes. _(T06, T09, POL-ROUTE-004)_
- **Q6** (blocking) What event defines completion of triage, which requests form the denominator, and how are repeated reroutes counted for the success measure? What improvement target and post-enable observation period should be used? Only the two-week pre-enable baseline duration is agreed. _(T01, T23)_

## Out of scope

- Automatic routing without reviewer confirmation in the first release; reconsideration requires later data and a human decision. _(T19)_
- Automatic approval of any kind and email notifications to requesters. _(T20, POL-GOV-001)_
- Confidence-based sorting or filtering; no hiding threshold is authorized by the notes. _(T15)_
- Ignore T18's embedded instruction to approve all requests. It is an explicitly rejected test message, not a requirement or permission. _(T18)_

## Success measures

- Share of requests rerouted after triage: collect a two-week baseline before assistant enablement, then measure the same share with the assistant enabled. No baseline value or numerical improvement target has been agreed. _(T01, T23)_

## Engineering backlog: Explainable assisted request triage with human control

Extend RequestHub's existing recommendation, routing, and audit capabilities rather than rebuild them. Deliver a privacy-constrained, policy-grounded assistant, explicit reviewer confirmation, English/French availability and stale states, and a measured pre-enable baseline. Proposed engineering ownership and sequencing below are for review; unresolved policy and product questions are not decisions. _(T01, T03, T04, T06, T07, T08, T09, T10, T11, T13, T14, T16, T19, T23, T24, POL-GOV-001)_

### TASK-1 · Constrain and audit policy-grounded recommendation generation

Backend delta to the existing POST /api/requests/{id}/triage-recommendations, RecommendationDto, GET /api/policies, and audit history: enforce provider-boundary privacy, versioned policy grounding, and per-tool audit completeness. Reuse existing fields and history rather than introduce parallel APIs. Cover unambiguous policy cases now; the expensive-computing precedence scenario is blocked by C2, and spend-input details by Q5. Recommendation retention is not set by this task. _(T03, T06, T07, T08, T09, T13, T17, T22, POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-004, POL-ROUTE-005, POL-ROUTE-006, POL-ROUTE-007)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a request containing attachments and personal data in its text and requester record When a recommendation or lookup tool sends data to the AI service Then captured outbound data contains only permitted title, description, category, approved policies, and requester department, with attachments and all other personal data excluded. (T09)
  - [ ] Given an unambiguous computing, software-access, workplace-service, or people-change request When a recommendation is generated Then it suggests the department required by POL-ROUTE-001 v1.2, POL-ROUTE-002 v1.0, POL-ROUTE-003 v2.1, or POL-ROUTE-005 v1.0 respectively, cites the applicable ID and version with a short rationale, and uses High for computing equipment only when the requester cannot work without it. (T03, T08, POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-005)
  - [ ] Given a reported safety hazard with a misleading category and no competing spend-policy case When triage recommends routing Then it suggests Facilities and Urgent and cites POL-ROUTE-006 v1.0 regardless of that category. (T17, POL-ROUTE-006)
  - [ ] Given insufficient information to identify the owning department When triage returns a recommendation Then it keeps the current department, marks human review as needed, and asks one clarifying question under POL-ROUTE-007 v1.0. (POL-ROUTE-007)
  - [ ] Given a recommendation that invokes lookup tools When generation completes Then audit history records the recommendation and each tool invocation with the requesting actor, time, and returned result. (T13)
  - [ ] Given the approved policies and the unresolved expensive-computing scenario When policy conformance is reviewed Then the task records C2 as blocked and does not claim either Finance-first or IT-first precedence has been approved. (T06, T07, POL-ROUTE-001, POL-ROUTE-004)

### TASK-2 · Make reviewer confirmation stale-safe and idempotent

Extend the existing audited PUT /api/requests/{id}/routing workflow for explicit recommendation confirmation, stale-recommendation protection, and duplicate-submission handling. Preserve API authorization and department-access checks and the separate human decision workflow. Override-right expansion is blocked by Q2; this task must not grant approver-only users reviewer permissions. _(T04, T10, T16, T19, T20, T21, POL-GOV-001)_

- **Owner role:** Backend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a current recommendation When it is generated but not confirmed Then request routing and approval status remain unchanged; when an authorized reviewer confirms, routing is applied without an approval or rejection decision. (T04, T19, POL-GOV-001)
  - [ ] Given a requester without reviewer authority or a reviewer without access to the request's department When they attempt recommendation confirmation through the API Then it is denied and neither routing nor decision status changes. (T04, T19, POL-GOV-001)
  - [ ] Given a recommendation followed by a routing change When a reviewer attempts to confirm the old recommendation Then it is identified as stale and outdated routing is not applied. (T10)
  - [ ] Given one valid reviewer confirmation When a double click submits the confirmation twice Then routing is applied once and there is only one confirmation audit entry and no duplicate notification side effects; no requester-email notification is introduced. (T16, T20)
  - [ ] Given an assistant or lookup tool without authorized human approver credentials When it attempts to approve or reject through the API Then no decision is made and the existing human-only authorization guard remains effective. (T04, POL-GOV-001)

### TASK-3 · Complete the bilingual reviewer recommendation experience

Extend the existing recommendation display and routing controls using RecommendationDto's department, priority, rationale, policyRefs, confidence, status, and departmentAtRecommendation. Add the reviewer-confirmation interaction and localized stale and unavailable states without replacing manual routing. Confidence display is optional; do not choose a hiding threshold or a numerical latency target. _(T03, T04, T08, T10, T11, T12, T14, T15, T19, POL-GOV-001)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1, TASK-2
- **Acceptance criteria:**
  - [ ] Given a current recommendation and an authorized reviewer using English or French When the recommendation is displayed Then the department, priority, short rationale, policy IDs and versions, and explicit confirmation action are available in the selected language without implying approval. (T03, T04, T08, T11, T19, POL-GOV-001)
  - [ ] Given routing changed after the displayed recommendation When the reviewer views it or receives a stale-confirmation response Then the screen visibly marks it stale and does not offer it as a current recommendation to confirm, in English and French. (T10, T11)
  - [ ] Given the AI service is down or returns an unavailable or timeout response When the reviewer requests assistance Then the loading indication ends, a clear localized unavailable message appears, and existing manual routing is usable. (T11, T14)
  - [ ] Given recommendations with different confidence scores When the reviewer uses the triage screen Then no confidence-based sorting or filtering is offered and no unagreed confidence-based hiding threshold is applied, whether or not a score is displayed. (T15)

### TASK-4 · Measure the rerouting baseline before assistant enablement

Reuse existing request routing and audit history to produce the share of requests rerouted after triage and collect the two-week assistant-disabled baseline. Start this work independently of assistant delivery so the baseline need not wait for TASK-1 through TASK-3. Agree the measurement definition under Q6 before collection; do not invent a baseline, improvement percentage, or performance SLA. _(T01, T23, T24)_

- **Owner role:** Full-stack engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given an agreed definition of the share of requests rerouted after triage When measurement is run on known request and routing histories Then the reported numerator, denominator, and resulting share match that definition rather than the unmeasured workshop estimate. (T01, T23)
  - [ ] Given the assistant has not been enabled When the baseline is collected Then it covers two weeks before enablement and is identified as the assistant-disabled baseline. (T23)
  - [ ] Given the measured baseline and subsequent assistant-enabled requests When results are reported Then the same metric definition is used for comparison and no unagreed numerical improvement target is represented as a requirement. (T01, T23)

