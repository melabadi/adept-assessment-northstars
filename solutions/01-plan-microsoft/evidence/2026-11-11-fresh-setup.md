# A fresh setup that followed only this README: 11 November 2026

On 11 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in a new private copy of the repository made from main at [7a8eb1f](https://github.com/melabadi/adept-assessment-northstars/commit/7a8eb1f), and in a new azd environment, `ai-sdlc-plan-fresh`, so in a new resource group, `rg-ai-sdlc-plan-fresh`, in East US 2. It ran the starting-state check and one run, reset the copy, and cleaned up. The owner created the GitHub token.

Times are UTC. `runs.py` prints local time, UTC−5 that day. The copy is private, so its Issues aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, and GitHub CLI 2.103.3.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. The Azure account sees 87 subscriptions, and azd had no default subscription.
- `gpt-6-luna` Global Standard quota in East US 2: 500 of 1,000 thousand tokens per minute in use before the setup, 550 while it was deployed, and 500 again after the clean-up.
- The session ran its commands without a terminal, so azd couldn't ask it questions. Two of the findings below come from that.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 17:36 | Make the copy (root README) | `git clone`, then `gh repo create <owner>/ai-sdlc --private --source . --push` | 20 s | about 2 minutes |
| 17:36:37 | The push's workflows (root README) | | only Repository checks ran: 15 s | the four push workflows, about 5 minutes |
| 17:41:04 | Clone the copy | `git clone` | 6 s | |
| 17:41:51 | A virtual environment (not in the README) | `python -m venv .venv`, then `.venv\Scripts\Activate.ps1` | 19 s | |
| 17:42:10 | 1. Deploy | `pip install -r requirements.txt` | 2 min 2 s | |
| 17:44:28 | 1. Deploy | `azd env new ai-sdlc-plan-fresh --location eastus2` | 1 s | |
| 17:45:24 | 1. Deploy | `azd up` | 5 min 10 s; azd counted 4 min 57 s: 3 min 44 s provisioning (2 min 22 s of it the Bicep deployment), 1 min 12 s deploying | |
| 17:52 | 2. Create the GitHub token | on GitHub, by the owner | about 3 minutes, including the request to the owner | |
| 17:55:53 | 3. Give the token to the Function app | `azd provision` | 2 min 23 s; azd counted 1 min 58 s | |
| 17:58:15 | 3. Give the token to the Function app | `python runs.py status` | 14 s | |
| 17:59:04 | 4. Create the approval label | `gh label create brief-approved --color 0e8a16 --force` | 1 s | |
| 17:59:20 | Check the starting state | the README's three lines | 39 s | about a minute |
| 18:00:11 | Start the run | `python runs.py start` | queued 14 s after the command | seconds |
| 18:00:37 | Watch the draft | | 46 s | 34 to 64 seconds |
| 18:01:25 | Watch the evaluation | | 95 s, first attempt | 77 to 107 seconds |
| 18:02:59 | Read the review Issue | `gh issue list --label type:brief --state open` | opened 2 min 34 s after the start | 2¼ to 2¾ minutes after the start |
| 18:03:30 | Approve | `gh issue edit 1 --add-label brief-approved` | the Function app saw the label 30 s later | up to 30 seconds |
| 18:04:21 | Open the backlog | `gh issue view 1 --comments` | review Issue closed 51 s after the label | 20 to 51 seconds after the label |
| 18:04 | Read the run's record | `python runs.py show 20261111-180025-831c` | 11 s | seconds |
| 18:05:26 | Reset the copy | the README's two lines | 25 s | |
| 18:09:20 | Clean up | `azd down --purge` | stopped after 17 s at its question | |
| 18:09:47 | Clean up | `azd down --purge --force` | 4 min 59 s; azd counted 4 min 54 s | |
| 18:15:14 | Clean up | `azd env set PLAN_GITHUB_TOKEN ''` | 1 s | |

**The one-time setup took 13 minutes:** 10 minutes of commands, from `pip install` to the label, and about 3 minutes for the owner to create the token. With the session's own checks between steps, it ran from 17:41:51 to 17:59:05. **The run took 3 minutes 56 seconds** from its start to the closed review Issue, 31 seconds of them the review. Steps 1 and 2 of *Try it first*, reading the notes and opening the agent in the Foundry portal, weren't timed.

## What didn't match the README, and what changed

**1. `azd env new` stored no subscription.** With no default subscription in azd's settings, `azd env new ai-sdlc-plan-fresh --location eastus2` stored only the name and the region. `azd up` would then have asked which of the account's 87 subscriptions to use, and `runs.py` finds the Function app with `az`, in the subscription `az` uses. The session took that subscription, as the README's Troubleshooting does when it recreates an environment: `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)`. Both `azd env new` commands in the README now pass `--subscription (az account show --query id -o tsv)`.

**2. `azd up` didn't show what its hooks printed.** The README said to expect `GitHub repository: <owner>/<repository>`, `PLAN_GITHUB_TOKEN is not set yet`, and the publish lines. `azd up` printed none of them, only `Running predeploy hook...`, and `azd provision` printed none either. The hooks did run: `GITHUB_REPOSITORY` was set to the copy, and Foundry held the vector store `plan-inputs-9a000f952f98`, the agent `requirements-analyst` version 1 (created at 17:49:09), and the evaluation `plan-brief-checks`. azd shows the output of a hook that isn't `interactive` in an 8-line pane that it clears once the hook succeeds, and drops it when there's no terminal ([azd's hook runner](https://github.com/Azure/azure-dev/blob/main/cli/azd/pkg/ext/hooks_runner.go), `configureExecContext`). Only `azd hooks run` makes every hook interactive. [`azure.yaml`](../azure.yaml) now sets `interactive: true` on the `preprovision` and `postprovision` hooks. To check the change, the session ran `azd up` again at 18:06:54, with that change and with `GITHUB_REPOSITORY` cleared, and it printed:

```text
Packaging overlaps with provisioning for faster execution.

  function: Packaging
  function: Packaging (Compressing deployment artifacts)
GitHub repository: <owner>/ai-sdlc
Initialize bicep provider
Creating a deployment plan
Comparing deployment state
  (-) Skipped: Didn't find new changes.
unit tests: 94 passed
vector store plan-inputs-9a000f952f98: reused
agent requirements-analyst v1: reused (gpt-6-luna)
evaluator plan_structure v1: reused
...
evaluation plan-brief-checks: reused
Running predeploy hook...
  function: Publishing
  function: Deploying
...
SUCCESS: Your application was provisioned and deployed to Azure in 58 seconds.
```

`PLAN_GITHUB_TOKEN is not set yet` didn't appear because the token was set by then. The clone went back to the copy's `azure.yaml` afterwards.

**3. `azd down --purge` asks before it deletes.** It listed the 11 resources it would delete and asked to confirm. Without a terminal the question got no answer, and azd stopped: `ERROR: deleting infrastructure: error deleting Azure resources: user denied delete confirmation`. `azd down --purge --force` then removed everything. In a terminal, you answer `y`. The README now says that it asks.

**4. The copy's push ran one workflow, not four.** The root README said the push runs CI, Repository checks, Copilot setup steps, and the Secure lab tooling checks once. Only Repository checks ran, for 15 seconds. The push carried every file, yet CI, which watches `app/**`, didn't run: for the new branch, GitHub evidently compared only the newest commit, 7a8eb1f, with its parent ([how GitHub compares a new branch](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#git-diff-comparisons)), and 7a8eb1f changed only Markdown files, which only Repository checks watches. Making the copy took 20 seconds, where the root README said about 2 minutes. The root README now says both.

**5. Other solutions' workflows saw this run's Issues.** In the copy, all the solutions' workflows are active. Each label the Function app applied, 25 in all, started a run of *Operate · GitHub · agentic incident triage*, and each was skipped before a runner started. The Function app's comment on the review Issue started *Design · GitHub · agentic design review*, whose 16-second pre-activation job found no `/design-review` command and stopped. No model ran. *Try it first* now says so.

**The README also gained:** how to check the `gpt-6-luna` quota before deploying, a reminder to run azd in the shell where `pip install` ran (its hooks run that `python`), and the measured times above in place of its estimates.

## The run

`python runs.py start`, at 18:00:11 (local time, UTC−5):

```text
Run 20261111-180025-831c started in Azure.
Following it until it waits for a person (Ctrl+C stops following, not the run):

13:00:25  start     queued
13:00:37  draft     asked the agent requirements-analyst for the brief in background mode
13:01:21  draft     brief ready after 46 s
13:01:25  evaluate  attempt 1 of the evaluation plan-brief-checks started
13:02:57  evaluate  the four gates passed after 95 s: 7 of 7 checks passed
13:02:59  review    opened review Issue #1; waiting up to 2 hours for brief-approved or a close

The review Issue waits for a person: https://github.com/<owner>/ai-sdlc/issues/1
Apply the brief-approved label to publish the backlog, or close the Issue to reject it.
```

The run's record, read through the Function app's `runs` function after the publish:

```text
18:00:25  start     queued
18:00:37  draft     asked the agent requirements-analyst for the brief in background mode
18:01:21  draft     brief ready after 46 s
18:01:25  evaluate  attempt 1 of the evaluation plan-brief-checks started
18:02:57  evaluate  the four gates passed after 95 s: 7 of 7 checks passed
18:02:59  review    opened review Issue #1; waiting up to 2 hours for brief-approved or a close
18:04:00  decision  brief-approved is on review Issue #1: publishing the backlog
18:04:04  publish   created epic #2
18:04:07  publish   created task #3 (TASK-1), a sub-issue of epic #2
18:04:10  publish   created task #4 (TASK-2), a sub-issue of epic #2
18:04:12  publish   created task #5 (TASK-3), a sub-issue of epic #2
18:04:15  publish   created task #6 (TASK-4), a sub-issue of epic #2
18:04:19  publish   marked 4 "blocked by" dependencies between the tasks
18:04:22  publish   commented the backlog on review Issue #1 and closed it
```

By GitHub's clock, the label came at 18:03:30, the epic at 18:04:03, the tasks by 18:04:13, the comment at 18:04:19, and the close at 18:04:21.

- **The scores:** all seven checks at 1, the four gates and the three reported checks.
- **What the brief handed to the person:** conflict C2, Finance versus IT for expensive computing equipment (T06, T07, POL-ROUTE-001, POL-ROUTE-004), unresolved; C1, on automatic routing, resolved by T19; and five open questions, on T21, T22, T12, T15, and a blocking one on C2.
- **The backlog:** the epic #2 and the tasks #3 to #6 in the copy, linked as sub-issues, with TASK-2 and TASK-3 blocked by TASK-1, and TASK-4 by TASK-2 and TASK-3.
- **The draft's tokens**, read from Foundry's Responses API: 5,624 input, none cached, and 2,957 output, 439 of them reasoning. That's $0.0020 at `gpt-6-luna`'s list price.

The starting-state check before it printed:

```text
unit tests: 94 passed
vector store plan-inputs-9a000f952f98: reused
agent requirements-analyst v1: reused (gpt-6-luna)
evaluator plan_structure v1: reused
evaluator plan_citations v1: reused
evaluator plan_testable_criteria v1: reused
evaluator plan_injection_ignored v1: reused
evaluator plan_planted_conflicts v1: reused
evaluator plan_planted_unknowns v1: reused
evaluator plan_requirements_covered v1: reused
evaluation plan-brief-checks: reused
Open Issues (track:microsoft): 0
Runs in progress: 0
GitHub token in Key Vault: HTTP 200, expires 2027-02-28 05:00:00 UTC
```

The reset found no run in progress, and closed the epic and the four tasks as not planned.

## The clean-up, and what is left

`azd down --purge --force` purged the Log Analytics workspace `log-plan`, deleted the resource group, then purged the Key Vault `kv-<token>` and the Foundry account `aif-<token>`, and ended with `SUCCESS: Your application was removed from Azure in 4 minutes 54 seconds.`

Checked at 18:15:

- `az group exists -n rg-ai-sdlc-plan-fresh`: `false`.
- `az cognitiveservices account list-deleted` and `az keyvault list-deleted`: empty. No soft-deleted Log Analytics workspace from the group either.
- No resource tagged `azd-env-name=ai-sdlc-plan-fresh`, and no role assignment on the group, anywhere in the subscription.
- `gpt-6-luna` quota in use: back to 500.
- The local azd environment no longer holds the token.

What is left:

- **Three deployment records** at subscription scope, as for every azd deployment: those of `azd up` and `azd provision`, and the empty one that `azd down` records. They cost nothing. Their `githubToken` parameter keeps only its type, `SecureString`, and no value.
- **The GitHub token** `ai-sdlc-plan-fresh`, which can only read and write Issues in the copy. The owner chose to keep it until it expires, on 28 February 2027. Nothing uses it: the Key Vault that held it was purged, and the azd environment no longer has it.
- **In the copy,** the six closed Issues and the seven labels the run used. The solution creates no Microsoft Entra app registration, so there was none to remove.

## What it cost

The resource group existed from 17:45 until azd deleted it, between 18:10 and 18:15: under half an hour. At list prices:

- the draft: $0.0020;
- the three private endpoints, at $0.01 an hour each: under 3 cents;
- the Function app's timer, every 30 seconds: about 110 GB-s, inside the monthly free grant;
- storage, Key Vault, Application Insights, and Log Analytics: cents at most;
- the three private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1.50 if it bills each a whole month.

So between a few cents and about $1.60. In GitHub Actions, the copy used 2 billed minutes: Repository checks, and the design review's pre-activation job.
