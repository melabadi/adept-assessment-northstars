# A fresh setup that followed only this README: 12 November 2026

On 12 November 2026, a GitHub Copilot agent session working for the repository owner set this solution up from scratch, as a customer would. It followed only this README's [Try it first in a copy of this repository](../README.md#try-it-first-in-a-copy-of-this-repository), in the private copy that the fresh setups of [01-plan-microsoft](../../01-plan-microsoft/evidence/2026-11-11-fresh-setup.md) to [04-test-microsoft](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md) had used, and in a new azd environment, `ai-sdlc-secure-fresh`, so in a new resource group, `rg-ai-sdlc-secure-fresh`, in Central US. It ran the Quick start, waited for Defender for Cloud's first assessment, ran the starting-state check and the steps, reverted the fix in the copy, and cleaned up. The owner created the GitHub token.

Times are UTC, all on 12 November; the session started at 19:36 on 11 November, Eastern time. The copy of the repository is private, so its Issues and pull requests aren't linked, and it appears as `<owner>/ai-sdlc`. Resource names with a random suffix appear with `<token>`, an agent blueprint's random part as `<hex>`, and the webhook's id as `<id>`. Host names, the subscription, and GUIDs are left out.

## What it ran on

- Windows, PowerShell 7.6.10, Python 3.14.10 in a virtual environment, Azure CLI 2.92.0, Azure Developer CLI (azd) 1.37.3, GitHub CLI 2.103.3, Git 2.56.0, and Node.js 22.23.4 for the repository's [`tools/screenshot.mjs`](../../../tools/screenshot.mjs).
- Already signed in, so `az login` and `azd auth login` weren't run; azd used the Azure CLI's sign-in. The Azure account sees 87 subscriptions, and azd had no default subscription.
- `gpt-6-luna` Global Standard quota in Central US: 500 of 1,000 thousand tokens per minute in use before the setup, 550 while it was deployed, and 500 again after the clean-up.
- The copy's `main` was at `62d2667`. The session took later updates with the root README's command, which merged main at [e3c9b49](https://github.com/melabadi/adept-assessment-northstars/commit/e3c9b49), and pushed them, before deploying anything. No file of this solution changed between the two.
- The token, created by the owner on GitHub, as [Create the GitHub token](../README.md#1-create-the-github-token) says, through the coordinating session: `ai-sdlc-secure-fresh`, for `<owner>/ai-sdlc` only, with Commit statuses, Contents, Issues, and Pull requests each read and write, and the Metadata read-only that GitHub adds, expiring on 28 February 2027. GitHub asked the owner to confirm access (sudo mode) before it showed the form, and the token was created at about 02:15, after `azd up` had started. The coordinating session checked it without printing it: Issues, pull requests, contents, and commit statuses answered 200, webhooks 403, and another private copy 404. It stored it at 03:23:21 with `azd env set POSTURE_GITHUB_TOKEN`, from a masked prompt, once `azd up` had ended.
- The session ran its commands without a terminal, so azd couldn't ask it questions. For the portal's steps it used `tools/screenshot.mjs` in the capture browser, signed in as the owner, which needs `npm ci --prefix app/web` once.
- From about 06:00, Microsoft Graph answered the agent sessions' shells on this machine with a continuous access evaluation challenge (`TokenCreatedWithOutdatedPolicies`), which a new sign-in cleared only in visible terminals. So the coordinating session ran Clean up's Microsoft Entra lines and checks in a visible terminal, in the session's folder, from command files that print only masked names. This was the machine's situation, not the README's.
- The fresh setups of [06-release-microsoft](../../06-release-microsoft/evidence/2026-11-12-fresh-setup.md) and 07-operate-microsoft used the same copy at the same time, each in its own resource group.

## Timeline

| UTC | Step | Command | Took | The README says |
| --- | --- | --- | --- | --- |
| 00:36:31 | Clone the copy | `git clone` | 10 s | |
| 00:37:04 | Take later updates (root README) | `git pull --no-rebase --no-edit https://github.com/melabadi/adept-assessment-northstars.git main` | 2 s; a merge commit with git's default message | |
| 00:37:12 | Push them to the copy (root README) | `git push` | 2 s; started *Repository checks*, which passed in 17 s | |
| 00:37:22 | A virtual environment (not in the README) | `python -m venv .venv`, then `.\.venv\Scripts\Activate.ps1` | 14 s | |
| 00:37:37 | Quick start | `pip install -r requirements.txt` | 1 min 49 s | |
| 00:39:49 | Quick start | `azd env new ai-sdlc-secure-fresh --location centralus` | 1 s; stored no subscription (finding 2) | |
| 00:39:58 | Not in the README | `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)` | 2 s | |
| about 02:15 | 1. Create the GitHub token | on GitHub, by the owner | a few minutes, once GitHub had confirmed access | |
| 02:13:41 | Quick start, before the token was stored | `azd up` | 20 min 21 s: provisioning 18 min 11 s, then it stopped while publishing the API's image (finding 3) | about 30 minutes in all |
| 02:40:29 | Not in the README | `azd deploy` | 3 min 7 s; azd counted 2 min 58 s | |
| 02:44:31 | Check the starting state | the README's lines | 17 s; Defender for Cloud: not found | about 5 minutes |
| 02:45 | Check the starting state | the token check | 7 s; `key not found` and HTTP 401: no token yet | |
| 02:45:42 | 3. Check that Azure sees the finding | `python remediation_agent.py try` | 24 s; the agent answered in 9 s; `OK` | |
| 03:23:21 | Quick start | `azd env set POSTURE_GITHUB_TOKEN …`, by the coordinating session | | |
| 03:23:58 | Deploy, for a token stored after `azd up`; with the `azure.yaml` fix of finding 1 | `azd provision` | 6 min 14 s; azd counted 5 min 43 s | 5 to 6 minutes |
| 03:30 | Check the starting state | the token check | 7 s; printed `<owner>/ai-sdlc` | |
| 03:31:12 | Not in the README: does finding 3 recur? | `azd deploy` | 3 min 0 s; azd counted 2 min 53 s; no error | |
| 08:34:44 | Wait for Defender for Cloud | | its first assessment: `Unhealthy`, 6 h 20 min after the storage account was created at 02:14:35, and 6 h 1 min after `azd up` ended | up to a day |
| 13:37:48 | Check the starting state | the README's lines | 22 s; PostgreSQL `Stopped` | about 5 minutes |
| 13:38:22 | Check the starting state | `az postgres flexible-server start …` | 2 min 8 s | 2 to 5 minutes |
| 13:41 | 1. Open the finding | the portal, through `tools/screenshot.mjs` | the Recommendations page took about 25 s to render | about 2 minutes |
| | 2. Ask Azure Copilot | | not run ([also seen](#also-seen-and-left-as-they-are)) | about 2 minutes |
| 14:53:10 | 3. Trigger the automation | **Take action** > **Trigger logic app**, through `tools/screenshot.mjs` | the Logic App run took 80.7 s (finding 4) | about a minute |
| 14:54:17 | 4. Read the Issue and the pull request | Issue #23 at 14:54:17, draft pull request #24 at 14:54:26; the README's commands at 14:57:36 | 4 s | about 3 minutes |
| 14:56:03 | 5. Wait for the preview | | `PASS` 2 min 53 s after the trigger; the job ran 97 s | 1 to 2 minutes after the trigger |
| 14:58:13 | 6. Review, merge, and deploy | `gh pr ready`, `gh pr merge --squash --delete-branch`, `git switch main`, `git pull` | 10 s | |
| 14:58:44 | 6. Review, merge, and deploy | `azd provision` | 6 min 12 s; azd counted 5 min 37 s | 5 to 7 minutes for the step |
| 15:05:13 | 7. Verify | `az rest … verify` | the Issue closed at 15:07:53, 2 min 40 s later | 1 to 15 minutes |
| 15:09 to 17:05 | Later: Defender for Cloud confirms | | not by 17:05, two hours after the deployment | 30 minutes to a day |
| 17:07:06 | Reset the copy, step 1 | `gh pr revert 24` | 3 s; the revert's preview passed at 17:08:31 | |
| 17:08:52 | Reset the copy, step 1 | `gh pr merge 25 --squash --delete-branch`, then `git pull` | 7 s | |
| 17:17:11 | Clean up, steps 1 and 2, by the coordinating session | the agent's Entra lines, then `$app` and `$sp` | 22 s; the deletions 7 s | |
| 17:18:26 | Clean up, as the README said | `azd down --purge` | stopped after 27 s at its question, after the predown hook had deleted the webhook (finding 5) | |
| 17:19:08 | Clean up, step 3 | `azd down --purge --force` | 35 min 53 s; azd counted 35 min 44 s | |
| 17:56:13 | Clean up, step 4, by the coordinating session | `az ad app delete --id $app`, then the purges of `$app` and `$sp` | 6 s | |
| 17:58:22 | Clean up, step 5 | `azd env remove ai-sdlc-secure-fresh --force` | 1 s | |

**The Quick start took 25 minutes 18 seconds**, from `pip install` to the end of the `azd deploy` that finished what `azd up` had started: `pip install` 1 minute 49 seconds, `azd up` 20 minutes 21 seconds, and `azd deploy` 3 minutes 7 seconds. The README said about 30 minutes. The token came after `azd up`, so the provision that stores it added 6 minutes 14 seconds. **Defender for Cloud's first assessment came 6 hours 20 minutes** after the storage account was created; the README said up to a day. **From the click to the verified fix took 14 minutes 43 seconds:** the Issue opened 67 seconds after the click and stayed open 13 minutes 36 seconds, with the review and merge done at once. The README said about 25 minutes for the seven steps, which include reading. Driving the portal for steps 1 and 3 took the session much longer than a person's clicks: it had to find the controls through the browser tool ([also seen](#also-seen-and-left-as-they-are)).

## What didn't match the README, and what changed

**1. `azd up` showed nothing that its hooks printed.** Its output went from the provisioned resources straight to `Running predeploy hook...`; it didn't even name the postprovision hook. Not the repository line or the token warning of the preprovision hook, not the publish and webhook lines that [Deploy](../README.md#2-deploy) quotes, and not the offline tests. The hooks did run: the environment held `GITHUB_REPOSITORY` and `POSTURE_WEBHOOK_SECRET`, Foundry had the agent's version 1 from 02:33:00, and the copy had the webhook from 02:33:03. azd shows a hook that isn't `interactive` in a pane that it clears once the hook succeeds. [`azure.yaml`](../azure.yaml) now makes all four hooks interactive, with a comment saying why, as 01 to 04 did. The provision at 03:23, with that change, printed:

```text
GitHub repository: <owner>/ai-sdlc
...
  (✓) Done: Function App: func-posture-<token> (11.943s)
Foundry agent posture-remediator v1 is up to date.
Webhook <id> in <owner>/ai-sdlc: pull_request events → the Function's preview route (updated).

SUCCESS: Your application was provisioned in Azure in 5 minutes 43 seconds.
```

The `azd deploy` at 03:31 printed the predeploy hook's tests: about 50 lines of messages from the cases they check, failures they provoke on purpose included, then:

```text
----------------------------------------------------------------------
Ran 109 tests in 1.007s

OK (skipped=1)
```

The skipped test reads `/proc`, which only the job's Linux has. And `azd down` printed `Webhook <id> deleted from <owner>/ai-sdlc.` [Deploy](../README.md#2-deploy) now says what the tests and a later provision print, and the README's Troubleshooting explains the pane.

**2. `azd env new` stored no subscription.** As in the fresh setups of 01 to 04, `azd env new ai-sdlc-secure-fresh --location centralus` stored only the environment's name and region, and azd has no default subscription here: `azd up` would have asked which of 87 subscriptions to use. The session stored the one `az` uses, where the README's commands look, with `azd env set AZURE_SUBSCRIPTION_ID (az account show --query id -o tsv)`. Both `azd env new` lines in the README now pass `--subscription (az account show --query id -o tsv)`, and [Deploy](../README.md#2-deploy) says why.

**3. `azd up` stopped while publishing the API's image.** Provisioning succeeded in 18 minutes 11 seconds: RequestHub's platform took 16 minutes 17 seconds, 15 minutes 42 seconds of it for the Container Apps environment, and the posture automation 1 minute 46 seconds. azd then started the two image builds in Azure Container Registry, and 55 seconds later failed:

```text
  api: Failed (step "publish-api" failed: publishing service api: failed publishing service 'api': HEAD https://<host>/<container>/logs/cj1/rawtext.log
RESPONSE 404: 404 The specified blob does not exist.
ERROR CODE: BlobNotFound
```

The registry had queued the API's build, `cj1`, created at 02:33:11, for 5 minutes: it started at 02:38:11 and succeeded at 02:39:59. The worker's build, `cj2`, had started at once and succeeded at 02:34:23. azd asked for the queued build's log before it existed, and gave up. Nothing in the README or the solution causes it. `azd deploy`, at 02:40:29, built both images again, both builds starting at once, and deployed the three services in 3 minutes 7 seconds. It didn't recur: the `azd deploy` at 03:31 built both images at once too, and the two `azd provision` runs build no images. The README's Troubleshooting now names the error and says to run `azd deploy`, and [One-time setup](../README.md#one-time-setup) and the Quick start give the times.

**4. The *Trigger a logic app* pane listed two `posture-intake` Logic Apps.** It lists the Logic Apps in the selected subscription that a recommendation can trigger, by name, subscription, and trigger type only: this environment's, and the live deployment's in `rg-ai-sdlc-secure`. Their links' addresses name their resource groups, and the session selected only the one in `rg-ai-sdlc-secure-fresh` ([the run](#the-run)). Then the run took 80.7 seconds, not about 20: the Function's first try failed with HTTP 502, and the Logic App's retry policy sent the recommendation again a minute later. [Step 3](../README.md#3-trigger-the-automation) now says how to pick the right Logic App, and why a run can take over a minute.

**5. `azd down --purge` stopped at its question.** Its predown hook deleted the webhook first, then azd listed the 19 resources it would delete, asked to confirm, got no answer, and stopped: `ERROR: deleting infrastructure: error deleting Azure resources: user denied delete confirmation`. Nothing in Azure had been deleted. `azd down --purge --force` then removed everything. [Clean up](../README.md#clean-up) now gives `--force` and says what happens without it.

**6. Microsoft Entra: Clean up handled one of the solution's three kinds of objects, and that one partly.**

- **The agent's identities.** When the postprovision hook published `posture-remediator`, at 02:32:58, Foundry created an agent identity blueprint, an app registration that the person who ran `azd up` and the project's managed identity owned, with its principal, and an agent identity: `aif-<token>-secure-posture-remediator-<hex>-AgentIdentityBlueprint` and `aif-<token>-secure-posture-remediator-AgentIdentity`. Three seconds earlier, it had created the project's shared pair, `aif-<token>-secure-AgentIdentityBlueprint`, owned by the project's managed identity alone, and `aif-<token>-secure-AgentIdentity`. `azd down` leaves the agent's pair, as the fresh setups of 01 to 03 found, and the README didn't mention them. [Clean up](../README.md#clean-up) now deletes the agent identity, then the blueprint, before `azd down`, with the lines of [#377](https://github.com/melabadi/adept-assessment-northstars/pull/377), whose `*` needs an agent's name and so leaves the project's pair to Foundry. [`main.bicep`](../infra/main.bicep) outputs no `FOUNDRY_ACCOUNT_NAME` or `FOUNDRY_PROJECT_NAME`, so the lines derive both from `FOUNDRY_PROJECT_ENDPOINT`, which also works for an environment provisioned before this change. Run without the deletions at about 03:35, they selected exactly the agent's identity and its blueprint. At 17:17, the coordinating session ran them: they deleted both in 7 seconds, and only the project's pair was still active afterwards. *Prerequisites* and *What azd up creates* now name the agent's objects.
- **RequestHub's app registration and its service principal.** Clean up deleted and purged the app, but not its service principal, which Entra moves to its recycle bin with the app, as [04-test-microsoft's fresh setup](../../04-test-microsoft/evidence/2026-11-11-fresh-setup.md) found. Clean up now reads `$sp` with `$app`, before `azd down`, and purges it last, as 04's does.
- **The managed identities' principals.** The group's deletion moved six to Entra's recycle bin, between 17:19:56 and 17:20:36: those of the posture Function app, the Foundry account `aif-<token>` and its project, the Logic App's `id-posture-intake-<token>`, the what-if job's `id-github-<token>`, and RequestHub's `id-app-<token>`. Clean up didn't say so. It now does, and cites the fresh setups of 04-test-microsoft and 06-release-microsoft, where Entra refused to purge such principals; this setup didn't try.

**7. Clean up removed the azd environment by the README's name.** `azd env remove ai-sdlc-secure --force` names the README's environment; a reader with another name removes nothing, or someone else's. It now says to use your environment's name, and the session ran it with `ai-sdlc-secure-fresh`.

**8. Smaller.** *Prerequisites* gained the quota check. [Try it first](../README.md#try-it-first-in-a-copy-of-this-repository) now names what the copy's other workflows did with this run's Issue, pull requests, and comments. The README's estimates gave way to the times above in its summary, [How it works](../README.md#how-it-works), [One-time setup](../README.md#one-time-setup), the Quick start, [Check the starting state](../README.md#check-the-starting-state), [How long each step takes](../README.md#how-long-each-step-takes), and [Clean up](../README.md#clean-up). Step 7 says why the Issue can get the evidence twice ([also seen](#also-seen-and-left-as-they-are)). PRESENTING.md's Secure combo gives the Quick start's time and Defender's first assessment.

Checked and found right:

- **`azd up` reached its hooks and didn't stop at `missing required inputs`.** [`main.bicep`](../infra/main.bicep) gives `githubRepository`, `postureGithubToken`, and `postureWebhookSecret` empty defaults, and azd fills its other parameters itself: the environment's name, the region, and the signed-in person's object id. `resources.bicep` and `automation.bicep` get every value without a default from `main.bicep`, and every parameter of the app's modules that azd deploys, in [`app/infra/api.parameters.json`](../../../app/infra/api.parameters.json) and [`worker.parameters.json`](../../../app/infra/worker.parameters.json), comes from the azd environment or `main.bicep`'s outputs, or has a default.
- **A token stored after `azd up`.** As [Deploy](../README.md#2-deploy) says, `azd up` deployed everything without it. The token check in [Check the starting state](../README.md#check-the-starting-state) answered `key not found`, then, after the coordinating session stored the token and the session ran `azd provision`, printed the copy's name. Key Vault's secret and the job's had the token.
- **`remediation_agent.py try` before Defender's first assessment.** It read Defender's missing assessment as none, and the agent's answer passed the Function's checks: `OK: the Function intake would apply this change and open it as a draft pull request.`
- **What the Function did before the steps.** The hourly `verify` answered `not fixed yet: the storage account has no approved private endpoint` each hour. The webhook reported a pull request of 06-release-microsoft's fresh setup, #22 in the copy, which changed only a Markdown file: `preview` answered `not previewed: it does not change the solution's infra/` when it opened, and `not previewed: the pull request is not open` when it merged. When Defender first assessed the posture Function's own storage account, `Healthy`, at 08:34:45, the workflow automation `posture-defender-healthy` sent it through `posture-intake`, and `intake` answered `ignored: another resource or recommendation`.
- **The root README's command for later updates** merged main into the copy, and `git push` sent it.
- **The reset's first step.** The revert's preview passed with one expected change, the virtual network, and listed the private endpoint, its DNS zone link, and the DNS zone as left in place, as [Reset the copy for another run](../README.md#reset-the-copy-for-another-run) says.

## Also seen, and left as they are

- **Step 2 wasn't run.** `tools/screenshot.mjs` opened Azure Copilot's pane, *New Chat with Copilot*, but found no field to type into: not a `textarea`, an editable element, or a field labelled *Message Copilot* in the page, nor a frame whose address names Copilot. This is about how the session drove the portal, not about the README; See it work also shows step 2 from an earlier run.
- **Driving the portal took the session longer than a person.** *Trigger logic app* did nothing when the session clicked it before the page had finished loading, and the pane's rows look alike. The session found its row by the resource group in the row's link, selected it, and checked, before it clicked **Trigger**, that its row read `aria-selected="true"` and the live deployment's `"false"`; the screenshot showed one row checked. The live deployment's `posture-intake` has no run since 11 November.
- **The Function's first try failed in Azure Resource Manager.** `intake failed: Azure Resource Manager answered HTTP 502: InvalidGatewayCertificate`, 1.2 seconds into the call; the retry a minute later read everything and drafted the fix in 17.0 seconds.
- **The preview listed five changes, not four.** Besides See it work's four, it listed RequestHub's storage account, `Modify (2 properties)`, which the agent's description had also expected. It passed: every change was of an expected type.
- **The Issue got the evidence twice.** The hourly `verify` started at 15:00:00, during `azd provision`, found the new private endpoint, and waited for Azure Policy; the session's `verify` started at 15:05:18. Azure Policy evaluated the account `Compliant` at 15:01, and both runs read it at about 15:07:50: they commented the same evidence 5 seconds apart, and the first closed the Issue.
- **The webhook's first delivery timed out.** GitHub pinged the new webhook at 02:33:14, before azd had deployed the Function's code, and gave up after 10 seconds. The pings don't matter to the Function; every pull request delivery after that answered HTTP 200.
- **A tenant policy stopped PostgreSQL** at 05:05:37, about three hours after `azd up` created it, as [Check the starting state](../README.md#check-the-starting-state) warns. The README's command started it in 2 minutes 8 seconds.
- **Defender for Cloud's risk level** for the account was `Low`, as in See it work, and the Issue reported the recommendation's severity, `Medium`.
- **The README's step commands name `rg-ai-sdlc-secure` and `ai-sdlc-secure`,** the README's environment; the session used its own, `ai-sdlc-secure-fresh`.

## The run

**The starting state, at 13:37:48.** PostgreSQL `Stopped`, 0 private endpoints on RequestHub's storage account, the solution's Azure Policy assignment `NonCompliant` for it, no open posture Issue, and Defender for Cloud `Unhealthy`. After the README's `az postgres flexible-server start`, from 13:38:22 to 13:40:30, the server was `Ready`.

**Step 1.** Defender for Cloud's *Recommendations* page, searched for *private link*, listed RequestHub's account under *Storage account should use a private link connection*; its page showed the risk level `Low`, the status `Unassigned`, and **Take action** with *Trigger logic app*. Azure Policy's compliance for *RequestHub: storage accounts should use private link*: `Non-compliant`, 50%, 1 of 2 resources.

**Step 3.** The Logic App run, as Azure recorded it:

| UTC | Action | Result |
| --- | --- | --- |
| 14:53:10.0 | the run, from Defender for Cloud's trigger | started |
| 14:53:10.3 | *Keep only the recommendation* | succeeded |
| 14:53:10.3 to 14:53:13.3 | *Send it to the posture Function*, first try | HTTP 502: Azure Resource Manager's `InvalidGatewayCertificate` |
| 14:54:13.7 to 14:54:30.7 | *Send it to the posture Function*, second try | HTTP 200, `{"issue":23,"filed":true,"agentAttempts":1,"result":"drafted a fix","pullRequest":24,"previewStarted":true}` |
| 14:54:30.8 | the run | succeeded, in 80.7 seconds |

**Step 4.** Issue #23, *Posture: attachment storage in rg-ai-sdlc-secure-fresh has no private endpoint*, labelled `posture`, at 14:54:17, 67 seconds after the click. Draft pull request #24, *Enable the storage private endpoint*, at 14:54:26, from the agent's first answer: between the `posture:editable` markers, two comment lines and `storagePrivateEndpoint: false` became one comment line and `storagePrivateEndpoint: true`. Its description says `Remediates #23` without closing it, and expects six changes: the storage account and the virtual network modified, and a private endpoint, a private DNS zone, its link, and the endpoint's DNS zone group created. The Function linked the pull request on the Issue at 14:54:30.

**Step 5.** The commit status `posture/what-if` went to pending at 14:54:28; the job `posture-whatif` ran from 14:54:29 to 14:56:06, commented at 14:56:02, and set `success` at 14:56:03: *PASS: 5 expected change(s), nothing else*. The comment listed the DNS zone link `vnet-link`, the private endpoint `pe-blob-…`, and its DNS zone group, created; the virtual network `vnet-…`, `Modify (1 property)`; and the storage account `st…`, `Modify (2 properties)`. It left out 10 resources with differences that what-if reports on every run, and named one it can't preview, PostgreSQL's administrators. The webhook's delivery for the new pull request reached `preview` at 14:54:30, which found the commit `already previewed`.

**Step 6.** Marked ready at 14:58:15 and merged at 14:58:17, a squash that deleted the branch. `azd provision`, from 14:58:44 to 15:04:56, created RequestHub's private endpoint `pe-blob-<token>` in 27.8 seconds.

**Step 7.** The `az rest` command returned at 15:05:19. `verify` ran for 161 seconds; the hourly run, started at 15:00:00, for 475. The evidence on #23, at 15:07:52 and 15:07:57: one approved private endpoint, public network access `Disabled`; both Azure Policy assignments, this resource group's and the one inherited from a management group, `Compliant`, as evaluated at 15:01; Defender for Cloud `Unhealthy`, not reassessed since the fix. The Issue closed as completed at 15:07:53.

**Later.** Defender for Cloud still reported the account `Unhealthy`, with its status unchanged since 08:34:44, at 15:09, 15:14, and 17:05; the session stopped waiting then, two hours after the deployment, so no confirmation came.

**The reset's first step.** Revert pull request #25 opened at 17:07:07. Its preview passed at 17:08:31, with one change, the virtual network, `Modify (1 property)`, and the private endpoint, its DNS zone link, and the DNS zone listed as left in place. It merged at 17:08:53. The copy's `resources.bicep` was then as before the run. The reset's other steps weren't needed: the clean-up came next.

## The clean-up, and what is left

Before the clean-up, Microsoft Entra ID held 14 objects of the deployment: the agent's identity, and its blueprint's app registration and principal; the project's shared pair, the same three; RequestHub's app registration `RequestHub (ai-sdlc-secure-fresh)` and its service principal; and the principals of six managed identities.

Clean up's steps 1 and 2, run by the coordinating session at 17:17, deleted the agent's identity and its blueprint in 7 seconds, and read `$app` and `$sp`. `azd down --purge`, as the README wrote it, stopped at its question (finding 5). `azd down --purge --force`, from 17:19:08, found no webhook left to delete, purged the Log Analytics workspace `log-<token>`, and deleted the resource group, the Container Apps environment last; Azure recorded the group deleted at 17:48:54. It then purged the Key Vault `kv-posture-<token>` and the Foundry account `aif-<token>`, and ended with `SUCCESS: Your application was removed from Azure in 35 minutes 44 seconds.` Step 4, at 17:56, deleted RequestHub's app registration and purged it and its service principal. Step 5 removed the local azd environment at 17:58.

Checked between 17:55 and 17:59:

- `az group exists -n rg-ai-sdlc-secure-fresh`: `false`. No resource group named after the environment or the token, the Container Apps environment's managed group `ME_cae-<token>_rg-ai-sdlc-secure-fresh_centralus` included.
- `az cognitiveservices account list-deleted`, `az keyvault list-deleted`, and `az monitor log-analytics workspace list-deleted-workspaces`: nothing named with the token.
- `gpt-6-luna` quota in Central US: 500 of 1,000 in use, as before the setup.
- None of the 11 role assignments in the group's scopes left, none whose scope names the group, none of the deployment's managed identities anywhere, and no policy assignment whose scope names the group. The template assigns every role inside the group. The ten role assignments created elsewhere in the subscription during the setup weren't this setup's: they were created between 13:42 and 13:59, while 07-operate-microsoft's fresh setup ran, nine of them in its resource group.
- No resource tagged `azd-env-name=ai-sdlc-secure-fresh`, and none named with the token, anywhere in the subscription.
- In the copy, no webhook.
- In Microsoft Entra ID, as the coordinating session's checks reported at 17:56: nothing active named after the token or `RequestHub (ai-sdlc-secure-fresh)`. RequestHub's app registration and service principal: neither active nor in the recycle bin. The project's shared pair: neither active nor in the recycle bin, so Foundry removed it with the project, as in 03-develop-microsoft's fresh setup. In the recycle bin: the agent identity, deleted at 17:17:18, the blueprint's app registration and its principal, at 17:17:21, and the six managed identities' principals, from 17:19:56 to 17:20:36.
- The live deployment, untouched: `rg-ai-sdlc-secure` held the same 41 resources as before the clean-up, and its `posture-intake` had last run on 11 November.
- The local azd environment is gone, with its copies of the token and the webhook secret, and the capture browser holds no tab of this session's.

What is left:

- **Four deployment records** at subscription scope, as for every azd deployment: those of `azd up` and the two `azd provision` runs, and the empty one that `azd down` records. They cost nothing. Their `postureGithubToken` and `postureWebhookSecret` parameters keep only their type, `SecureString`, and no value.
- **In Entra's recycle bin,** until Entra removes them, 30 days after 17:17 and 17:20: the agent identity, the blueprint's app registration and principal, and the six managed identities' principals. Clean up doesn't purge them, as its text says.
- **The GitHub token** `ai-sdlc-secure-fresh`, which can read and write the copy's code, Issues, pull requests, and commit statuses. The owner chose to keep it until it expires, on 28 February 2027. Nothing uses it: the Key Vault and the job that held it are gone, and so is the local azd environment.
- **In the copy,** `main` at `c0ecb8c`, with the fix and its revert merged; the closed Issue #23 and the merged pull requests #24 and #25; and the `posture` label, which GitHub created when the Function filed the Issue with it.

## What it cost

The resource group existed from 02:14 until Azure deleted it at 17:48: 15 hours 35 minutes. At list prices:

- the resource group, RequestHub's platform and the posture Function's private endpoints, at about $2 to $3 a day: about $1.30 to $1.95, less while the tenant's policy kept PostgreSQL stopped, from 05:07 to 13:40;
- Defender for Cloud, whose Defender for Storage and Defender CSPM plans are on in this subscription: Defender for Storage at $0.0134 an hour for each of the two storage accounts, about 42 cents, and Defender CSPM at $0.007 an hour for each billable resource, the two storage accounts and the PostgreSQL server, about 33 cents;
- the agent's two answers on `gpt-6-luna`, from `remediation_agent.py try` and from `intake`, at about 6,700 input and 400 output tokens each: under a cent;
- the Function on Flex Consumption, the Logic App's two runs, the what-if job's two executions, Key Vault, and the image builds: cents at most.

So about $2 to $3. In GitHub Actions, the copy ran 17 jobs for 170 seconds because of this run, 17 minutes as billed in a private repository, where each job counts as at least a minute: *Repository checks* for the update's push, the two pull requests, and their merges (10 jobs); *Develop · GitHub · feature bounds* for the two pull requests (2); and the `pre_activation` check of *Design · GitHub · agentic design review* for five comments (5). *Operate · GitHub · agentic incident triage* skipped every job for the Issue. No model ran in GitHub.
