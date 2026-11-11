# AI across the software development lifecycle

Fourteen working solutions add AI to each phase of the software development lifecycle (SDLC). Every phase has two, both applied to the same app, [RequestHub](app/README.md):

- **GitHub**: GitHub Copilot (custom agents, skills, the cloud agent, code review) with GitHub Enterprise (Actions, Issues, environments, rulesets, code security).
- **Microsoft**: AI that runs in Azure. Microsoft Foundry agents and evaluations, Copilot in Azure, and Azure services (AI Search, Load Testing, Defender for Cloud, Azure Policy, Container Apps, Azure SRE Agent), orchestrated in Azure. GitHub only holds the code, pull requests, and Issues.

In every solution, AI does the tedious part and a person keeps the decision. Each solution's README shows a real run, step by step, with its screenshots, timings, and links you can check, and what it measured. Then it shows how to add the solution to your own repository, and how to try it first in a copy of this one.

## The fourteen solutions

| Phase | GitHub | Microsoft |
| --- | --- | --- |
| **1. Plan** | [**Backlog refinement with Copilot**](solutions/01-plan-github/)<br/>A Copilot agent turns a stakeholder transcript into a traceable backlog. Actions validate it and publish GitHub Issues. | [**Requirements analyst in Foundry**](solutions/01-plan-microsoft/)<br/>An Azure Function asks a Foundry agent to draft a brief from the same transcript, scores it with a Foundry evaluation, and publishes the backlog as GitHub Issues after a person approves. |
| **2. Design** | [**Architecture review with Copilot**](solutions/02-design-github/)<br/>A Copilot agent drafts an architecture decision record. Actions check it and the API contract impact on every design pull request. | [**Architecture advisor in Foundry**](solutions/02-design-microsoft/)<br/>A design question filed as an Issue goes to Azure. An Azure Function asks a Foundry agent grounded in your standards through Foundry IQ, checks every citation, and opens an ADR draft. A Foundry evaluation scores the agent on labelled cases. |
| **3. Develop** | [**Issue to pull request with the Copilot cloud agent**](solutions/03-develop-github/)<br/>Assign a bounded feature Issue to Copilot. It opens a tested pull request for human review. | [**Pull request reviewer in Azure**](solutions/03-develop-microsoft/)<br/>Label a pull request: an Azure Function checks it against the team's rules, builds and tests it in an Azure sandbox, and posts a Foundry agent's review. A person still decides. |
| **4. Test** | [**Regression lab with Copilot**](solutions/04-test-github/)<br/>Copilot reproduces a duplicate-decision defect, writes the failing test, and fixes the code. | [**Performance lab with Azure Load Testing**](solutions/04-test-microsoft/)<br/>Azure Load Testing's pass/fail criteria catch an injected slowdown, an Azure Function opens the Issue, and Azure Copilot helps find the cause. |
| **5. Secure** | [**Code security remediation**](solutions/05-secure-github/)<br/>Copilot code review flags an injection flaw on a lab branch. The Copilot cloud agent fixes it with a regression test that fails before the fix. CodeQL and Copilot Autofix join on public or licensed repositories. | [**Cloud posture remediation**](solutions/05-secure-microsoft/)<br/>Defender for Cloud and Azure Policy flag a storage misconfiguration, and Copilot in Azure explains it. An Azure Function asks a Foundry agent for the Bicep fix and opens it as a pull request, previewed with what-if in Azure and verified after a person deploys it. |
| **6. Release** | [**Release evidence on GitHub**](solutions/06-release-github/)<br/>A gated release workflow produces release notes, test evidence, and an approval record. | [**Safe rollout on Container Apps**](solutions/06-release-microsoft/)<br/>Azure builds each merge, and an Azure Function starts its release: a candidate revision, tested before a person promotes it. A bad revision never gets traffic, Azure Copilot helps explain why, and a rollback is one traffic change. |
| **7. Operate** | [**Incident follow-up with Copilot**](solutions/07-operate-github/)<br/>Copilot triages an incident Issue, in an agentic workflow or from Copilot CLI. The Copilot cloud agent then opens a regression-test pull request, proven to fail without the fix. | [**Incident investigation with Azure SRE Agent**](solutions/07-operate-microsoft/)<br/>An alert on the worker's backlog starts an Azure SRE Agent investigation. The agent finds the cause, proposes a fix that runs only after a person approves it, and drafts the incident record for a person to file as a GitHub Issue. |

## How a solution is packaged

Everything a solution needs lives in its folder. The only shared piece is the app.

```text
solutions/04-test-microsoft/
├── README.md          what it does and what it's worth, a real run, how to add it to your repository, and how to try it first
├── .github/           GitHub solutions: Copilot custom agent, skills, workflows, and issue templates. Microsoft solutions: only thin workflow triggers and issue templates
├── azure.yaml         (Microsoft solutions) azd project for the solution's own resource group
├── infra/             (Microsoft solutions) Bicep for that resource group
├── requirements.txt   Python packages for the solution's scripts
└── ...                scripts, prompts, inputs, and evaluation cases
```

GitHub only reads agents, skills, workflows, and issue templates from the repository's root `.github/` folder. The root therefore holds a synchronized copy of every solution's `.github/` files. Edit the solution's copy, then run `python tools/sync_solutions.py`. A check fails the pull request if the copies drift.

## Add a solution to your repository

Each solution works on its own: start with the phase you want to improve.

1. **Check the tools and access** in [Before you start](#before-you-start).
2. **Try it first, if you like,** in [a copy of this repository](#try-it-in-a-copy-of-this-repository), where it runs on RequestHub as in its README's *See it work*, before you adapt anything.
3. **Follow its README's *Add it to your repository*:** what to copy, what to change for your code, and each one-time step, with what you should see when it worked. A Microsoft solution deploys into its own Azure resource group with `azd up`; see [what the Microsoft solutions cost](#what-the-microsoft-solutions-cost).

### Before you start

Every solution needs:

- A GitHub repository: yours, or [a copy of this one](#try-it-in-a-copy-of-this-repository). The GitHub solutions need a paid **GitHub Copilot** plan, and solutions that assign work to Copilot also need the **Copilot cloud agent** allowed in the repository.
- [GitHub CLI](https://cli.github.com/), signed in with the `workflow` scope: `gh auth login --scopes workflow`, or `gh auth refresh --scopes workflow` if you are already signed in. Solutions add workflow files, and GitHub refuses a push of workflow files from a token without that scope. The GitHub solutions also use [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli) (`copilot`); Visual Studio Code with GitHub Copilot works for their interactive steps too.
- Python 3.12 or later for the solution scripts (`pip install -r requirements.txt` in the solution folder, when it has one).
- [PowerShell 7.4 or later](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (`pwsh`). The READMEs' commands are written for it. Windows PowerShell 5.1 handles quotes and file encodings differently, and some commands fail there.

Where the Copilot cloud agent runs RequestHub's tests (03-develop-github, 04-test-github, 05-secure-github, and 07-operate-github), its session must run on GitHub Actions, where [`copilot-setup-steps.yml`](.github/workflows/copilot-setup-steps.yml) starts PostgreSQL. Cloud sandboxes don't run setup steps, and cloud is the default wherever GitHub offers a choice of environment: pick GitHub Actions ([GitHub's comparison](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github#comparison-of-github-actions-based-sessions-and-cloud-sandboxes)).

Microsoft solutions also need:

- An Azure subscription where you can create resource groups, Microsoft Entra app registrations, and role assignments (for example Owner on the subscription).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`) and [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) (`azd auth login`).
- Admin rights on the repository. Each Microsoft solution's setup connects it to GitHub once, limited to that repository: a fine-grained token, a GitHub App, or a webhook.

Each solution README lists anything else it needs.

### Try it in a copy of this repository

To try the solutions on RequestHub before you adapt them, make one copy of this repository for all of them, private or public, in your account or organization (about 2 minutes). In PowerShell 7, with `<owner>` your account or organization:

```powershell
git clone https://github.com/melabadi/adept-assessment-northstars.git ai-sdlc
cd ai-sdlc
git remote remove origin
gh repo create <owner>/ai-sdlc --private --source . --push
git remote -v
```

`git remote -v` lists only `origin`, your copy, so the solutions' scripts and `gh` commands act on it. Don't add this repository back as a remote named `upstream`: `gh` prefers that name over `origin`, and would file your Issues here. To take later updates, pull without a remote: `git pull https://github.com/melabadi/adept-assessment-northstars.git main`. For a public copy, use `--public`, after changing the [settings for a public copy](CONTRIBUTING.md#settings-for-a-public-copy).

The push runs your copy's four push workflows once (CI, Repository checks, Copilot setup steps, and the Secure lab tooling checks): about 5 minutes of GitHub-hosted runners, 10 as billed in a private repository. Nothing else runs until you set a solution up.

Then follow the solution's *Try it first in a copy of this repository*. The runs in the READMEs keep their links to this repository's Issues and pull requests.

When you no longer need your copy, follow the *Clean up* of each solution you tried: a Microsoft solution's clean-up removes its Azure resources and says which GitHub token to revoke. Then delete the copy: `gh auth refresh --scopes delete_repo`, then `gh repo delete <owner>/ai-sdlc --yes`.

## What the Microsoft solutions cost

The GitHub solutions use your Copilot plan and GitHub Actions minutes. The Microsoft solutions bill while their resource groups exist, even when idle:

| Bills by the hour while deployed | Solutions |
| --- | --- |
| A PostgreSQL flexible server and two container apps kept at one replica each (RequestHub) | 04-test, 05-secure, 06-release, and 07-operate (Microsoft) |
| Three private endpoints and their DNS zones, for the planner Function's storage, queue, and Key Vault: about $23 a month, plus up to about $4.50 for its timer, which runs every 30 seconds | 01-plan-microsoft |
| Azure AI Search, Basic tier, and three private endpoints and their DNS zones, for the advisor Function's storage, queues, and Key Vault: about $96 a month | 02-design-microsoft |
| Three private endpoints and their DNS zones, for the reviewer Function's storage and Key Vault: about $23 a month | 03-develop-microsoft |
| Three private endpoints and their DNS zones, for the reporting Function's storage, queue, and Key Vault: about $23 a month | 04-test-microsoft |
| Two private endpoints and their DNS zones, for the posture Function's storage and Key Vault: about $16 a month | 05-secure-microsoft |
| One private endpoint, for the release trigger Function's storage: about $7 a month | 06-release-microsoft |
| Azure SRE Agent: 4 Azure Agent Units (AAUs) an hour while it exists (about $292 a month), plus roughly 10 to 35 AAUs per investigation (capped at 1,000 a month) | 07-operate-microsoft |

Everything else bills for what you use: Foundry models and evaluations, Azure Functions, 05-secure-microsoft's Logic App, Container Apps jobs and dynamic sessions, Azure Load Testing, and Defender for Cloud. Delete a solution's resource group when you won't use it for a while: `azd up` recreates it.

## Repository layout

```text
app/         RequestHub: API, worker, web UI, tests, API contract, and the Bicep modules that host it
solutions/   the fourteen solutions, one folder each
tools/       repository tooling: sync_solutions.py (mirror check), check_links.py (links and anchors), screenshot.mjs and redact.py (masked screenshots)
.github/     shared CI, Copilot setup steps and instructions, plus the mirrored solution files
```

## Good to know

- **All data is synthetic.** No real people, customers, credentials, or tenant details appear in the code or in the runs the READMEs show.
- **Azure costs stay contained.** Each Microsoft solution deploys into its own resource group, and its README's clean-up steps remove everything it created: `azd down --purge` for the resource group, plus any Microsoft Entra app registration, which lives outside it. To revoke a solution's GitHub access, delete its token or GitHub App on GitHub; its README says which.
- **Agentic workflows need a Copilot token.** The AI release summary in [06-release-github](solutions/06-release-github/) and the incident triage in [07-operate-github](solutions/07-operate-github/) are GitHub Agentic Workflows. In a personal repository they authenticate with a `COPILOT_GITHUB_TOKEN` secret, a fine-grained personal access token with **Copilot Requests: Read**. Their READMEs show how to create it, and how to carry on with the rest of the solution without it.
- **Outsiders start nothing that costs you.** On a public repository, Issues, comments, and fork pull requests from people outside it start no model, no Azure resource, and nothing that uses your tokens. Each solution checks who asked where it runs. Before you make a repository with these solutions public, change the settings listed in [CONTRIBUTING.md](CONTRIBUTING.md#settings-for-a-public-copy).
- **Some GitHub security features depend on your plan.** CodeQL code scanning (including running CodeQL in a workflow), Copilot Autofix, secret scanning, and push protection are free on public repositories. On a private repository they need GitHub Code Security or GitHub Secret Protection, which require a GitHub Team or Enterprise plan. Solutions that use them say what runs without them.
- **Presenting the solutions:** [PRESENTING.md](PRESENTING.md) suggests formats and an order, the combos that put a phase's two solutions on one change, and one requirement followed from Plan to Test.
- **Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md) for how solutions are structured and validated.
