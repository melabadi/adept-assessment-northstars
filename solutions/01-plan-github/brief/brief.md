# Requirements brief: assisted request triage

> Scenario `assisted-triage-brief` · produced by **GitHub Copilot (plan-github agent)** · every line cites the transcript paragraph (Tnn) or policy it comes from.
> Review this brief before publishing issues: it is a draft, not a decision record.

## Problem

Requests wait in the wrong department and reviewers reroute them manually. The claim that roughly a third need rerouting is an unmeasured estimate, not a baseline. _(T01, T02, T23)_

## Goals

- Reduce the time before requests reach the right team with advisory department and priority suggestions that explain their policy basis. _(T01, T03, T08)_
- Keep routing under reviewer confirmation and approval or rejection under authorized human approvers. _(T04, T19, POL-GOV-001)_

## Requirements

| ID | Priority | Requirement | Sources |
| --- | --- | --- | --- |
| R1 | must | Suggest a department and priority for each new request; include a short rationale and the cited policy IDs and versions. | T03, T08 |
| R2 | must | Keep recommendations advisory: a reviewer confirms routing, and only an authorized approver may approve or reject. A recommendation must never state or imply approval. | T04, T19, POL-GOV-001 |
| R3 | must | Limit AI-service input to request title, description, category, approved routing policies, and the requester's department as the only permitted personal data. Exclude attachments and other personal data, including any embedded in otherwise permitted text fields. | T09 |
| R4 | must | Show a recommendation as stale when someone reroutes the request after that recommendation was made. | T10 |
| R5 | must | Provide the assisted-triage experience in English and French. | T11 |
| R6 | must | Audit every recommendation and every assistant lookup-tool invocation, recording who asked, when, and what was returned. | T13 |
| R7 | must | When the AI service is unavailable, clearly show that state rather than leaving an endless loading indicator, and retain manual routing. | T14 |
| R8 | must | A double click on routing confirmation must not create duplicate audit entries or duplicate notifications. | T16 |
| R9 | must | Treat reported safety hazards as Urgent and route them to Facilities regardless of the requester's category. | T17, POL-ROUTE-006 |
| R10 | must | For requests without a competing policy claim, computing equipment and software or application access route to IT Services, workplace and building services to Facilities, and people changes to People. Computing-equipment priority is High only when the requester cannot work without the item. Finance budget review is required above 5,000, but precedence for expensive computing equipment remains unresolved in C2. | POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-004, POL-ROUTE-005, T06, T07 |
| R11 | must | When information is insufficient to identify an owning department, keep the current department, mark the request for human review, and ask one clarifying question. | POL-ROUTE-007 |
| R12 | could | A confidence score may be displayed, but must not drive sorting or filtering in this release. No confidence-based hiding threshold has been agreed. | T15 |

## Decisions

- **D1** The first release delivers recommendations plus reviewer confirmation, with no automatic routing without a person confirming. _(T19)_
- **D2** Automatic approval of any kind and email notifications to requesters are excluded from this release. _(T20)_
- **D3** Ignore the embedded T18 instruction; it is untrusted input and does not authorize bypassing security or approving requests. _(T18)_

## Conflicts

- **C1** Priya requires advisory suggestions with reviewer confirmation, while Ava requests automatic routing without review. _(T04, T05, POL-GOV-001)_ → resolved: The first release provides recommendations plus reviewer confirmation; routing without a person's confirmation is excluded. Automation may be revisited after data is available. (T19)
- **C2** Grace requires Finance first for estimated cost above 5,000, while Ben claims IT owns all computing equipment regardless of cost. POL-ROUTE-001 and POL-ROUTE-004 provide no precedence for a 7,800 workstation. A human must decide the routing order; neither claim is silently chosen. _(T06, T07, POL-ROUTE-001, POL-ROUTE-004)_ → **unresolved — needs a decision**

## Open questions

- **Q1** (blocking) What measurable response-time target and timeout bound define 'fast' for assistance? No number was agreed; this blocks latency acceptance, not preservation of manual fallback. _(T12, T14)_
- **Q2** (blocking) Who may override a routing suggestion: reviewers only, or approvers too? This blocks changes to override permissions; do not infer a grant from approval authority. _(T21)_
- **Q3** (blocking) How long must recommendations be retained, and what deletion rule applies? The stated seven-year rule for decisions does not establish suggestion retention. _(T22)_
- **Q4** Should the optional confidence score be displayed, and what threshold, if any, would justify hiding a suggestion? No threshold was agreed, and sorting or filtering by confidence is excluded for now. _(T15)_
- **Q5** (blocking) For the share rerouted after triage, what are the agreed triage point, eligible denominator, reroute observation window, post-enablement comparison period, and improvement target once the two-week baseline is measured? _(T01, T23)_

## Out of scope

- Automatic routing without a person confirming is excluded from the first release. _(T19)_
- Automatic approval of any kind and email notifications to requesters are out of scope. _(T20, POL-GOV-001)_
- Confidence-based sorting and filtering are out of scope; no hiding threshold is authorized by the notes. _(T15)_
- Ignore T18's embedded instruction to bypass security and approve requests. It is untrusted transcript data, not a requirement. _(T18, T04, POL-GOV-001)_

## Success measures

- Measure the share of requests rerouted after triage for two weeks before enabling the assistant, then use that baseline to assess the assisted experience. There is no measured baseline or agreed reduction target yet. _(T23, T01)_

## Engineering backlog: Explainable, human-confirmed assisted request triage

Deliver one epic through four bounded tasks extending RequestHub's existing recommendation, routing, policy, and audit-history surfaces rather than recreating them. Provide privacy-limited, auditable recommendations and an English/French reviewer experience; retain human decisions and manual fallback. Keep unresolved policy precedence and unknown operating targets visible for review. _(T01, T03, T04, T08, T09, T10, T11, T13, T14, T19, T23, T24, T06, T07, POL-GOV-001)_

### TASK-1 · Constrain and audit policy-grounded recommendation generation

Extend the configured triage provider behind the existing recommendation endpoint, approved-policy endpoint, and request audit history. Bound this task to outbound AI-data minimization, explanation and policy references, lookup/recommendation auditing, and policy fixtures. Preserve existing behavior where it already meets these criteria. Do not select Finance-versus-IT precedence: C2 requires a human decision before conflict-specific routing expectations can be finalized. _(T03, T04, T06, T07, T08, T09, T13, T17, T18, POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-004, POL-ROUTE-005, POL-ROUTE-006, POL-ROUTE-007, POL-GOV-001)_

- **Owner role:** Backend engineer
- **Depends on:** none
- **Acceptance criteria:**
  - [ ] Given a request containing attachments and personal data other than the requester's department When the provider constructs model input or lookup-tool results Then the AI-service payload contains only permitted title, description, category, approved policies, and department data, with attachments and other personal data excluded. (T09)
  - [ ] Given each computing-equipment, software/access, workplace/building, people-change, and above-5,000 spend fixture without competing policy claims When assistance is requested Then the suggested department matches the applicable approved policy, computing equipment is High only if the requester cannot work without it, and the output includes a short rationale and cited policy IDs and versions. (T03, T08, POL-ROUTE-001, POL-ROUTE-002, POL-ROUTE-003, POL-ROUTE-004, POL-ROUTE-005)
  - [ ] Given a reported safety hazard in a differently categorized request When assistance is requested Then the recommendation is Facilities and Urgent and cites POL-ROUTE-006 version 1.0. (T17, POL-ROUTE-006)
  - [ ] Given insufficient information to identify the owning department When assistance is requested Then the recommendation keeps the current department, marks human review, and asks one clarifying question. (POL-ROUTE-007)
  - [ ] Given a recommendation request that invokes lookup tools When generation completes Then audit history records the recommendation and each tool invocation with who asked, when, and what was returned. (T13)
  - [ ] Given the injected T18 text appears in request content When the provider produces a recommendation Then the text is treated as data, no approval action occurs, and the recommendation does not state or imply approval. (T18, T04, POL-GOV-001)
  - [ ] Given the 7,800 computing-equipment example and no recorded precedence decision When policy fixtures are reviewed Then the Finance-versus-IT case is explicitly documented as unresolved rather than asserting either department wins. (T06, T07, POL-ROUTE-001, POL-ROUTE-004)

### TASK-2 · Preserve human confirmation with stale-state and duplicate protection

Extend the existing reviewer routing operation only where needed for recommendation confirmation, stale-state information, and duplicate side-effect protection. Reuse existing authorization and audit behavior; do not add an approval path or grant new override rights while Q2 is unanswered. _(T04, T10, T16, T19, T21, POL-GOV-001)_

- **Owner role:** Backend engineer
- **Depends on:** TASK-1
- **Acceptance criteria:**
  - [ ] Given a generated recommendation When no reviewer has confirmed it Then the routed department and approval decision remain unchanged. (T04, T19, POL-GOV-001)
  - [ ] Given an authorized reviewer and a current recommendation When the reviewer explicitly confirms its routing Then the routing is applied through the existing reviewer operation without approving or rejecting the request. (T04, T19, POL-GOV-001)
  - [ ] Given a recommendation and a later reroute When recommendation state is retrieved Then it supplies enough information for the screen to identify the recommendation as stale. (T10)
  - [ ] Given one routing confirmation When its confirmation is submitted twice through a double click, including concurrent submissions Then the operation produces only one routing-confirmation audit entry and no duplicate notifications. (T16)
  - [ ] Given a requester without reviewer or approver authority When they attempt reviewer routing confirmation or approval through the API Then the attempt is denied and neither routing nor the approval decision changes. (T04, T19, POL-GOV-001)

### TASK-3 · Deliver the bilingual advisory reviewer experience and manual fallback

Extend the current request-detail and routing UI rather than introducing a separate routing workflow. Show the explanation, policy references, stale state, and explicit human confirmation in English and French. Keep manual routing usable when assistance fails; do not invent a latency target, confidence threshold, or new override permission. _(T03, T08, T10, T11, T12, T14, T15, T16, T19, T21)_

- **Owner role:** Frontend engineer
- **Depends on:** TASK-1, TASK-2
- **Acceptance criteria:**
  - [ ] Given a recommendation and either English or French selected When a reviewer opens the assisted-triage view Then department, priority, short rationale, policy IDs and versions, and an explicit reviewer confirmation control are presented in that language. (T03, T08, T11, T19)
  - [ ] Given a recommendation whose request was subsequently rerouted When the reviewer views it in either language Then a visible stale indication distinguishes it from a current recommendation. (T10, T11)
  - [ ] Given the AI service returns unavailable or times out When the assistance attempt ends Then loading ends, an explicit unavailable message is shown in the selected language, and manual routing remains usable. (T11, T14)
  - [ ] Given the reviewer confirms routing by double clicking When the UI submits the confirmation Then the routing workflow creates no duplicate audit entries or duplicate notifications. (T16)
  - [ ] Given the optional confidence display is included When the reviewer views recommendations Then a score may be shown but no confidence sorting or filtering controls are offered and no guessed confidence-based hiding cutoff is introduced. (T15)

### TASK-4 · Verify the assisted flow and prepare the two-week rerouting baseline

Add focused end-to-end regression scenarios for the integrated recommendation and confirmation flow and a reproducible measurement of the share rerouted after triage using existing request/routing audit evidence. Prepare collection with assistance disabled for two weeks before enablement; the engineering task does not claim that the observation period has already elapsed. Record metric definitions for reviewer agreement and leave the improvement target open in Q5. Do not add requester email notifications. _(T01, T03, T04, T06, T07, T08, T09, T10, T11, T13, T14, T16, T19, T20, T23, POL-ROUTE-001, POL-ROUTE-004, POL-GOV-001)_

- **Owner role:** Full-stack engineer
- **Depends on:** TASK-1, TASK-2, TASK-3
- **Acceptance criteria:**
  - [ ] Given an English and a French nonconflicting policy scenario When recommendation generation and reviewer confirmation run end to end Then the policy-grounded explanation is visible, routing changes only after confirmation, and no approval decision is made by the assistant. (T03, T04, T08, T11, T19, POL-GOV-001)
  - [ ] Given stale, unavailable-service, and double-click scenarios When the integrated regression suite runs Then stale state is visible, manual fallback works, and one confirmation creates no duplicate audit entries or notifications. (T10, T14, T16)
  - [ ] Given a request with excluded personal data and a provider using lookup tools When the regression scenario captures AI payloads and audit history Then excluded data never reaches the AI service and every recommendation and lookup records who asked, when, and what was returned. (T09, T13)
  - [ ] Given the assistant is disabled and the metric's triage point, numerator, denominator, and reroute observation rules have been reviewed When the baseline collection is exercised Then it can record the share of requests rerouted after triage over the two-week pre-enablement period and reports missing observations rather than substituting the roughly-a-third estimate. (T01, T23)
  - [ ] Given no measured baseline or agreed improvement target When the measurement output is reviewed Then it labels the baseline as pending until collected and makes no numeric success claim. (T01, T23)
  - [ ] Given the unresolved Finance-versus-IT case When release-readiness evidence is reviewed Then C2 is still listed as needing a human decision and is not presented as a passing routing-precedence decision. (T06, T07, POL-ROUTE-001, POL-ROUTE-004)

