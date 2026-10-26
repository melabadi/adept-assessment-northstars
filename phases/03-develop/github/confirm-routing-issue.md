## Problem

Reviewers can ask the triage assistant for a routing recommendation, but to act on it they reroute the request by hand.
The history then shows a manual reroute and nothing links it to the recommendation, so nobody can tell whether the
suggestion was accepted. We want one deliberate action that confirms the suggested department and records that a person made
that decision.

## Scope

An **additive** API operation and a button on the request detail page:

`POST /api/requests/{id}/triage-recommendations/{recommendationId}/confirm` returns `200` with the updated request detail.

Implement the business rules in `RequestWorkflow` (`app/src/RequestHub.Core/Services/RequestWorkflow.cs`), map the endpoint in
`ApiEndpoints`, and add the button to `TriagePanel` (`app/web/src/features/detail/TriagePanel.tsx`).

## Acceptance criteria

1. **Permitted roles.** Only a reviewer or admin who may change routing for the request (access to the request's current
   department and to the suggested department) can confirm. Everyone else gets `403`. Requesters never see the button.
2. **Effect.** Confirming routes the request to the suggested department when it differs (same status change and notifications as
   a manual reroute) and marks the recommendation `Confirmed`. Priority, decision, and approval status do not change. If the
   suggested department is already the current department, the recommendation is still marked `Confirmed`.
3. **Audit.** Exactly one `triage.confirmed` audit entry with the recommendation id, from and to departments, cited policy refs,
   and provider.
4. **Stale recommendations** are refused with `409` and code `recommendation.stale`: the recommendation was superseded, or the
   request's department changed after the recommendation was made.
5. **Duplicate confirmation.** Confirming the same recommendation again returns `409` with code
   `recommendation.already_confirmed` and writes no audit entry.
6. **Closed requests.** Approved or rejected requests return `409` with code `request.terminal`.
7. **UI.** The latest recommendation shows a **Confirm routing** button when the user may confirm it. After confirming, the panel
   shows **Confirmed by {name}** and the request shows the new department. English and French strings.
8. **Contract and tests.** Regenerate `app/contracts/openapi.json` (additive change only). Add an integration test for each
   criterion above (including the negative ones) and a web unit test for the button states.

## Out of scope

Changing who can approve or reject, editing a recommendation, bulk confirmation, and any change to the triage providers.
