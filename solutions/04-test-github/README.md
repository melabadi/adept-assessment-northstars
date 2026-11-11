# Test · Regression lab with GitHub Copilot

Defects that only show up under retries or simultaneous clicks slip through review: nobody wrote the test that would have caught them, and a green pull request doesn't say whether its new tests ever failed. In this solution a reported defect, a request that can be approved and then rejected, is replayed against the running API from a scenario file. The Copilot cloud agent commits failing regression tests first, including an eight-click race, then the fix. GitHub Actions proves that the tests fail at the tests-only commit and pass at the fix, Copilot code review looks for what the tests miss, and a person decides.

![The review evidence on Copilot's pull request: every check passes, and Copilot's regression tests fail at the tests-only commit and pass at the head](images/07-evidence-checks.png)

- **Present it in about 20 minutes:** walk through [the recorded run](#the-recorded-run), a real run with a screenshot and a link for every step. Nothing to start or sign in to.
- **Set it up yourself in about 2 minutes:** follow [Set it up yourself](#set-it-up-yourself) in your copy of the repository, which the [root README](../../README.md) makes once for every solution. A run then needs about 22 minutes of unattended work by Copilot and the checks, which you can start before the audience arrives: see [Run it yourself](#run-it-yourself).

## Why it matters

**Phase 4 of 7: Test.** Today a defect is usually fixed first and tested afterwards, if at all. Nobody sees whether the new test would have caught the defect, races are hard to reproduce by hand, and a green check with an empty review looks like a clean one. With this solution the order of the evidence is the point: the tests fail at one known commit and pass at the next, the checks are reported apart from the review comments, and a person decides with that proof in hand.

| | Today | With this solution |
| --- | --- | --- |
| Reproducing | Someone repeats the clicks from the bug report by hand, and races are hard to trigger. | A scenario file replays the report against the API, including eight parallel clicks, and lists the expectations that break. |
| Regression tests | Written after the fix, if at all. Nobody knows whether they would have caught the bug. | Copilot commits the failing tests on their own, then the fix in a separate commit. |
| Review | A green check and a few comments. An empty review looks like a clean one. | Actions reruns the new tests at the tests-only commit (at least one must fail) and at the head (all must pass) and keeps both outputs. Comments are reported apart from the checks. |
| Decision | Implicit in the merge button. | A person approves the workflow runs, reads the tests, and approves or requests changes; the evidence comment records who decided. |

The value: a defect report becomes a proven, reviewable fix in under half an hour, and the reviewer gets evidence to check rather than a green mark to trust. The recorded run, on 28 October 2026, measured:

- **8 minutes 46 seconds** from assigning the Issue to Copilot's fix, in a 13-minute session. The failing tests came first, committed 6 minutes after the Issue was filed.
- **5 of 7** selected tests failed at the tests-only commit, and **7 of 7** passed at the fix. Six were Copilot's new tests; the seventh was an existing test that the proof script of that day also picked up ([step 5](#5-the-proof-showed-the-tests-failing-first)). The proof took 1 minute 44 seconds.
- **One authorization gap** that no test covered, found by Copilot code review in 6 minutes. Copilot fixed it, with a new test, 7 minutes after a person asked, and the new commit passed the same gates.
- **23 minutes** from filing the Issue to a passing proof, 7 of them waiting for a person to approve the workflow runs.

The Microsoft counterpart, [04-test-microsoft](../04-test-microsoft/), load-tests the API with Azure Load Testing. To load-test the very commit that this solution proves, follow the [Test solution combo](../../PRESENTING.md#test-copilot-proves-the-repair-azure-load-tests-the-same-commit).

## How it works

```mermaid
flowchart LR
  L[Lab branch<br/>main + defect patch] --> R[Scenario against<br/>the running API]
  R -->|REPRODUCED| I[GitHub Issue]
  I -->|assigned with the<br/>test-github agent| C[Copilot cloud agent]
  C -->|1. failing tests<br/>2. fix| PR[Pull request<br/>into the lab branch]
  PR --> CI[Actions: CI<br/>full test suite]
  PR --> P[Actions: prove the fix<br/>fails before, passes after]
  PR --> CR[Copilot code review]
  CI --> E[Review evidence<br/>comment]
  P --> E
  CR --> E
  E --> H{Person decides}
```

- **Copilot** runs the custom agent [`test-github`](.github/agents/test-github.agent.md) in the cloud agent. With the `failure-reproduction` skill it runs the Issue's scenario, writes integration tests that assert the expected behavior, commits them alone, fixes the code in a second commit, and reruns the tests, the `regression-validation` suites, and the scenario. Copilot code review then looks for what the tests miss.
- **GitHub Actions** runs [CI](../../.github/workflows/ci.yml) (the full test suite) and [`test-github-proof.yml`](.github/workflows/test-github-proof.yml), which reruns the tests the tests-only commit added at that commit and at the head, each in a clean worktree, and keeps both outputs. Its script comes from the base branch. GitHub still runs a pull request's own copy of the workflow files, so the evidence report flags a pull request that changes them, the skills they run, or `tools/`.
- **A person** files the Issue, approves the workflow runs, reads the tests, and approves or requests changes. The `review-evidence` skill reports the checks apart from the comments and records who decided.

**Outside contributions.** On a public repository anyone can open an Issue with this solution's form, or a pull request from a fork. Neither starts Copilot: only people with write access can assign an Issue to Copilot or mention `@copilot`. The proof runs a fork's pull request into a `lab/test-*` branch once someone with write access approves the run: it runs that pull request's tests with a read-only token, no secrets, and no credentials left in the checkout, and takes the proof script from the base branch. A pull request can still change the workflow files GitHub runs for it, so the evidence report flags one that does. The evidence comment is posted with your token, so it never speaks for anyone else: only reviews from the owner, members, and collaborators count as the decision, and everything it quotes from GitHub is inert: it can't mention anyone (`@copilot` included) or refer to an Issue or a pull request, and it can't add a link, an image, or HTML.

## The recorded run

This run took place on 28 October 2026, from 14:44 to 16:31 UTC, on `main` at [`79f9d2c`](https://github.com/melabadi/adept-assessment-northstars/commit/79f9d2c6b1b55a63ba26b063a63658fce6fd3a90). The repository's owner started it and took every person's step, as the presenter; Copilot and GitHub Actions did the rest. The defect report became Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100), and Copilot's work became pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101). Every link below opens without signing in. The workflow runs' summaries and logs need a GitHub sign-in and expire, so the screenshots show them, and [`evidence/`](evidence/) keeps both proofs. Every screenshot comes from this run, except the recorded approval in step 8.

| Step | When (UTC) | Who | How long |
| --- | --- | --- | --- |
| [1. The lab branch was rebuilt](#1-the-lab-branch-was-rebuilt-from-main) | 14:44 | Presenter | seconds |
| [2. The scenario reproduced the defect](#2-the-scenario-reproduced-the-defect) | 14:48 | Presenter | seconds per scenario run |
| [3. Copilot wrote the tests, then the fix](#3-copilot-committed-failing-tests-then-the-fix) | 14:44 to 14:59 | Presenter, then Copilot | 13 min 24 s of Copilot's work |
| [4. A person approved the runs](#4-a-person-approved-the-workflow-runs) | 15:06 | Presenter | 14 s |
| [5. The proof passed](#5-the-proof-showed-the-tests-failing-first) | 15:06 to 15:08 | GitHub Actions | 1 min 44 s |
| [6. Copilot code review](#6-copilot-code-review-found-a-gap-the-tests-missed) | 15:08 to 15:14 | Copilot | 6 min 14 s |
| [7. The evidence comment](#7-the-evidence-comment-kept-checks-apart-from-comments) | 15:22 | Presenter | seconds |
| [8. The review loop](#8-a-person-asked-for-a-change-and-the-new-commit-passed-the-same-gates) | 15:22 to 16:04 | Presenter, Copilot, GitHub Actions | 6 min 54 s from the request to Copilot's new commit |
| [9. Optional: Copilot CLI](#9-optional-copilot-cli-fixed-a-second-defect) | 15:23 to 15:41 | Presenter, then Copilot CLI | 17 min 50 s |

Steps 1 and 3 ran first, so Copilot was already working while step 2 reproduced the defect.

### 1. The lab branch was rebuilt from main

The presenter rebuilt `lab/test-duplicate-decision` from `main` plus [`lab/duplicate-decision.patch`](lab/duplicate-decision.patch), which removes the decision guards and the tests that cover them, and force-pushed it. The push landed at 14:44:20 UTC: [`df99c1b`](https://github.com/melabadi/adept-assessment-northstars/commit/df99c1b0e011fbe8d93178d5c1bde115e4357e50), one commit on top of `main`. The patch file stayed off the lab branch. Copilot could still read the code from before the defect commit, as an engineer would when a regression appears: what the demo proves is the order of the evidence.

![The lab branch rebuilt: one commit on top of main, force-pushed as lab/test-duplicate-decision](images/01-lab-branch.png)

**Point out:** the defect exists only on a lab branch built from that day's `main`; `main` itself stays healthy.

### 2. The scenario reproduced the defect

At 14:48 UTC, while Copilot worked on step 3, the presenter replayed [`scenarios/duplicate-decision.json`](scenarios/duplicate-decision.json) with [`repro.py`](.github/skills/failure-reproduction/repro.py) against the API built from the lab branch: a retry with the same idempotency key, a second approver, and eight parallel clicks. Six of its nine steps failed:

![The scenario against the lab build: six of nine steps fail, and eight parallel approvals return 201 three times and 500 five times](images/02-reproduce.png)

Against the API built from `main`, the same scenario passed every step, so it is a fair oracle:

![The same scenario against main: every step behaves as expected](images/02-not-reproduced-on-main.png)

The two APIs ran side by side on ports 5092 and 5091, with `--api`, because the machine was shared. Each scenario run took seconds. This step ran on the presenter's machine, so the screenshots are its record.

**Point out:** step 8, a double-click of eight requests, recorded three decisions and answered the rest with `500` (three `201`s and five `500`s; the split changes from run to run). On `main` it returned one `201` and seven `409`s.

### 3. Copilot committed failing tests, then the fix

At 14:44:47 UTC the presenter filed Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100) from [`duplicate-decision-issue.md`](duplicate-decision-issue.md). Five seconds later they assigned it to Copilot, with the `test-github` custom agent and the base branch `lab/test-duplicate-decision`. Copilot opened draft pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101) six seconds after the assignment:

![The Issue's header: Copilot's session (here already complete) and its draft pull request #101, linked under the title](images/03-issue-assigned.png)

Copilot worked from 14:45:30 to 14:58:54 UTC, 13 minutes 24 seconds. It ran the scenario, committed the failing tests, then the fix, reran the tests, the regression suites, and the scenario, and ended with an evidence summary:

![Copilot's session: its last steps, and an evidence summary with the tests-only and fix commits, the proof, and the scenario result](images/03-copilot-session.png)

Its commits, in order (all on the pull request's [Commits](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits) tab):

- [`9e550ce`](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits/9e550ce8746775bcd63e64d4cabcb294c8938ff7) at 14:50:55, 6 minutes after the Issue: *Add failing regression tests for #100*, 116 new lines in `RequestLifecycleTests.cs`.
- [`8de3d60`](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits/8de3d60fb425ca76d3d6bc3e94042fa9a02deb53) at 14:53:34: *Refine duplicate decision regression assertions*, tests only.
- [`a92d4b3`](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits/a92d4b313e1eb202c6a80e2af50fa49883a59e23) at 14:53:38: the fix, 20 lines in `RequestWorkflow.cs`, under the previous commit's message.

![Copilot's commits: two that change only the tests, then one that changes only RequestWorkflow.cs](images/03-copilot-commits.png)

The tests-only commits include the [eight-click test](https://github.com/melabadi/adept-assessment-northstars/blob/8de3d60fb425ca76d3d6bc3e94042fa9a02deb53/app/tests/RequestHub.Tests/RequestLifecycleTests.cs#L114-L127):

![Copilot's double-click test: eight approvals at once with Task.WhenAll, exactly one 201 and seven 409s](images/03-concurrent-test.png)

Copilot's output varies from run to run. In this one the fix reused the previous commit's message, and the evidence summary was in the session rather than in the pull request description. Neither matters to the gate in step 5: it reads what each commit changes, not what its message says.

**Point out:** the tests landed in their own commits, touching only `app/tests/`, before any production code changed.

### 4. A person approved the workflow runs

Copilot's pushes started no workflow on their own: their runs waited for a person.

![The pull request's merge box: four workflows awaiting approval, with the Approve workflows to run button](images/04-approve-workflows.png)

At 15:06 UTC, 7 minutes after Copilot finished, the presenter started the eight waiting runs of Copilot's two pushes with code, the tests and then the fix, from a terminal with `gh run rerun`, within 14 seconds. The runs of the earlier push were cancelled, because each shares a concurrency group with its counterpart on the latest push. Nobody approved the one run on Copilot's first commit, *Initial plan*: the feature bounds check, which ran again on the later commits. It waited until the pull request closed.

**Point out:** no workflow ran on Copilot's commits until a person approved it.

### 5. The proof showed the tests failing first

The proof check, [`test-github-proof.yml`](.github/workflows/test-github-proof.yml), selected the tests that the tests-only commits added or changed, and ran them in clean worktrees at the tests-only commit `8de3d60fb` and at the head `a92d4b313`. It ran from 15:06:29 to 15:08:13 UTC: 1 minute 44 seconds. CI's full test suite passed at 15:10:26, after 3 minutes 52 seconds.

![The proof check's summary: 5 of 7 selected tests fail at the tests-only commit, and 7 of 7 pass at the head](images/05-proof-check.png)

Below the table, the summary listed each failure at the tests-only commit in the tests' own words:

![The failures at the tests-only commit, in the tests' words: a later decision gets Created instead of Conflict, a same-key retry gets Created instead of OK, and eight parallel clicks get no conflicts](images/05-proof-failures.png)

Two tests passed before the fix. Copilot's new `Requester_cannot_self_approve_after_another_approver_has_decided` guards a rule that already held: a requester can't decide their own request. `Search_treats_percent_and_underscore_as_literal_characters` was an existing test, the last in the file: the proof script of that day counted it as changed because Copilot added helper methods below it. [#135](https://github.com/melabadi/adept-assessment-northstars/pull/135) fixed that after the run: the script now ends each test where its method ends. The proof and both test reports are in [`evidence/proof-a92d4b313`](evidence/proof-a92d4b313/proof.md), copied from the run's artifact.

**Point out:** the same tests failed at one known SHA, for the reasons the Issue describes, and passed at the next.

### 6. Copilot code review found a gap the tests missed

At 15:08:21 UTC the presenter requested a review from Copilot. [Its review](https://github.com/melabadi/adept-assessment-northstars/pull/101#pullrequestreview-5685021802) arrived at 15:14:35, 6 minutes 14 seconds later: changes recommended, with [one high-severity finding](https://github.com/melabadi/adept-assessment-northstars/pull/101#discussion_r4402383848). If a request was rerouted to another department and decided while an approval was being saved, the recovery path could return that department's decision, comment included, to a caller who isn't allowed to see it.

![Copilot code review: changes recommended, with a high-severity finding that the concurrency recovery path can return another department's decision](images/06-copilot-review.png)

Copilot's own self-check in its session had found no issues.

**Point out:** the review found an authorization gap that no test covered, a request rerouted between the access check and the save.

### 7. The evidence comment kept checks apart from comments

At 15:22:17 UTC the presenter ran [`review_evidence.py`](.github/skills/review-evidence/review_evidence.py) `--pr 101 --comment` and posted [the evidence comment](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473019762). Section 1, *Deterministic acceptance*, lists the checks and the proof at two known SHAs (the image at the top of this README): it decides. Section 2, *Review comments*, lists Copilot's finding: it informs. Section 3, *Reviewer decision*, stayed pending, because nobody had approved or requested changes.

![The review comments and reviewer decision sections: Copilot's finding is listed, no comments does not mean correct, and the decision is pending](images/07-evidence-review.png)

These images show the comment after step 8 updated it at 16:04 UTC, so the head is the review-loop commit `e1d52334d`.

**Point out:** what decides (checks and proof) is kept apart from what informs (review comments).

### 8. A person asked for a change, and the new commit passed the same gates

At 15:22:37 UTC the presenter [asked Copilot](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473028998), on the pull request, to address the review's finding:

```text
@copilot Please address the Copilot code review comment on `RequestWorkflow.cs`: in the concurrency recovery path, recheck department access for the reloaded request before returning its decision, and return `403 auth.department_forbidden` when access is denied. Add a regression test for this case. Give each new commit a message that says what it changes, and do not rewrite or squash the earlier commits.
```

Copilot started at 15:23:20 and pushed [`e1d5233`](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits/e1d52334df6c372dcf44e7cec4965bfb180f54d5) at 15:29:31, 6 minutes 54 seconds after the request: the department check, and a deterministic race test in a new `DecisionRecoveryAuthorizationTests.cs`. It [replied](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473266654) at 15:32:34 that all 64 API and worker tests passed.

![The review loop: the @copilot request, Copilot's new commit, and its reply that the authorization check and a deterministic race test were added](images/08-review-loop.png)

At 15:58 UTC the presenter started the new commit's four waiting runs. The proof passed again in 1 minute 33 seconds, still 5 of 7 failing at `8de3d60fb` and now 7 of 7 passing at `e1d52334d` ([`evidence/proof-e1d52334d`](evidence/proof-e1d52334d/proof.md)), and CI passed in 2 minutes 49 seconds. At 16:04 the presenter updated the evidence comment. Tests added after the fix are guards: CI runs them, and the proof keeps covering the tests committed before the fix.

The presenter didn't record a GitHub review in this run, so the decision stayed pending. At 16:31 UTC they [closed the pull request without merging](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6474687761), as every demo run does, because the lab branch is rebuilt for the next one. In the run of 10 November 2026 (Issue [#299](https://github.com/melabadi/adept-assessment-northstars/issues/299), pull request [#300](https://github.com/melabadi/adept-assessment-northstars/pull/300)), the test lead [approved](https://github.com/melabadi/adept-assessment-northstars/pull/300#pullrequestreview-5849409617) with a GitHub review, and [the evidence comment](https://github.com/melabadi/adept-assessment-northstars/pull/300#issuecomment-6779284427) recorded who decided:

![The evidence comment on pull request 300 after the test lead's review: every check passes, 3 of 3 selected tests fail at the tests-only commit 78908821d and pass at the head 24bf08614, no Copilot code review was requested, and the reviewer decision reads approved, naming the proof and the load run](images/combo-05-decision-recorded.png)

**Point out:** the reviewer's finding became code and a test within minutes and went through the same gates, while the decision stayed with a person.

### 9. Optional: Copilot CLI fixed a second defect

From 15:23:48 to 15:41:38 UTC, on the presenter's machine, Copilot CLI ran the same `test-github` agent on a second defect: the lab build accepted a rejection whose comment was only spaces. Copilot reproduced it with [`scenarios/whitespace-rejection.json`](scenarios/whitespace-rejection.json) (`REPRODUCED: 2 step(s)`) and committed failing tests, then the fix. The session took 17 minutes 50 seconds and reported 25.48 AI credits. The local proof then selected the tests that the tests-only commits added:

![The local proof for the second defect: 4 of 4 selected tests fail at the tests-only commit and pass at the fix](images/09-local-proof.png)

Four of four failed at the tests-only commit `b9e90bb` and passed at the fix `e899718`. These commits stayed on the presenter's machine, so the screenshot is this step's record.

**Point out:** the same skills and the same proof worked on a different defect, from the terminal, with no pull request.

## Results and value

**What the run left behind:**

- Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100), closed as not planned, and pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101), closed without merging: Copilot's five commits (its plan, two tests-only commits, the fix, and the review-loop commit), Copilot code review's finding, Copilot's reply, and the evidence comment.
- Two proofs, both *Proven*, in [`evidence/`](evidence/): the same 5 of 7 tests failed at `8de3d60fb`, and 7 of 7 passed at `a92d4b313` and again at `e1d52334d`.
- The person's decisions: approving Copilot's workflow runs twice, and asking Copilot for a change after the review. No GitHub review was recorded, so the evidence comment's decision stayed pending; step 8 shows how the 10 November run recorded an approval.

**What was measured:**

| Measure | Recorded run |
| --- | --- |
| Filing the Issue to Copilot's draft pull request | 11 s |
| Copilot's first session | 13 min 24 s and 6.3 AI credits, as its session page reported. Its first tests-only commit came 6 min 8 s after the Issue was filed, and the fix 8 min 46 s after the assignment |
| Waiting for a person to approve the workflow runs | 7 min 26 s |
| Proof | 1 min 44 s; 1 min 33 s after the review loop |
| CI, the full test suite | 3 min 52 s; 2 min 49 s after the review loop |
| Copilot code review | 6 min 14 s, one high-severity finding |
| Review loop: the request to Copilot's new commit | 6 min 54 s |
| Filing the Issue to the first passing proof | 23 min 26 s |
| GitHub-hosted runner time: every workflow the run started, Copilot's two sessions and its code review included | 42.8 min of job time; 57 min as billed in a private repository, where each job is rounded up to a whole minute |
| Optional Copilot CLI session (step 9) | 17 min 50 s, 25.48 AI credits |

**What a team gets:**

- **Time.** Copilot wrote the failing tests and the fix unattended. The person's part was filing the Issue, approving the workflow runs, asking for one change, and reading the evidence.
- **Risk removed.** A fix can't arrive without at least one test that failed first: the proof names the tests that failed, at a known SHA. Races are tested, not assumed: eight parallel clicks must produce exactly one `201`, in the scenario and in the tests. The code review caught an authorization gap before anyone merged.
- **Evidence a reviewer or auditor can follow.** The evidence comment on the pull request gives the proof's verdict at two known SHAs and keeps the review comments apart from the checks. The test reports at both SHAs are in the proof run's artifact; artifacts expire, so keep the ones you need, as [`evidence/`](evidence/) does here. Once a person submits a review, the comment records who decided.
- **People stay in charge.** Workflows on Copilot's pull request run only after a person approves them, a person decides on the change, and RequestHub's own rule is untouched: only approvers decide, never on their own request.

**The metric to track in a pilot:** lead time from a defect report to a proven fix, from the Issue's creation to the first passing proof check on Copilot's pull request. Both timestamps are on GitHub. The recorded run measured 23 minutes 26 seconds, 7 minutes 26 seconds of them waiting for a person to approve the runs; the 10 November run measured 14 minutes 50 seconds. Track alongside it how many fixes arrive with tests that failed first (the proof's verdict), and how many review findings become a commit before merge. Compare both with similar defects fixed before the pilot. A target such as "a proven fix within an hour of the report" is the team's goal, never a result to report.

## What's in this folder

```text
04-test-github/
├── README.md
├── duplicate-decision-issue.md         the defect report: becomes the Issue Copilot receives
├── requirements.txt                    no packages needed: the scripts use the Python standard library
├── evidence/                           the recorded run's two proofs, copied from the workflow's artifacts
├── images/                             screenshots from the recorded run, used in this README
├── lab/duplicate-decision.patch        the defect: removes the decision guards and the tests that cover them
├── scenarios/
│   ├── duplicate-decision.json         the reported defect as data: a retry, a second approver, eight parallel clicks
│   └── whitespace-rejection.json       a second, smaller defect for the same procedure
├── tests/test_review_evidence.py       unit tests: the evidence report never speaks for anyone else (offline, fake gh)
└── .github/
    ├── agents/test-github.agent.md     the custom Copilot agent: reproduce, failing tests first, then the fix
    ├── skills/
    │   ├── failure-reproduction/       repro.py runs a scenario against a running API
    │   ├── review-evidence/            prove_fix.py (fails before, passes after) and review_evidence.py (the report)
    │   ├── regression-validation/      runs the test suites that cover a change (shared with 03-develop-github)
    │   └── contract-impact/            additive-only API contract check that regression-validation calls (shared)
    ├── workflows/
    │   ├── test-github-proof.yml       proves the fix test-first on fix pull requests
    │   └── test-github-checks.yml      runs the unit tests on pull requests that change this solution
    └── ISSUE_TEMPLATE/04-test-github-defect.yml
```

## Set it up yourself

### Prerequisites

Your copy of the repository, and the tools every solution needs, in the root README's [Before you start](../../README.md#before-you-start). This solution's scripts use only Python's standard library. It also needs:

- **A paid GitHub Copilot plan** that lets you assign Issues to Copilot, with the Copilot cloud agent allowed in your copy. For a repository you own, turn it on in your account's Copilot settings, under **Features** (`github.com/settings/copilot/features`); in an organization, an owner allows it ([why Copilot may be missing from an Issue's assignees](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/troubleshoot-cloud-agent)). Step 6 uses Copilot code review, and the optional step 9 [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli).
- **A Copilot session on GitHub Actions.** Copilot gets PostgreSQL for its tests from [`copilot-setup-steps.yml`](../../.github/workflows/copilot-setup-steps.yml), and cloud sandboxes don't run setup steps ([Copilot's environments](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github#comparison-of-github-actions-based-sessions-and-cloud-sandboxes)). Assigning the Issue started a GitHub Actions-based session in the recorded run and in the 10 November run; if you're offered a choice of environment, pick GitHub Actions.
- **For steps 2 and 9 only:** the [.NET 10 SDK](https://dotnet.microsoft.com/download) and PostgreSQL on `localhost:5432` (user `requesthub`, password `devpass`). The [app README](../../app/README.md#run-it-locally) has a one-line Docker command.

### Quick start

About 2 minutes, in your copy of the repository, from its root folder: the [root README](../../README.md)'s *Set it up yourself* makes that copy, once for every solution. In PowerShell 7, create the two labels the demo's Issue uses; the commands took 3 seconds when this README was checked:

```powershell
gh label create ai-sdlc --color 1D76DB --description "AI-SDLC demo work" --force
gh label create phase:test --color C5DEF5 --description "SDLC phase 4: Test" --force
```

Then allow the Copilot cloud agent in your copy, as in the prerequisites. To run steps 2 and 9 on your machine, also do [one-time step 5](#one-time-steps-in-detail).

**What it costs.** Setting it up costs nothing: the labels and the setting use no AI credits or runner minutes. A demo run draws on your Copilot plan's AI credits, for the cloud agent's sessions, its code review, and Copilot CLI in step 9, and on GitHub Actions. In the recorded run, Copilot's first session reported 6.3 AI credits and step 9's Copilot CLI session 25.48, and the workflows, Copilot's sessions included, used 42.8 minutes of standard GitHub-hosted runners. Those minutes are free in a public repository. In a private one they count against your plan's included usage: 57 minutes for the recorded run, because each job is rounded up to a whole minute ([GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Copilot billing](https://docs.github.com/en/copilot/concepts/billing-and-usage)).

### One-time steps in detail

1. **Start in your copy.** The [root README](../../README.md)'s *Set it up yourself* makes it, once for every solution. Run this README's commands from its root folder. What you should see: `gh repo view --json nameWithOwner -q .nameWithOwner` prints your copy, the repository that every `gh` command below acts on.
2. **Let Copilot work in it.** Allow the Copilot cloud agent in the repository, as in the prerequisites. What you should see: on any Issue in your copy, **Assignees** lists **Copilot**.
3. **Create the labels** that step 3's Issue uses (`bug` comes with every new repository). What you should see:

   ```powershell
   gh label list --search phase:test
   ```

   prints `phase:test  SDLC phase 4: Test  #C5DEF5` on its first line.
4. **Check the custom agent.** The cloud agent reads custom agents from the default branch, and skills and scripts from the branch it works on.

   ```powershell
   gh api 'repos/{owner}/{repo}/contents/.github/agents/test-github.agent.md' --jq .path
   ```

   prints `.github/agents/test-github.agent.md`. The skills, the proof workflow, and the issue form are active too, because the repository's root `.github/` folder mirrors this solution's.
5. **Prepare your machine for steps 2 and 9.** Start PostgreSQL, and build the API once:

   ```powershell
   dotnet build app/src/RequestHub.Api
   ```

   What you should see: the build succeeds with no errors. A cold restore and build took 19 seconds when this README was checked; after it, step 2's `dotnet run` starts in seconds.

## Run it yourself

Optional: for a live session, or to check a new setup. The steps have the same numbers as [the recorded run](#the-recorded-run), which shows what each one looks like. Your SHAs, test names, and counts will differ, because Copilot writes new tests every time.

### Before you start

- [ ] **Confirm the starting state.** `gh pr list --base lab/test-duplicate-decision` prints nothing, and `gh issue list --label phase:test --state open` shows no Issue left over from an earlier run. This repository keeps Issue [#5](https://github.com/melabadi/adept-assessment-northstars/issues/5) open on purpose, with its draft pull request [#6](https://github.com/melabadi/adept-assessment-northstars/pull/6) on a frozen copy of the lab branch: the first run's evidence. Anything else left over, see [Reset and clean up](#reset-and-clean-up) first.
- [ ] **Start the slow parts about 30 minutes early.** Run steps 1 and 3 before the audience arrives: Copilot's first session took 13 minutes in the recorded run, and between 11 and 31 minutes across six runs. Build the API once, so step 2 starts in seconds. If you plan to show step 9, run it beforehand too: Copilot CLI took 18 minutes in the recorded run.
- [ ] **Open in advance.** Two PowerShell terminals at the repository root, on the lab branch; the second one runs the API. Browser tabs: the Issue, Copilot's pull request, its **View session** page, and the latest run of **Test · GitHub · prove the fix test-first** under **Actions**. In the editor: [`duplicate-decision-issue.md`](duplicate-decision-issue.md) and [`scenarios/duplicate-decision.json`](scenarios/duplicate-decision.json).
- [ ] **Plan the time.** About 20 minutes on stage when steps 1, 3, and 9 ran beforehand. The waiting times come from the recorded run:

| Step | On stage | Waiting |
| --- | --- | --- |
| 1. Rebuild the lab branch | 1 min | |
| 2. Reproduce the defect | 2 min | |
| 3. Hand the defect to Copilot | 3 min | Copilot: 13 min (11 to 31 across six runs) |
| 4. Approve the workflow runs | 1 min | the proof: 2 min; CI: 4 min |
| 5. Watch the proof | 2 min | |
| 6. Ask Copilot for a code review | 2 min | the review: 6 min |
| 7. Assemble the evidence | 2 min | |
| 8. Decide, with a review loop | 4 min | Copilot: 7 min to a new commit, then the checks: 3 min |
| 9. Optional: a second defect with Copilot CLI | 3 min | Copilot CLI: 18 min |

### The steps

1. **Rebuild the lab branch from `main`.** Do this before every run. The defect lives only on `lab/test-duplicate-decision`: `main` plus [`lab/duplicate-decision.patch`](lab/duplicate-decision.patch).

   ```powershell
   git fetch origin
   git switch -C lab/test-duplicate-decision origin/main --no-track
   git apply solutions/04-test-github/lab/duplicate-decision.patch
   git rm -q solutions/04-test-github/lab/duplicate-decision.patch
   git commit -qam "Test lab: decision guards removed (duplicate-decision scenario)"
   git push --force origin lab/test-duplicate-decision
   ```

   The push reports a forced update, or `[new branch]` on a new copy's first run: see [step 1](#1-the-lab-branch-was-rebuilt-from-main).

2. **Reproduce the defect.** Start the API from the lab branch in the second terminal, then run the scenario in the first:

   ```powershell
   dotnet run --project app/src/RequestHub.Api        # second terminal; http://localhost:5080
   python .github/skills/failure-reproduction/repro.py solutions/04-test-github/scenarios/duplicate-decision.json
   ```

   It ends with `REPRODUCED`. To show that the scenario is a fair oracle, run it against `main` too: stop the API (Ctrl+C), `git switch main`, start the API again, and rerun the scenario, which ends with `Not reproduced`. Switch back with `git switch lab/test-duplicate-decision`. See [step 2](#2-the-scenario-reproduced-the-defect).

3. **Hand the defect to Copilot.** Create the Issue from the defect report:

   ```powershell
   gh issue create --title "Test: a request can be decided more than once" --label ai-sdlc --label phase:test --label bug --body-file solutions/04-test-github/duplicate-decision-issue.md
   ```

   Open the Issue and assign it to **Copilot**. In the dialog, pick the **test-github** agent and the base branch **lab/test-duplicate-decision**. From a terminal instead (replace `<issue>`; it prints `Copilot` and your login):

   ```powershell
   $repo = gh repo view --json nameWithOwner -q .nameWithOwner
   @{ assignees = @('copilot-swe-agent[bot]'); agent_assignment = @{ target_repo = $repo; base_branch = 'lab/test-duplicate-decision'; custom_agent = 'test-github' } } |
     ConvertTo-Json -Compress | gh api -X POST "repos/$repo/issues/<issue>/assignees" --input - --jq '.assignees[].login'
   ```

   Within seconds Copilot opens a draft pull request. Select **View session** on it to watch Copilot work. When the session ends, list its commits, and open the tests-only commit's concurrent test with `git show <tests-only commit>:app/tests/RequestHub.Tests/RequestLifecycleTests.cs`:

   ```powershell
   git fetch origin
   # Copilot's branch name is at the top of the pull request
   git --no-pager log --reverse --stat=100 --format="%n%h %s" origin/lab/test-duplicate-decision..origin/copilot/labtest-duplicate-decision
   ```

   See [step 3](#3-copilot-committed-failing-tests-then-the-fix).

4. **Approve the workflow runs.** Select **Approve workflows to run** in the pull request's merge box. From a terminal instead, start every waiting run of the pull request's latest commit:

   ```powershell
   $head = gh pr view <pr> --json headRefOid -q .headRefOid
   gh run list --commit $head --json databaseId,conclusion -q '.[] | select(.conclusion == "action_required") | .databaseId' | ForEach-Object { gh run rerun $_ }
   ```

   The two to watch are **CI** and **Test · GitHub · prove the fix test-first**; checks from other solutions may run and pass or skip. See [step 4](#4-a-person-approved-the-workflow-runs).

5. **Watch the proof.** Open the **Regression tests fail before the fix and pass after it** check and its summary, or follow the checks from a terminal with `gh pr checks <pr> --watch`. See [step 5](#5-the-proof-showed-the-tests-failing-first).

6. **Ask Copilot for a code review.** In the pull request, select **Reviewers** > **Copilot**, or run `gh pr edit <pr> --add-reviewer "@copilot"`. You can do this right after step 4, so the review runs while you show the proof. See [step 6](#6-copilot-code-review-found-a-gap-the-tests-missed).

7. **Assemble the evidence** and post it on the pull request. Run it from `main` or the lab branch, never from the pull request's branch: its copy of the script could leave out what the report must say.

   ```powershell
   python .github/skills/review-evidence/review_evidence.py --pr <pr> --comment
   ```

   It takes seconds (9 for pull request #101 when this README was checked). If the pull request changes where its checks are defined (anything under `.github/workflows/`, `.github/actions/`, `.github/skills/`, or `tools/`), section 1 opens with a warning that lists those files, because its checks ran with its own version of its workflows: read them first. Only reviews from the repository's owner, members, and collaborators count as the decision; anyone else's review is listed as not counted, without its text. The comment is posted with your token, so everything it quotes from GitHub is inert: it can't mention anyone, which would start Copilot in your name, or refer to an Issue or a pull request, and it can't add a link, an image, or HTML. See [step 7](#7-the-evidence-comment-kept-checks-apart-from-comments).

8. **Decide.** Read the tests in the tests-only commit: do they assert what the Issue expects, including the concurrent case? If the review found a gap, ask Copilot on the pull request, as the recorded run did. Approve the new commit's workflow runs (step 4), then run step 7 again. When you are satisfied, approve or request changes as a GitHub review, and record it with step 7:

   ```powershell
   gh pr review <pr> --approve --body "<what you checked: the tests, the proof, the review>"
   python .github/skills/review-evidence/review_evidence.py --pr <pr> --comment
   ```

   Use `--request-changes` instead of `--approve` to send it back. Don't merge: the lab branch is rebuilt for every run. See [step 8](#8-a-person-asked-for-a-change-and-the-new-commit-passed-the-same-gates).

9. **Optional: a second defect with Copilot CLI.** The lab build also accepts a rejection whose comment is only spaces. Stop the API (Ctrl+C), so Copilot CLI can start its own, then:

   ```powershell
   git switch -c test/whitespace-rejection lab/test-duplicate-decision
   copilot --agent test-github --allow-all-tools -p "Fix this defect test-first. A rejection whose comment is only spaces is accepted; it must return 400 validation.failed and the request must stay Submitted. Scenario: solutions/04-test-github/scenarios/whitespace-rejection.json"
   python .github/skills/review-evidence/prove_fix.py --base origin/lab/test-duplicate-decision --head HEAD
   ```

   Copilot reproduces the defect, commits failing tests, then the fix, and the local proof runs the selected tests at the last tests-only commit and at the fix. See [step 9](#9-optional-copilot-cli-fixed-a-second-defect).

## Reset and clean up

```powershell
gh pr close <pr> --delete-branch --comment "Demo run: closed without merging."
gh issue close <issue> --reason "not planned"
git switch main
git branch -D test/whitespace-rejection    # if you ran step 9
```

Never merge Copilot's pull request. Step 1 rebuilds the lab branch from `main` for the next run.

## Use it in your own repository

1. Copy this folder's `.github/` contents into your repository's `.github/` folder, and `tests/` to your repository's root; then, in `test-github-checks.yml`, run `tests` instead of `solutions/04-test-github/tests`, and watch `tests/**` instead of `solutions/04-test-github/**`. The cloud agent loads the custom agent profile from the default branch, so merge changes to the agent before you assign work. Skills and scripts come from the branch Copilot works on.
2. Point the scripts at your stack: the sign-in header and base URL in `repro.py`, the solution and test folder (`app/RequestHub.slnx`, `app/tests/`) and the xUnit attribute pattern in `prove_fix.py`, the suites in `run_regression.py`, and `CHECK_DEFINITIONS` in `review_evidence.py`: every path that holds what your workflows run.
3. Decide which pull requests need the proof. The workflow runs only on pull requests into `lab/test-**` branches, so it never touches other work. For fixes into `main`, change its `branches` filter, add an `if:` that recognizes a fix (for example a `bug` label), and make the check required in a ruleset.
4. Write a scenario for your next defect report, and make sure the Copilot cloud agent can run your tests (database services in `copilot-setup-steps.yml`).

## Troubleshooting

- **No checks on Copilot's pull request.** Workflows on pull requests from the cloud agent wait for a person. Select **Approve workflows to run**, or run `gh run rerun <run-id>`.
- **The runs of an earlier commit show as cancelled.** Approving the waiting runs of several commits starts them together, and the newest run in each concurrency group cancels the older ones. Approve the latest commit's runs; the proof still tests the tests-only commit.
- **The feature bounds check on Copilot's *Initial plan* commit keeps waiting.** Nothing needs it: approve the latest commit's runs, which include the same check. When the pull request closes, GitHub marks the waiting run as failed, without running it.
- **The pull request description has no evidence.** Copilot sometimes writes its evidence summary only at the end of the session. Read it under **View session**, or ask `@copilot` to add it to the description.
- **Port 5080 or the `requesthub` database is already in use** (for example on a shared machine). Give the API its own: set `$env:ConnectionStrings__RequestHub = "Host=localhost;Port=5432;Database=rh_lab;Username=requesthub;Password=devpass"`, start it with `--urls http://localhost:5081`, and pass `--api http://localhost:5081` to `repro.py`. Tell Copilot CLI the same port and database in its prompt.
- **`error: cannot reach http://localhost:5080`.** The API is not running yet, or runs on another port.
