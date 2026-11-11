# Evidence: the model refresh of 11 November 2026

On 11 November 2026, the remediation agent moved from `gpt-5-mini` to `gpt-6-luna`, and the solution's Python packages moved to newer releases. This file records how the change was deployed and the runs that validated it, so that anyone can check them without signing in to Azure. Times are UTC.

- **What changed.** The agent's model went from `gpt-5-mini` version 2025-08-07, which Azure retires on 13 July 2027, to `gpt-6-luna` version 2026-09-22, generally available, which Azure retires on 11 March 2028. Both are Global Standard deployments of 50,000 tokens per minute, with the same low reasoning effort. The packages went to azure-ai-projects 2.10.0 and azure-identity 1.27.0 for the scripts, and to azure-functions 1.26.0 and azure-identity 1.27.0 for the Function. azure-functions 1.26.0 is the newest release for Python 3.12; its 2.x releases need Python 3.13. The agent's instructions, its answer's schema, and the Function's checks didn't change.
- **Who ran it.** A GitHub Copilot agent session working for the repository owner, signed in to Azure and GitHub as the owner, in resource group `rg-ai-sdlc-secure`, from the branch of the pull request that made the change. It ran each command in PowerShell 7 from `solutions/05-secure-microsoft`.
- **On GitHub:** the replay through the Function filed Issue [#335](https://github.com/melabadi/adept-assessment-northstars/issues/335) and opened pull request [#336](https://github.com/melabadi/adept-assessment-northstars/pull/336), with Azure's what-if preview. Both were closed afterwards, and nothing was deployed.
- **Resource names** keep their prefix, with the random token that identifies the deployment replaced by `…`.

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 05:08:44 | The tenant's automation stopped RequestHub's PostgreSQL server | Activity log |
| 14:10:33 to 14:12:50 | Six tries of the agent on `gpt-5-mini`, version 6, before the change (their start times) | [Six tries each](#six-tries-each) |
| 14:18:04 | The operator's start of the server finished; it took 2 minutes 10 seconds | Activity log, terminal |
| 14:18:18 | `azd provision` started, with the new packages | Terminal |
| 14:23:21 | The model deployment `gpt-6-luna` was created | Activity log |
| 14:24:36 | `remediation_agent.py publish`, the postprovision hook, published agent version 7 on `gpt-6-luna` | Foundry's agent versions |
| 14:24:39 | The hook updated the repository webhook | GitHub's webhook record |
| 14:24:40 | `azd provision` ended: *provisioned in 5 minutes 55 seconds* | Terminal |
| 14:25:15 | `azd deploy posture` started, with the Function's new packages: *deployed in 23 seconds* | Terminal |
| 14:26:33 to 14:28:35 | Six tries of the agent on `gpt-6-luna`, version 7 (their start times) | [Six tries each](#six-tries-each) |
| 14:29:56 | The replay: the operator resubmitted the recorded run's Defender for Cloud trigger | [The replay](#the-replay-through-the-function) |
| 14:31:29 | The replay's preview passed | [The replay](#the-replay-through-the-function) |
| 14:35:50 | Pull request #336 was closed without merging, and its branch deleted | GitHub |
| 14:35:53 | Issue #335 was closed as not planned | GitHub |
| 14:36:49 | The model deployment `gpt-5-mini` was deleted, after nothing had called it since the six tries | Activity log, [Azure Monitor](#tokens-and-cost) |
| 14:37:06 | One more try on `gpt-6-luna`, after the deletion: the checks passed | [Six tries each](#six-tries-each) |

The commands, from the solution folder, with this repository's virtual environment first on `PATH`, so that azd's hooks ran with the new packages:

```powershell
$rg = azd env get-value AZURE_RESOURCE_GROUP
pip install -r requirements.txt
az postgres flexible-server start -g $rg -n (az postgres flexible-server list -g $rg --query "[0].name" -o tsv)
azd provision
azd deploy posture
python remediation_agent.py try
az cognitiveservices account deployment delete -g $rg -n (az cognitiveservices account list -g $rg --query "[0].name" -o tsv) --deployment-name gpt-5-mini
```

One webhook delivery failed while `azd provision` ran. At 14:23:02, the deployment wrote this azd environment's webhook secret into Key Vault, as a new version: an earlier provision from another azd environment had stored a different one. The GitHub token's secret, written by the same deployment with an unchanged value, kept its version from 10 November. At 14:23:34, GitHub signed a delivery with the webhook's old secret, and the Function refused it with HTTP 401 `invalid signature`. At 14:24:39, the postprovision hook gave the webhook the new secret, and later deliveries succeeded. The refused delivery reported pull request #331, from another solution, which changes nothing in this solution's `infra/`, so it would not have been previewed.

## Six tries each

`python remediation_agent.py try` builds the document that the Function's `intake` sends the agent, from the live finding, and sends it to the agent's latest version. It then checks the answer with the Function's own code. It deploys nothing and writes nothing to GitHub. The operator ran it six times before the change, on agent version 6 (`gpt-5-mini`), and six times after it, on version 7 (`gpt-6-luna`). Each document had 6,786 input tokens.

*Preview changes named* compares the agent's expected changes with the four changes that Azure's preview showed for this fix, in the recorded run and in the replay: Create the private endpoint, its DNS zone group, and the DNS zone's link to the virtual network, and Modify the virtual network.

| Model | Started | Answered in | Output tokens | The Function's checks | Preview changes named | Its comment above the edited line |
| --- | --- | --- | --- | --- | --- | --- |
| `gpt-5-mini` | 14:10:33 | 11 s | 794 | passed | 3 of 4, not the link | *Reach Blob storage through a private endpoint in the app's virtual network and close the public endpoint.* plus one line |
| `gpt-5-mini` | 14:11:01 | 9 s | 647 | passed | 3 of 4, not the link | *Reach Blob storage through a private endpoint in the app's virtual network and close the public endpoint. This* … (two lines) |
| `gpt-5-mini` | 14:11:29 | 8 s | 616 | passed | 3 of 4, not the virtual network | *Reach Blob storage through a private endpoint in the app's virtual network; close the public endpoint so* … (two lines) |
| `gpt-5-mini` | 14:11:54 | 9 s | 655 | passed | 3 of 4, not the link | *Reach Blob storage through a private endpoint in the app's virtual network and close its public endpoint.* plus one line |
| `gpt-5-mini` | 14:12:22 | 8 s | 668 | passed | 3 of 4, not the virtual network | *Reach Blob storage through the app virtual network using a private endpoint; Azure Policy requires this.* |
| `gpt-5-mini` | 14:12:50 | 8 s | 647 | passed | 2 of 4, not the link or the virtual network | *Reach Blob storage through a private endpoint in the app's virtual network and close the public endpoint.* plus one line |
| `gpt-6-luna` | 14:26:33 | 6 s | 262 | passed | 3 of 4, not the virtual network | *Use a private endpoint for Blob traffic and disable the storage account's public endpoint.* |
| `gpt-6-luna` | 14:26:56 | 6 s | 258 | passed | 3 of 4, not the virtual network | *Route Blob storage privately and disable its public endpoint to comply with the private link policy.* |
| `gpt-6-luna` | 14:27:19 | 6 s | 271 | passed | 3 of 4, not the virtual network | *Enable the module's private Blob endpoint so the storage account is reachable privately and complies with policy.* |
| `gpt-6-luna` | 14:27:43 | 6 s | 285 | passed | 4 of 4 | *Use the module's private endpoint so Blob traffic stays on the app's virtual network and the storage account's* … (two lines) |
| `gpt-6-luna` | 14:28:09 | 6 s | 276 | passed | 4 of 4 | *Use a private endpoint so storage has an approved private link and remains reachable from the app's virtual network.* |
| `gpt-6-luna` | 14:28:35 | 7 s | 269 | passed | 4 of 4 | *Use the module's private Blob endpoint and private DNS so the storage account is reachable privately.* |
| `gpt-6-luna`, after the deletion | 14:37:06 | 7 s | 271 | passed | 3 of 4, not the virtual network | *Create a private endpoint so Blob traffic uses the app's virtual network and the storage account's public endpoint is closed.* |

- **The same fix every time.** Every answer, on both models, decided to change `storagePrivateEndpoint` from `false` to `true` and replaced the comment above it, between the `posture:editable` markers, and every one passed the Function's checks on the first try.
- **The expected changes.** In the six tries each, the `gpt-6-luna` answers named 3.5 of the preview's four changes on average, and the `gpt-5-mini` answers 2.8. The recorded run's answer, in pull request [#224](https://github.com/melabadi/adept-assessment-northstars/pull/224), named 2, and the replay's, in #336, 3. Every answer on both models also expected a new private DNS zone, and all but the recorded one a modified storage account. Neither appears in the preview: the zone already exists, for the posture Function's own storage, and the account's public endpoint is already closed. The agent reads only the Bicep, not the deployed state. That is why the preview, not the agent, says what a deployment would do.
- **The titles.** `gpt-5-mini`: *Enable private endpoint for storage account* (three times), *Enable private endpoint for storage*, and *Enable storage private endpoint for RequestHub* (twice). `gpt-6-luna`: *Enable the storage private endpoint* (six of its seven answers here) and *Enable the storage account private endpoint* (once, and in the replay).

## The replay through the Function

To run the whole path on the new model, the operator resubmitted the trigger of the recorded run's Logic App run, `08584081827396975775796129199CU16`. Resubmitting sends the same Defender for Cloud recommendation through `posture-intake` again. The Function then read the recommendation again from Azure and found it still `Unhealthy`, and found no private endpoint, as on 31 October:

```powershell
$wf = "/subscriptions/{subscriptionId}/resourceGroups/$(azd env get-value AZURE_RESOURCE_GROUP)/providers/Microsoft.Logic/workflows/posture-intake"
az rest --method post --url "$wf/triggers/Defender_recommendation/histories/08584081827396975775796129199CU16/resubmit" --url-parameters api-version=2016-06-01
```

| UTC | What happened | Source |
| --- | --- | --- |
| 14:29:57.5 | The Logic App run `08584071994880179503933012216CU04` started | Logic App run history |
| 14:29:58 | The Function's `intake` started; it answered after 15.8 seconds | Application Insights |
| 14:30:00 | Issue #335 was filed, 2.5 seconds after the run started | GitHub |
| 14:30:09 | Draft pull request #336 was opened, 11.5 seconds after the run started, from the agent's first answer | GitHub |
| 14:30:12 | `posture/what-if` was set to pending on its commit | [GitHub's API](https://api.github.com/repos/melabadi/adept-assessment-northstars/commits/d354bd0d94dbcee34401c9d100e24e01c1d7950b/statuses) |
| 14:30:13 | The `posture-whatif` job's execution `posture-whatif-0kpiglx` started | Job execution history |
| 14:30:14.2 | The Logic App run ended, after 16.7 seconds | Logic App run history |
| 14:30:12.6 | The webhook's delivery for #336 reached `preview`, which answered at 14:30:14 that the commit was already being previewed | Application Insights |
| 14:31:29 | `posture/what-if` turned to success, *PASS: 4 expected change(s), nothing else*, 91.5 seconds after the run started | GitHub's API |
| 14:31:34 | The job's execution ended, after 81 seconds | Job execution history |

The Function's answer, the output of the Logic App's step *Send it to the posture Function*: `{"issue":335,"filed":true,"agentAttempts":1,"result":"drafted a fix","pullRequest":336,"previewStarted":true}`.

The Function's log, from Application Insights:

| UTC | Message |
| --- | --- |
| 14:30:14 | `intake: drafted a fix` |
| 14:30:14 | `preview of pull request #336 (pull_request.opened): already previewed` |

The agent's pull request, [#336](https://github.com/melabadi/adept-assessment-northstars/pull/336), made the recorded run's one-value change, with the comment *Enable the module's private Blob endpoint and close the storage account's public endpoint.* It expected a new private endpoint, DNS zone group, DNS zone link, and DNS zone, and a modified storage account. Azure's [preview](https://github.com/melabadi/adept-assessment-northstars/pull/336#issuecomment-6798573824) showed the same four changes as the recorded run's, each expected, and passed.

## Tokens and cost

Azure Monitor's token counts for the Foundry account, by model deployment, in one-minute totals:

```powershell
$id = az cognitiveservices account list -g (azd env get-value AZURE_RESOURCE_GROUP) --query "[0].id" -o tsv
az monitor metrics list --resource $id --metric InputTokens OutputTokens cacheReadInputTokens --start-time 2026-11-11T14:08:00Z --end-time 2026-11-11T14:45:00Z --interval PT1M --aggregation Total --filter "ModelDeploymentName eq '*'" -o table
az monitor metrics list --resource $id --metric InputTokens OutputTokens cacheReadInputTokens --start-time 2026-10-31T05:10:00Z --end-time 2026-10-31T05:30:00Z --interval PT1M --aggregation Total --filter "ModelDeploymentName eq '*'" -o table
```

| Calls | Deployment | Input tokens | Output tokens | Cached input tokens |
| --- | --- | --- | --- | --- |
| The recorded run's agent call, 31 October (Azure Monitor's 05:23 total) | `gpt-5-mini` | 6,783 | 771 | none |
| The six tries before the change | `gpt-5-mini` | 40,716 | 4,027 | none |
| The six tries after the change | `gpt-6-luna` | 40,716 | 1,621 | none |
| The replay's agent call | `gpt-6-luna` | 6,786 | 271 | none |
| The try after the deletion | `gpt-6-luna` | 6,786 | 271 | none |

Azure Monitor's totals equal the tokens the tries printed. List prices, per million tokens, for Global Standard deployments in Central US, from the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Foundry%20Models%27%20and%20armRegionName%20eq%20%27centralus%27) (meters *GPT 5 Mini … Glbl* and *6-luna ShortCo … Std Gl*):

| Model | Input | Cached input | Output | One answer here |
| --- | --- | --- | --- | --- |
| `gpt-5-mini` | $0.25 | $0.025 | $2.00 | $0.0032 in the recorded run (6,783 and 771 tokens); $0.0030 on average in the tries |
| `gpt-6-luna` | $0.10 | $0.01 | $0.50 | $0.0008 in the replay (6,786 and 271 tokens), and on average in the tries |

An answer on `gpt-6-luna` cost about a quarter of one on `gpt-5-mini`. The whole validation cost about $0.025 in tokens: $0.018 for the six `gpt-5-mini` tries and $0.0065 for the eight `gpt-6-luna` calls. The rest bills per use, at a small cost: one Logic App run, one job execution of 81 seconds, and the Function's executions.
