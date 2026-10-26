---
name: review-evidence
description: Assemble the evidence a reviewer needs for a pull request, separating deterministic acceptance (CI checks, regression tests that fail at the tests-only commit and pass at the head) from review comments (Copilot code review, people) and recording the human decision. Use before asking for review, when reviewing an agent's PR, and before merging.
---

# Review evidence

A PR is accepted by deterministic checks and a person. Copilot code review comments help the reviewer, but an empty review is
not proof of correctness. This skill keeps those two kinds of evidence apart in one PR comment.

## When to use
- An agent or a developer opened a fix PR and asks for review.
- You review a PR and want to see that the regression test failed before the fix and passes after it.

## Inputs
- The PR number. GitHub CLI signed in with access to the repository.
- For `--run`: PostgreSQL on `localhost:5432` (the tests run in temporary git worktrees at each commit).

## Procedure
1. Make sure the PR has a commit that only adds tests, followed by the fix (failure-reproduction skill, step 4).
2. Request a Copilot code review on the PR (Reviewers > Copilot, or `gh pr edit <n> --add-reviewer @copilot`).
3. Produce the evidence:
   `python .github/skills/review-evidence/review_evidence.py --pr <n> --run --filter "*Decision*" --comment`
4. Read the comment top-down: every deterministic check must pass and the tests-only commit must show failures. Then read the
   Copilot comments and decide which to apply. Record the decision as a GitHub review (Approve or Request changes).

## Expected output
```
| `1a2b3c4d5` | tests only: Add failing regression tests for #7 | ❌ 3 of 3 failed (must fail: proves the defect) |
| `9f8e7d6c5` | PR head | ✅ 3 of 3 passed (must pass) |
- Copilot code review: 2 inline comment(s).
- **approved** by @reviewer (2026-10-26)
```

## Failure handling
- `No CI checks reported yet`: workflows on Copilot PRs wait for a maintainer to click **Approve and run workflows**.
- `no tests-only commit`: ask the author to split the commit, or rerun the tests at the base branch to show the failure.
- `did not run (build error?)`: the commit does not build; that is itself a finding for the review.
