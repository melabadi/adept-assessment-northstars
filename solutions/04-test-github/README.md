# Test · Regression lab with GitHub Copilot

Defects that only show up under retries or simultaneous clicks slip through review: nobody wrote the test that would have caught them, and a green pull request doesn't say whether its new tests ever failed. This solution adds a test-first loop to your repository. A scenario file replays a reported defect against your running API, and a custom agent for the Copilot cloud agent commits failing regression tests first, then the fix. A GitHub Actions workflow proves that the tests fail at the tests-only commit and pass at the fix. When CI fails on the pull request, an agentic workflow explains each failure: a new test failing as intended, a regression, or a failure that isn't the change's. Copilot code review looks for what the tests miss, and an evidence report keeps the checks apart from the review comments, so a person decides with the proof in hand.

![The review evidence on Copilot's pull request: every check passes, and Copilot's regression tests fail at the tests-only commit and pass at the head](images/07-evidence-checks.png)

- **Install it in your repository:** [copy 20 files, edit them for your code, and set them up once](#install-it-in-your-repository), with the commands in order in [Getting started](#getting-started). The setup's commands took seconds when this README was checked, 5 to 9 to copy the files and 4 for the labels; the rest is a settings page, a token, a pull request, and the changes your stack needs.
- **Files to edit to tweak it:** [the agent's instructions, the scenario runner's sign-in, the proof's test patterns and command, and the CI failure investigation's triggers](#files-to-edit-to-tweak-it).
- **See it work:** [a real run on this repository](#see-it-work), step by step. A request that could be approved and then rejected was reproduced, tested with an eight-click race, fixed, and reviewed, with a screenshot and a link anyone can open for every step. A later run shows the agentic workflow explaining two red CI runs.
- **Try it first in a copy of this repository:** [about 2 minutes to set up](#try-it-first-in-a-copy-of-this-repository), in the copy that the [root README](../../README.md#try-it-in-a-copy-of-this-repository) makes once for every solution. A run then needs about 22 minutes of Copilot and the checks working unattended.

## Technologies used

| Technology | What it does here |
| --- | --- |
| [Copilot cloud agent](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github) | Fixes the defect from its Issue, unattended, in a session on GitHub Actions: the failing tests in their own commit, then the fix |
| A [custom agent](https://docs.github.com/en/copilot/concepts/customizations/custom-agents) and five [agent skills](https://docs.github.com/en/copilot/concepts/customizations/agent-skills) | Reproduce the defect with a scenario, prove that the new tests failed before the fix, run the test suites a change touches, keep the API contract additive, explain a red CI run, and post the review evidence |
| [Copilot code review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-code-review) | Looks for what the tests miss |
| [GitHub Agentic Workflows](https://github.com/github/gh-aw) | Runs Copilot when CI fails on a fix's pull request, to explain each failure in one comment and one label |
| [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-cli) | Optional: runs the same agent on your machine, to fix a defect from your terminal |
| GitHub Issues, with an [issue form](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms) | Hold the defect: what was observed, how to reproduce it, and what is expected |
| [GitHub Actions](https://docs.github.com/en/actions) | Runs your CI, the proof that the new tests fail before the fix and pass after it, and Copilot's session, which `copilot-setup-steps.yml` prepares |
| Python 3.12, standard library only | The scenario runner, the proof, the evidence report, and the facts of a failed CI run |
| GitHub CLI and PowerShell 7 | The commands in this README |

The files are written for RequestHub's stack: a .NET 10 API, xUnit v3 integration tests, and PostgreSQL. [Files to edit to tweak it](#files-to-edit-to-tweak-it) names what to change for yours.

## What it does and how it works

### What it does

**Phase 4 of 7: Test.** Today a defect is usually fixed first and tested afterwards, if at all. Nobody sees whether the new test would have caught the defect, races are hard to reproduce by hand, and a green check with an empty review looks like a clean one. With this solution the order of the evidence is the point: the tests fail at one known commit and pass at the next, the checks are reported apart from the review comments, and a person decides with that proof in hand.

| | Today | With this solution |
| --- | --- | --- |
| Reproducing | Someone repeats the clicks from the bug report by hand, and races are hard to trigger. | A scenario file replays the report against the API, including eight parallel clicks, and lists the expectations that break. |
| Regression tests | Written after the fix, if at all. Nobody knows whether they would have caught the bug. | Copilot commits the failing tests on their own, then the fix in a separate commit. |
| A red CI run | Someone reads the log to find the failing test, then guesses whether the change caused it. | An agentic workflow reads the log, the diff, and main's latest CI result, sorts each failing test (a new test failing as intended, a regression, or a failure that also happens on main), and posts one comment and one label. |
| Review | A green check and a few comments. An empty review looks like a clean one. | Actions reruns the new tests at the tests-only commit (at least one must fail) and at the head (all must pass) and keeps both outputs. Comments are reported apart from the checks. |
| Decision | Implicit in the merge button. | A person approves the workflow runs, reads the tests, and approves or requests changes; the evidence comment records who decided. |

The value: a defect report becomes a proven, reviewable fix in under half an hour, and the reviewer gets evidence to check rather than a green mark to trust. [Results and value](#results-and-value) has what the recorded run measured.

The Microsoft counterpart, [04-test-microsoft](../04-test-microsoft/), load-tests the API with Azure Load Testing. The [Test combo](../../PRESENTING.md#test-copilot-proves-the-repair-azure-load-tests-the-same-commit) uses both on one change: Azure load-tests the very commit that this solution proves.

### How it works

```mermaid
flowchart LR
  L["Branch with the defect<br/>(a lab branch in the run)"] --> R[Scenario against<br/>the running API]
  R -->|REPRODUCED| I[GitHub Issue]
  I -->|assigned with the<br/>test-github agent| C[Copilot cloud agent]
  C -->|1. failing tests<br/>2. fix| PR[Pull request<br/>into that branch]
  PR --> CI[Actions: CI<br/>full test suite]
  PR --> P[Actions: prove the fix<br/>fails before, passes after]
  PR --> CR[Copilot code review]
  CI -->|if it fails| AW[Agentic workflow:<br/>why CI failed]
  CI --> E[Review evidence<br/>comment]
  P --> E
  CR --> E
  E --> H{Person decides}
  AW -->|one comment,<br/>one label| H
```

- **Copilot** runs the custom agent [`test-github`](.github/agents/test-github.agent.md) in the cloud agent. With the `failure-reproduction` skill it runs the Issue's scenario, writes integration tests that assert the expected behavior, commits them alone, fixes the code in a second commit, and reruns the tests, the `regression-validation` suites, and the scenario. Copilot code review then looks for what the tests miss.
- **GitHub Actions** runs [CI](../../.github/workflows/ci.yml) (the full test suite) and [`test-github-proof.yml`](.github/workflows/test-github-proof.yml), which reruns the tests the tests-only commit added at that commit and at the head, each in a clean worktree, and keeps both outputs. Its script comes from the base branch. GitHub still runs a pull request's own copy of the workflow files, so the evidence report flags a pull request that changes them, the skills they run, or `tools/`.
- **GitHub Agentic Workflows** runs [`test-github-ci-investigation.md`](.github/workflows/test-github-ci-investigation.md) when CI fails on a fix's pull request. First a script from the default branch, [`ci_failure_facts.py`](.github/skills/ci-investigation/ci_failure_facts.py), collects the facts: each failing test's message, file, and line, whether the pull request adds or changes that test, and whether main's latest CI run fails it too. Then Copilot follows the [`ci-investigation`](.github/skills/ci-investigation/SKILL.md) skill and sorts each failure into one of three classes: (a) a test the pull request adds, failing as intended, so the defect is reproduced; (b) an existing test that the change broke; or (c) a failure that also happens on main, or isn't a test. It posts one comment with each failure's log link and next step, and adds one label: `ci:defect-reproduced`, `ci:regression`, or `ci:infrastructure`. It reads; it can't rerun, push, or approve anything, and threat detection checks the comment and the label before they're applied: a run it flags applies nothing. The workflow is compiled with gh-aw v1.2.2, and [`test-github-checks.yml`](.github/workflows/test-github-checks.yml) fails if the committed lock file isn't what that version compiles.
- **A person** files the Issue, approves the workflow runs, reads the tests, and approves or requests changes. The `review-evidence` skill reports the checks apart from the comments and records who decided.

**Outside contributions.** On a public repository anyone can open an Issue with this solution's form, or a pull request from a fork. Neither starts Copilot: only people with write access can assign an Issue to Copilot or mention `@copilot`. The proof runs a fork's pull request into a `lab/test-*` branch once someone with write access approves the run: it runs that pull request's tests with a read-only token, no secrets, and no credentials left in the checkout, and takes the proof script from the base branch. A pull request can still change the workflow files GitHub runs for it, so the evidence report flags one that does. The evidence comment is posted with your token, so it never speaks for anyone else: only reviews from the owner, members, and collaborators count as the decision, and everything it quotes from GitHub is inert: it can't mention anyone (`@copilot` included) or refer to an Issue or a pull request, and it can't add a link, an image, or HTML. The CI failure investigation investigates only a failed CI run of a pull request from one of this repository's own branches, opened by the owner, a member, a collaborator, or Copilot; for any other run, including one from a fork's pull request with a workflow of its own named CI, its agent never starts. gh-aw also checks that whoever triggered the run has write access. The investigation's comment can't mention anyone or refer to an Issue or a pull request, and its links can only point at GitHub.

## Install it in your repository

[Getting started](#getting-started) lists the commands in order, and the sections after it explain each step and what you should see. [Files to edit to tweak it](#files-to-edit-to-tweak-it) names what to change for your code. The commands are the ones this repository uses.

### Prerequisites

- **The tools every solution needs,** in the root README's [Before you start](../../README.md#before-you-start): GitHub CLI, PowerShell 7.4 or later, and Python 3.12 or later. This solution's scripts use only Python's standard library.
- **A paid GitHub Copilot plan** that lets you assign Issues to Copilot, with the Copilot cloud agent allowed in your repository. For a repository you own, turn it on in your account's Copilot settings, under **Features** (`github.com/settings/copilot/features`); in an organization, an owner allows it ([why Copilot may be missing from an Issue's assignees](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/troubleshoot-cloud-agent)). Copilot code review reviews the fix. To fix a defect from your terminal instead, as in the optional [step 9](#9-optional-copilot-cli-fixed-a-second-defect), install [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli).
- **A Copilot session on GitHub Actions.** Copilot runs your tests in its session, with the services that `copilot-setup-steps.yml` starts ([this repository's](../../.github/workflows/copilot-setup-steps.yml) starts PostgreSQL), and cloud sandboxes don't run setup steps ([Copilot's environments](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github#comparison-of-github-actions-based-sessions-and-cloud-sandboxes)). If you're offered a choice of environment, pick GitHub Actions.
- **An API you can run, and integration tests.** A scenario calls your API over HTTP, with a test sign-in, so you run the API on your machine and Copilot runs it in its session. CI and the proof run your integration tests on GitHub-hosted runners.
- **For the CI failure investigation:** a CI workflow that runs your tests on pull requests, and [GitHub Agentic Workflows](https://github.com/github/gh-aw) with its `gh aw` extension, to compile the workflow after you change it: `gh extension install github/gh-aw --pin v1.2.2`. Its Copilot engine authenticates with a `COPILOT_GITHUB_TOKEN` secret, a fine-grained personal access token with **Copilot Requests: Read** ([one-time step 6](#one-time-setup)). In an organization with a Copilot subscription and centralized billing, gh-aw recommends `copilot-requests: write` in the workflow's `permissions:` instead, with no token.

### Getting started

From the root of your repository, in PowerShell 7. Each step links to its details and to what you should see.

1. **Check the tools.** `gh auth status` must list `workflow` among the token's scopes, Python must be 3.12 or later, and PowerShell 7.4 or later. `gh aw version` must print `v1.2.2`, the version that compiles the CI failure investigation: step 4 installs it if it's missing, and [Troubleshooting](#troubleshooting) says how to replace an older one. Copilot CLI is needed only to fix a defect from your terminal ([Prerequisites](#prerequisites)).

   ```powershell
   gh --version; gh auth status
   python --version; $PSVersionTable.PSVersion.ToString()
   copilot --version
   gh aw version
   ```

2. **Copy the files on a new branch.** The copy adds the licence that must travel with the files, as `.github/LICENSE-ai-sdlc`, and prints the commit it copied from: keep it to [take updates later](../../README.md#take-updates-later).

   ```powershell
   git switch -c add-test-github
   $src = Join-Path ([IO.Path]::GetTempPath()) 'ai-sdlc-04-test-github'
   git clone --quiet --depth 1 https://github.com/melabadi/adept-assessment-northstars.git $src
   "Copying from ai-sdlc commit $(git -C $src rev-parse --short HEAD)"
   New-Item -ItemType Directory -Force .github, tests | Out-Null
   Copy-Item -Recurse -Force (Join-Path $src 'solutions/04-test-github/.github/*') .github
   Copy-Item -Force (Join-Path $src 'solutions/04-test-github/tests/test_*.py') tests
   Copy-Item -Force (Join-Path $src 'LICENSE') .github/LICENSE-ai-sdlc
   Remove-Item -Recurse -Force $src
   git status --short --untracked-files=all
   ```

   What you should see: the commit, then 20 new files, in 5 to 9 seconds when this README was checked; the other files in `.github/` and `tests/` stay. GitHub reads a repository's own licence only from its root, so yours doesn't change.

3. **Edit the files for your code,** as [Files to edit to tweak it](#files-to-edit-to-tweak-it) lists. Then run the unit tests. They import the skills' scripts, so first keep Python from writing `__pycache__` folders into `.github/` and `tests/`:

   ```powershell
   $env:PYTHONDONTWRITEBYTECODE = '1'
   python -m unittest discover -s tests
   ```

   They end with `OK` ([one-time step 1](#one-time-setup)), and `git status` lists no `__pycache__` folder.

4. **Set it up once.** Give Copilot and the proof your test services, point the proof at your fixes, and allow the Copilot cloud agent ([one-time steps 2, 3, and 5](#one-time-setup)). Create a fine-grained token with **Copilot Requests: Read** on GitHub ([one-time step 6](#one-time-setup)). Then create the labels, store the token as a secret, and compile the CI failure investigation with your changes ([one-time steps 4, 6, and 7](#one-time-setup)):

   ```powershell
   gh label create ai-sdlc --color 1D76DB --description "AI-SDLC demo work" --force
   gh label create phase:test --color C5DEF5 --description "SDLC phase 4: Test" --force
   gh label create ci:defect-reproduced --color 0E8A16 --description "CI failure investigation: tests this pull request adds fail as intended" --force
   gh label create ci:regression --color B60205 --description "CI failure investigation: the change broke an existing test or check" --force
   gh label create ci:infrastructure --color FBCA04 --description "CI failure investigation: fails on main too, or the failure isn't a test" --force
   gh secret set COPILOT_GITHUB_TOKEN    # paste the token when prompted
   gh extension install github/gh-aw --pin v1.2.2
   gh aw compile test-github-ci-investigation --strict
   ```

5. **Merge it into your default branch,** where the cloud agent finds custom agents, GitHub offers issue forms, and the CI failure investigation runs ([one-time step 8](#one-time-setup)). Replace `<commit>` with the one step 2 printed:

   ```powershell
   git add .github tests
   git commit -m "Add 04-test-github from ai-sdlc <commit>"
   git push -u origin add-test-github
   gh pr create --fill
   ```

   Merge the pull request as you merge any change. To make the proof a gate, require its check in a ruleset ([one-time step 3](#one-time-setup)).

6. **Use it on your next defect.** Reproduce it with a scenario against your API, file it with the *Test: defect to fix test-first with Copilot* form, then assign it to Copilot with the `test-github` agent and, as the base branch, the branch that has the defect (replace `<scenario.json>`, `<your API's address>`, `<issue>`, and `<branch>`):

   ```powershell
   python .github/skills/failure-reproduction/repro.py <scenario.json> --api <your API's address>
   $repo = gh repo view --json nameWithOwner -q .nameWithOwner
   @{ assignees = @('copilot-swe-agent[bot]'); agent_assignment = @{ target_repo = $repo; base_branch = '<branch>'; custom_agent = 'test-github' } } |
     ConvertTo-Json -Compress | gh api -X POST "repos/$repo/issues/<issue>/assignees" --input - --jq '.assignees[].login'
   ```

   Then approve its workflow runs, read the proof, and decide, as [Use it the first time](#use-it-the-first-time) describes.

### One-time setup

1. **Copy the files and make the changes in [Files to edit to tweak it](#files-to-edit-to-tweak-it),** on a branch, as in [Getting started](#getting-started). What you should see: `python -m unittest discover -s tests` ends with `OK`. The unit tests run offline, with a fake `gh`, in a second or two.
2. **Give Copilot and the proof your test services.** Before Copilot starts, GitHub runs the job named `copilot-setup-steps` in `.github/workflows/copilot-setup-steps.yml`. Start your database there as a service and install your toolchain, as [this repository's](../../.github/workflows/copilot-setup-steps.yml) does for PostgreSQL and .NET, and give `test-github-proof.yml` the same service. What you should see: once the file is on your default branch, `gh workflow run copilot-setup-steps.yml` starts it (it needs a `workflow_dispatch` trigger, as this repository's has), and `gh run list --workflow copilot-setup-steps.yml --limit 1` then shows it `completed` with `success`.
3. **Point the proof at your fixes.** In `test-github-proof.yml`, set `branches` to the branches your fixes go into, for example `main`, and `paths` to your code. A pull request without a tests-only commit before its fix fails the proof, so if not every pull request into those branches is a fix, guard the job. [`develop-github-bounds.yml`](../../.github/workflows/develop-github-bounds.yml), from 03-develop-github, shows how: it looks up the Issues that a pull request closes and skips its checks when none carries its label. The same lookup with your defect label, for example `bug`, keeps the proof to fixes. To make the proof a gate, require its check, *Regression tests fail before the fix and pass after it*, in a ruleset on those branches. What you should see: after the merge in step 8, `gh workflow list` lists *Test · GitHub · prove the fix test-first* as `active`.
4. **Create the labels** that the issue form applies (`bug` comes with every new repository), and the three that the CI failure investigation chooses from:

   ```powershell
   gh label create ai-sdlc --color 1D76DB --description "AI-SDLC demo work" --force
   gh label create phase:test --color C5DEF5 --description "SDLC phase 4: Test" --force
   gh label create ci:defect-reproduced --color 0E8A16 --description "CI failure investigation: tests this pull request adds fail as intended" --force
   gh label create ci:regression --color B60205 --description "CI failure investigation: the change broke an existing test or check" --force
   gh label create ci:infrastructure --color FBCA04 --description "CI failure investigation: fails on main too, or the failure isn't a test" --force
   ```

   What you should see: `gh label list --search phase:test` prints `phase:test  SDLC phase 4: Test  #C5DEF5` on its first line, and `gh label list --search ci:` lists the three `ci:` labels. The search can take a few seconds to find a new label.
5. **Allow the Copilot cloud agent** in the repository, as in the [prerequisites](#prerequisites). What you should see: on any Issue, **Assignees** lists **Copilot**.
6. **Give the CI failure investigation access to Copilot.** Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new?name=COPILOT_GITHUB_TOKEN&description=GitHub+Agentic+Workflows+-+Copilot+engine+authentication&user_copilot_requests=read). Set the resource owner to your user account, and under **Account permissions** set **Copilot Requests** to **Read**. Nothing else is needed. Store it as a repository secret:

   ```powershell
   gh secret set COPILOT_GITHUB_TOKEN    # paste the token when prompted
   ```

   What you should see: `gh secret list` lists `COPILOT_GITHUB_TOKEN`. The investigations' AI credits count against the token owner's Copilot plan. In an organization with centralized Copilot billing, add `copilot-requests: write` under `permissions:` in the workflow's source instead, and compile it again. Without either, everything else works, and the investigation's run fails at `Validate COPILOT_GITHUB_TOKEN secret`.
7. **Compile the CI failure investigation** after you change its source. GitHub runs the compiled `.lock.yml`, not the `.md`:

   ```powershell
   gh extension install github/gh-aw --pin v1.2.2
   gh aw compile test-github-ci-investigation --strict
   ```

   What you should see: `✓ Compiled 1 workflow: 1 succeeded, 0 warnings`, after 3 seconds when this README was checked. Commit the `.lock.yml` with the `.md`: `test-github-checks.yml` compiles the source again with the version in `GH_AW_VERSION` and fails if the result differs. The lock file also records the frontmatter of every custom agent in `.github/agents/`, so compile again when an agent's frontmatter changes.
8. **Merge it into your default branch.** The cloud agent loads custom agents from the default branch, GitHub offers issue forms from it, and an agentic workflow that another workflow starts runs from it; skills and scripts come from the branch Copilot works on. What you should see:

   ```powershell
   gh api 'repos/{owner}/{repo}/contents/.github/agents/test-github.agent.md' --jq .path
   ```

   prints `.github/agents/test-github.agent.md`, **New issue** offers *Test: defect to fix test-first with Copilot*, and `gh workflow list` lists *Test · GitHub · agentic CI failure investigation*.

### Use it the first time

On your own defect, the steps are those of [See it work](#see-it-work), from step 2 on:

1. **Reproduce the defect.** Write the report as a scenario: who calls which endpoint, with what body, and what the correct answer is; `parallel` sends one call several times at once, for double-clicks and retries. [`repro.py`](.github/skills/failure-reproduction/repro.py) describes the format, and [`scenarios/duplicate-decision.json`](scenarios/duplicate-decision.json) is the run's. Run it against your API:

   ```powershell
   python .github/skills/failure-reproduction/repro.py <scenario.json> --api <your API's address>
   ```

   What you should see: it ends with `REPRODUCED` and lists the expectations the defect breaks, as in [step 2](#2-the-scenario-reproduced-the-defect).
2. **Hand it to Copilot.** File the Issue with the *Test: defect to fix test-first with Copilot* form, with the scenario and its output under *Reproduce*. Assign it to **Copilot** with the **test-github** agent and, as the base branch, the branch that has the defect: one the proof watches. From a terminal instead (replace `<issue>` and `<branch>`; it prints `Copilot` and your login):

   ```powershell
   $repo = gh repo view --json nameWithOwner -q .nameWithOwner
   @{ assignees = @('copilot-swe-agent[bot]'); agent_assignment = @{ target_repo = $repo; base_branch = '<branch>'; custom_agent = 'test-github' } } |
     ConvertTo-Json -Compress | gh api -X POST "repos/$repo/issues/<issue>/assignees" --input - --jq '.assignees[].login'
   ```

   What you should see: within seconds Copilot opens a draft pull request, and when its session ends, a tests-only commit comes before the fix, as in [step 3](#3-copilot-committed-failing-tests-then-the-fix).
3. **Approve its workflow runs:** select **Approve workflows to run** in the pull request's merge box, or start every waiting run of its latest commit from a terminal:

   ```powershell
   $head = gh pr view <pr> --json headRefOid -q .headRefOid
   gh run list --commit $head --json databaseId,conclusion -q '.[] | select(.conclusion == "action_required") | .databaseId' | ForEach-Object { gh run rerun $_ }
   ```

   See [step 4](#4-a-person-approved-the-workflow-runs).
4. **Read the proof:** `gh pr checks <pr> --watch`. What you should see: *Regression tests fail before the fix and pass after it* passes, and its summary lists each failure at the tests-only commit in the tests' own words, as in [step 5](#5-the-proof-showed-the-tests-failing-first).
5. **If CI fails, read why.** When CI fails on the pull request, the CI failure investigation adds one label and posts a comment headed *CI failure investigation*. For each failing test it gives the assertion message, the file and line, a link to the log, its class, and the next step. `ci:defect-reproduced` means every failure is a test that the pull request adds or changes, failing as intended, as on a tests-only commit: the fix should make it pass. `ci:regression` means the change broke a test or a check that passes on main: fix the code, not the test. `ci:infrastructure` means a failure also happens on main, or isn't a test: rerun the failed job. The comment explains; you decide. [Step 10](#10-added-since-an-agentic-workflow-explained-two-red-ci-runs-11-november-2026) shows a `ci:defect-reproduced` comment and a `ci:regression` one.
6. **Ask Copilot for a code review:** select **Reviewers** > **Copilot** in the pull request, or run `gh pr edit <pr> --add-reviewer "@copilot"`. See [step 6](#6-copilot-code-review-found-a-gap-the-tests-missed).
7. **Post the evidence** on the pull request. Run it from your default branch, never from the pull request's branch: its copy of the script could leave out what the report must say.

   ```powershell
   python .github/skills/review-evidence/review_evidence.py --pr <pr> --comment
   ```

   Section 1 lists the checks and the proof: they decide. If the pull request changes where its checks are defined (anything under the folders in `CHECK_DEFINITIONS`), section 1 opens with a warning that lists those files, because its checks ran with its own version of its workflows: read them first. Section 2 lists the review comments: they inform. Section 3 records the decision: only reviews from the repository's owner, members, and collaborators count, and anyone else's review is listed as not counted, without its text. The comment is posted with your token, so everything it quotes from GitHub is inert: it can't mention anyone, which would start Copilot in your name, or refer to an Issue or a pull request, and it can't add a link, an image, or HTML. See [step 7](#7-the-evidence-comment-kept-checks-apart-from-comments).
8. **Decide.** Read the tests in the tests-only commit: do they assert what the Issue expects, including the concurrent case? If the review found a gap, ask `@copilot` on the pull request, as in [step 8](#8-a-person-asked-for-a-change-and-the-new-commit-passed-the-same-gates), approve the new commit's runs, and post the evidence again. Then approve or request changes as a GitHub review, and post the evidence once more, so it records who decided:

   ```powershell
   gh pr review <pr> --approve --body "<what you checked: the tests, the proof, the review>"
   python .github/skills/review-evidence/review_evidence.py --pr <pr> --comment
   ```

   Use `--request-changes` instead of `--approve` to send it back. Once you approve, merge the fix as you merge any change.

Then make it part of your workflow: write each reproducible defect as a scenario and hand it to Copilot with the `test-github` agent, and require the proof's check on the branches your fixes go into ([one-time step 3](#one-time-setup)), so that no fix merges without a test that failed first. When CI fails on a fix's pull request, start from the investigation's label and comment.

**The metric to track when you adopt it:** lead time from a defect report to a proven fix, from the Issue's creation to the first passing proof check on Copilot's pull request. Both timestamps are on GitHub. The recorded run measured 23 minutes 26 seconds, 7 minutes 26 seconds of them waiting for a person to approve the runs; the 10 November run measured 14 minutes 50 seconds. Track alongside it how many fixes arrive with tests that failed first (the proof's verdict), and how many review findings become a commit before merge. For the CI failure investigation, track how often its label matches what the reviewer concluded about the failure. Compare each with similar defects fixed before you adopted it. A target such as "a proven fix within an hour of the report" is your team's goal, never a result to report.

### What it costs

Setting it up uses no AI credits. Each defect fixed this way draws on your Copilot plan's AI credits, for the cloud agent's sessions and its code review, and on GitHub Actions. In the recorded run, Copilot's first session reported 6.3 AI credits, and the optional Copilot CLI session of step 9 reported 25.48. The run used 42.8 minutes of standard GitHub-hosted runners: 29.8 for Copilot's two sessions and its code review, 8.2 for CI, 3.1 for the proof, and 1.7 for this repository's other workflows. Those minutes are free in a public repository. In a private one they count against your plan's included usage: 57 minutes for the recorded run, because each job is rounded up to a whole minute. The length of your test suite changes the CI and proof minutes ([GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Copilot billing](https://docs.github.com/en/copilot/concepts/billing-and-usage)).

The CI failure investigation runs only when CI fails on a fix's pull request. In step 10's four runs, Copilot used 13.3 to 15.2 AI credits per run and threat detection 0.62, drawn from the Copilot plan of the token's owner. gh-aw stops a run at 40 credits for Copilot and 2 for detection, about 2.5 times the most a run used, and stops the workflow at 400 credits a day, about 25 investigations. These caps are `max-ai-credits`, `safe-outputs.threat-detection.max-ai-credits`, and `max-daily-ai-credits` in its source. Each run used 4 min 49 s to 6 min 0 s of runner time: 3.5 to 4.5 minutes on `ubuntu-latest` for Copilot and detection, and 1.1 to 1.6 on the single-CPU `ubuntu-slim` for the other four jobs. Those minutes are free in a public repository. In a private one, each job is rounded up to a whole minute, so each run counted 5 minutes of 2-core Linux and 4 of 1-core Linux ([runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing)).

## Files to edit to tweak it

The copy adds the agent, five skills, the proof and checks workflows, the CI failure investigation with its compiled lock file, and the issue form to your `.github/` folder, with the licence, `.github/LICENSE-ai-sdlc`, and the unit tests to `tests/`. The solution also relies on two files of your own: your CI workflow, which runs your tests on pull requests, as RequestHub's [`ci.yml`](../../.github/workflows/ci.yml) does, and `copilot-setup-steps.yml`, the cloud agent's environment. The scenarios, the lab patch, and the defect report stay behind, because they describe RequestHub's defect: use them as examples for yours.

### Edit to fit your code

Change what assumes RequestHub:

| File, under `.github/` | As shipped, for RequestHub | Change it to |
| --- | --- | --- |
| [`agents/test-github.agent.md`](.github/agents/test-github.agent.md) | How to start the API (`dotnet run --project app/src/RequestHub.Api`, port 5080), where the tests live (`app/tests/RequestHub.Tests/`: xUnit v3, `ApiFixture`, personas through `X-RequestHub-User`), how to run one test, and RequestHub's rules: approval authority, and the contract in `app/contracts/openapi.json` | Your start command and health URL, your test folder, framework, and fixtures, the command that runs one test, and the rules Copilot must never break in your code. Keep the order of the commits (the tests alone, then the fix) and the *Evidence* section. |
| [`skills/failure-reproduction/repro.py`](.github/skills/failure-reproduction/repro.py) | Development sign-in through the `X-RequestHub-User` header, and `--api` defaulting to `http://localhost:5080` | Your API's test sign-in and address. The scenario format stays. |
| [`skills/review-evidence/prove_fix.py`](.github/skills/review-evidence/prove_fix.py) | .NET and xUnit v3: `SOLUTION`, `DOTNET_TESTS`, `TEST_FILE`, `TEST_ATTRIBUTE`, `METHOD`, and `CLASS` find the tests a commit added, and `run_tests` runs them with `dotnet test`, whose xUnit v3 reporter writes a [CTRF](https://ctrf.io/) report | Your test folder, how a test method and its class start in your language, and a test command that runs the selected tests and writes a CTRF report. |
| [`skills/review-evidence/review_evidence.py`](.github/skills/review-evidence/review_evidence.py) | `CHECK_DEFINITIONS`: the folders that hold what this repository's workflows run (`.github/workflows/`, `.github/actions/`, `.github/skills/`, and `tools/`) | The folders that hold what yours run, so a pull request that changes them is flagged. `tests/test_review_evidence.py` expects these four: update it with yours. |
| [`skills/regression-validation/run_regression.py`](.github/skills/regression-validation/run_regression.py) | RequestHub's suites: the .NET build and tests, the web typecheck and unit tests, the contract check, and the Playwright tests with `--e2e` | Your suites. |
| [`skills/ci-investigation/ci_failure_facts.py`](.github/skills/ci-investigation/ci_failure_facts.py) | How a failure looks in the output of .NET's test platform with xUnit v3, Playwright, Vitest, and the C# and TypeScript compilers; `prove_fix.py`'s patterns tell whether the pull request adds or changes a test | How your test runners print a failure, if they print it differently. `tests/test_ci_investigation.py` has a sample of each format: add yours. |
| [`skills/contract-impact/`](.github/skills/contract-impact/) | An OpenAPI contract in `app/contracts/openapi.json` that may only grow | Your contract file, or delete the skill and its call in `run_regression.py`. |
| [`workflows/test-github-proof.yml`](.github/workflows/test-github-proof.yml) | Pull requests into `lab/test-**` that change `app/**`, a PostgreSQL service, and .NET 10 | The branches and paths of your fixes, your database service, and your toolchain: see [one-time step 3](#one-time-setup). |
| [`workflows/test-github-ci-investigation.md`](.github/workflows/test-github-ci-investigation.md) | Starts when the workflow named `CI`, in `.github/workflows/ci.yml`, fails on a pull request from a `copilot/**` or `fix/**` branch into a `lab/test-*` branch | Your CI workflow's name (`workflows:`) and file (`workflow_run.path` in the `if:`), the branches your fixes come from (`branches:`), and the branches they go into: `lab/test-` in the `if:` and `--base` in its step, for example `main`. Then compile it, in [one-time step 7](#one-time-setup). |
| [`workflows/test-github-checks.yml`](.github/workflows/test-github-checks.yml) | This solution's folder: it watches `solutions/04-test-github/**` and runs `solutions/04-test-github/tests`. It also compiles the CI failure investigation with the gh-aw version in `GH_AW_VERSION`, v1.2.2, and fails if the committed lock file differs | Watch `tests/**` and run `tests`. Keep `GH_AW_VERSION` at the version you compile with. |
| [`ISSUE_TEMPLATE/04-test-github-defect.yml`](.github/ISSUE_TEMPLATE/04-test-github-defect.yml) | The labels `ai-sdlc`, `phase:test`, and `bug` | Your labels, if you don't create these in [one-time step 4](#one-time-setup). |

### Edit to tune it

These settings change how the solution behaves, whatever your code:

| To change | Edit | As shipped |
| --- | --- | --- |
| The tools Copilot may use | `tools` in the front matter of [`agents/test-github.agent.md`](.github/agents/test-github.agent.md) | `read`, `edit`, `search`, and `execute` |
| What Copilot must never do | *Rules* in the same file | Only the code and tests the fix needs; no weakened, skipped, or deleted test, guard, or validation; no sleep, retry, or catch-all exception handler to hide a race; no approval, merge, or review evidence |
| What a defect Issue asks for | The fields of [`ISSUE_TEMPLATE/04-test-github-defect.yml`](.github/ISSUE_TEMPLATE/04-test-github-defect.yml) | *Observed behavior*, *Reproduce*, and *Expected behavior*, each required |
| How long the proof keeps both test outputs | `retention-days` in [`workflows/test-github-proof.yml`](.github/workflows/test-github-proof.yml) | 90 days |
| What the CI failure investigation may spend | `max-ai-credits`, `max-daily-ai-credits`, and `safe-outputs.threat-detection.max-ai-credits` in [`workflows/test-github-ci-investigation.md`](.github/workflows/test-github-ci-investigation.md), then compile it as in [one-time step 7](#one-time-setup) | 40 AI credits a run, 400 a day, and 2 a run for threat detection |

### What the copy adds

```text
.github/
├── agents/test-github.agent.md     the custom Copilot agent: reproduce, failing tests first, then the fix
├── skills/
│   ├── failure-reproduction/       repro.py runs a scenario against a running API
│   ├── review-evidence/            prove_fix.py (fails before, passes after) and review_evidence.py (the report)
│   ├── ci-investigation/           ci_failure_facts.py collects a failed CI run's facts; SKILL.md sorts them into three classes
│   ├── regression-validation/      runs the test suites that cover a change (shared with 03-develop-github)
│   └── contract-impact/            additive-only API contract check that regression-validation calls (shared)
├── workflows/
│   ├── test-github-proof.yml       proves the fix test-first on fix pull requests
│   ├── test-github-ci-investigation.md         the agentic workflow: explains why CI failed on a fix's pull request
│   ├── test-github-ci-investigation.lock.yml   what GitHub runs: compiled from the .md by gh-aw v1.2.2
│   └── test-github-checks.yml      runs the unit tests, and checks the lock file, on pull requests that change this solution
├── ISSUE_TEMPLATE/04-test-github-defect.yml
└── LICENSE-ai-sdlc                 the licence that travels with the files, added by the copy
tests/
├── test_review_evidence.py         unit tests: the evidence report never speaks for anyone else (offline, fake gh)
└── test_ci_investigation.py        unit tests: the CI investigation's facts, and the runs it must leave alone (offline, fake gh)
```

### After you edit

Run the unit tests as in [Getting started](#getting-started) step 3. After a change to the CI failure investigation's source, compile it as in [one-time step 7](#one-time-setup) and commit its `.lock.yml` with it. Then merge your change: custom agents, issue forms, and the CI failure investigation take effect from your default branch, and the proof runs its script from each pull request's base branch.

## Clean up

Remove what you copied, the labels, the token, and the services you added to `copilot-setup-steps.yml` only for this solution. Two skills are shared: 03-develop-github uses `regression-validation` and `contract-impact`, and 02-design-github uses `contract-impact`. If you required the proof's check in a ruleset ([one-time step 3](#one-time-setup)), remove it from the ruleset first.

```powershell
Remove-Item -Recurse -Force .github/agents/test-github.agent.md, .github/skills/failure-reproduction, .github/skills/review-evidence, .github/skills/ci-investigation, .github/workflows/test-github-proof.yml, .github/workflows/test-github-checks.yml, .github/workflows/test-github-ci-investigation.md, .github/workflows/test-github-ci-investigation.lock.yml, .github/ISSUE_TEMPLATE/04-test-github-defect.yml, tests/test_review_evidence.py, tests/test_ci_investigation.py
Remove-Item -Recurse -Force .github/skills/regression-validation, .github/skills/contract-impact    # unless another solution uses them
Remove-Item -Force .github/LICENSE-ai-sdlc    # unless you keep another solution from this repository
gh label delete phase:test --yes
gh label delete ci:defect-reproduced --yes
gh label delete ci:regression --yes
gh label delete ci:infrastructure --yes
gh label delete ai-sdlc --yes    # unless other Issues carry it
gh secret delete COPILOT_GITHUB_TOKEN    # unless another agentic workflow uses it
```

Then revoke the token: on GitHub, **Settings** → **Developer settings** → **Personal access tokens** → [**Fine-grained tokens**](https://github.com/settings/personal-access-tokens), delete `COPILOT_GITHUB_TOKEN`. The agentic workflows of [06-release-github](../06-release-github/) and [07-operate-github](../07-operate-github/) use the same secret: keep it if you use them.

This solution creates no GitHub App or webhook, and apart from the CI failure investigation's token, no secret: you act with your own GitHub CLI sign-in, and its workflows with the token GitHub gives each run.

## Troubleshooting

- **No checks on Copilot's pull request.** Workflows on pull requests from the cloud agent wait for a person. Select **Approve workflows to run**, or run `gh run rerun <run-id>`.
- **The runs of an earlier commit show as cancelled.** Approving the waiting runs of several commits starts them together, and the newest run in each concurrency group cancels the older ones. Approve the latest commit's runs; the proof still tests the tests-only commit.
- **The proof fails with *Not proven: no tests-only commit before the fix* on a pull request that isn't a fix.** The proof ran on a pull request into one of its `branches` that has no tests-only commit. Narrow `branches`, or guard the proof as in [one-time step 3](#one-time-setup).
- **The pull request description has no evidence.** Copilot sometimes writes its evidence summary only at the end of the session. Read it under **View session**, or ask `@copilot` to add it to the description.
- **`error: cannot reach http://localhost:5080`.** The API is not running yet, or runs on another port.
- **`gh aw compile` fails with *Unknown properties: report-missing-data, report-missing-tool*.** Your gh-aw is older than the workflow: v0.92.0 printed this when this README was checked. `gh aw version` must print `v1.2.2`, the version in `test-github-checks.yml`. Run `gh extension remove gh-aw`, then `gh extension install github/gh-aw --pin v1.2.2`, and compile again.
- **`gh aw compile --strict` fails with *CTR-021: [workflow-run-scope] workflow_run lacks positive branch scope*.** Strict mode refuses `branches: ["**"]` and negative-only patterns under `on.workflow_run`. Name the branches your fixes come from, such as `copilot/**` for Copilot's and `fix/**` for your own.
- **The links in the CI failure investigation's comment are broken, with `%60%60` in them.** With `allowed-github-references: []`, which keeps the comment from adding an item to any Issue's or pull request's timeline, gh-aw wraps everything shaped like a GitHub reference (`#123`, `owner/repo#123`) in a code span, inside links too. A link that ends in `…/RequestHub.Tests/RequestLifecycleTests.cs#L102` or `…/job/130606824425#step:6:1` has that shape: the first comes out as `…/RequestHub.%60%60Tests/RequestLifecycleTests.cs#L102%60%60`. `ci_failure_facts.py` puts a query before every `#` (`?plain=1#L102`, `?pr=359#step:6:1`), which the pattern can't match, and `tests/test_ci_investigation.py` runs gh-aw's pattern over every link the facts hold. If you change how the facts build a link, keep a query before its `#`.

## See it work

This run took place on 28 October 2026, from 14:44 to 16:31 UTC, on `main` at [`79f9d2c`](https://github.com/melabadi/adept-assessment-northstars/commit/c6b8055ddf71f4d848045619273d664ddb09c57e). The repository's owner started it and took every person's step; Copilot and GitHub Actions did the rest. The defect report became Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100), and Copilot's work became pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101). Every link below opens without signing in. The workflow runs' summaries and logs need a GitHub sign-in and expire, so the screenshots show them, and [`evidence/`](evidence/) keeps both proofs. Every screenshot comes from this run, except the recorded approval in step 8 and the screenshots of step 10, which come from the runs they describe.

| Step | When (UTC) | Who | How long |
| --- | --- | --- | --- |
| [1. The lab branch was rebuilt](#1-the-lab-branch-was-rebuilt-from-main) | 14:44 | Owner | seconds |
| [2. The scenario reproduced the defect](#2-the-scenario-reproduced-the-defect) | 14:48 | Owner | seconds per scenario run |
| [3. Copilot wrote the tests, then the fix](#3-copilot-committed-failing-tests-then-the-fix) | 14:44 to 14:59 | Owner, then Copilot | 13 min 24 s of Copilot's work |
| [4. A person approved the runs](#4-a-person-approved-the-workflow-runs) | 15:06 | Owner | 14 s |
| [5. The proof passed](#5-the-proof-showed-the-tests-failing-first) | 15:06 to 15:08 | GitHub Actions | 1 min 44 s |
| [6. Copilot code review](#6-copilot-code-review-found-a-gap-the-tests-missed) | 15:08 to 15:14 | Copilot | 6 min 14 s |
| [7. The evidence comment](#7-the-evidence-comment-kept-checks-apart-from-comments) | 15:22 | Owner | seconds |
| [8. The review loop](#8-a-person-asked-for-a-change-and-the-new-commit-passed-the-same-gates) | 15:22 to 16:04 | Owner, Copilot, GitHub Actions | 6 min 54 s from the request to Copilot's new commit |
| [9. Optional: Copilot CLI](#9-optional-copilot-cli-fixed-a-second-defect) | 15:23 to 15:41 | Owner, then Copilot CLI | 17 min 50 s |
| [10. Added since: the CI failure investigation](#10-added-since-an-agentic-workflow-explained-two-red-ci-runs-11-november-2026) | 11 November, 15:05 to 15:41 | Owner, GitHub Actions, Copilot | 5 min 44 s from CI's failure to the comment on #359 |

Steps 1 and 3 ran first, so Copilot was already working while step 2 reproduced the defect. Step 10 ran on 11 November, after the CI failure investigation was added.

### 1. The lab branch was rebuilt from main

The owner rebuilt `lab/test-duplicate-decision` from `main` plus [`lab/duplicate-decision.patch`](lab/duplicate-decision.patch), which removes the decision guards and the tests that cover them, and force-pushed it. The push landed at 14:44:20 UTC: [`df99c1b`](https://github.com/melabadi/adept-assessment-northstars/commit/df99c1b0e011fbe8d93178d5c1bde115e4357e50), one commit on top of `main`. The patch file stayed off the lab branch. Copilot could still read the code from before the defect commit, as an engineer would when a regression appears: what the run proves is the order of the evidence.

![The lab branch rebuilt: one commit on top of main, force-pushed as lab/test-duplicate-decision](images/01-lab-branch.png)

**What this shows:** the defect existed only on a lab branch built from that day's `main`, so `main` stayed healthy and the run can be repeated.

### 2. The scenario reproduced the defect

At 14:48 UTC, while Copilot worked on step 3, the owner replayed [`scenarios/duplicate-decision.json`](scenarios/duplicate-decision.json) with [`repro.py`](.github/skills/failure-reproduction/repro.py) against the API built from the lab branch: a retry with the same idempotency key, a second approver, and eight parallel clicks. Six of its nine steps failed:

![The scenario against the lab build: six of nine steps fail, and eight parallel approvals return 201 three times and 500 five times](images/02-reproduce.png)

Against the API built from `main`, the same scenario passed every step, so it is a fair oracle:

![The same scenario against main: every step behaves as expected](images/02-not-reproduced-on-main.png)

The two APIs ran side by side on ports 5092 and 5091, with `--api`, because the machine was shared. Each scenario run took seconds. This step ran on the owner's machine, so the screenshots are its record.

**What this shows:** a double-click of eight requests recorded three decisions and answered the rest with `500` (three `201`s and five `500`s; the split changes from run to run), where `main` returned one `201` and seven `409`s.

### 3. Copilot committed failing tests, then the fix

At 14:44:47 UTC the owner filed Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100) from [`duplicate-decision-issue.md`](duplicate-decision-issue.md). Five seconds later they assigned it to Copilot, with the `test-github` custom agent and the base branch `lab/test-duplicate-decision`. Copilot opened draft pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101) six seconds after the assignment:

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

**What this shows:** the tests landed in their own commits, touching only `app/tests/`, before any production code changed.

### 4. A person approved the workflow runs

Copilot's pushes started no workflow on their own: their runs waited for a person.

![The pull request's merge box: four workflows awaiting approval, with the Approve workflows to run button](images/04-approve-workflows.png)

At 15:06 UTC, 7 minutes after Copilot finished, the owner started the eight waiting runs of Copilot's two pushes with code, the tests and then the fix, from a terminal with `gh run rerun`, within 14 seconds. The runs of the earlier push were cancelled, because each shares a concurrency group with its counterpart on the latest push. Nobody approved the one run on Copilot's first commit, *Initial plan*: the feature bounds check, which ran again on the later commits. It waited until the pull request closed.

**What this shows:** no workflow ran on Copilot's commits until a person approved it.

### 5. The proof showed the tests failing first

The proof check, [`test-github-proof.yml`](.github/workflows/test-github-proof.yml), selected the tests that the tests-only commits added or changed, and ran them in clean worktrees at the tests-only commit `8de3d60fb` and at the head `a92d4b313`. It ran from 15:06:29 to 15:08:13 UTC: 1 minute 44 seconds. CI's full test suite passed at 15:10:26, after 3 minutes 52 seconds.

![The proof check's summary: 5 of 7 selected tests fail at the tests-only commit, and 7 of 7 pass at the head](images/05-proof-check.png)

Below the table, the summary listed each failure at the tests-only commit in the tests' own words:

![The failures at the tests-only commit, in the tests' words: a later decision gets Created instead of Conflict, a same-key retry gets Created instead of OK, and eight parallel clicks get no conflicts](images/05-proof-failures.png)

Two tests passed before the fix. Copilot's new `Requester_cannot_self_approve_after_another_approver_has_decided` guards a rule that already held: a requester can't decide their own request. `Search_treats_percent_and_underscore_as_literal_characters` was an existing test, the last in the file: the proof script of that day counted it as changed because Copilot added helper methods below it. [#135](https://github.com/melabadi/adept-assessment-northstars/pull/135) fixed that after the run: the script now ends each test where its method ends. The proof and both test reports are in [`evidence/proof-a92d4b313`](evidence/proof-a92d4b313/proof.md), copied from the run's artifact.

**What this shows:** the same tests failed at one known SHA, for the reasons the Issue describes, and passed at the next.

### 6. Copilot code review found a gap the tests missed

At 15:08:21 UTC the owner requested a review from Copilot. [Its review](https://github.com/melabadi/adept-assessment-northstars/pull/101#pullrequestreview-5685021802) arrived at 15:14:35, 6 minutes 14 seconds later: changes recommended, with [one high-severity finding](https://github.com/melabadi/adept-assessment-northstars/pull/101#discussion_r4402383848). If a request was rerouted to another department and decided while an approval was being saved, the recovery path could return that department's decision, comment included, to a caller who isn't allowed to see it.

![Copilot code review: changes recommended, with a high-severity finding that the concurrency recovery path can return another department's decision](images/06-copilot-review.png)

Copilot's own self-check in its session had found no issues.

**What this shows:** the review found an authorization gap that no test covered: a request rerouted between the access check and the save.

### 7. The evidence comment kept checks apart from comments

At 15:22:17 UTC the owner ran [`review_evidence.py`](.github/skills/review-evidence/review_evidence.py) `--pr 101 --comment` and posted [the evidence comment](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473019762). Section 1, *Deterministic acceptance*, lists the checks and the proof at two known SHAs (the image at the top of this README): it decides. Section 2, *Review comments*, lists Copilot's finding: it informs. Section 3, *Reviewer decision*, stayed pending, because nobody had approved or requested changes.

![The review comments and reviewer decision sections: Copilot's finding is listed, no comments does not mean correct, and the decision is pending](images/07-evidence-review.png)

These images show the comment after step 8 updated it at 16:04 UTC, so the head is the review-loop commit `e1d52334d`.

**What this shows:** what decides (the checks and the proof) was kept apart from what informs (the review comments).

### 8. A person asked for a change, and the new commit passed the same gates

At 15:22:37 UTC the owner [asked Copilot](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473028998), on the pull request, to address the review's finding:

```text
@copilot Please address the Copilot code review comment on `RequestWorkflow.cs`: in the concurrency recovery path, recheck department access for the reloaded request before returning its decision, and return `403 auth.department_forbidden` when access is denied. Add a regression test for this case. Give each new commit a message that says what it changes, and do not rewrite or squash the earlier commits.
```

Copilot started at 15:23:20 and pushed [`e1d5233`](https://github.com/melabadi/adept-assessment-northstars/pull/101/commits/e1d52334df6c372dcf44e7cec4965bfb180f54d5) at 15:29:31, 6 minutes 54 seconds after the request: the department check, and a deterministic race test in a new `DecisionRecoveryAuthorizationTests.cs`. It [replied](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6473266654) at 15:32:34 that all 64 API and worker tests passed.

![The review loop: the @copilot request, Copilot's new commit, and its reply that the authorization check and a deterministic race test were added](images/08-review-loop.png)

At 15:58 UTC the owner started the new commit's four waiting runs. The proof passed again in 1 minute 33 seconds, still 5 of 7 failing at `8de3d60fb` and now 7 of 7 passing at `e1d52334d` ([`evidence/proof-e1d52334d`](evidence/proof-e1d52334d/proof.md)), and CI passed in 2 minutes 49 seconds. At 16:04 the owner updated the evidence comment. Tests added after the fix are guards: CI runs them, and the proof keeps covering the tests committed before the fix.

The owner didn't record a GitHub review in this run, so the decision stayed pending. At 16:31 UTC they [closed the pull request without merging](https://github.com/melabadi/adept-assessment-northstars/pull/101#issuecomment-6474687761), as every run in this repository does, because the lab branch is rebuilt for the next one. In the run of 10 November 2026 (Issue [#299](https://github.com/melabadi/adept-assessment-northstars/issues/299), pull request [#300](https://github.com/melabadi/adept-assessment-northstars/pull/300)), the owner [approved](https://github.com/melabadi/adept-assessment-northstars/pull/300#pullrequestreview-5849409617) with a GitHub review, and [the evidence comment](https://github.com/melabadi/adept-assessment-northstars/pull/300#issuecomment-6779284427) recorded who decided:

![The evidence comment on pull request 300 after the owner's approving review: every check passes, 3 of 3 selected tests fail at the tests-only commit 78908821d and pass at the head 24bf08614, no Copilot code review was requested, and the reviewer decision reads approved, naming the proof and the load run](images/combo-05-decision-recorded.png)

**What this shows:** the reviewer's finding became code and a test within minutes and went through the same gates, while the decision stayed with a person.

### 9. Optional: Copilot CLI fixed a second defect

From 15:23:48 to 15:41:38 UTC, on the owner's machine, Copilot CLI ran the same `test-github` agent on a second defect: the lab build accepted a rejection whose comment was only spaces. Copilot reproduced it with [`scenarios/whitespace-rejection.json`](scenarios/whitespace-rejection.json) (`REPRODUCED: 2 step(s)`) and committed failing tests, then the fix. The session took 17 minutes 50 seconds and reported 25.48 AI credits. The local proof then selected the tests that the tests-only commits added:

![The local proof for the second defect: 4 of 4 selected tests fail at the tests-only commit and pass at the fix](images/09-local-proof.png)

Four of four failed at the tests-only commit `b9e90bb` and passed at the fix `e899718`. These commits stayed on the owner's machine, so the screenshot is this step's record.

**What this shows:** the same skills and the same proof worked on a different defect, from the terminal, with no pull request.

### 10. Added since: an agentic workflow explained two red CI runs (11 November 2026)

The CI failure investigation was added after the recorded run, so this step comes from a run of its own. At 15:05 UTC on 11 November 2026 the owner rebuilt the lab branch from `main` at [`640f3e5`](https://github.com/melabadi/adept-assessment-northstars/commit/640f3e5db13494d1af8d4b236b26f3f87f41f2df), as in step 1. At 15:07 they opened two pull requests into it from `fix/` branches:

- [#359](https://github.com/melabadi/adept-assessment-northstars/pull/359) added the three regression tests that the lab branch lacks, in [`42f4090`](https://github.com/melabadi/adept-assessment-northstars/pull/359/commits/42f40901d492c6d477066f6fbe74c518bc9588f0), without the fix: test-first, the way Copilot works.
- [#360](https://github.com/melabadi/adept-assessment-northstars/pull/360) fixed step 9's defect, the blank rejection comment, test-first: a new test in [`06ce023`](https://github.com/melabadi/adept-assessment-northstars/pull/360/commits/06ce0236c1f9c41358da9f55b9a59752d65394e6), then the fix in [`d0eee36`](https://github.com/melabadi/adept-assessment-northstars/pull/360/commits/d0eee36b2443996644d650b95d9f65bcbcf821f0). The fix also dropped the check that only a rejection needs a comment.

CI failed on both within a minute: three tests failed on #359, and four on #360. On #360 the proof passed, because its new test failed before the fix and passed after it. The proof reruns only the tests that a pull request adds; CI runs them all:

![The checks of pull request 360: in CI, the API and worker tests fail and the browser tests are skipped, while the proof, regression tests fail before the fix and pass after it, passes](images/10-ci-failed-proof-passed.png)

Within 4 seconds of each failure, GitHub queued a run of the investigation from `main`. A script collected the facts, Copilot sorted the failures, and threat detection checked the comment and the label before they were applied. On #359, Copilot found that all three failures were tests the pull request adds, failing as intended. It labeled the pull request `ci:defect-reproduced`, and for each test its next step was to fix the code, not the test:

![The investigation's comment on pull request 359, under the label ci:defect-reproduced: three tests this pull request adds fail as intended, each with its assertion message, its line, its log, and the next step](images/10-ci-investigation-defect-reproduced.png)

On #360, the four failures were existing tests that pass on main. Copilot labeled it `ci:regression` and traced the failures, in the diff, to the condition that the fix dropped. Approvals without a comment now got a 400, which also hid three authorization checks behind the validation error:

![The investigation's comment on pull request 360, under the label ci:regression: four existing tests fail with BadRequest, traced to the Rejected condition dropped in RequestWorkflow.cs, with the next step to restore it and leave the four tests unchanged](images/10-ci-investigation-regression.png)

The first comments, at 15:12 and 15:17 UTC, sorted every failure the same way, but their links to the lines and to the logs were broken (see [Troubleshooting](#troubleshooting)). [#361](https://github.com/melabadi/adept-assessment-northstars/pull/361) fixed the links, test-first, and at 15:22 the owner re-ran CI's failed job on both pull requests. The comments above come from those re-runs:

- on [#359](https://github.com/melabadi/adept-assessment-northstars/pull/359#issuecomment-6799930281) at 15:29:12, 5 minutes 44 seconds after CI failed;
- on [#360](https://github.com/melabadi/adept-assessment-northstars/pull/360#issuecomment-6800062263) at 15:34:46, 11 minutes 18 seconds after CI failed, 6 minutes 24 seconds of them spent waiting for the first run to end, because the runs go one at a time.

Each run used 13.3 to 15.2 AI credits for Copilot and 0.62 for threat detection ([the runs' evidence](evidence/ci-investigation-2026-11-11.md)).

At 15:33 the owner pushed the fix to #359, in [`ea02930`](https://github.com/melabadi/adept-assessment-northstars/pull/359/commits/ea029304a1c032e7147f8cf1bbd02fdacf2f4cae). CI and the proof passed by 15:35:44, and the investigation's run skipped every job, because nothing failed. The owner then closed both pull requests without merging.

**What this shows:** a red CI run arrives explained. The comment says which failures reproduce the defect on purpose and which are a regression the change caused, each with its line, its log, and the next step. On #360 the proof alone was green, and the investigation pointed at the line that broke four existing tests.

## Results and value

**What the run left behind:**

- Issue [#100](https://github.com/melabadi/adept-assessment-northstars/issues/100), closed as not planned, and pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101), closed without merging: Copilot's five commits (its plan, two tests-only commits, the fix, and the review-loop commit), Copilot code review's finding, Copilot's reply, and the evidence comment.
- Two proofs, both *Proven*, in [`evidence/`](evidence/): the same 5 of 7 tests failed at `8de3d60fb`, and 7 of 7 passed at `a92d4b313` and again at `e1d52334d`.
- The person's decisions: approving Copilot's workflow runs twice, and asking Copilot for a change after the review. No GitHub review was recorded, so the evidence comment's decision stayed pending; step 8 shows how the 10 November run recorded an approval.
- From step 10's run, on 11 November: pull requests [#359](https://github.com/melabadi/adept-assessment-northstars/pull/359) and [#360](https://github.com/melabadi/adept-assessment-northstars/pull/360), closed without merging, each with its label and the investigation's comment, and the runs' record in [`evidence/ci-investigation-2026-11-11.md`](evidence/ci-investigation-2026-11-11.md).

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
| CI failure investigation, from CI's failure to the comment (step 10, 11 November) | 4 min 50 s and 5 min 44 s; 9 min 59 s and 11 min 18 s for the two runs that waited for another to end |
| CI failure investigation, per run (step 10) | 13.3 to 15.2 AI credits for Copilot and 0.62 for threat detection; 4 min 49 s to 6 min 0 s of job time |

**What a team gets:**

- **Time.** Copilot wrote the failing tests and the fix unattended. The person's part was filing the Issue, approving the workflow runs, asking for one change, and reading the evidence.
- **Risk removed.** A fix can't arrive without at least one test that failed first: the proof names the tests that failed, at a known SHA. Races are tested, not assumed: eight parallel clicks must produce exactly one `201`, in the scenario and in the tests. The code review caught an authorization gap before anyone merged.
- **Evidence a reviewer or auditor can follow.** The evidence comment on the pull request gives the proof's verdict at two known SHAs and keeps the review comments apart from the checks. The test reports at both SHAs are in the proof run's artifact; artifacts expire, so keep the ones you need, as [`evidence/`](evidence/) does here. Once a person submits a review, the comment records who decided.
- **People stay in charge.** Workflows on Copilot's pull request run only after a person approves them, a person decides on the change, and RequestHub's own rule is untouched: only approvers decide, never on their own request.
- **A red CI run explained.** Minutes after CI fails, the pull request says which failures reproduce the defect on purpose and which are a regression the change caused, with the line, the log, and the next step for each. On #360 that was a dropped condition behind four failing tests, while the proof's check was green.

## Try it first in a copy of this repository

Optional: the same solution on RequestHub, before you adapt anything. You repeat the run in [See it work](#see-it-work) in your own copy, and it costs what [What it costs](#what-it-costs) lists for the recorded run.

The copy also has the files of this folder that belong to the demo: [`duplicate-decision-issue.md`](duplicate-decision-issue.md), the defect report that becomes the Issue Copilot receives; [`lab/duplicate-decision.patch`](lab/duplicate-decision.patch), the defect, which removes the decision guards and the tests that cover them; [`scenarios/duplicate-decision.json`](scenarios/duplicate-decision.json), the reported defect as data (a retry, a second approver, and eight parallel clicks), and [`scenarios/whitespace-rejection.json`](scenarios/whitespace-rejection.json), a second, smaller defect for the same procedure; [`evidence/`](evidence/), the recorded run's two proofs, and the CI failure investigation's runs of 11 November; and [`images/`](images/), the screenshots from the recorded run and from step 10's run.

### Quick start

About 2 minutes, from the root of your copy of this repository: the [root README](../../README.md#try-it-in-a-copy-of-this-repository) makes that copy, once for every solution. You need the [prerequisites](#prerequisites); the copy already holds the files, and RequestHub is the API and the tests, so there is nothing to copy or change. In PowerShell 7, create the labels: the two the defect's Issue uses, and the three the CI failure investigation chooses from (4 seconds when this README was checked):

```powershell
gh label create ai-sdlc --color 1D76DB --description "AI-SDLC demo work" --force
gh label create phase:test --color C5DEF5 --description "SDLC phase 4: Test" --force
gh label create ci:defect-reproduced --color 0E8A16 --description "CI failure investigation: tests this pull request adds fail as intended" --force
gh label create ci:regression --color B60205 --description "CI failure investigation: the change broke an existing test or check" --force
gh label create ci:infrastructure --color FBCA04 --description "CI failure investigation: fails on main too, or the failure isn't a test" --force
```

Then allow the Copilot cloud agent in your copy, as in the [prerequisites](#prerequisites). For the CI failure investigation, also store a `COPILOT_GITHUB_TOKEN` secret, as in [one-time step 6](#one-time-setup); the rest works without it. What you should see: `gh repo view --json nameWithOwner -q .nameWithOwner` prints your copy, the repository that every `gh` command below acts on; `gh label list --search phase:test` prints `phase:test  SDLC phase 4: Test  #C5DEF5` on its first line, and `gh label list --search ci:` lists the three `ci:` labels; on any Issue in your copy, **Assignees** lists **Copilot**; `gh secret list` lists `COPILOT_GITHUB_TOKEN`, if you stored it; and

```powershell
gh api 'repos/{owner}/{repo}/contents/.github/agents/test-github.agent.md' --jq .path
```

prints `.github/agents/test-github.agent.md`. The skills, the workflows, and the issue form are active too, because the copy's root `.github/` folder mirrors this solution's.

Steps 2 and 9 run RequestHub on your machine, so they need the [.NET 10 SDK](https://dotnet.microsoft.com/download) and PostgreSQL on `localhost:5432` (user `requesthub`, password `devpass`); the [app README](../../app/README.md#run-it-locally) has a one-line Docker command. Start PostgreSQL, and build the API once:

```powershell
dotnet build app/src/RequestHub.Api
```

What you should see: the build succeeds with no errors. A cold restore and build took 19 seconds when this README was checked; after it, the API starts in seconds.

### The steps

The steps have the numbers of [See it work](#see-it-work), which shows what each one looks like. Your SHAs, test names, and counts will differ, because Copilot writes new tests every time. Steps 1 and 3 take the longest to finish, so run them first and do step 2 while Copilot works, as the recorded run did.

| Step | How long it took in the recorded run |
| --- | --- |
| 1. Rebuild the lab branch | seconds: the push landed 12 s after the commit |
| 2. Reproduce the defect | seconds per scenario run |
| 3. Hand the defect to Copilot | 5 s to assign it; Copilot's session took 13 min 24 s (between 11 and 31 minutes across six runs) |
| 4. Approve the workflow runs | 14 s to start eight runs |
| 5. Watch the proof | the proof 1 min 44 s, CI 3 min 52 s |
| 6. Ask Copilot for a code review | the review 6 min 14 s |
| 7. Assemble the evidence | seconds: the script took 9 s on pull request #101 when this README was checked |
| 8. Decide, with a review loop | Copilot 6 min 54 s to a new commit, then the proof 1 min 33 s and CI 2 min 49 s |
| 9. Optional: a second defect with Copilot CLI | 17 min 50 s |
| 10. Optional: let CI fail, and read why | in the run of 11 November, CI failed within a minute, and the comment came 4 min 50 s to 5 min 44 s after it |

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

2. **Reproduce the defect.** Start the API from the lab branch in a second terminal, then run the scenario in the first:

   ```powershell
   dotnet run --project app/src/RequestHub.Api        # second terminal; http://localhost:5080
   python .github/skills/failure-reproduction/repro.py solutions/04-test-github/scenarios/duplicate-decision.json
   ```

   It ends with `REPRODUCED`. To check that the scenario is a fair oracle, run it against `main` too: stop the API (Ctrl+C), `git switch main`, start the API again, and rerun the scenario, which ends with `Not reproduced`. Switch back with `git switch lab/test-duplicate-decision`. See [step 2](#2-the-scenario-reproduced-the-defect).

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

6. **Ask Copilot for a code review.** In the pull request, select **Reviewers** > **Copilot**, or run `gh pr edit <pr> --add-reviewer "@copilot"`. You can do this right after step 4, so the review runs while the proof does. See [step 6](#6-copilot-code-review-found-a-gap-the-tests-missed).

7. **Assemble the evidence** and post it on the pull request. Run it from `main` or the lab branch, never from the pull request's branch:

   ```powershell
   python .github/skills/review-evidence/review_evidence.py --pr <pr> --comment
   ```

   [Use it the first time](#use-it-the-first-time), step 7, says what the report holds and why everything it quotes is inert. See [step 7](#7-the-evidence-comment-kept-checks-apart-from-comments).

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

10. **Optional: let CI fail, and read why.** This needs the `COPILOT_GITHUB_TOKEN` secret from the [quick start](#quick-start). Open a pull request from a `fix/` branch into the lab branch with the regression tests that the lab branch lacks, and no fix. `main`'s copy of the test file has them:

    ```powershell
    git fetch origin
    git switch -c fix/duplicate-decision origin/lab/test-duplicate-decision
    git checkout origin/main -- app/tests/RequestHub.Tests/RequestLifecycleTests.cs
    git commit -m "Add regression tests: a request is decided only once"
    git push -u origin fix/duplicate-decision
    gh pr create --base lab/test-duplicate-decision --title "Decide a request only once: regression tests first" --body "Regression tests first; the fix follows."
    ```

    CI fails within about a minute. About 5 minutes later, `gh pr view fix/duplicate-decision --json labels -q '.labels[].name'` prints `ci:defect-reproduced`, and the pull request's comment lists the three tests, each with its message, its line, its log, and the next step. Any change that breaks an existing test gets `ci:regression` instead, as #360 did. See [step 10](#10-added-since-an-agentic-workflow-explained-two-red-ci-runs-11-november-2026).

### Reset the copy for another run

```powershell
gh pr close <pr> --delete-branch --comment "Demo run: closed without merging."
gh issue close <issue> --reason "not planned"
git switch main
gh pr close fix/duplicate-decision --delete-branch --comment "Demo run: closed without merging."    # if you ran step 10
git branch -D test/whitespace-rejection    # if you ran step 9
```

Never merge Copilot's pull request in the copy: step 1 rebuilds the lab branch from `main` for the next run. What you should see: `gh pr list --base lab/test-duplicate-decision` prints nothing, and `gh issue list --label phase:test --state open` lists no Issue from the run.

When you no longer use this solution in the copy, delete the lab branch:

```powershell
git branch -D lab/test-duplicate-decision
git push origin --delete lab/test-duplicate-decision
```

When you no longer need the copy, the [root README](../../README.md#try-it-in-a-copy-of-this-repository) says how to delete it.

### Troubleshooting the copy

- **The feature bounds check on Copilot's *Initial plan* commit keeps waiting.** Nothing needs it: approve the latest commit's runs, which include the same check. When the pull request closes, GitHub marks the waiting run as failed, without running it.
- **Port 5080 or the `requesthub` database is already in use** (for example on a shared machine). Give the API its own: set `$env:ConnectionStrings__RequestHub = "Host=localhost;Port=5432;Database=rh_lab;Username=requesthub;Password=devpass"`, start it with `--urls http://localhost:5081`, and pass `--api http://localhost:5081` to `repro.py`. Tell Copilot CLI the same port and database in its prompt.
