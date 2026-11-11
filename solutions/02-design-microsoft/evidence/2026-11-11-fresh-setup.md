# A fresh setup that followed only this README: 11 November 2026

On 11 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in a new azd environment, `ai-sdlc-design-fresh`, so in a new resource group, `rg-ai-sdlc-design-fresh`, with Foundry and the Function in East US 2 and Azure AI Search in Central US. It ran the starting-state check, the seven steps, and `python evaluate.py` once, reset the copy, and cleaned up. The owner created and installed the GitHub App.

Times are UTC. The copy of the repository is private, so its Issues and pull requests aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, and Git 2.56.0.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. azd had no default subscription.
- `gpt-6-luna` Global Standard quota in East US 2: 500 of 1,000 thousand tokens per minute in use before the setup, 750 while it was deployed, and 500 again after the clean-up.
- The copy that [the fresh setup of 01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md) had used, made from main at [7a8eb1f](https://github.com/melabadi/adept-assessment-northstars/commit/7a8eb1f), two commits behind main. The session cloned it, pulled main at [d20e654](https://github.com/melabadi/adept-assessment-northstars/commit/d20e654) as the root README says for later updates, and pushed it to the copy before deploying anything. A standards run reads the standards, `agent.yaml`, and the labelled cases from the copy's default branch, and `eval_cases.jsonl` had changed in between: without the push, the copy would have evaluated older labels than the ones the session deployed. The push ran *Repository checks* once, for 9 seconds.
- The session ran its commands without a terminal, so azd couldn't ask it questions.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 18:34:21 | Clone the copy | `git clone` | 5 s | |
| 18:34:26 | Take later updates (root README) | `git pull https://github.com/melabadi/adept-assessment-northstars.git main` | 6 s | |
| 18:35:22 | Push them to the copy (not in the README) | `git push origin main` | 2 s | |
| 18:35:51 | Quick start | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 17 s | |
| 18:36:09 | Quick start | `pip install -r requirements.txt` | 2 min 15 s | |
| 18:38:31 | Quick start | `gh label create design-advisor …` | 1 s | |
| 18:38:32 | Quick start | `azd env new ai-sdlc-design-fresh --location eastus2` | 1 s | |
| 18:38:43 | Not in the README | `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)` | 2 s | |
| 18:38:46 | Quick start, the note after it | `azd env set GITHUB_APP_NAME "AI-SDLC design advisor fresh"` | 1 s | |
| 18:38:59 | Quick start | `azd up` | stopped after 13 s: `missing required inputs` | about 6 minutes |
| 18:40:51 | Quick start | `azd up`, with `main.bicep` fixed | 23 min 25 s; azd counted 23 min 10 s: 21 min 55 s provisioning, 19 min 46 s of it Azure AI Search, and 1 min 14 s deploying | about 6 minutes |
| 19:05:08 | A check of the `azure.yaml` fix | `azd up` again | 1 min 33 s; azd counted 1 min 20 s | 3 to 4 minutes after the first |
| 19:07 | Connect GitHub | `python setup_azure.py github`, then a person on two web pages | the app was created at 19:29:41 and connected by 19:30:02; the request waited for the owner | about 3 minutes |
| 19:07:30 | Use it the first time, step 3 | `python evaluate.py` | 3 min 48 s; it counted 223 s | 3 to 7 minutes |
| 19:30:18 | Check the starting state | `python setup_azure.py github --check` | 6 s | under a minute |
| 19:30:39 | 1. Change a standard | `git switch -c …` to `gh pr merge --squash --delete-branch` | 13 s; the pull request merged 4 s after it opened, at 19:30:47 | about 2 minutes |
| 19:31:08 | 2. Watch Azure re-index | the log query, twice | the index changed 18 s after the merge, the evaluation started 29 s after it; the lines showed in the second query, at 19:31:52 | under half a minute after the merge |
| 19:31:15 | 3. Read the evaluation | followed through Foundry's evaluation API, not the portal | both runs reported at 19:39:46, 9 min after the merge | 3 to 7 minutes after the merge |
| 19:32:31 | 4. Ask from GitHub | `gh issue create …`, the README's terminal form | 2 s | about 1 minute |
| 19:32:42 | 5. Follow the advisor run | the log query, four times | the run queued 4 s after the Issue and finished 46 s after it; every line showed in the fourth query, at 19:34:04 | about a minute |
| 19:34:23 | 6. Review | `gh issue view --comments`, `gh pr view`, `gh pr diff` | 4 s | about 3 minutes |
| 19:34:50 | 7. Trace the answer | an Application Insights query instead of the portal | 6 s | about 1 minute |
| 19:35:41 | Reset the copy | the README's two lines | 6 s | |
| 19:42:34 | Clean up | `azd down --purge --force` | 4 min 1 s; azd counted 3 min 57 s | |
| 19:50:21 | Not in the README | delete the agents' Microsoft Entra objects | 4 objects deleted by 20:01:25 | |

**The one-time setup took about half an hour:** 26 minutes 15 seconds of commands from `python -m venv` to `azd up`'s `SUCCESS`, 19 minutes 46 seconds of them for Azure AI Search to start, and the person's clicks to create and install the GitHub App, which weren't timed. The README said about 10 minutes, from a first setup in October whose `azd up` took about 6. **The seven steps took 4 minutes 17 seconds**, from `git switch` at 19:30:39 to the trace at 19:34:56, besides the evaluation, which reported 9 minutes after the merge. The README's 20 minutes include reading the answer, the ADR, and the evaluation.

## What didn't match the README, and what changed

**1. `azd up` stopped before its first hook.** It printed `Initialize bicep provider`, then:

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
    Description: GitHub repository (owner/name) the advisor answers and writes ADR drafts to. Set by the preprovision hook.
```

The `preprovision` hook that sets `GITHUB_REPOSITORY` hadn't run: azd checks the Bicep parameters first, and a string parameter with an empty value and no default counts as missing ([azd's `armParameterFileValue`](https://github.com/Azure/azure-dev/blob/main/cli/azd/pkg/infra/provisioning/bicep/bicep_provider.go)). In a terminal, azd would have asked for the value instead. 01-plan-microsoft, 04-test-microsoft, and 05-secure-microsoft give the same parameter an empty default; [`infra/main.bicep`](../infra/main.bicep) now does too, with a comment saying why. With it, `azd up` ran the hook, which found the copy from `gh repo view`, and the Function's `GITHUB_REPOSITORY` app setting was `<owner>/ai-sdlc`. The second `azd up` below, run with `GITHUB_REPOSITORY` cleared, checked the same. The README's Troubleshooting now names the error.

**2. `azd env new` stored no subscription.** As in 01-plan-microsoft's fresh setup, `azd env new ai-sdlc-design-fresh --location eastus2` stored only the name and the region, so `azd up` would have asked which subscription to use. The session set the one `az` uses, where the README's `az` commands look for the resources. Both `azd env new` commands in the README now pass `--subscription (az account show --query id -o tsv)`.

**3. `azd up` didn't show what its hooks printed.** The README lists four things its hooks print. `azd up` showed none of them, only `Running predeploy hook...` and `Running postdeploy hook...`. The hooks did run: the environment held `GITHUB_REPOSITORY`, and the next run found the index, the agents, and the evaluators already published. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds. [`azure.yaml`](../azure.yaml) now makes all four hooks interactive. With that change, and with `GITHUB_REPOSITORY` cleared, the session ran `azd up` again at 19:05:08, and it printed every line the README describes:

```text
GitHub repository: <owner>/ai-sdlc
Initialize bicep provider
Creating a deployment plan
Comparing deployment state
  (-) Skipped: Didn't find new changes.
index architecture-standards: 12 standards (0 new, 0 changed, 0 removed, 0 failed), 12 in the index
  small-team  can retrieve  9; only this profile sees STD-DATA-002, STD-OPS-001
  enterprise  can retrieve 10; only this profile sees STD-AI-002, STD-DATA-001, STD-OPS-002
  knowledge base standards-small-team: base filter scope eq 'all' or scope eq 'small-team'
  knowledge base standards-enterprise: base filter scope eq 'all' or scope eq 'enterprise'
agent architecture-advisor-small-team v1 (reused): knowledge base standards-small-team
agent architecture-advisor-enterprise v1 (reused): knowledge base standards-enterprise
evaluators: advisor_citations v1, advisor_access v1, advisor_grounding v1, advisor_abstention v1, advisor_conflicts v1
evaluation: "Architecture advisor · labelled cases" (Foundry portal > Evaluations)
Running predeploy hook...
----------------------------------------------------------------------
Ran 106 tests in 4.126s

OK
  function: Publishing
  function: Deploying
...
Running postdeploy hook...
GitHub is not connected yet. To connect <owner>/ai-sdlc, run: python setup_azure.py github
...
SUCCESS: Your application was provisioned and deployed to Azure in 1 minute 20 seconds.
```

The clone went back to the copy's `azure.yaml` and `main.bicep` afterwards. The Troubleshooting entry *azd shows no hook output* now explains the pane.

**4. The agents' Microsoft Entra objects outlived `azd down --purge`.** When `setup_azure.py foundry` published the two agents, Foundry created, for each, an agent identity blueprint, which is an app registration owned by the person who published it, and an agent identity, a service principal ([agent identities in Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity)). After the clean-up, all four were still in Microsoft Entra ID, named after the deleted Foundry account: `aif-<token>-design-architecture-advisor-small-team-<hex>-AgentIdentityBlueprint` and `aif-<token>-design-architecture-advisor-small-team-AgentIdentity`, and the same for `enterprise`. The session deleted both blueprints at 19:50, which deleted their principals too, and purged the app registrations from the recycle bin. Deleting a blueprint should soft-delete its agent identities as well ([agent identity deletion](https://learn.microsoft.com/entra/agent-id/concept-agent-identity-deletion)), but both were still active 10 minutes later, so the session deleted them at 20:01 and purged them. Entra refuses to purge a blueprint principal (`Authorization_RequestDenied`), as Microsoft Learn says, so the two principals stay in the recycle bin until Entra removes them after 30 days. [Clean up](../README.md#clean-up) now deletes each agent identity, then each blueprint, before `azd down`: after `azd down`, `azd env get-value FOUNDRY_ACCOUNT_NAME` answers `key not found`.

**5. The standards run's evaluation took longer than the README said.** Its two runs started 29 seconds after the merge, showed no results for 8½ minutes, and reported together 9 minutes after the merge; the README said 3 to 7 minutes. Its last log line says `evaluation started in Foundry`, because the Function never reads the results. The table in [How long each step takes](../README.md#how-long-each-step-takes) now says 3 to 9 minutes, and the Troubleshooting entry *A standards run's evaluation stays in progress* now says that a run shows no results until it finishes.

**6. Other solutions' workflows saw this run's pull requests, Issue, and comments.** In the copy, every solution's workflows are active. The two pull requests, the step 1 change and the advisor's ADR draft, and the merge started three runs of *Repository checks* (12, 12, and 37 seconds) and two of *Develop · GitHub · feature bounds* (10 and 7 seconds), all green. The `design-advisor` label started *Operate · GitHub · agentic incident triage*, skipped before a runner started. The advisor's comment and the reset's two comments started three runs of *Design · GitHub · agentic design review*, each stopped by its pre-activation job after 7 to 10 seconds, for want of a `/design-review` command. No model ran. *Try it first* now says so.

**7. `azd down --purge` asks before it deletes.** The README already passes `--force`, which skips the question; [01-plan-microsoft's fresh setup](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md) showed the question without it. *Clean up* now says what `--force` is for and what `--purge` removes.

**Also seen, and left as they are:**

- **Connect GitHub ran in a browser panel.** At the owner's request, the coordinating session opened the Function's setup link in the GitHub Copilot app's built-in browser panel, through a temporary local page that redirected to it and was deleted afterwards, so the link and the Function key in it never appeared in a chat. The README's step opens the default browser instead. The owner kept the proposed name, created the app, and installed it on the copy only. The app had the README's permissions (Contents, Issues, and Pull requests write, Metadata read) and events (Issues and Push).
- **`gh pr merge --squash --delete-branch` already switches to `main` and pulls**, so step 1's `git switch main` and `git pull` found nothing to do.
- **`gh pr close … --delete-branch` printed `! Skipped deleting the local branch since current directory is not a git repository`**, from the solution folder of the clone. There was no local branch, and it deleted the remote one.

## The run

**Step 1.** The keyword `OpenTelemetry collector` went into STD-OBS-001's `keywords:` line. Pull request #7 in the copy opened at 19:30:43 and merged at 19:30:47 as commit `7a94d4b`.

**Steps 2 and 3.** The standards run's lines, from the README's log query:

```text
2026-11-11T19:30:49.7086451Z	standards run ef50c2481c09: 7a94d4b queued (push to the default branch, 1 file(s) in the solution)
2026-11-11T19:31:01.9775472Z	standards run ef50c2481c09: 7a94d4b is on main; 1 changed file(s) in the solution
2026-11-11T19:31:05.1192096Z	standards run ef50c2481c09: re-indexed architecture-standards: 12 standards (0 new, 1 changed, 0 removed, 0 failed)
2026-11-11T19:31:08.9801937Z	standards run ef50c2481c09: agents architecture-advisor-small-team v1 (reused), architecture-advisor-enterprise v1 (reused)
2026-11-11T19:31:16.0804733Z	standards run ef50c2481c09: evaluation started in Foundry: 2 run(s), 10 case(s); done in 16 s
```

The evaluation's two runs, `… · commit 7a94d4b`, were created at 19:31:15. The agents answered their cases between 19:32:31 and 19:33:30, by their traces, and both runs reported at 19:39:46. [The evaluations](#the-evaluations) has their results.

**Step 4.** Issue #8, filed at 19:32:31 with the README's terminal form: the profile small-team and the question of See it work.

**Step 5.** The advisor run's lines:

```text
2026-11-11T19:32:34.9456498Z	advisor run 750dc5b8b457: #8 queued (issues.labeled, small-team profile)
2026-11-11T19:33:08.221281Z	advisor run 750dc5b8b457: #8 asked architecture-advisor-small-team v1: completed in 27 s
2026-11-11T19:33:12.4053719Z	advisor run 750dc5b8b457: #8 the gate passed the answer: 7 standard(s) cited, 7 retrieved, all in the small-team scope
2026-11-11T19:33:14.6209778Z	advisor run 750dc5b8b457: #8 branch design/advisor-issue-8 created
2026-11-11T19:33:15.8040825Z	advisor run 750dc5b8b457: #8 ADR draft committed at e8c467e
2026-11-11T19:33:17.0992967Z	advisor run 750dc5b8b457: #8 pull request #9 opened
2026-11-11T19:33:17.6609732Z	advisor run 750dc5b8b457: #8 commented the answer; done in 36 s
```

**Step 6.** By GitHub's clock, the pull request opened at 19:33:16 and the comment at 19:33:17, 45 and 46 seconds after the Issue, both from the GitHub App. The comment's recommendation: *Prefer implementing the live provider behind ITriageProvider within the existing RequestHub API, and record the AI data flow and any separate-service justification in an ADR*, the conclusion of See it work. It listed seven standards with their versions and requirements: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-OBS-002, and STD-DATA-002. Two of them, STD-OPS-001 and STD-DATA-002, only the small-team profile sees, and none of the three that only the enterprise profile sees appeared. It named the conflict between STD-SEC-002 and STD-OBS-002 for an architect, and two unknowns: whether the capability needs independent scaling, a different security boundary, or a separate release cadence, and how the architect resolves the logging conflict. The pull request added `solutions/02-design-microsoft/adr/issue-8.md`, *Proposed*, 68 lines.

**Step 7.** The session read the answer's trace from the Application Insights resource connected to the Foundry project, the data the portal's **Traces** tab shows: response `resp_0ba1e6cb3027e50b006af4c2dd17448195b9670b76e7269819`, the agent invocation (22.6 seconds), two knowledge-base retrievals (1.8 and 1.5 seconds), and the model call (15.2 seconds, 3,181 input and 1,788 output tokens).

**The reset** closed pull request #9 and deleted its branch at 19:35:41, and closed Issue #8 as not planned at 19:35:45.

The starting-state check before the run printed:

```text
GitHub is connected (GitHub App) for <owner>/ai-sdlc; webhook secret stored: True.
```

## The evaluations

`python evaluate.py`, at 19:07:30, its first and only run:

```text
started architecture-advisor-small-team v1 on 5 case(s): E01, E03, E05, E07, E09
started architecture-advisor-enterprise v1 on 5 case(s): E02, E04, E06, E08, E10
Foundry portal: Evaluations > "Architecture advisor · labelled cases"

architecture-advisor-small-team v1: completed, 4/5 cases passed every check
  citations 5/5 · access 5/5 · grounding 4/5 · abstention 5/5 · conflicts 5/5
  E01  FAIL: grounding
  E03  PASS
  E05  PASS
  E07  PASS
  E09  PASS

architecture-advisor-enterprise v1: completed, 4/5 cases passed every check
  citations 5/5 · access 5/5 · grounding 4/5 · abstention 5/5 · conflicts 5/5
  E02  PASS
  E04  FAIL: grounding
  E06  PASS
  E08  PASS
  E10  PASS

First attempt: 8 passed, 2 failed, 0 could not be graded (of 10 cases)
Retries: none

Last run of each profile: 8/10 cases passed in 223 s
```

The standards run's evaluation, scored the same way: small-team 5 of 5; enterprise E02, E06, and E08 passed, E04 failed grounding, and E10 had no answer to grade. The agent call for E10, *Can we rename the recommendation fields in the RequestHub API response to make them clearer?*, failed with HTTP 400 `invalid_prompt`: *your prompt was flagged as potentially violating our usage policy*. The same case had passed in `evaluate.py`'s run.

The session read the three grounding failures' answers. All three are right answers that the check misread:

- **E01, in `evaluate.py`'s run.** The recommendation began *Prefer the existing API and ITriageProvider boundary for the initial implementation*, which none of E01's four claims (`inside* existing`, `in the existing* api`, `extend* the existing`, `keep* it in the existing`) accepts. The summary, *The standards favor implementing live triage behind RequestHub's existing ITriageProvider interface, rather than adding a separate RequestHub service*, holds *rather*, which the check counts as a negation.
- **E04, in `evaluate.py`'s run.** The summary said *For other request data, send only fields the use case needs and exclude personal data*: *exclude* is a negation word in the same clause as *only fields*, the misread [the E04 claims](2026-11-11-e04-claim.md) describe. The recommendation, *Use a minimized, explicitly documented allowlist of necessary non-personal request fields*, puts five words between *allowlist* and *fields*, and a claim allows three.
- **E04, in the standards run's evaluation.** The answer said *send only those the AI use case needs* and *define the minimum necessary set for the triage use case*, without the word *fields* after *only* or *minimum*.

So both of E04's answers were misread, after its claims were widened earlier the same day, and E01's is the first misread of that case on record. The labels didn't change: claims are added only after a misread recurs, behind `--check-graders` and a rescore of stored answers. The Troubleshooting entry on `FAIL: grounding` now counts these misreads.

The answers' tokens, from Foundry: `evaluate.py`'s ten, 35,255 input (9,260 cached) and 15,294 output; the standards run's nine, 30,826 input (10,607 cached) and 14,026 output; the advisor's answer, 3,181 input and 1,788 output.

## The clean-up, and what is left

`azd down --purge --force` purged the Log Analytics workspace `log-<token>`, deleted the resource group, then purged the Key Vault `kv-<token>` and the Foundry account `aif-<token>`, and ended with `SUCCESS: Your application was removed from Azure in 3 minutes 57 seconds.`

Checked at 19:46 and, for Microsoft Entra ID, at 20:02:

- `az group exists -n rg-ai-sdlc-design-fresh`: `false`.
- `az cognitiveservices account list-deleted`, `az keyvault list-deleted`, and `az monitor log-analytics workspace list-deleted-workspaces`: empty. Azure AI Search keeps no deleted services.
- No resource tagged `azd-env-name=ai-sdlc-design-fresh`, and none named with the setup's token, anywhere in the subscription.
- The 14 role assignments inside the group before the clean-up, 10 for managed identities and 4 for the person, were gone.
- No service principal named after the Function, the Foundry account, or the search service.
- `gpt-6-luna` quota in use: back to 500.
- The agents' Entra objects, as in finding 4: the two app registrations and the two agent identities deleted and purged; the two blueprint principals deleted, and in Entra's recycle bin until it removes them after 30 days.

What is left:

- **Two deployment records** at subscription scope, as for every azd deployment: that of the first `azd up` that provisioned, and the empty one that `azd down` records. The second `azd up` found no changes and recorded none. They cost nothing, and the template has no secure parameter.
- **The GitHub App** `AI-SDLC design advisor fresh`, installed on the copy only. The README says to delete it on GitHub, and the owner was asked to. Nothing can use it: the Key Vault that held its private key and webhook secret is purged.
- **In the copy,** `main` at the pulled d20e654 and then commit `7a94d4b` with the new keyword, which can stay, as the README says; pull request #7, merged; Issue #8 and pull request #9, closed; and the `design-advisor` label.

## What it cost

The resource group existed from 18:41 until azd deleted it, between 19:42 and 19:46: about an hour. At list prices:

- the model tokens of the 20 answers: about $0.023 at `gpt-6-luna`'s $0.10 per million input and $0.50 per million output tokens;
- Azure AI Search Basic, at about $0.10 an hour: about 11 cents;
- the three private endpoints, at $0.01 an hour each: about 3 cents;
- the Function on Flex Consumption: a few executions, inside the monthly free grant;
- storage, Key Vault, Application Insights, and Log Analytics: cents at most;
- the three private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1.50 if it bills each a whole month.

So between about 20 cents and about $1.70. In GitHub Actions, the copy used about 13 billed minutes: four runs of *Repository checks*, two jobs each, including the one the session's push of main started; two of *Develop · GitHub · feature bounds*; and three pre-activation jobs of *Design · GitHub · agentic design review*.
