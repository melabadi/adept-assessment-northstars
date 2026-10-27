---
name: architecture-evaluation
description: Run and interpret the ten-case evaluation of the Foundry architecture advisor (grounding, abstention on unanswerable questions, conflict detection, scope-based access, citation and excerpt validity) with optional repeats to measure run-to-run stability. Use before a demo, after changing the agent definition, the model, or a standard, or when explaining advisor quality.
---

# Architecture evaluation

## When to use
- After changing `solutions/02-design-microsoft/agent.yaml` (instructions, sampling, search settings), the model deployment, or any standard.
- To show measured advisor quality instead of anecdotes.

## Inputs
- `solutions/02-design-microsoft/eval_cases.jsonl`: ten labelled cases. Each has a profile, a question, `expectAnswerable`, `expectStandards` (must be cited), `forbidStandards` (out of the profile's scope, must not be cited), and `expectConflict` (must be reported together).
- A live Foundry project and a synced standards index (standards-grounding skill).

## Procedure
1. `python solutions/02-design-microsoft/eval_advisor.py` (about one minute; four cases run in parallel).
2. Stability: `python solutions/02-design-microsoft/eval_advisor.py --repeat 3`, or a subset with `--cases E06,E07 --repeat 3`. Models are not deterministic: judge a change on repeated runs, never on one.
3. Read each FAIL line:
   - `did not cite X`: check `retrievedStandards` in the run (results.json). Not retrieved: a retrieval gap (standards-grounding skill). Retrieved but not cited: an instruction gap.
   - `citation: X ... does not exist` or `excerpt: ... is not in the standard`: the model invented a standard or a quote. The checks did their job; improve the instructions (for example, always search first).
   - `access: ...` or `cited out-of-scope X`: stop and investigate. The profile's filter or the checks failed.
   - `did not flag the conflict`: instruction quality; measure with `--repeat` before changing anything.
   - `expected answerable=False, got True`: the advisor answered something the standards do not cover.
4. From GitHub: run *Design · Microsoft · sync the standards and evaluate the advisor* (`gh workflow run design-microsoft-eval.yml -f repeat=3`). Its summary shows the same table.
5. Attach `out/eval/results.md` or the workflow run to the pull request that changed the advisor.

## Expected output
```
E07    small-team  PASS   14.2 s  resp_...
E08    enterprise  PASS    6.1 s  resp_...
10/10 runs passed in 58.3 s · model gpt-5.4-mini · results: .../out/eval/results.json
```

## Failure handling
- Exit code 2 or `service error: ... 429`: the model deployment is throttled. Run with `--workers 1`, or raise `modelCapacity` in `infra/main.bicep` and run `azd provision`.
- `PermissionDenied`: the identity lacks Foundry User on the Foundry account, or the role is still propagating.
- Never edit expectations or the checks to turn a FAIL into a PASS; report the result as observed.
