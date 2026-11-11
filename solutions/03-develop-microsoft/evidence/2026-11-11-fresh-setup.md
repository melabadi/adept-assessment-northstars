# A fresh setup that followed only this README: 11 November 2026

On 11 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in the private copy that the fresh setups of [01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md) and [02-design-microsoft](../../02-design-microsoft/evidence/2026-11-11-fresh-setup.md) had used, and in a new azd environment, `ai-sdlc-develop-fresh`, so in a new resource group, `rg-ai-sdlc-develop-fresh`, with the group and its monitoring in Central US and everything else in East US 2. It ran the Quick start, the starting-state check, the seven steps, reset the copy, and cleaned up. The owner created the GitHub token.

Times are UTC. The copy of the repository is private, so its pull requests aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`, and the webhook's id as `<id>`.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, and Git 2.56.0.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. azd had no default subscription, and the README's `azd env new` already passes `--subscription`, so none was missing.
- `gpt-6-luna` Global Standard quota in East US 2: 500 of 1,000 thousand tokens per minute in use before the setup and again after the clean-up. The deployment takes 150.
- The copy's `main` was at `7a94d4b`, the change that 02-design-microsoft's step 1 had merged on top of [d20e654](https://github.com/melabadi/adept-assessment-northstars/commit/d20e654). The session took later updates as the root README says, which failed (finding 1), merged main at [4d53e96](https://github.com/melabadi/adept-assessment-northstars/commit/4d53e96), and pushed the copy's `main`, `334a6df`, before deploying anything: the Function reads the rule checker from the copy's `main`. No file of this solution changed between the two.
- The token, created by the owner on GitHub as the README's step 2 says, through the coordinating session: `ai-sdlc-develop-fresh`, for `<owner>/ai-sdlc` only, with Contents read-only and Pull requests read and write, expiring on 28 February 2027. The owner stored it with the README's `azd env set GITHUB_REVIEW_TOKEN (Read-Host -MaskInput 'Fine-grained token')`.
- The session ran its commands without a terminal, so azd and the GitHub CLI couldn't ask it questions.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 20:40:35 | Clone the copy | `git clone` | 12 s | |
| 20:40:54 | Take later updates (root README) | `git pull https://github.com/melabadi/adept-assessment-northstars.git main` | stopped after 1 s: `Need to specify how to reconcile divergent branches` | |
| 20:41:30 | Take later updates | `git pull --no-rebase --no-edit …` | 1 s | |
| 20:41:36 | Push them to the copy (not in the README) | `git push origin main` | 2 s | |
| 20:41:58 | Quick start | `azd env new ai-sdlc-develop-fresh --location centralus --subscription (az account show --query id -o tsv)` | 3 s, before `pip install`, so the owner could store the token meanwhile | |
| 20:42:21 | A virtual environment (not in the README) | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 17 s | |
| 20:42:39 | Quick start | `pip install -r requirements.txt` | 2 min 17 s | |
| 20:45 | 2. Create the reviewer's GitHub token | on GitHub, by the owner | stored by 21:08 | |
| 20:59:28 | Quick start | `azd up` | stopped after 17 s: `missing required inputs` | |
| 21:00:01 | Quick start, before the token was stored | `azd up`, with `main.bicep` fixed | 4 min 43 s; azd counted 4 min 31 s: 3 min 12 s provisioning, 1 min 18 s deploying | |
| 21:05:38 | Quick start | `python eval_reviewer.py --setup` | 2 min 0 s | 2 min 7 s on 10 November |
| 21:09:17 | Quick start, with the token, and a check of the `azure.yaml` fix | `azd up` again | 2 min 34 s; azd counted 2 min 21 s: 1 min 49 s provisioning, 32 s deploying | |
| 21:12:12 | Quick start | `python eval_reviewer.py --cases admins-decide --local` | 2 min 17 s; the dry run took 134 s | 196 s on 10 November |
| 21:14:40 | Check the starting state | the README's four lines | 9 s | about 10 seconds |
| 21:15:11 | 1. Open the pull request | `git fetch` to `gh pr create` | 6 s; pull request #20 opened at 21:15:15, 2 s after the commit | under a minute |
| 21:15:26 | 2. Ask for a review | `gh pr edit --add-label review:azure` | 2 s; the Function answered GitHub in 1.19 s | a few seconds |
| 21:15:28 | 3. Watch the Function work | the README's log query, from the terminal | the review was posted at 21:17:52, 2 min 26 s after the label | 2 to 4 minutes |
| 21:18 | 4. Read the review | `gh pr view --json reviews --jq '.reviews[-1].body'` | 2 s | a few minutes |
| 21:19 | 5. Open the agent and its traces | `python publish_reviewer_agent.py --show`, and an Application Insights query instead of the portal | 5 s, and seconds | a few minutes |
| 21:19:37 | 6. Push a fix | `git apply` to `git push` | 4 s; the review was posted at 21:22:01, 2 min 24 s after the commit | 2 to 4 minutes |
| 21:23:00 | 7. Measure the reviewer | `python eval_reviewer.py` | 8 min 43 s, graded once | about 9 minutes |
| 21:31:55 | 7. Measure the reviewer | `python eval_reviewer.py --check-graders --local` | 1 s | about a second |
| 21:31:56 | 7. Measure the reviewer | `python eval_reviewer.py --check-graders` | 3 min 36 s, graded once | 3 to 8 minutes per grading |
| 21:33:18 | Reset the copy | the README's two lines | 4 s | |
| 21:37:07 | Clean up: the evaluation's branches | `python eval_reviewer.py --cleanup` | 38 s | |
| 21:37:54 | Not in the README | delete the Microsoft Entra objects that Foundry created, with [#374](https://github.com/melabadi/adept-assessment-northstars/pull/374)'s lines | 12 s; two of the four deletions refused | |
| 21:38:49 | Clean up: Azure | `azd down --purge` | stopped after 21 s at its question, after its predown hook had deleted the webhook | |
| 21:39:31 | Clean up: Azure | `azd down --purge --force` | 4 min 16 s; azd counted 4 min 9 s | |
| 21:44 | Clean up: the label | `gh label delete "review:azure"` | stopped at once: `--yes required when not running interactively`; with `--yes`, 2 s | |

**The one-time setup's commands took 14 minutes 26 seconds in all**, from `azd env new` to the end of the dry run, besides the wait for the owner's token: 11 minutes 36 seconds without the `azd up` that stopped and the second `azd up` that the token needed. The README said about 30 minutes. **The seven steps took 20 minutes 22 seconds**, from step 1's `git fetch` at 21:15:11 to the end of the last grading at 21:35:33: 6 minutes 50 seconds to the second review, then 12 minutes 33 seconds for step 7. The README said about 40 minutes, which includes reading the reviews and opening the Foundry portal.

## What didn't match the README, and what changed

**1. The root README's command for later updates failed on the copy.** `git pull https://github.com/melabadi/adept-assessment-northstars.git main` stopped after the fetch:

```text
hint: You have divergent branches and need to specify how to reconcile them.
...
fatal: Need to specify how to reconcile divergent branches.
```

The copy's `main` had a commit of its own, the one 02-design-microsoft's step 1 merges, and git, with neither `pull.rebase` nor `pull.ff` set, won't choose between a merge and a rebase. `git pull --no-rebase --no-edit …` merged main at 4d53e96 with the default message. The root README's [Try it in a copy of this repository](../../../README.md#try-it-in-a-copy-of-this-repository) now gives that command, followed by `git push`, which it didn't mention: the Function reads the rule checker from the copy's `main` on GitHub, and 02-design-microsoft's standards runs read the standards from it, so updates pulled into a clone change nothing in Azure until they're pushed. For a copy whose ruleset refuses a push to `main`, as the settings for a public copy do, it gives a pull request merged with a merge commit instead; the session's private copy has no such ruleset, so that route wasn't run. The push started *Repository checks* (see [Also seen](#also-seen-and-left-as-they-are)).

**2. `azd up` stopped before its first hook.** As in [02-design-microsoft's fresh setup](../../02-design-microsoft/evidence/2026-11-11-fresh-setup.md), it printed `Initialize bicep provider`, then:

```text
ERROR: missing required inputs

──────────────────────────────────────────────────────────────
Provision cannot continue (interactive prompts disabled)
──────────────────────────────────────────────────────────────

1 required input is missing.

Missing required inputs:

• githubRepository
    Environment variable: GITHUB_REPOSITORY
    Environment configuration key: infra.parameters.githubRepository
    Type: string
    Constraints:
        Min length: 3
    Description: GitHub repository (owner/name) whose pull requests are reviewed. Set it with `azd env set GITHUB_REPOSITORY`.
```

azd checks the Bicep parameters before it runs any hook, and the `preprovision` hook that finds the repository hadn't run. [`infra/main.bicep`](../infra/main.bicep) now gives `githubRepository` an empty default, with a comment saying why. Bicep refuses an empty default under `@minLength(3)` (error BCP333), so that check moved to the hook, which sets the value: [`configure_github.py`](../configure_github.py) `prepare` now stops azd unless it names the repository as owner/name, and a test in [`test_configure_github.py`](../test_configure_github.py) shows that it stores nothing then. The parameter's description now says the hook sets it. With the fix, `azd up` ran the hook, which found the copy from `gh repo view`, and the Function reviewed the copy's pull request below. The README's Troubleshooting names the error.

**3. `azd up` showed nothing that its hooks printed.** The first `azd up` that provisioned showed only `Running predeploy hook...` and `Running postdeploy hook...`: not the repository, not the published agent, not the unit tests, and not the warning that the token wasn't set, which the README promises ("Without the token, `azd up` still deploys everything and warns you"). The hooks did run: the environment held `GITHUB_REPOSITORY` and the webhook secret, Foundry held `requesthub-pr-reviewer` version 1, and the copy had the `review:azure` label and, without the token, no webhook. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds. [`azure.yaml`](../azure.yaml) now makes all five hooks interactive. The `azd up` at 21:09, with that change and the token stored, printed every line the README describes:

```text
GitHub repository: <owner>/ai-sdlc
Webhook secret: already set.
Initialize bicep provider
Creating a deployment plan
Comparing deployment state
Validating deployment
Creating/Updating resources
...
  (✓) Done: Function App: func-<token> (2.602s)
unchanged: requesthub-pr-reviewer v1 (model gpt-6-luna)
Running predeploy hook...
----------------------------------------------------------------------
Ran 50 tests in 0.377s

OK
  reviewer: Publishing
  reviewer: Deploying
...
Running postdeploy hook...
Label review:azure in <owner>/ai-sdlc: ready.
GITHUB_REVIEW_TOKEN: GitHub accepts it for <owner>/ai-sdlc; it expires 2027-02-28 05:00:00 UTC.
The reviewer's Function refuses unsigned deliveries, as it should.
Webhook <id> in <owner>/ai-sdlc: signed pull_request events → the reviewer's Function (created).
...
SUCCESS: Your application was provisioned and deployed to Azure in 2 minutes 21 seconds.
```

The agent was `unchanged` because the first `azd up` had published it; the script prints `published new version: requesthub-pr-reviewer v1 (model gpt-6-luna)` then, as the README says. The predeploy hook's `OK` is now in the README too, and a Troubleshooting entry explains the pane.

**4. Publishing the agent created Microsoft Entra objects that `azd down` doesn't remove.** The README said the solution creates no Microsoft Entra app registration. When the postprovision hook published the agent, at 21:03, Foundry created two agent identity blueprints, which are app registrations, each with an agent identity, a service principal:

- for the agent, `aif-<token>-develop-requesthub-pr-reviewer-<hex>-AgentIdentityBlueprint`, owned by the person who ran `azd up` and by the project's managed identity, and `aif-<token>-develop-requesthub-pr-reviewer-AgentIdentity`;
- for the project, a shared pair, `aif-<token>-develop-AgentIdentityBlueprint`, owned by the project's managed identity alone, and `aif-<token>-develop-AgentIdentity`, which Foundry keeps for agents that predate per-agent identities ([agent identities in Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity)).

Before `azd down`, the session ran the lines that [#374](https://github.com/melabadi/adept-assessment-northstars/pull/374) and [#375](https://github.com/melabadi/adept-assessment-northstars/pull/375) added to 01's and 02's Clean up, which select every object whose name starts with the account's name. They deleted the agent's identity and blueprint. Entra refused both deletions of the project's pair, `Authorization_RequestDenied` and `Insufficient privileges to complete the operation`: the session's account didn't own them and had no Entra role that manages applications. `azd down` then deleted the project, and with it the shared pair, as Microsoft Learn says ("deleting the Foundry project removes its shared agent blueprint and identity"): at 21:45, neither was in Entra, nor in its recycle bin. [Clean up](../README.md#clean-up) now deletes the agent's two objects by the agent's name, before `azd down`, which forgets the account's name, and says why the project's pair needs nothing. The session also purged the agent identity and the blueprint's app registration from the recycle bin; Entra refused to purge the blueprint's principal (`Authorization_RequestDenied`), as it did in 02's fresh setup, so it stays there until the 30 days are over.

**5. `azd down --purge` deleted the webhook before it asked.** Without a terminal, it listed the resources it would delete, asked to confirm, got no answer, and stopped: `ERROR: deleting infrastructure: error deleting Azure resources: user denied delete confirmation`. By then its predown hook had already deleted the webhook: had a person answered no, the Function would have stayed deployed with nothing calling it. `azd down --purge --force` then removed everything, and its predown hook printed `No webhook to the reviewer's Function found in <owner>/ai-sdlc: nothing to remove.` Clean up now gives `--force`, says that azd asks without it, and says that `azd hooks run postdeploy` connects GitHub again after a no.

**6. CI's browser tests failed on the demo's first commit.** The README's See it work said of that change: "Every test still passes." The sandbox runs the API integration tests and the web UI's typecheck and unit tests, and all of them passed: 67 of 67 and 14 of 14. But in the copy, CI ran on both commits of pull request #20, and on the first, `09a7999`, its *Browser tests* job failed, on the first try and on the retry:

```text
✘  3 [chromium] › e2e/requesthub.spec.ts:53:3 › RequestHub in Development auth mode › Hugo opening his own REQ-1024 sees the self-approval message and no Approve button (10.7s)
    Error: expect(locator).toContainText(expected) failed
    Expected substring: "You can't approve or reject your own request."
    Received string:    "DecisionDecision commentOptional to approve, required to reject. The requester can read it.0 / 2,000 charactersApproveReject"
```

The same test failed on See it work's first commit, 4f351a5, on 31 October ([CI run](https://github.com/melabadi/adept-assessment-northstars/actions/runs/41168011967)). Step 1 of See it work now says that the API and web unit tests pass and that one browser test, which runs in CI and not in the sandbox, failed; its *What this shows* and *Risk removed* say "its unit and integration tests" and "its API and web unit tests" instead of every test.

**7. Other solutions' workflows saw this run's pull request and comment.** In the copy, every solution's workflows are active. Each of pull request #20's two commits started CI (API and worker tests, Web UI checks, and Browser tests: 3 min 15 s on the first commit, which failed as above, and 3 min on the second, which passed), *Develop · GitHub · feature bounds* (13 and 9 s, green), and *Operate · GitHub · prove the regression test* (10 and 13 s, its proof job skipped). The reset's comment started *Design · GitHub · agentic design review*, which its 19-second pre-activation job stopped. *Test · GitHub · agentic CI failure investigation* watches only `copilot/**` and `fix/**` branches, so CI's failure didn't start it. The ten evaluation pull requests, whose commits are marked `[skip ci]`, started nothing. No model ran in GitHub. *Try it first* now says so.

**8. Smaller.** `gh label delete "review:azure"` asks to confirm, and without a terminal stops with `--yes required when not running interactively`; Clean up now says it asks. The token stays in the local azd environment after the clean-up; Clean up now removes it with `azd env set GITHUB_REVIEW_TOKEN ''`, as 01-plan-microsoft's does. *Prerequisites* gained the quota check, and the README's estimates gave way to the times above.

## Also seen, and left as they are

- **The push of `main` started *Repository checks*, which never ran.** Its run stayed `queued` with no job for over an hour, while the demo's workflows ran within seconds. GitHub refused to cancel it, saying both that it was completed and that it hadn't been queued yet. It has nothing to do with this solution.
- **azd's progress list leaves out the two session pools**, `judgepool` and `runpool`, though it creates them: `az resource list` showed both in East US 2.
- **The deliveries' response bodies.** The README sends you to the webhook's **Recent Deliveries** page; through the API, `gh` listed the deliveries and their status codes but needed the `admin:repo_hook` scope to show a body. The Function's log has the same facts.
- **Step 3's commands name `rg-ai-sdlc-develop`,** the group of the README's environment; the session used its own, `rg-ai-sdlc-develop-fresh`.
- **The agent rated the second review's point higher than in See it work.** It raised the title and description's promise of a self-approval path that the diff no longer has as a ❗ concern, where version 4 on `gpt-5.4-mini` had raised it as a ⚠️ warning.

## The run

The starting-state check printed nothing for the two GitHub lines, then:

```text
Label review:azure in <owner>/ai-sdlc: ready.
GITHUB_REVIEW_TOKEN: GitHub accepts it for <owner>/ai-sdlc; it expires 2027-02-28 05:00:00 UTC.
The reviewer's Function refuses unsigned deliveries, as it should.
Webhook <id> in <owner>/ai-sdlc: signed pull_request events → the reviewer's Function (updated).
```

**Steps 1 and 2.** Commit `09a7999` at 21:15:13, pull request #20 at 21:15:15, the label at 21:15:26, by GitHub's clock. The webhook's deliveries: `opened` at 21:15:18, answered 200 in 0.5 s (no label yet, so nothing was queued), and `labeled` at 21:15:28, answered 202 in 1.19 s.

**Step 3.** The README's log query, run from the terminal:

```text
21:15:28 | review f5907c93c2c3: #20 queued (pull_request.labeled)
21:15:30 | review f5907c93c2c3: #20 at 09a7999
21:15:37 | review f5907c93c2c3: the rule checker from main read both trees in the judge's session in 2 s: 1 of 5 rules failed
21:15:38 | review f5907c93c2c3: the pull request's code runs only now, in its own session: build and tests started
21:17:39 | review f5907c93c2c3: build and tests: API 67 of 67 passed, web 14 of 14 passed in 1 min 43 s
21:17:51 | review f5907c93c2c3: agent requesthub-pr-reviewer v1 answered in 12 s (completed, 2 sandbox commands)
21:17:52 | review f5907c93c2c3: posted a COMMENT review on 09a7999
21:17:53 | review f5907c93c2c3: done in 2 min 23 s; sessions deleted
```

**Step 4.** The review, a COMMENT from the token's owner at 21:17:52: *Team rules: ❌ 1 of 5 failed*, *Approval authority is untouched* with `DecideAsync` and `PermissionsFor` differing from the base, the other four passing; in the sandbox, 67 of 67 API integration tests and 14 of 14 web unit tests, toolchain setup 21 s, 1 min 43 s in all; and the commentary of `requesthub-pr-reviewer` v1 on `gpt-6-luna`, after 2 read-only commands in the sandbox. Its ❗ concern, on `RequestWorkflow.cs` line 257, said that low-priority self-decisions allow either outcome, so a requester can also reject their own request; its ⚠️ warning said that the updated test covers only self-approval. It ended: *Consider whether the policy exception should cover rejection as well as approval, and assess the reported approval-authority FAIL.*

**Step 5.** `python publish_reviewer_agent.py --show` printed the definition, the model `gpt-6-luna` and the `runInSandbox` tool, with the run pool's endpoint masked. The answer's trace, read from the Application Insights resource connected to the Foundry project, the data the agent's **Traces** tab shows: the agent run took 8.3 s, with two `runInSandbox` calls of 1.4 and 1.1 s and a final model call of 2.7 s.

**Step 6.** Commit `9d29e32` at 21:19:37, pushed at 21:19:41; the `synchronize` delivery at 21:19:46 was answered 202 in 4.3 s. The log:

```text
21:19:45 | review bebd90f865e4: #20 queued (pull_request.synchronize)
21:19:59 | review bebd90f865e4: #20 at 9d29e32
21:20:05 | review bebd90f865e4: the rule checker from main read both trees in the judge's session in 3 s: all 5 rules passed
21:20:06 | review bebd90f865e4: the pull request's code runs only now, in its own session: build and tests started
21:21:47 | review bebd90f865e4: build and tests: API 68 of 68 passed, web 14 of 14 passed in 1 min 33 s
21:21:59 | review bebd90f865e4: agent requesthub-pr-reviewer v1 answered in 13 s (completed, 2 sandbox commands)
21:22:01 | review bebd90f865e4: posted a COMMENT review on 9d29e32
21:22:02 | review bebd90f865e4: done in 2 min 04 s; sessions deleted
```

The second review: all five rules passed, *Approval authority is untouched* with `DecideAsync` and `PermissionsFor` unchanged; 68 of 68 API and 14 of 14 web tests; and a ❗ concern that the title and description promise a low-priority self-approval path that the diff, which only adds a test, doesn't contain, for the person to decide.

**The reset** closed pull request #20 with the README's comment at 21:33:18 and deleted its branch on GitHub and in the clone.

## The evaluation

The Quick start's dry run, at 21:12:12: `admins-decide` (#12) Succeeded in 134 s, and passed all five checks.

`python eval_reviewer.py`, at 21:23:00, its first and only run:

```text
Dry-running the reviewer on 10 labelled cases in <owner>/ai-sdlc, 4 at a time:
  admins-decide          #12    Succeeded   132 s
  confirm-routing        #10    Succeeded   134 s
  literal-wildcards      #13    Succeeded   134 s
  first-decision-wins    #11    Succeeded   147 s
  sql-concatenation      #15    Succeeded   122 s
  parameterized-search   #16    Succeeded   122 s
  load-test-cleanup      #14    Succeeded   127 s
  delivery-timeout       #17    Succeeded   123 s
  index-no-cache         #19    Succeeded   122 s
  token-reuse            #18    Succeeded   123 s

Case                  PR   Kind        rule_verdicts  verdicts_verbatim  advisory_only  useful_commentary  sandbox_ran  Dry run
confirm-routing       #10  known-good  pass           pass               pass           pass               pass         Succeeded
first-decision-wins   #11  flagged     pass           pass               pass           pass               pass         Succeeded
admins-decide         #12  known-bad   pass           pass               pass           pass               pass         Succeeded
literal-wildcards     #13  known-good  pass           pass               pass           pass               pass         Succeeded
load-test-cleanup     #14  flagged     pass           pass               pass           pass               pass         Succeeded
sql-concatenation     #15  known-bad   pass           pass               pass           pass               pass         Succeeded
parameterized-search  #16  known-good  pass           pass               pass           pass               pass         Succeeded
delivery-timeout      #17  known-good  pass           pass               pass           pass               pass         Succeeded
token-reuse           #18  known-good  pass           pass               pass           pass               pass         Succeeded
index-no-cache        #19  known-good  pass           pass               pass           pass               pass         Succeeded
Passed                                 10/10          10/10              10/10          10/10              10/10
...
  Foundry evaluation run started: 10 labelled pull requests · agent v1 · 2026-11-11 21:29 UTC
  Foundry evaluation run completed.
    pr_review_rule_verdicts                  passed 10, failed 0
    pr_review_verdicts_verbatim              passed 10, failed 0
    pr_review_advisory_only                  passed 10, failed 0
    pr_review_useful_commentary              passed 10, failed 0
    pr_review_sandbox_ran                    passed 10, failed 0
```

It exited with 0 after 8 min 43 s: every check passed on every case, on the session's machine and in Foundry, which graded once. `python eval_reviewer.py --check-graders --local` graded the 26 fixed reviews as See it work describes, paired 13 of 13 and held-out 11 of 13, with the two known misses; `python eval_reviewer.py --check-graders` then had Foundry grade them once, the same way as the local checks, and exited with 0.

The agent's model use, read from the project's Responses API with [the method of the 11 November evaluation](2026-11-11-evaluation.md#the-agents-model-use):

| Answers | Tokens in (cached) | Tokens out |
| --- | --- | --- |
| The Quick start's dry run | 2,694 (0) | 648 |
| The two reviews | 7,741 (2,488) | 1,456 |
| The evaluation's ten dry runs | 62,394 (12,440) | 6,354 |

## The clean-up, and what is left

`python eval_reviewer.py --cleanup` closed the ten pull requests, which were already closed, deleted their twenty branches, and emptied `REVIEWER_EVAL_PRS`. The Entra lines and both runs of `azd down` are in findings 4 and 5. `azd down --purge --force` purged the Log Analytics workspace `log-<token>`, deleted the resource group, then purged the Key Vault `kv-<token>` and the Foundry account `aif-<token>`, and ended with `SUCCESS: Your application was removed from Azure in 4 minutes 9 seconds.`

Checked between 21:44 and 21:47:

- `az group exists -n rg-ai-sdlc-develop-fresh`: `false`.
- `az cognitiveservices account list-deleted`, `az keyvault list-deleted`, and `az monitor log-analytics workspace list-deleted-workspaces`: empty.
- No resource tagged `azd-env-name=ai-sdlc-develop-fresh`, and none named with the setup's token, anywhere in the subscription, and no session pool listed in the group.
- No role assignment whose scope names the group. The template assigns every role inside the group.
- In Microsoft Entra ID, nothing named after the Foundry account, and in its recycle bin only the agent blueprint's principal, which Entra refuses to purge (finding 4).
- No webhook in the copy, no branch but `main`, no open pull request, and no `review:azure` label.
- `gpt-6-luna` quota in use: back to 500.
- The local azd environment no longer holds the token.

What is left:

- **Three deployment records** at subscription scope, as for every azd deployment: those of the two `azd up` runs that provisioned, and the empty one that `azd down` records. They cost nothing. Their `githubToken` and `githubWebhookSecret` parameters keep only their type, `SecureString`, and no value.
- **The agent blueprint's principal,** in Entra's recycle bin until it removes it, 30 days after 21:38.
- **The GitHub token** `ai-sdlc-develop-fresh`, which can only read the copy's code and read and write its pull requests. The owner chose to keep it until it expires, on 28 February 2027. Nothing uses it: the Key Vault that held it was purged, and neither the azd environment nor the copy's webhooks have it.
- **In the copy,** `main` at `334a6df`, the closed pull requests #10 to #20, and the *Repository checks* run that never left the queue.

## What it cost

The resource group existed from 21:00 until azd deleted it, between 21:39 and 21:43: about 43 minutes. At list prices:

- the model tokens of the 13 answers: about $0.012 at `gpt-6-luna`'s $0.10 per million input and $0.50 per million output tokens;
- the 26 sandbox sessions of the 13 reviews and dry runs, at the $0.03 per session of [What it costs](../README.md#what-it-costs): about $0.78;
- the three private endpoints, at $0.01 an hour each: about 2 cents;
- the Function on Flex Consumption: 13 reviews and dry runs, inside the monthly free grant;
- the two Foundry gradings, whose code-based evaluators call no model, and storage, Key Vault, Application Insights, and Log Analytics: cents at most;
- the three private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1.50 if it bills each a whole month.

So between about 85 cents and about $2.35. In GitHub Actions, the copy ran 11 jobs for 7.9 minutes, 15 minutes as billed in a private repository, where each job counts as at least a minute: the two CI runs, two each of feature bounds and of the regression proof's first job, and the design review's pre-activation job.
