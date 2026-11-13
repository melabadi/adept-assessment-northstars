# A fresh setup that followed only this README: 12 November 2026

On 12 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in the private copy that the fresh setups of [01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md), [02-design-microsoft](../../02-design-microsoft/evidence/2026-11-11-fresh-setup.md), [03-develop-microsoft](../../03-develop-microsoft/evidence/2026-11-11-fresh-setup.md), [04-test-microsoft](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md), and [06-release-microsoft](../../06-release-microsoft/evidence/2026-11-12-fresh-setup.md) had used, and in a new azd environment, `ai-sdlc-operate-fresh`, so in a new resource group, `rg-ai-sdlc-operate-fresh`, in Central US. It ran the Quick start, opened the agent, connected the copy, checked the starting state, ran the seven steps, reset the copy, and cleaned up. The steps ran twice up to the alert: the first alert went to another environment's agent (finding 1). The owner created the GitHub token, connected it in the agent's portal, and confirmed the agent's proposal before the session approved it. A coordinating session relayed between them and ran the Microsoft Graph commands.

Times are UTC. The copy of the repository is private, so its Issues aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`, and the agent's identity, which has a suffix of its own, as `id-sre-<sre-token>`. Host names, the subscription, and GUIDs are left out.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, Git 2.56.0, and Node.js 22.23.4 for the repository's screenshot tool.
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. azd had no default subscription.
- Microsoft Graph didn't answer the session's shell. Since about 06:00 that day, `az ad` and `az rest` calls to Microsoft Graph from the sandboxed shells of this machine's agent sessions failed with a continuous access evaluation challenge (`InteractionRequired`, `TokenCreatedWithOutdatedPolicies`), while visible terminals worked. So the coordinating session ran every Graph command, the Entra checks and Clean up's `az ad` and Graph lines, in a visible PowerShell 7 terminal in this folder, and reported masked results. This is this machine's situation, not the README's. Azure Resource Manager worked, and so did `azd up`, whose Bicep Microsoft Graph extension created RequestHub's app registration.
- The copy's `main` was at `edb1fbf`. The session took later updates with the root README's command, which merged main at [313bfab](https://github.com/melabadi/adept-assessment-northstars/commit/313bfab), and pushed them before deploying anything. No file of this solution or of `app/` differed from 313bfab.
- The token, `ai-sdlc-operate-fresh`, for `<owner>/ai-sdlc` only, with Contents read-only and the Metadata read-only that GitHub adds, expiring on 28 February 2027, as [Connect GitHub](../README.md#3-connect-github) says, except the expiry, which the owner chose. The owner created it on GitHub at about 14:05, after GitHub asked them to confirm their access, and added the repository in the [SRE Agent portal](https://sre.azure.com), which signed them in with single sign-on.
- The session ran its commands without a terminal, so azd couldn't ask it questions. For the portal's steps it read the agent's own API, the one the portal uses, the Alerts Management API, the Activity Log, and RequestHub's Admin API. To click in the portal, it used the repository's [`tools/screenshot.mjs`](../../../tools/screenshot.mjs) in the capture browser, signed in as the owner, on the Azure portal's agent blade, which shows the SRE Agent portal in a frame: the sign-in pop-up of sre.azure.com defeats the tool.
- The deployment of [See it work](../README.md#see-it-work), resource group `rg-ai-sdlc-operate` with its agent `sre-ai-sdlc-operate`, ran in the same subscription (finding 1).

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 13:38:02 | Clone the copy | `git clone` | 8 s | |
| 13:38:30 | Take later updates (root README) | `git pull --no-rebase --no-edit https://github.com/melabadi/adept-assessment-northstars.git main` | 2 s; a merge commit with git's default message | |
| 13:38:32 | Push them (root README) | `git push` | 2 s; started *Repository checks*, whose two jobs passed in 6 and 9 s | |
| 13:39:10 | A virtual environment (not in the README) | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 19 s | |
| 13:39:29 | Quick start | `pip install -r requirements.txt` | 44 s | |
| 13:40:21 | Quick start | `azd env new ai-sdlc-operate-fresh --location centralus` | 1 s; stored no subscription (finding 3) | |
| 13:40:30 | Not in the README | `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)` | 2 s | |
| 13:41:14 | Quick start | `azd up` | 15 min 10 s; azd counted 14 min 53 s: 12 min 7 s provisioning, 2 min 45 s deploying | about 15 minutes |
| 13:57:00 | Quick start | the two `gh label create` lines | 2 s; `ai-sdlc` existed, `phase:operate` was new; no workflow ran | |
| 13:59:37 | 2. Open the agent once | the agent's page in the Azure portal, through `tools/screenshot.mjs`, then **Done and go to agent** | 1 min 54 s to the *Team onboarding* chat | |
| about 14:01 | Not in the README: Microsoft Entra after `azd up` | by the coordinating session | RequestHub's app and its service principal, and four managed identities' principals; nothing else | |
| about 14:05 | 3. Connect GitHub: the token | on GitHub, by the owner | a few minutes | |
| about 14:10 | 3. Connect GitHub: **Add repository** | in the SRE Agent portal, by the owner | the agent's API listed the repository, its code ready, at 14:10:41 | |
| 14:11:17 | 3. Connect GitHub: the check | `python configure_sre_agent.py` | 36.5 s: connected, credential healthy, code ready | |
| 14:12:11 | Check the starting state | `az account show`, the agent's administrator role, and the workbook, through `tools/screenshot.mjs` | 46 s; every row **Ready** | about 5 minutes |
| 14:13:20 | 1. Look at the configuration | `python configure_sre_agent.py --check`, then the response plan, the guard hook, and the identities' roles through the APIs | 36 s; `--check` took 12 s | about 3 minutes |
| 14:14:05 | 2. Inject the slowdown, first drill | `python incident.py start` | 2 min 18 s; 360 pending | 1 to 2 minutes |
| 14:20:30 | 3. The alert fires | | 4 min 13 s after the last request | about 6½ minutes after the requests |
| 14:21:19 | 4. The investigation | | another environment's agent acknowledged the alert, and this one listed nothing (finding 1) | 2 to 3 minutes to the report |
| about 14:30 | Not in the README | the other agent's response plan Off, by the owner, in that agent's portal | | |
| 14:37:10 | Reset the first drill | `python incident.py reset` | 1 min 25 s; the backlog was 0 at 14:38:52, and the alert resolved at 14:42:34 | |
| 14:45:57 | 2. Inject the slowdown, second drill | `python incident.py start` | 2 min 20 s; 360 pending | 1 to 2 minutes |
| 14:52:33 | 3. The alert fires | | 4 min 22 s after the last request | about 6½ minutes after the requests |
| 14:53:04 | 4. The investigation | the agent's API instead of the portal | started 31 s after the alert; the report at 14:54:27, 1 min 54 s after it | 2 to 3 minutes to the report |
| 15:05:29 | 5. Approve: **Allow once** | `tools/screenshot.mjs`, after the owner confirmed | 11 min 1 s after the request | as long as you take to decide |
| 15:07:33 | 5. Approve: **Grant permissions** | `tools/screenshot.mjs` | 2 min 4 s after **Allow once**; the command ran for 51.7 s | then about a minute |
| 15:08:09 | 6. Watch it recover | the Alerts Management and Admin APIs instead of the workbook | the backlog drained at 15:09:38, 1 min 29 s after the change began, and the alert resolved at 15:14:38, 5 min later | about 2 minutes to drain, then about 5 for the alert |
| 15:15:36 | 7. The agent's draft | | 58 s after the alert resolved | |
| about 15:16 to 17:04 | The session was interrupted ([also seen](#also-seen-and-left-as-they-are)) | | | |
| 17:09:10 | Not in the README | the other agent's response plan On again, by the coordinating session | | |
| 17:09:28 | 7. File the record | the draft through the agent's API instead of the copy button, then `gh issue create … --body-file $env:TEMP\record.md` | 2 s: Issue #26, identical to the draft | about 2 minutes after the agent's last reply |
| 17:11:17 | Reset the copy | `python incident.py reset`, then `gh issue close 26` | 17 s and 2 s | |
| 17:11:54 | Not in the README: a check of the `azure.yaml` fix | `azd provision` | 1 min 8 s; no changes, and the hook's whole report (finding 2) | |
| 17:16:01 | Clean up | in the portal: **Code access**, **GitHub**, select the repository, **Delete** | no confirmation; the agent's API listed no repository at 17:16:49 | |
| 17:16:49 | Clean up | `$sre = …`, then `az role assignment delete … --role "Monitoring Contributor" …` | 17 s | |
| 17:18:34 | Clean up | `$app = …` and `$sp = …`, by the coordinating session | | |
| 17:19:36 | Clean up | `azd down --purge --force` | 29 min 49 s; azd counted 29 min 44 s | |
| 17:54:21 | Clean up | `az ad app delete --id $app`, then `az rest --method delete` on `deletedItems/$app` and `deletedItems/$sp`, by the coordinating session | | |

**The Quick start took 18½ minutes of commands**, from `pip install` to the check after connecting GitHub: 18 minutes 29 seconds, with a person's few minutes for the token and the dialog alongside. The README said about 20 minutes. By the wall clock it took 32 minutes 24 seconds, 14 of them between `azd up` and the connection: the Entra check, opening the agent, and the owner's token and dialog, which the coordinating session relayed. **The seven steps took 29 minutes 22 seconds** from the second drill's fault to the agent's draft, 13 minutes 5 seconds of them between the approval request and **Grant permissions**, while the request went to the owner and back. See it work took 21 minutes 50 seconds for the same span, and the README says about 25 minutes for the seven steps. The record was filed 1 hour 54 minutes after the draft, because the session was interrupted.

## What didn't match the README, and what changed

**1. Another environment's agent took the copy's alert.** The deployment of See it work runs in the same subscription, and its agent's response plan, like the copy's, sends Sev2 alerts whose title contains *notification backlog* to its custom agent. The first drill's alert fired at 14:20:30. At 14:21:19, 49 seconds later, the Activity Log recorded `Microsoft.AlertsManagement/alerts/changestate/action` by the user-assigned identity of the other agent, `sre-ai-sdlc-operate`, and the alert's history read *Acknowledged by SRE Agent*. The copy's agent listed no incident at 14:24 or at 14:27. Microsoft Learn says the agent's scanner reads the alerts of the subscriptions in its scope every minute ([Azure Monitor alerts in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts#scanner-behavior)), and the platform gives each agent Monitoring Contributor on the subscription. So an agent sees every alert in its subscription, not only those of the resource group it manages, as [How it works](../README.md#how-it-works) said, and its response plan's title and severity decide which ones it investigates.

The owner chose to switch the other agent's plan Off for a second drill, and did so at about 14:30, in its portal. The session reset the drill, waited until Azure Monitor had resolved the alert, at 14:42:34, and started again: the copy's agent acknowledged the second alert at 14:53:04, and the Activity Log shows no other identity acting on it. The coordinating session switched the other agent's plan On again at 17:09:10, changing only its `isEnabled`. The other agent's thread on the first alert stays in its history, with the active flow it used; nobody acted in it.

[How it works](../README.md#how-it-works) and the header of [`infra/sre-agent.bicep`](../infra/sre-agent.bicep) now say where alerts come from. [Try it first](../README.md#try-it-first-in-a-copy-of-this-repository) now asks for a subscription without another environment of this solution, or for the other environment's plan to be Off while the steps run. [Check the starting state](../README.md#check-the-starting-state) lists the subscription's agents with `az resource list --resource-type Microsoft.App/agents`, the `agent.yaml` row of [Edit to fit your code](../README.md#edit-to-fit-your-code) says that `titleContains` must match only your alert, and Troubleshooting explains the symptom: an alert that reads *Acknowledged* while your agent lists nothing. Giving each environment its own alert title would avoid the collision too, but renaming the alert in `infra/monitoring.bicep` would add a second alert rule to a running deployment at its next `azd provision`, so the README asks for one environment of this solution per subscription instead.

**2. `azd up` showed nothing that its hook printed.** Its output went from the provisioned resources, the agent last, to `worker: Publishing` and the deployment, then `SUCCESS`: not one line of `configure_sre_agent.py`, whose report [Deploy](../README.md#1-deploy) quotes. The hook did run: at 13:57 the agent's API listed the response plan `requesthub-notification-backlog`, the custom agent, the three skills, the guard hook, and the tool policy, with 7 allowed, 2 asked, and 39 denied entries. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds, and shows nothing without a terminal. [`azure.yaml`](../azure.yaml) now makes the hook interactive, with a comment saying why. With that change, `azd provision` at 17:11:54 found no change to deploy, ran the hook, and printed its report:

```text
Comparing deployment state
  (-) Skipped: Didn't find new changes.
SRE Agent sre-ai-sdlc-operate-fresh in rg-ai-sdlc-operate-fresh
Tools
  ok      GitHub: <owner>/ai-sdlc is connected, credential healthy, code ready; the agent can read its code and has no GitHub tool that writes
  ok      GitHub write tools denied by pattern: CreateGithubIssue, *Create*Issue*, *Update*Issue*, *Close*Issue*, *issue_write*, *Comment*, *PullRequest*, *pull_request*, *Workflow*, *Branch*, *Commit*, *Merge*, *Push*, *Webhook*, *create_or_update_file*, *delete_file*, *create_repository*, *fork_repository*
Knowledge
  ok  requesthub-worker-runbook.md
Skills
  ok  skills/investigate-notification-backlog
  ok  skills/verify-worker-recovery
  ok  skills/draft-incident-record
Custom agent
  ok  agents/notification-backlog-responder
Tool policy
  ok  allow 7, ask 2, deny 39
Guard hook
  ok  hooks/no-identifiers-in-github
Response plan
  ok  incidentFilters/requesthub-notification-backlog
Read back
  ok  skills/investigate-notification-backlog
  ok  skills/verify-worker-recovery
  ok  skills/draft-incident-record
  ok  agents/notification-backlog-responder
  ok  hooks/no-identifiers-in-github
  ok  incidentFilters/requesthub-notification-backlog
  ok  tool policy

SRE Agent configured. Response plan 'requesthub-notification-backlog' sends Sev2 alerts whose title contains 'notification backlog' to 'notification-backlog-responder' in Review mode. It drafts the incident record in its reply for a person to file in <owner>/ai-sdlc; every GitHub write tool is denied.

SUCCESS: There are no changes to provision for your application.
```

The clone went back to the copy's `azure.yaml` afterwards. [Deploy](../README.md#1-deploy) now says that the hook reports once the resources are provisioned, and the README's Troubleshooting explains the pane, for copies made before this change.

**3. `azd env new` stored no subscription.** As in the fresh setups of 01 to 06, `azd env new ai-sdlc-operate-fresh --location centralus` stored only the environment's name and region, and azd has no default subscription here. `azd up` would then have asked which subscription to use, while `incident.py` and the README's `az` commands find the resources in the subscription `az` uses. The session stored that subscription with `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)`. Both `azd env new` commands in the README now pass `--subscription (az account show --query id -o tsv)`, and [Deploy](../README.md#1-deploy) says why.

**4. Opening the agent, not `azd up`, added Monitoring Contributor on the subscription.** Deploy's *What you should see* said that the platform adds that role for the agent's identity. The only role assignment that the subscription gained during the setup was created at 13:59:58, 3½ minutes after `azd up` had ended and 21 seconds after the agent's page began to load in the portal. The Activity Log recorded its `roleAssignments/write` under the owner's account, which had opened the page. Microsoft Learn says the agent receives the role when Azure Monitor is connected as its incident platform, and that a banner in the portal asks for it when it is missing ([Diagnose with Azure observability](https://learn.microsoft.com/azure/sre-agent/diagnose-azure-observability#azure-monitor-metrics)). [Open the agent once](../README.md#2-open-the-agent-once) now says so, and that the person who opens the agent first needs the right to assign roles on the subscription.

**5. Clean up's lines for the copy named the README's resource group.** They read `$sre` from `az identity list -g rg-ai-sdlc-operate`. In this environment, that group is the deployment of See it work: the next line would have deleted that agent's Monitoring Contributor role, and left this one's. The session didn't run that line. [Clean up](../README.md#clean-up) now reads the group from the azd environment, as its lines for your repository already did, and so does the command that starts the database in [Check the starting state](../README.md#check-the-starting-state).

**6. Clean up didn't purge RequestHub's service principal, and `azd down --purge` asks to confirm.** [04-test-microsoft's fresh setup](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md) found that deleting the app registration moves its service principal to Entra's recycle bin, and [06-release-microsoft's](../../06-release-microsoft/evidence/2026-11-12-fresh-setup.md) that `azd down --purge` stops at its question without a terminal. This README had the same lines. [Clean up](../README.md#clean-up) now reads `$sp` with `$app`, before `azd down`, purges it last, and runs `azd down --purge --force`, and the session ran it that way ([what is left](#the-clean-up-and-what-is-left)).

**7. The record wasn't in the agent's last reply.** The agent's reply at 15:15:36 ended with the draft. Its Stop hook, [`hooks/evidence-checklist.md`](../sre-agent/hooks/evidence-checklist.md), sent it back at 15:15:39, in 2.7 seconds: *Missing investigation structure: confirmed facts are not clearly separated from hypotheses with an explicit confidence.* The agent answered at 15:15:45 with the facts and hypotheses, without the draft, and the hook sent that back too, at 15:15:48: *missing the next validation step*. The agent wrote nothing more. In See it work, the hook allowed the last reply at once. [File the record](../README.md#7-file-the-record) now says that the record stays in the reply before when the hook asks for more.

**8. The workbook pointed at a section that no longer exists.** The **Ready for a drill** table's advice for a stopped database read *Start the database server (README, Before each session)*. [`infra/workbook.json`](../infra/workbook.json) now names [Check the starting state](../README.md#check-the-starting-state).

**9. Other solutions' workflows saw step 7's Issue.** In the copy, every solution's workflows are active. Opening Issue #26, with its labels `ai-sdlc` and `phase:operate`, started *Operate · GitHub · agentic incident triage* twice, at 17:09:34, and both runs skipped all six of their jobs in 1 and 2 seconds. Closing it started nothing, and neither did the labels' creation. No model ran. [Try it first](../README.md#try-it-first-in-a-copy-of-this-repository) now says so.

**10. The README's estimates gave way to the times above,** in its summary, [One-time setup](../README.md#one-time-setup), [Use it the first time](../README.md#use-it-the-first-time), the [Quick start](../README.md#quick-start), [Check the starting state](../README.md#check-the-starting-state), and [How long each step takes](../README.md#how-long-each-step-takes). The alert fired 4 minutes 13 seconds and 4 minutes 22 seconds after the requests, against 6 minutes 33 seconds in See it work, so steps 3 and 4 now say 4 to 6½ minutes, and about 2 minutes to the report. [PRESENTING.md](../../../PRESENTING.md) says the same.

**11. `azd down` removes the deployment's outputs from the azd environment.** Afterwards, the environment kept only its name, its subscription, and the services' names, images, and address: `azd env get-value` answered *key not found* for `API_CLIENT_ID` and `AZURE_RESOURCE_GROUP` in the coordinating session's terminal. Clean up's lines already read `$app` and `$sp` before `azd down`; [Clean up](../README.md#clean-up) now says why, so nobody moves them after it.

Checked and found right:

- **`azd up` reached its hook and didn't stop at `missing required inputs`.** [`infra/main.bicep`](../infra/main.bicep) reads `environmentName`, `location`, and `principalId`, which azd sets, and three parameters with defaults. Every parameter of the modules that azd deploys, in [`app/infra/api.parameters.json`](../../../app/infra/api.parameters.json) and [`worker.parameters.json`](../../../app/infra/worker.parameters.json), comes from `main.bicep`'s outputs or azd's image names, or has a default.
- **No Microsoft Entra object of the agent's own.** After `azd up`, the coordinating session found, by the environment's name and by both suffixes, the app registration `RequestHub (ai-sdlc-operate-fresh)`, created at 13:49:18, its service principal, and four managed identities' principals: `id-app-<token>`, `id-github-<token>`, `id-sre-<sre-token>`, and the agent's system-assigned identity, `sre-ai-sdlc-operate-fresh`. No other app registration had been created in the tenant since 13:40. Microsoft Learn says that creating an agent creates two managed identities ([agent identity](https://learn.microsoft.com/azure/sre-agent/agent-identity)).
- **`azd up` finished in one go.** The `BlobNotFound` that 05-secure-microsoft's `azd up` hit while publishing an image didn't happen: both images built in Azure Container Registry, and the API deployed 2 minutes 21 seconds after publishing began.
- **The region and the GitHub connection.** The README's `az provider show` command listed Central US among the agent's regions, and the hook's GitHub line matched the portal's green connection.
- **The root README's update command** merged main into the copy, and `git push` sent it.

## Also seen, and left as they are

- **The session was interrupted from about 15:16 to 17:04.** The deployment sat idle, the record waited to be filed, and the other agent's plan stayed Off until 17:09. The capture browser had closed meanwhile; the session started it again with `node tools/screenshot.mjs browser`. This is about the session, not the README.
- **The first visit started the onboarding chat before Done and go to agent.** The agent's *Team onboarding* thread began at 13:59:47, 10 seconds after its page began to load, while the setup checklist still showed. The README now says the first visit starts it.
- **The portal's blade for the agent warns that it is going away.** It read *SRE Agent has moved to a new experience at sre.azure.com and managing it will no longer be supported from the Azure Portal by October 2026.* It still worked on 12 November, and the README points to sre.azure.com.
- **The agent's always-on flow was free.** Its page read *Always-on flow charges are waived for this agent through 12/12/26 at 1:50 PM UTC. Active-usage charges apply.* That is the subscription's [30-day evaluation](https://learn.microsoft.com/azure/sre-agent/evaluate), as [What it costs](../README.md#what-it-costs) says.
- **Three of the agent's commands failed, and it went on without them.** `az monitor alert-management show` wasn't recognized, an `az containerapp revision list` query with backticks failed, and `az monitor metrics list` found no metric configuration for the custom gauge. It read the alert with `az rest --method get` instead. Its *Session Insights* also lists a `RunInTerminal` call with `sleep 65` that a permission rule blocked: the tool policy denies the terminal, as designed.
- **The agent read the runbook from the copy's code.** Besides its memory, it opened `ai-sdlc/solutions/07-operate-microsoft/sre-agent/knowledge/requesthub-worker-runbook.md` from the connected repository, 15 seconds into the investigation.
- **The report noted a spoiled baseline.** Its 30-minute window before the alert included the first drill's fault, which it called *not a healthy comparison*: a consequence of finding 1's second drill.
- **The agent's own review blamed a person.** Its *Session Insights*, at 15:52:50, said that *the user requested, and received, a correction*: it was the Stop hook that asked.
- **A link to the thread in the portal's blade opened the agent's home page.** The session went through **Incidents** and the incident's row instead.
- **Code access's Delete asks nothing.** It removed the repository at once.
- **The README's portal pointers name `rg-ai-sdlc-operate`,** the group of the README's environment; the session used its own, `rg-ai-sdlc-operate-fresh`.
- **Other runs in the copy at 17:07 to 17:09,** a pull request's checks, a comment's design review, and a push's checks, weren't this run's: 05-secure-microsoft's fresh setup ran in the same copy at the same time.

## The run

### The starting state

At 14:12, after `azd up` and the connection. The workbook's **Ready for a drill** table, through `tools/screenshot.mjs`: **Database** Ready, **Worker fault** None, **Backlog alert** Not fired, **Azure SRE Agent** Running, every row **Ready**, and both backlog charts at zero. `az account show` named the account that ran `azd up`, the subscription was the azd environment's, and that account had the **SRE Agent Administrator** role on the agent. At 14:11, `configure_sre_agent.py` had found the copy connected under **Code access**.

### Step 1: the configuration

`python configure_sre_agent.py --check` ended in 12 seconds with `sre-agent/ is valid: custom agent 'notification-backlog-responder', 3 skills, 1 knowledge file(s), response plan 'requesthub-notification-backlog' in Review mode, no GitHub tool for the agent and every GitHub write tool denied (Issue writes included), Azure writes need approval, deletes denied, Azure DevOps pipeline runs and repository connections denied, guard hook 'no-identifiers-in-github' as a backstop.` Read through the agent's API: the response plan was enabled, for Sev2, with `notification-backlog-responder` in Review mode, and the guard hook ran before tool use, as a command, with fail mode `block` and a 30-second timeout. The agent's user-assigned identity had Reader, Monitoring Reader, and Log Analytics Reader on the resource group, and Monitoring Contributor on the subscription; its system-assigned identity had the three reader roles on the group.

### Step 2: the slowdown

The second drill's `python incident.py start`, from 14:45:57:

```text
Drill 20261112-144610 started at 14:46:10Z. Backlog before: 0 pending, oldest 0s
1. Slow the worker down: each delivery waits 10s until 15:31:10Z
  > az containerapp update -n ca-worker-<token> -g rg-ai-sdlc-operate-fresh --set-env-vars Faults__WorkerDelayMs=10000 Faults__ExpiresAtUtc=2026-11-12T15:31:10Z
  * the slowed worker revision took over at 14:47:35Z
2. Submit 200 synthetic requests (each notifies the department's reviewers)
  * 200 submitted, 0 failed, at 14:48:11Z
Backlog now: 360 pending. The worker delivers about 6 per minute, so the backlog grows older until someone acts or the fault expires at 15:31:10Z.
Next: the alert fires once the oldest notification has waited 60s, and Azure SRE Agent opens an investigation. Follow both in the Azure portal (README, steps 3 and 4).
```

The Activity Log recorded the worker update at 14:46:14, under the account signed in to the Azure CLI. During the first drill, at 14:16:52, the workbook's **Worker fault** row read **Injected**, as step 3 says.

### Step 3: the alert

Azure Monitor fired *RequestHub notification backlog*, Sev2, at 14:52:33, 4 minutes 22 seconds after the last request. RequestHub's Admin API reported 345 pending and the oldest 347.8 seconds old at 14:53:28.

### Step 4: the investigation

The copy's agent acknowledged the alert at 14:53:04, under its user-assigned identity, and opened the thread *[Sev2] RequestHub notification backlog*. Read through the agent's API:

| UTC | Message |
| --- | --- |
| 14:53:04 | The alert's card, then "Alert received ✅ Initiating investigation to assess the situation and identify potential causes 🛠️" |
| 14:53:08 | "Investigating the Sev2 backlog alert from 14:52:33 UTC. I’ll check the runbook, measure the backlog, and compare the worker's recent changes before proposing any mitigation." |
| 14:53:11 to 14:53:19 | Read its memory, `debugging.md` and `logs.md`, which the *Team onboarding* chat had written; a memory search with 1 result; and the runbook, from the copy's code |
| 14:53:23 | `az monitor alert-management show` failed |
| 14:53:37 | "The runbook confirms the delay fault, database failure, stopped worker, and load spike as causes to test." Then `az rest --method get` on the alert, `az containerapp revision list`, and `az containerapp show` |
| 14:53:54 | The active revision had the 10-second delay until 15:31:10 and 345 pending; `az containerapp revision show` and `az monitor activity-log list` |
| 14:54:12 | `az containerapp revision show` on the revision before |
| 14:54:27 | The report |
| 14:54:28 | The request to approve one command |

The report, 1 minute 54 seconds after the alert fired:

> **Impact:** Sev2 alert fired at 14:52:33 UTC for oldest pending age over 60 seconds; it remains **Fired** and is Acknowledged. At 14:53:29–14:53:38, the worker reported 325 pending, oldest age 348.5 seconds, and about 6 deliveries/minute at roughly 10 seconds each. The 13:52:33–14:22:33 baseline was already impaired: deliveries also took about 10 seconds, and pending peaked at 345.
>
> **UTC timeline:** The earlier delay-fault revision began at 14:14:34. A revision without fault settings began at 14:37:27; its backlog reports reached zero by 14:38:18. An update started at 14:46:14, creating the current revision at 14:46:21. Pending was zero at 14:49:38, then 345 at 14:50:38. The alert fired at 14:52:33.
>
> **Confirmed facts:** The current revision sets `Faults__WorkerDelayMs=10000` and `Faults__ExpiresAtUtc=2026-11-12T15:31:10Z`; the immediately preceding revision has neither setting. The latest backlog report says `workerDelayFaultActive=True`, and delivery spans carry the 10,000 ms fault tag. In the investigation window, the worker recorded 2,172 PostgreSQL dependency calls with none failed, 2,350 traces with no warnings/errors, and no exceptions; the API recorded 738 requests with none failed. System logs show transient startup probe failures but a ready, running revision afterward. The current burst of 131 submitted requests is comparable to the earlier burst of 134, so load alone does not explain sustained slow delivery.
>
> **Hypotheses and gaps:** Delay fault is the **high-confidence** cause; a load burst added notifications but is not sufficient on its own. There is no evidence of ongoing crashes, database failure, or API failure. The baseline was already affected by an earlier fault, so it is not a healthy comparison, and telemetry near “now” may still be arriving.
>
> **Probable root cause and action:** The reintroduced 10-second-per-delivery fault prevents the one-replica worker from keeping up. I’m submitting **only** the specified removal of the two fault settings for administrator approval. If approved, it creates a new worker revision without the fault; the backlog is expected to drain within about a minute of readiness. Rollback would restore the two prior settings, subject to separate approval. Without intervention, the current fault expires at **15:31:10 UTC**. The change is reversible and scoped to the worker, with a brief revision transition; no API or database changes are proposed.

### Step 5: the approval

The session sent the command on the approval card to the coordinating session, which relayed it to the owner. The owner confirmed it, and the session selected **Allow once**, then **Grant permissions**, in the copy's agent, after checking through the agent's API that the request was still pending there with the same command.

| | Approval request | Grant |
| --- | --- | --- |
| Status | Approved (**Allow once**) | Completed (**Grant permissions**) |
| Requested | 14:54:28.268 | 15:05:29.449 |
| Decided | 15:05:29.291, with the owner's account | 15:07:33.131; the command ran until 15:08:24.783, with the owner's permissions |
| Tool | `RunAzCliWriteCommands` | the same command |
| Why | *Permission rule requires approval for this tool.* | *Authorization required: please grant access to the requested Azure resources.* The card said the agent had received an authorization error with its managed identity |
| Command | `az containerapp update -n <worker> -g rg-ai-sdlc-operate-fresh --subscription <subscription> --remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc` | |

Before each click, the session compared the card's command with the azd environment's worker, resource group, and subscription: they matched.

### Step 6: the recovery

The Activity Log's *Started* events for the worker and the alert, with each caller compared with the account signed in to the Azure CLI and with the agents' identities:

```text
14:14:26  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
14:21:19  Started    Microsoft.AlertsManagement/alerts/changestate/action  the other environment's agent
14:37:20  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
14:46:14  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
14:53:04  Started    Microsoft.AlertsManagement/alerts/changestate/action  this agent's managed identity
15:08:09  Started    Microsoft.App/containerApps/write                     the account signed in to the Azure CLI
```

The update at 15:08:09 is the approved command, run with the owner's permissions; the session's own commands used the same account. The new revision, `0000004`, without fault settings, was ready at 15:08:19, as the agent read it. The session's own checks, every 20 to 30 seconds: the alert's condition from the Alerts Management API, the backlog from RequestHub's Admin API, and the worker from Azure Resource Manager:

```text
15:08:52Z alert Fired | backlog 20 pending, oldest 1262.4s | worker revision 0000004 ready, no fault settings
15:09:46Z alert Fired | backlog 0 pending, oldest 0s | worker revision 0000004 ready, no fault settings
15:15:16Z alert Resolved at 15:14:38 | backlog 0 pending, oldest 0s | worker revision 0000004 ready, no fault settings
```

The agent wrote at 15:10:01: *The backlog reached zero at 15:09:38 UTC, about 79 seconds after the new revision became ready. The worker reported 249 sent notifications during the 15:09 minute, with untagged delivery spans averaging about 0.03 ms after the old in-flight spans finished.* It checked the alert with `az rest` every half minute to a minute, and wrote at 15:15:09: *The alert resolved at 15:14:38 UTC.* Azure Monitor had resolved it 22 minutes 5 seconds after it fired, against 12 minutes 57 seconds in See it work, where the approval took 2 minutes 42 seconds instead of 11 minutes 1 second.

In all, the thread had 92 messages: 37 reasoning steps, 31 Azure CLI commands, 16 messages of text, 3 file reads, 2 hook runs, 1 approval request, 1 memory search, and the platform's *Session Insights*. 30 of the commands ran as the agent, which can only read, and 3 of those failed ([also seen](#also-seen-and-left-as-they-are)); the one change ran with the owner's permissions.

### Step 7: the record

The agent's reply at 15:15:36, 58 seconds after the alert resolved, began with *Resolved*, a table of the backlog, the deliveries, and the alert before and after the change, and *A person can review and file this single draft as a GitHub Issue in `<owner>/ai-sdlc`; no Issue was filed by the agent.* Then the title, *Incident record: notification backlog, 2026-11-12*, the labels `ai-sdlc` and `phase:operate`, and the body in a code block. The Stop hook then sent the reply back twice (finding 7), and the agent's last reply, at 15:15:45, held its facts and ranked hypotheses without the draft.

The session read the draft's body through the agent's API, checked it for GUIDs, trace ids, Azure host names, resource ids, e-mail addresses, both suffixes, the subscription, the tenant, and the resource group's name, and found none. At 17:09:28, after the interruption, it filed the body unchanged with `gh issue create`, the draft's title, and its two labels: Issue #26 in the copy, whose body and the draft are the same 3,200 characters:

```markdown
## Summary
Requesters and reviewers received submission, comment, and decision notifications late while the worker processed deliveries with an injected delay. The backlog cleared at 15:09:38 UTC; the alert was active for 22 minutes 5 seconds.

## Impact
| Measure | Value |
| --- | --- |
| Alert fired (UTC) | 2026-11-12 14:52:33 |
| Mitigation ran (UTC) | 2026-11-12 15:08:09 |
| Backlog drained (UTC) | 2026-11-12 15:09:38 |
| Alert resolved (UTC) | 2026-11-12 15:14:38 |
| Peak oldest pending notification | 1,283.1 seconds during the alert, from a worker report |
| Peak pending notifications | 345 |

## Timeline (UTC)
| Time | Event | Evidence |
| --- | --- | --- |
| 14:14:26 | An earlier worker update introduced a delivery delay. | Activity Log and the earlier worker revision's fault settings. |
| 14:37:20–14:38:18 | A worker update removed the fault; the earlier backlog cleared. | Activity Log, revision settings, and worker reports. |
| 14:46:14 | Another worker update reintroduced the 10-second delivery delay. | Activity Log and comparison of the current and previous worker revisions. |
| 14:50:09 | The worker reported 345 pending notifications. | Worker backlog report. |
| 14:52:33 | The Sev2 backlog alert fired. | Alert record. |
| 15:08:09–15:08:19 | The approved mitigation ran and the new worker revision became ready. | Activity Log and revision events. |
| 15:09:38 | Pending count and oldest age reached zero. | Application telemetry. |
| 15:14:38 | The alert resolved. | Alert record. |

## Recent changes
Worker configuration updates began at 14:37:20 UTC (fault removed) and 14:46:14 UTC (fault reintroduced); the approved mitigation began at 15:08:09 UTC (fault removed again). The Activity Log showed no API updates in the checked period. An earlier worker update at 14:14:26 UTC explains why the pre-alert baseline was already impaired.

## Root cause
The worker's configuration reintroduced `Faults__WorkerDelayMs=10000`. Its reports showed `workerDelayFaultActive=True`, and delivery spans carried the 10,000 ms fault tag and took roughly 10 seconds. Worker database calls and API requests showed no failures in the investigation window. A burst of new requests added notifications, but a comparable earlier burst cleared when the fault was absent.

## Mitigation
An SRE Agent Administrator approved removal of exactly the two fault settings, and the change ran with the approver's permissions: `az containerapp update -n <worker> -g <resource group> --remove-env-vars Faults__WorkerDelayMs Faults__ExpiresAtUtc`. The new worker revision is ready without either setting. The backlog reached zero about 79 seconds after revision readiness.

## Follow-up
Add an end-of-drill checklist gate requiring confirmation that the worker revision has no `Faults__` settings and reports `workerDelayFaultActive=False`; verify both checks before closing each drill.

## Status
| Field | Value |
| --- | --- |
| Status | Resolved |
| Environment | `ai-sdlc-operate-fresh` (Azure) |
| Detected at (UTC) | 2026-11-12T14:52Z |

---
Drafted by Azure SRE Agent from its investigation of the alert, and filed by a person who read it. All data comes from RequestHub's synthetic demo.
```

`python incident.py reset` found no fault and reseeded the data in 17 seconds, and `gh issue close 26` closed the Issue at 17:11:34.

### The first drill

`python incident.py start`, from 14:14:05, set the fault at 14:14:26, expiring at 14:59:22, and submitted the 200 requests by 14:16:17: 360 pending. The alert fired at 14:20:30. At 14:21:19, the other environment's agent acknowledged it (finding 1), and the copy's agent listed nothing under **Incidents** at 14:24 and 14:27. At 14:28:25 the backlog was 285 pending, the oldest 753.7 seconds old. After the owner switched the other agent's plan Off, `python incident.py reset` removed the fault at 14:37:20, in 1 minute 25 seconds; the backlog was 0 at 14:38:52, and Azure Monitor resolved the alert at 14:42:34.

## The clean-up, and what is left

The session removed the agent's GitHub connection first, as Clean up says: at 17:16, **Delete** in **Code access** removed it at once, and the agent's API then listed no repository. It kept the token, which the owner chose to keep. At 17:16:49, `az role assignment delete` removed the agent identity's Monitoring Contributor on the subscription, in 17 seconds. The coordinating session read `$app` and `$sp` at 17:18:34. `azd down --purge --force`, from 17:19:36, purged the Log Analytics workspace `log-<token>`, deleted the resource group, and ended with `SUCCESS: Your application was removed from Azure in 29 minutes 44 seconds.` From 17:29 on, only the Container Apps environment, its virtual network, and three network security groups that a tenant policy had added were left in the group, and the environment read `ScheduledForDelete` at 17:40. At 17:54:21, the coordinating session checked that both ids still named `RequestHub (ai-sdlc-operate-fresh)`, then deleted the app registration and purged it and its service principal from the recycle bin, in 5.8 seconds.

Checked between 17:50 and 17:55:

- `az group exists -n rg-ai-sdlc-operate-fresh`: `false`, and no resource group named after the environment.
- No resource tagged `azd-env-name=ai-sdlc-operate-fresh`, and none named with either suffix, anywhere in the subscription.
- Nothing soft-deleted: no deleted Key Vault in the subscription (the solution creates none), and no deleted Log Analytics workspace, Cognitive Services account, or App Configuration store named with either suffix.
- The subscription's role assignments, inherited ones included, were the same 51 as before `azd up`: the agent identity's Monitoring Contributor was gone, and no role assignment's scope named the group.
- The agent no longer existed, and with it its connection to the copy. The copy had no webhook and no deploy key.
- In Microsoft Entra ID, no application `RequestHub (ai-sdlc-operate-fresh)` and no service principal for it, active or in the recycle bin. The coordinating session checked them by the object ids read before `azd down`: by then, the azd environment no longer had `API_CLIENT_ID` (finding 11). No active application or service principal was named after the environment or with either suffix.
- In Entra's recycle bin, the service principals of the four managed identities, deleted with the group: `id-app-<token>`, `id-github-<token>`, and `id-sre-<sre-token>` at 17:20:19, and the agent's system-assigned identity, `sre-ai-sdlc-operate-fresh`, at 17:21:50. Nobody tried to purge them: Entra refused that in the fresh setups of [04-test-microsoft](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md#the-clean-up-and-what-is-left) and [06-release-microsoft](../../06-release-microsoft/evidence/2026-11-12-fresh-setup.md#the-clean-up-and-what-is-left), with `Authorization_RequestDenied`.
- The deployment of See it work, untouched: `rg-ai-sdlc-operate` still exists, with its 28 resources, its agent `sre-ai-sdlc-operate` running, its alert rule enabled, and its response plan On again since 17:09:10.

What is left:

- **Two deployment records** at subscription scope, as for every azd deployment: that of `azd up`, and the empty one that `azd down` records. `azd provision`, which found no changes, recorded none. They cost nothing, and the template has no secure parameter.
- **The four managed identities' service principals,** in Entra's recycle bin until it removes them, 30 days after they were deleted.
- **The GitHub token** `ai-sdlc-operate-fresh`, which could only read the copy's contents, until it was deleted on 12 November 2026, after the seven fresh setups, as the owner asked. Nothing used it after the clean-up: the agent that held it was deleted.
- **In the copy,** the update's merge commit `7f6b5d0` in `main`'s history, the closed Issue #26, and the label `phase:operate`, which the Quick start created; `ai-sdlc` existed already. The copy was deleted on 12 November 2026, after the seven fresh setups, as the owner asked.
- **In the other deployment's agent,** its thread on the first drill's alert, with the active flow it used.
- **The local clone's azd environment,** which `azd down` left with the environment's name, its subscription, and the two services' names, images, and address; it holds no password or token.

## What it cost

The resource group existed from 13:41 until azd deleted it at 17:49: 4 hours 8 minutes. At list prices:

- RequestHub's platform, at the $85 a month that the [Quick start](../README.md#quick-start) gives: about 48 cents;
- the two private DNS zones, at $0.50 a month each: under a cent if Azure prorates them, $1 if it bills each a whole month;
- the agent's always-on flow: nothing, because the subscription's evaluation waived it for this agent; otherwise 4 AAUs an hour, about $1.60 for the 4 hours the agent existed;
- the agent's active flow, for the onboarding chat and the investigation with its checks of the recovery: roughly 10 to 35 AAUs, $1 to $3.50, as [What it costs](../README.md#what-it-costs) estimates. The session couldn't see the count, which Microsoft Cost Management shows later;
- log ingestion for two drills: about $2, at the README's $1 a drill;
- the two images' builds in the registry: cents.

So between about $3.50 and $7. The other deployment's agent also investigated the first drill's alert, for roughly 10 to 35 more AAUs, $1 to $3.50, on that deployment's bill. In GitHub Actions, the copy ran 2 jobs for 15 seconds, 2 minutes as billed in a private repository, where each job counts as at least a minute: *Repository checks* after the update's push. The two triage runs skipped their jobs, which bill nothing. No model ran in GitHub.
