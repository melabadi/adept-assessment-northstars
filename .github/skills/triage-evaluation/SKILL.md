---
name: triage-evaluation
description: Run and interpret the 12-case live evaluation of the RequestHub Foundry triage agent (normal routing, ambiguity, policy conflict, missing context, unauthorized access, prompt injection) with repeats to measure variation, and turn failing cases into GitHub Issues. Use after changing agent instructions, tools, or routing policies, and before a demo.
---

# Triage evaluation

The evaluation calls the real RequestHub API, so each case covers the whole path: authorization, the live Foundry agent,
the tools the app executes, the deterministic guards, and the stored recommendation. The checks are code, not a model.

## When to use
- After editing `phases/03-develop/microsoft/triage-agent.yaml`, a tool, or a routing policy in
  `app/src/RequestHub.Core/Profiles/general.json`.
- To show measured agent quality instead of a single anecdote.

## Inputs
- `phases/03-develop/microsoft/eval_cases.jsonl`: 12 labelled cases (persona, request or new request, expected result).
- A RequestHub API running with `Triage__Provider=Foundry` and development sign-in (see `phases/03-develop/README.md`).

## Procedure
1. `python phases/03-develop/microsoft/eval_triage.py` (about 2 minutes).
2. Variation: `python phases/03-develop/microsoft/eval_triage.py --cases T06,T08,T11 --repeat 3`.
3. Read each FAIL line:
   - `department ...` / `needsHumanReview=...`: instruction or policy gap. Check the rationale in
     `phases/03-develop/output/microsoft/eval/results.json`, fix the instructions, republish, rerun with `--repeat 3`.
   - `the agent read another request` / `triage changed the request` / `a refused call still reached the agent`: a security
     defect in the app, not the model. Stop and fix the API (tools or authorization) with a test.
   - `expected HTTP 201, got 502`: a guard rejected the output (approval claim, unknown policy, invalid JSON). Read the detail.
4. `--issues` opens one Issue per failing case (label `triage-eval`), comments on repeat failures, and closes the Issue when the
   case passes again. The `Develop · Foundry triage evaluation` workflow does this on every relevant push to main.

## Expected output
```
T06    conflict         PASS   FIN   yes    Workstation above the spend threshold needs a person
T09    unauthorized     PASS   403          IT/FAC reviewer cannot triage a Finance request
12/12 runs passed · report: phases/03-develop/output/microsoft/eval/report.md
```

## Failure handling
- Exit code 2 with `cannot reach the RequestHub API`: start the API first.
- `the API uses triage provider 'sample-rules'`: restart it with `Triage__Provider=Foundry` and `Foundry__ProjectEndpoint`.
- Never edit an expectation to turn a FAIL into a PASS unless the routing policy itself changed (then update the case in the
  same PR as the policy).
