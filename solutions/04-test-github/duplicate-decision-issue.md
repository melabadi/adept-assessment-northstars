### Observed behavior

A request can be decided more than once. On the lab build (branch `lab/test-duplicate-decision`):

- **A second approver silently overrides the first.** Chloé approves a request, then Dan rejects it. Both calls return
  `201 Created`, the request ends up **Rejected**, and the history shows three `decision.recorded` entries.
- **Retries create new decisions.** When the browser retries the same click with the same `Idempotency-Key`, the API
  records another decision instead of returning the original one.
- **A double-click records several decisions or fails.** Eight simultaneous approvals by the same approver returned
  `201` three times and `500 Internal Server Error` five times, and recorded three decisions.

### Reproduce

Start the API on `lab/test-duplicate-decision` (`dotnet run --project app/src/RequestHub.Api`, development sign-in on
http://localhost:5080), then run:

```bash
python .github/skills/failure-reproduction/repro.py solutions/04-test-github/scenarios/duplicate-decision.json
```

```
 3. FAIL Chloé's browser retries the same click (same Idempotency-Key)  ->  HTTP 201
 4. FAIL Dan rejects the already approved request  ->  HTTP 201
 5. FAIL The request is still approved by Chloé  ->  HTTP 200
          status = 'Rejected', expected 'Approved'
 6. FAIL History records exactly one decision  ->  HTTP 200
          3 item(s) with action=decision.recorded, expected 1
 8. FAIL Chloé double-clicks Approve: eight requests at once  ->  HTTP 201 x3, HTTP 500 x5
 9. FAIL History records exactly one decision after the double-click  ->  HTTP 200

REPRODUCED: 6 step(s) did not behave as expected.
```

### Expected behavior

- A request has at most one decision. The first decision wins.
- A retry by the same approver with the same `Idempotency-Key` returns `200` with the original decision and records nothing new.
- Any other later attempt returns `409` with code `decision.already_decided` and the existing decision.
- Concurrent attempts (a double-click, two approvers at once) produce exactly one `201`; the others get `409`, or `200`
  for a retry with the same key. Never `500`.
- Exactly one `decision.recorded` audit entry and one requester notification per request.
- Approval authority does not change: only approvers decide, and never on their own request.
