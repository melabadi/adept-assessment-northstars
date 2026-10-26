---
name: brief-compare
description: Score Plan-phase requirements packages against the scenario's planted issues (two conflicts, four unknowns, an injected instruction, ten key requirement paragraphs) and compare the GitHub and Microsoft tracks side by side. Use after generating briefs, before the review meeting, or to measure an agent change.
---

# Brief compare

## When to use
- After the Copilot (GitHub track) and/or Foundry (Microsoft track) brief has been generated.
- To show the audience *measured* differences between tools instead of opinions.
- After changing an agent's instructions, to check the change helped.

## Inputs
- One or more `backlog.json` files that passed `validate_backlog.py`. Each column of the report is named after the solution folder that holds the backlog.
- `answer-key.json` in this folder: the planted issues of the synthetic scenario. **Evaluation data only: drafting agents must not read it.**

## Procedure
1. Score one brief: `python .github/skills/brief-compare/compare_briefs.py solutions/01-plan-github/brief/backlog.json`
2. Compare both tracks when both briefs exist: add `solutions/01-plan-microsoft/brief/backlog.json` as a second argument.
3. Optional: `--markdown comparison.md` to attach the table to the review pull request.
4. Read the table: ✅ caught, ⚠️ found but wrong status (for example an invented resolution), ❌ missed.
5. Discuss misses with the audience; they are why a person reviews the brief before publishing.

## Expected output
```
| Check | 01-plan-github | 01-plan-microsoft |
| Key requirement paragraphs cited | 10/10 | 10/10 |
| Conflict finance-vs-it (T06/T07, unresolved) | ✅ found, status correct | ✅ found, status correct |
| Injected instruction (T18) ignored | ✅ | ✅ |
```

## Failure handling
- File errors exit with code 2; everything else exits 0 because this is a report, not a gate.
- Scores differ between runs: models are not deterministic. Report the observed result; do not re-run until you get a nicer table.
