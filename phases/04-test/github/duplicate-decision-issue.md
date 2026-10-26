## Observed behavior

A request can be decided more than once. On the lab build (`lab/test-duplicate-decision`):

- **A second approver silently overrides the first.** Chloé approves a request, then Dan rejects it a minute later. Both calls
  return `201 Created`, the request ends up **Rejected**, and the requester receives two "request decided" notifications.
- **Retries create new decisions.** When the browser retries the same click with the same `Idempotency-Key`, the API records a
  second decision instead of returning the original one.
- **A double-click records several decisions or fails.** Eight simultaneous approvals by the same approver returned
  `201` four times and `500 Internal Server Error` four times; history shows four `decision.recorded` entries.

## Reproduce

Start the API on the lab branch (`dotnet run --project app/src/RequestHub.Api`, development sign-in on http://localhost:5080),
then run:

```bash
python .github/skills/failure-reproduction/repro.py phases/04-test/github/repro/duplicate-decision.json
```

```
 3. FAIL Chloé's browser retries the same click (same Idempotency-Key)  ->  HTTP 201
 4. FAIL Dan rejects the already approved request  ->  HTTP 201
 5. FAIL The request is still approved by Chloé  ->  status = 'Rejected', expected 'Approved'
 8. FAIL Chloé double-clicks Approve: eight requests at once  ->  HTTP 201 x4, HTTP 500 x4
```

## Expected behavior

- A request has at most one decision. The first decision wins.
- A retry by the same approver with the same `Idempotency-Key` returns `200` with the original decision and records nothing new.
- Any other later attempt returns `409` with code `decision.already_decided` and the existing decision.
- Concurrent attempts (double-click, two approvers at once) produce exactly one `201`; the others get `409` (or `200` for the same
  key). Never `500`.
- Exactly one `decision.recorded` audit entry and one requester notification per request.

## How to fix

1. Write the failing tests first and commit them on their own: sequential second decision, same-key retry, and a concurrent
   double-click (for example eight parallel requests with `Task.WhenAll`). Show the failing output in the PR description.
2. Fix `RequestWorkflow.DecideAsync` so the rules above hold, including the race between two requests that both see no decision.
3. Rerun the tests and the regression suite. Keep approval authority unchanged (only approvers decide; never their own request).
