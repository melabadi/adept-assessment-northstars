---
name: architecture-evaluation
description: Run and interpret the ten-case evaluation of the Foundry architecture advisor (grounding, abstention on unanswerable questions, conflict detection, scope-based access, citation validity) with optional repeats to measure run-to-run stability. Use before a demo, after changing advisor instructions or standards, or when explaining advisor quality.
---

# Architecture evaluation

## When to use
- After changing `INSTRUCTIONS` in `phases/02-design/microsoft/advisor.py` or any standard.
- To show the audience measured advisor quality instead of anecdotes.

## Inputs
- `phases/02-design/microsoft/eval_cases.jsonl`: ten labelled cases (profile, question, expected/forbidden standards, expected conflict, answerable).
- A live Foundry project and the ingested standards index.

## Procedure
1. `python phases/02-design/microsoft/eval_advisor.py` (about one minute).
2. Stability: `python phases/02-design/microsoft/eval_advisor.py --cases E07,E01 --repeat 3`.
3. Read each FAIL line:
   - `did not cite X` → check retrieval (standards-grounding skill) before touching instructions.
   - `cited out-of-scope X` or `access: …` → a real defect: the scope filter or the advisor's checks failed. Stop and investigate.
   - `did not flag conflict` → instruction quality; models vary, so measure with `--repeat` before changing anything.
   - `expected answerable=False` → the advisor invented an answer; tighten abstention instructions.
4. Record results (`phases/02-design/output/microsoft/eval/results.json`) in the review PR.

## Expected output
```
E07   small-team  PASS   resp_...
E08   enterprise  PASS   resp_...
10/10 runs passed
```

## Failure handling
- Exit code 2: configuration or service error (see the foundry-requirements-agent skill for auth fixes).
- Never edit expectations to turn a FAIL into a PASS; report the result as observed.
