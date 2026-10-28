# Develop · Triage agent in Microsoft Foundry

Reviewers in RequestHub route every request by hand. In this solution the app's **Triage assistant** panel calls a Microsoft Foundry agent that recommends a department and priority, citing the routing policies it applied. The agent reads data only through two read-only tools that the app executes with the reviewer's permissions. The app's deterministic guards reject unsafe answers, and people still confirm the routing and make the decision. Every change to the agent is evaluated on 12 labelled cases before it ships.

![RequestHub's page for REQ-1012, a workstation estimated at 7,800: the Foundry agent suggests Finance and cites two routing policies, the app's guard marks it Needs human review, and the History lists the agent's two tool reads](images/03-needs-human-review.png)

## Where it fits

**Phase 3 of 7: Develop.** The GitHub counterpart is [03-develop-github](../03-develop-github/).

| | Today | With this solution |
| --- | --- | --- |
| Building an AI feature | A prompt in the code, checked by trying a few examples. | A versioned agent definition next to the code, published to Foundry only when it changes. |
| Data access | The model sees whatever the prompt includes. | Two read-only tools, scoped to the one request being triaged, executed and audited by the app. |
| Safety | Hope the model behaves. | No approval tool. Guards in the app reject approval claims, unknown policies, and policy conflicts that are not flagged for a person. |
| Quality | Anecdotes. | 12 labelled cases (routing, conflict, ambiguity, missing context, unauthorized access, prompt injection) run on every change. A failing case becomes an Issue. |
| Shipping a change | Redeploy the app to change a prompt. | Publish a new agent version and the app uses it right away. Pull requests are evaluated against a temporary candidate agent first. |

## How it works

```mermaid
sequenceDiagram
  actor R as Reviewer
  participant UI as RequestHub (Container Apps)
  participant F as Foundry agent<br/>requesthub-triage
  R->>UI: Get recommendation (REQ-1001)
  UI->>UI: Check role and department access
  UI->>F: Responses API, managed identity
  F-->>UI: Call get_request and get_routing_policies
  UI->>UI: Run the tools for this request only, write audit entries
  UI-->>F: Permitted fields and policies
  F-->>UI: JSON recommendation with cited policies
  UI->>UI: Guards: known policies, no approval claims, conflicts flagged
  UI-->>R: Suggested department, priority, rationale, citations
  R->>UI: Confirm or change the routing
  Note over R,UI: Only an approver can approve or reject
```

- **Microsoft Foundry** hosts the `requesthub-triage` prompt agent on `gpt-4.1-mini`. [`triage-agent.yaml`](triage-agent.yaml) defines it: instructions, the two tool schemas, and a strict JSON output schema.
- **RequestHub** in Azure Container Apps calls the agent with its managed identity. It executes the tools itself (`ScopedTriageTools` in [`RequestWorkflow.cs`](../../app/src/RequestHub.Core/Services/RequestWorkflow.cs)), applies the guards, and stores the recommendation and an audit entry for every tool call. The guards are code: an answer that claims approval or cites an unknown policy is rejected, and when the cited policies route the request to different departments, the app sets **Needs human review** even if the model did not.
- **GitHub Actions** ([`develop-microsoft-eval.yml`](.github/workflows/develop-microsoft-eval.yml)) publishes and evaluates the agent through OIDC. A pull request gets a temporary candidate agent, an evaluation report as a comment, and the candidate is deleted afterwards. A push to `main` publishes the real agent and opens an Issue for each failing case. The Foundry project endpoint is a GitHub environment secret, so the logs show `***` where the host name would be.
- **People** confirm the routing (reviewers) and approve or reject (approvers). No agent or tool can do either.

## What's in this folder

```text
03-develop-microsoft/
├── README.md
├── triage-agent.yaml                   the Foundry agent: instructions, tools, output schema
├── publish_triage_agent.py             publishes a new agent version only when the definition changes
├── eval_triage.py                      runs the labelled cases through the RequestHub API and checks every result
├── eval_cases.jsonl                    the 12 labelled cases
├── azd_env.py                          reads settings from this solution's azd environment
├── configure_github.py                 azd hooks: connect the solution to GitHub Actions
├── requirements.txt                    Python packages
├── images/                             screenshots from a live run, used in this README
├── azure.yaml                          azd project: infra plus the shared app's api and worker
├── infra/
│   ├── main.bicep                      resource group, RequestHub platform (app/infra), Foundry
│   ├── foundry.bicep                   Foundry account, project, model, Foundry User roles
│   └── main.parameters.json
└── .github/
    ├── agents/develop-microsoft.agent.md   Copilot agent that changes and evaluates the Foundry agent
    ├── skills/
    │   ├── foundry-tools/              how tools are declared, executed, and checked (check_tools.py)
    │   └── triage-evaluation/          how to run and read the evaluation
    └── workflows/develop-microsoft-eval.yml
```

The app itself lives in [`app/`](../../app/README.md). This solution deploys it with the Foundry provider switched on.

## Prerequisites

- An Azure subscription where you can create resource groups, Microsoft Entra app registrations, and role assignments, for example as Owner.
- A region that allows PostgreSQL Flexible Server for the app (the examples use `centralus`) and quota for `gpt-4.1-mini` (Global Standard, 50,000 tokens per minute) in the Foundry region (`eastus2` by default).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd), and the [GitHub CLI](https://cli.github.com/) signed in as a repository admin. The hooks create a GitHub environment and its secrets.
- Python 3.12 or later.
- For the local evaluation: the [.NET 10 SDK](https://dotnet.microsoft.com/download) and PostgreSQL (Docker is easiest, see [`app/README.md`](../../app/README.md#run-it-locally)).

## Set up

Run once, from the repository root:

```powershell
cd solutions/03-develop-microsoft
pip install -r requirements.txt
az login
azd auth login
azd env new ai-sdlc-develop --location centralus
azd up
python publish_triage_agent.py
```

`azd up` takes about 13 minutes. It creates resource group `rg-ai-sdlc-develop` and fills it as follows:

- **RequestHub's platform** from [`app/infra/requesthub.bicep`](../../app/infra/requesthub.bicep): a Container Apps environment, private PostgreSQL with Microsoft Entra authentication only, Blob storage behind a private endpoint, a container registry, Application Insights, and a Microsoft Entra app registration with RequestHub's app roles. You get every role.
- **The app**, deployed as two container apps (API with web UI, and the notification worker). The images are built in the registry, so Docker is not needed.
- **Microsoft Foundry** in `eastus2`: an account, a `develop` project, and `gpt-4.1-mini`. You, the app's managed identity, and the GitHub Actions identity get the **Foundry User** role (formerly Azure AI User).
- **GitHub environment `develop-microsoft`**, created by the hooks. The OIDC sign-in values and the Foundry project endpoint are secrets, which GitHub masks in workflow logs; only the model deployment name, which identifies nothing, is a variable.

`publish_triage_agent.py` publishes `requesthub-triage v1`. Until it runs, the triage panel reports that the assistant is unavailable.

What you should see: `azd up` ends with `SUCCESS`, and its last hook prints `GitHub environment 'develop-microsoft' in <owner>/<repo>: 4 secrets, 1 variables set.` The publish script prints `published new version: requesthub-triage v1 (model gpt-4.1-mini)`, and `unchanged: requesthub-triage v1 (model gpt-4.1-mini)` when you run it again.

The first time you open the app, Microsoft Entra asks you to pick your account and to accept the permissions the RequestHub app registration requests (sign-in and your basic profile).

## Before each session

- [ ] **Confirm the starting state.** From the repository root:

  ```powershell
  $pg = az postgres flexible-server list -g rg-ai-sdlc-develop --query "[0].name" -o tsv
  az postgres flexible-server show -g rg-ai-sdlc-develop -n $pg --query state -o tsv   # Ready
  python solutions/03-develop-microsoft/publish_triage_agent.py                       # unchanged: requesthub-triage v1 (model gpt-4.1-mini)
  gh pr list --head demo/develop-shorter-rationale --state open                       # prints nothing
  gh issue list --label triage-eval --state open                                      # prints nothing
  ```

  - If the server state is `Stopped`, start it: `az postgres flexible-server start -g rg-ai-sdlc-develop -n $pg` takes 3 to 5 minutes. A tenant policy can stop PostgreSQL servers on a schedule, and the app then fails its readiness probe.
  - Run the publish script from an up-to-date `main`. It publishes a new version only when your `triage-agent.yaml` differs from the latest published version, so it normally prints `unchanged`.
  - If a demo pull request or a `triage-eval` Issue is still open, follow [Reset and clean up](#reset-and-clean-up).
  - Reset the demo data (the commands are in [Reset and clean up](#reset-and-clean-up)), then open **REQ-1001** in the app. Its **Triage assistant** shows **No recommendation yet**:

  ![REQ-1001's Triage assistant panel in its starting state: No recommendation yet, and the Get recommendation button](images/00-starting-state.png)

- [ ] **Start the slow parts early.** Sign in to the app once before the audience arrives, so Microsoft Entra's account picker, and the first time its permissions prompt, do not appear on stage. If you show the local evaluation in step 6, start the API in its own terminal a few minutes before: the first build takes about a minute.
- [ ] **Open in advance.**
  - Browser tabs: the app on **REQ-1001** and on **REQ-1012** (get the URL with `azd env get-value API_URL` in this folder). In [ai.azure.com](https://ai.azure.com), the `develop` project's **Agents** page and the **requesthub-triage** agent. On GitHub, **Actions** › **Develop · Microsoft · evaluate the triage agent**.
  - In the editor: [`triage-agent.yaml`](triage-agent.yaml) and [`eval_cases.jsonl`](eval_cases.jsonl).
  - Two PowerShell terminals at the repository root.
- [ ] **Plan the time.** About 20 minutes on stage. The waiting times come from the live runs behind this README:

| Step | On stage | Waiting |
| --- | --- | --- |
| 1. Show the agent | 2 min | the Foundry page loads in about 20 s |
| 2. Get a recommendation | 2 min | about 6 s per recommendation |
| 3. A conflict goes to a person | 2 min | about 6 s |
| 4. Every tool call is audited | 1 min | |
| 5. People route and decide | 1 min | |
| 6. Evaluate the agent | 3 min | about 2 min in GitHub Actions, about 90 s locally |
| 7. Change the agent safely | 4 min | the check takes about 2½ min |
| 8. Ship it, or don't | 2 min | |

## Run the demo

Run the commands from the repository root unless a step says otherwise. The screenshots come from the live run with demo pull request #131 and workflow runs 40728168191 and 40723993656. Your response ids, confidences, and rationales will differ, because the agent answers live every time.

1. **Show the agent.** Open [`triage-agent.yaml`](triage-agent.yaml): the instructions, two tools (`get_request` and `get_routing_policies`), and a strict output schema. Nothing in it can change a request. Then show the same agent as Foundry runs it: in [ai.azure.com](https://ai.azure.com), open the `develop` project (resource group `rg-ai-sdlc-develop`) and select **Build** › **Agents** › **requesthub-triage**. The **Playground** tab shows the model, the instructions, and the two function tools.

   ![The requesthub-triage agent in the Foundry portal's Playground: model gpt-4.1-mini, the instructions from triage-agent.yaml, and the two function tools get_request and get_routing_policies](images/01-agent-in-foundry.png)

   *About 2 minutes.* **Point out:** the agent can only read, through two function tools, and it has no approval tool. Its definition lives in Git next to the code, and Foundry runs the version that the publish script created from it.

2. **Get a recommendation.** Open the app, sign in, and open **REQ-1001** (a replacement laptop). In **Triage assistant**, select **Get recommendation**.

   ![The Triage assistant for REQ-1001: an AI recommendation from foundry-agent with its provider trace, IT Services at High priority with 95% confidence, the rationale, and the cited policy POL-ROUTE-001 v1.2](images/02-recommendation.png)

   *About 6 seconds.* **Point out:** the recommendation cites the policy it applied, `POL-ROUTE-001`, with its version, and **Provider trace** is the Foundry response id, so every answer can be traced back. The note at the bottom says it plainly: recommendations are advisory.

3. **A conflict goes to a person.** Open **REQ-1012**, a workstation estimated at 7,800, and select **Get recommendation**. Two policies disagree: computing equipment goes to IT (`POL-ROUTE-001`), and spend above 5,000 goes to Finance (`POL-ROUTE-004`). The panel shows **Needs human review** and cites both. The agent sometimes flags the conflict itself. When it does not, as in this run, RequestHub's guard does, and says so with `[Guard: ...]` in the rationale.

   ![REQ-1012: the agent suggests Finance citing POL-ROUTE-001 and POL-ROUTE-004, the app's guard marks it Needs human review, and the History lists the agent's two tool reads](images/03-needs-human-review.png)

   *About 2 minutes.* **Point out:** the guard is code in the API (`RecommendAsync` in [`RequestWorkflow.cs`](../../app/src/RequestHub.Core/Services/RequestWorkflow.cs)), not a prompt, so the model's answer cannot skip it.

4. **Every tool call is audited.** Scroll to the request's **History**.

   ![REQ-1012's History: the request submitted by its requester, then Assistant read request data for get_request and for get_routing_policies, and Assistant suggested Finance, all by the signed-in reviewer with one correlation ID](images/04-history.png)

   *About 1 minute.* **Point out:** the agent read this request and the routing policies, and nothing else. Each read is recorded on behalf of the reviewer who asked, with one correlation ID per recommendation.

5. **People route and decide.** Below the **Triage assistant** are the **Routing** and **Decision** panels.

   ![The Routing panel, where a reviewer changes the department with a reason, and the Decision panel with Approve and Reject](images/05-people-decide.png)

   *About 1 minute.* **Point out:** the recommendation has no "apply" button. A reviewer changes the routing, audited and with a reason, and only an approver can approve or reject, never on their own request.

6. **Evaluate the agent.** The evaluation needs several personas, so it runs against RequestHub with the development persona switcher: in GitHub Actions, or on your machine. In GitHub Actions:

   ```powershell
   gh workflow run develop-microsoft-eval.yml
   Start-Sleep -Seconds 5
   $run = gh run list --workflow develop-microsoft-eval.yml --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId'
   gh run watch $run --exit-status
   ```

   The run's **Summary** page shows the report:

   ![The evaluation workflow's job summary: 12/12 runs passed against the live agent, with each case's department, review flag, cited policies, and tool calls](images/06-eval-actions.png)

   Or locally, with PostgreSQL on `localhost:5432`. Start the API in the second terminal and leave it running, then run the evaluation in the first:

   ```powershell
   $env:Triage__Provider = "Foundry"
   $env:Foundry__ProjectEndpoint = (azd env get-value FOUNDRY_PROJECT_ENDPOINT --cwd solutions/03-develop-microsoft)
   dotnet run --project app/src/RequestHub.Api            # second terminal; http://localhost:5080
   python solutions/03-develop-microsoft/eval_triage.py   # first terminal
   ```

   ![The local evaluation in PowerShell: twelve cases from normal routing to prompt injection, all PASS, and 12/12 runs passed](images/06-eval-local.png)

   Each line is one case: routing, conflict, ambiguity, missing context, unauthorized access, and prompt injection. Add `--cases T06,T08 --repeat 3` to show how stable a case is (6/6 in 36 seconds in this run). The local screenshot ran the API on its own port and database, because the machine was shared (see [Troubleshooting](#troubleshooting)). *About 2 minutes in GitHub Actions, and about 90 seconds locally once the API runs.* **Point out:** every case goes through the API, so it checks authorization, the tools, the guards, and that triage changed nothing on the request. T09 and T10 are refused before the agent runs, and T11 and T12 hide instructions in the request text that the agent must ignore.

7. **Change the agent safely.** Make a small change on a branch, here a shorter rationale, and open a pull request:

   ```powershell
   git fetch origin
   git switch -c demo/develop-shorter-rationale origin/main --no-track
   $file = 'solutions/03-develop-microsoft/triage-agent.yaml'
   (Get-Content $file -Raw) -replace 'under 400 characters', 'under 200 characters' | Set-Content $file -NoNewline
   git commit -am "Triage agent: keep the rationale under 200 characters (demo)"
   git push -u origin demo/develop-shorter-rationale
   gh pr create --fill
   ```

   The **Develop · Microsoft · evaluate the triage agent** workflow (check **Publish the agent and evaluate it**) publishes the change as a candidate agent `requesthub-triage-pr-<number>`, runs the 12 cases against it, comments the report on the pull request, and deletes the candidate. The candidate exists for about a minute: refresh the **Agents** page in Foundry once the run's **Publish the agent** step is done.

   ![The develop project's Agents page during the check: the candidate requesthub-triage-pr-131 next to requesthub-triage, both at version 1](images/07-candidate-agent.png)

   ![The evaluation comment on demo pull request #131: candidate agent requesthub-triage-pr-131 evaluated in a linked run, and 12/12 runs passed](images/07-pr-comment.png)

   *About 4 minutes, of which the check takes about 2½.* **Point out:** the change was evaluated live before anyone could merge it, and the app in Azure kept calling `requesthub-triage` the whole time.

8. **Ship it, or don't.** To keep the demo repeatable, close the pull request without merging and delete its branch:

   ```powershell
   gh pr close demo/develop-shorter-rationale --delete-branch
   ```

   The **Agents** page lists only `requesthub-triage`, still at version 1:

   ![The Agents page after the check: only requesthub-triage, still at version 1, because the candidate was deleted](images/08-agents-after.png)

   If you merge instead, the push to `main` publishes `requesthub-triage v2`, evaluates it again, and the app uses it at once, without a redeploy: get a new recommendation for REQ-1001 to see the shorter rationale. Revert the change afterwards; the revert publishes v3 with the original instructions. *About 2 minutes.* **Point out:** only `main` publishes the agent the app calls, and every version is evaluated.

## What to observe

- **The agent never reaches data it should not.** Unauthorized callers are refused before the agent runs (T09, T10). An instruction hidden in a request to read another request is refused by the tool and audited (T12).
- **Advisory only.** The agent has no approval tool. An answer that claims approval or cites an unknown policy is rejected and nothing is saved. Conflicts always go to a person (T06, T08): when the cited policies route a request to different departments, the app's guard sets **Needs human review** even if the model did not (step 3).
- **Measured quality.** Twelve labelled cases with deterministic checks, run on every change, with repeat runs to show variation instead of hiding it.
- **A safe change process.** Pull requests are evaluated against a temporary candidate agent. Only `main` publishes the agent the app uses, and a new version needs no redeploy.
- **No secrets anywhere.** The app uses its managed identity, GitHub Actions uses OIDC, and your terminal uses your Microsoft Entra ID sign-in. The Foundry endpoint is a GitHub environment secret, so workflow logs show `***` instead of resource names.

## Reset and clean up

After each demo, close the demo pull request without merging if step 8 did not, and close any `triage-eval` Issue the evaluation opened:

```powershell
gh pr close demo/develop-shorter-rationale --delete-branch
gh issue list --label triage-eval --state open
gh issue close <number> --reason "not planned"
```

The check deletes its candidate agent itself; the `develop` project's **Agents** page in Foundry lists only `requesthub-triage`. If you merged and reverted, it is now at a higher version, which is fine. To put the app's demo data back to its initial state, run this in the solution folder (you are an Admin):

```powershell
$token = az account get-access-token --scope "$(azd env get-value API_IDENTIFIER_URI)/user_impersonation" --query accessToken -o tsv
curl.exe -s -X POST -H "Authorization: Bearer $token" "$(azd env get-value API_URL)/api/admin/reset"
```

It prints `{"reset":true,"industry":"general","requests":24}`.

When you no longer need the solution:

```powershell
cd solutions/03-develop-microsoft
$app = az ad app show --id (azd env get-value API_CLIENT_ID) --query id -o tsv
azd down --purge
az ad app delete --id $app
az rest --method delete --url "https://graph.microsoft.com/v1.0/directory/deletedItems/$app"
gh api -X DELETE 'repos/{owner}/{repo}/environments/develop-microsoft'
```

`azd down` deletes the resource group. RequestHub's sign-in app registration is a Microsoft Entra object, which no resource group contains, so `az ad app delete` removes it and `az rest` empties it from the recycle bin. Without that last step, a new `azd up` with the same environment name can't create the app registration again for 30 days.

## Use it in your own repository

1. Copy this folder and its `.github/` contents into your repository's `.github/` folder.
2. Describe your agent in `triage-agent.yaml`: instructions, tools with closed schemas, and an output schema. The **foundry-tools** skill explains the rules for tools.
3. Execute the tools in your own API with the caller's permissions and an audit entry, as `FoundryTriageProvider` and `ScopedTriageTools` do in RequestHub. Keep anything that changes data out of the agent's reach.
4. Write labelled cases for your own risks in `eval_cases.jsonl`, and point `azure.yaml` and `infra/main.bicep` at your app.
5. Keep resource names out of public logs: store the Foundry endpoint, and anything else that names a deployed resource, as a GitHub environment secret, as `configure_github.py` does. Variables appear in every workflow step's environment listing.

## Troubleshooting

- **A button in the app fails with HTTP 403 and no body** (the panel says *Something went wrong. Details: HTTP 403*). Container Apps authentication rejects a browser `POST` from an origin that is not in its `login.allowedExternalRedirectUrls` list, and deployments made before #134 lack the app's own origin there. Run `azd deploy api` in this folder from an up-to-date `main`. Calls with a bearer token, such as the reset command, are not affected.
- **The app times out or fails its readiness probe.** Its PostgreSQL server was stopped, for example by a tenant policy that stops servers on a schedule. Start it; it takes 3 to 5 minutes:

  ```powershell
  $pg = az postgres flexible-server list -g rg-ai-sdlc-develop --query "[0].name" -o tsv
  az postgres flexible-server start -g rg-ai-sdlc-develop -n $pg
  ```

- **The triage panel says the assistant is unavailable.** Run `python publish_triage_agent.py` in this folder. If the agent exists, new role assignments can take a few minutes; check the app's logs in Application Insights.
- **The evaluation workflow fails with `FOUNDRY_PROJECT_ENDPOINT is not set`.** An earlier version of this solution stored the endpoint as a GitHub environment variable. In this folder, run `azd hooks run postprovision`: it stores the endpoint as a secret and deletes the variable. If it says `GITHUB_REPOSITORY is not set`, run `azd hooks run preprovision` first.
- **`LocationIsOfferRestricted` for PostgreSQL during `azd up`.** Your subscription cannot create PostgreSQL Flexible Server in that region. Create a new azd environment in another region, for example `centralus`.
- **`AzureCLICredential: exit status 1` from an azd command**, such as `azd up` or `azd env refresh`. azd could not get a token from the Azure CLI in time; the CLI can take more than 10 seconds per token. Run `az account get-access-token`, then run the azd command again.
- **`DeploymentNotFound` or `The project does not exist` right after re-creating the solution.** After `azd down --purge`, re-creating it under the same environment name reuses the same Foundry names, and the project endpoint can keep answering for the deleted account for more than an hour. Create it under a new environment name instead (for example `azd env new ai-sdlc-develop2 --location centralus`, then `azd up` and `python publish_triage_agent.py`).
- **The evaluation stops with `the API uses triage provider 'sample-rules'`.** Start the API with `Triage__Provider=Foundry` and `Foundry__ProjectEndpoint` as in step 6.
- **Port 5080 or the `requesthub` database is already in use**, for example on a shared machine. Give the local API its own: set `$env:ConnectionStrings__RequestHub = "Host=localhost;Port=5432;Database=requesthub_eval;Username=requesthub;Password=devpass"`, add `-- --urls http://localhost:5131` to the `dotnet run` command, and set `$env:REQUESTHUB_API = "http://localhost:5131"` before you run `eval_triage.py`.
