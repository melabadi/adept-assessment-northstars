---
name: review-evidence
description: Assemble the evidence a reviewer needs for a pull request, separating deterministic acceptance (CI checks, regression tests that fail at the tests-only commit and pass at the head) from review comments (Copilot code review, people) and recording the human decision. Use before asking for review, when reviewing an agent's PR, and before merging.
---

# Review evidence

A fix is accepted by deterministic checks and a person. Copilot code review comments help the reviewer, but an empty
review is not proof of correctness. This skill produces both kinds of evidence and keeps them apart.

## When to use
- An agent or a developer opened a fix pull request and asks for review.
- You review a fix and want to see that its regression tests failed before the fix and pass after it.
- Before you merge, to record which checks passed and who decided.

## Inputs
- A pull request whose first change is a commit that only adds or changes tests, followed by the fix
  (failure-reproduction skill, step 4).
- GitHub CLI signed in with access to the repository.
- For local proofs (`prove_fix.py`, or `review_evidence.py --run`): the .NET SDK and PostgreSQL on localhost:5432.

## Procedure
1. **Prove the order of evidence.** The workflow *Test · GitHub · prove the fix test-first*
   (`.github/workflows/test-github-proof.yml`) runs on fix pull requests. It finds the tests-only commit, selects the
   test methods it added or changed, and runs them in clean worktrees at that commit (at least one must fail) and at
   the head (every one must still exist and pass, so skipping or deleting a failing test does not count). Both test
   outputs are kept in its `regression-proof` artifact. To run the same proof locally:
   `python .github/skills/review-evidence/prove_fix.py --pr <n>` (or `--base <branch> --head HEAD` for local commits).
2. **Ask for Copilot code review**: Reviewers > Copilot on the pull request, or `gh pr edit <n> --add-reviewer @copilot`.
3. **Assemble the report** and post it on the pull request:
   `python .github/skills/review-evidence/review_evidence.py --pr <n> --comment`.
   Section 1 (checks and the proof) decides; section 2 (Copilot and people's comments) informs; section 3 records the
   decision. A pull request's checks run with its own version of its workflows, so they can't vouch for one that
   changes where its checks and proof are defined: when the pull request changes anything under the paths in
   `CHECK_DEFINITIONS` (here `.github/workflows/`, `.github/actions/`, `.github/skills/`, and `tools/`), section 1
   opens with a warning that lists those files, before the checks. Read those files first. The warning also says when
   the changed files can't all be read. Run the report from the default branch, never from the pull request's checkout:
   its copy of this skill could leave the warning out.
   Only reviews from the repository's owner, members, and collaborators (`author_association` `OWNER`,
   `MEMBER`, or `COLLABORATOR`) count as the decision; anyone else's review is listed as not counted, without its text.
   The report is posted with your token, so everything it quotes from GitHub (the title, check names, review notes,
   comments, logins, and the commit titles, test names, and messages in the proof) is inert: it can't @-mention anyone,
   which would start Copilot in your name, or refer to an Issue or a pull request, and it can't add a link, an image,
   or HTML.
4. **Decide.** Read the tests themselves: do they assert the behavior the Issue describes? Then approve or request
   changes as a GitHub review, and run step 3 again: it updates the same comment with the decision.

## Expected output
```
| `8654a2fa4` | tests only: Add failing regression tests for #5 | ❌ 8 of 10 failed | must fail: proves the defect |
| `f69668543` | head: Fix first-wins decisions ... | ✅ 10 of 10 passed | must pass: proves the fix |

✅ Proven: 8 of 10 selected tests fail at the tests-only commit, and all 10 pass at the head.
- Copilot code review: 2 inline comment(s).
- approved by @reviewer on 2026-10-27
```
Exit codes of `prove_fix.py`: 0 proven, 1 not proven, 2 setup error.

## Failure handling
- `No checks yet`: workflows on Copilot's pull requests wait until a person selects **Approve and run workflows**.
- `no tests-only commit before the fix`: ask the author to commit the failing tests on their own first. Do not accept a
  proof run at the base branch instead; it does not show that the tests in the pull request detect the defect.
- `the new tests pass without the fix`: the tests do not detect the defect. Ask for stronger tests.
- `did not run (build error?)`: that commit does not build; open its log in the artifact. That is a review finding.
- Tests added after the fix (for example after a review comment) are not in the proof: they are guards, and CI runs
  them. The proof covers the tests committed before the fix.
- A proof says ✅ but the tests assert something trivial: the proof shows the order of evidence, not test quality.
  The reviewer still reads the tests.
- `Not counted` in section 3: that review's author is not the repository's owner, a member, or a collaborator, so the
  review never decides, whatever it says. If that person should decide, add them as a collaborator first.
- A warning at the top of section 1: the pull request changes where its checks are defined. Read the listed files
  before you trust its checks or its proof; one that the pull request rewrote looks exactly like a real one. If the
  report says it couldn't read all the changed files, read the pull request's `.github/` and `tools/` changes yourself.
