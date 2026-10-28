# AI across the software development lifecycle

Fourteen working demos show how to add AI to each phase of the software development lifecycle (SDLC). Every phase has two offerings, both applied to the same app, [RequestHub](app/README.md):

- **GitHub**: GitHub Copilot (custom agents, skills, the cloud agent, code review) with GitHub Enterprise (Actions, Issues, environments, rulesets, code security).
- **Microsoft**: Microsoft Foundry agents with Azure services (AI Search, Load Testing, Defender for Cloud, Azure Policy, Container Apps, Azure SRE Agent).

Each solution is self-contained, and its README is the demo script: every step has the command or click, a screenshot from a live run, how long it takes, and what to point out. Pick one, open its README, and run it. To plan a session with several demos (formats, what to start early, costs), see [PRESENTING.md](PRESENTING.md).

## The fourteen solutions

| Phase | GitHub | Microsoft |
| --- | --- | --- |
| **1. Plan** | [**Backlog refinement with Copilot**](solutions/01-plan-github/)<br/>A Copilot agent turns a stakeholder transcript into a traceable backlog. Actions validate it and publish GitHub Issues. | [**Requirements analyst in Foundry**](solutions/01-plan-microsoft/)<br/>A Foundry agent turns the same transcript into a requirements brief and backlog, checked by the same rules. |
| **2. Design** | [**Architecture review with Copilot**](solutions/02-design-github/)<br/>A Copilot agent drafts an architecture decision record. Actions check it and the API contract impact on every design pull request. | [**Architecture advisor in Foundry**](solutions/02-design-microsoft/)<br/>An agent grounded in your architecture standards through Azure AI Search reviews a design, scored on labelled cases. |
| **3. Develop** | [**Issue to pull request with the Copilot cloud agent**](solutions/03-develop-github/)<br/>Assign a bounded feature Issue to Copilot. It opens a tested pull request for human review. | [**Triage agent in Foundry**](solutions/03-develop-microsoft/)<br/>RequestHub's triage panel calls a Foundry agent with read-only tools. Every change is evaluated on labelled cases. |
| **4. Test** | [**Regression lab with Copilot**](solutions/04-test-github/)<br/>Copilot reproduces a duplicate-decision defect, writes the failing test, and fixes the code. | [**Performance lab with Azure Load Testing**](solutions/04-test-microsoft/)<br/>An authenticated load test with pass/fail criteria catches an injected slowdown. |
| **5. Secure** | [**Code security remediation**](solutions/05-secure-github/)<br/>Copilot code review flags an injection flaw on a lab branch. The Copilot cloud agent fixes it with a regression test that fails before the fix. CodeQL and Copilot Autofix join on public or licensed repositories. | [**Cloud posture remediation**](solutions/05-secure-microsoft/)<br/>Defender for Cloud and Azure Policy flag a storage misconfiguration. The Bicep fix is previewed with what-if and verified after deployment. |
| **6. Release** | [**Release evidence on GitHub**](solutions/06-release-github/)<br/>A gated release workflow produces release notes, test evidence, and an approval record. | [**Safe rollout on Container Apps**](solutions/06-release-microsoft/)<br/>A candidate revision is tested before promotion. A bad revision is caught and rolled back. |
| **7. Operate** | [**Incident follow-up with Copilot**](solutions/07-operate-github/)<br/>Copilot triages an incident Issue, in an agentic workflow or from Copilot CLI. The Copilot cloud agent then opens a regression-test pull request, proven to fail without the fix. | [**Incident investigation with Azure SRE Agent**](solutions/07-operate-microsoft/)<br/>An alert on the worker's backlog starts an SRE Agent investigation. The agent finds the cause and proposes a fix that runs only after a person approves it. |

## How a solution is packaged

Everything a demo needs lives in its folder. The only shared piece is the app.

```text
solutions/03-develop-microsoft/
├── README.md          what it shows, setup, the demo script, what to observe, how to adopt it
├── .github/           Copilot custom agent, skills, workflows, and issue templates
├── azure.yaml         (Microsoft solutions) azd project for the solution's own resource group
├── infra/             (Microsoft solutions) Bicep for that resource group
├── requirements.txt   Python packages for the solution's scripts
└── ...                scripts, prompts, inputs, and evaluation cases
```

GitHub only reads agents, skills, workflows, and issue templates from the repository's root `.github/` folder. The root therefore holds a synchronized copy of every solution's `.github/` files. Edit the solution's copy, then run `python tools/sync_solutions.py`. A check fails the pull request if the copies drift.

## Before you start

Every solution needs:

- A copy of this repository on GitHub with **GitHub Copilot Business or Enterprise**. Solutions that assign work to Copilot also need the **Copilot cloud agent** enabled for the repository.
- [GitHub CLI](https://cli.github.com/) (`gh auth login`) and [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/set-up/install-copilot-cli) (`copilot`). Visual Studio Code with GitHub Copilot works for the interactive steps too.
- Python 3.12 or later for the solution scripts (`pip install -r requirements.txt` in the solution folder, when it has one).
- [PowerShell 7.4 or later](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (`pwsh`). The READMEs' commands are written for it. Windows PowerShell 5.1 handles quotes and file encodings differently, and some commands fail there.

Microsoft solutions also need:

- An Azure subscription where you can create resource groups, Microsoft Entra app registrations, and role assignments (for example Owner on the subscription).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`) and [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) (`azd auth login`).

Each solution README lists anything else it needs.

## Repository layout

```text
app/         RequestHub: API, worker, web UI, tests, API contract, and the Bicep modules that host it
solutions/   the fourteen solutions, one folder each
tools/       repository tooling: sync_solutions.py (mirror check), screenshot.mjs and redact.py (masked screenshots)
.github/     shared CI, Copilot setup steps and instructions, plus the mirrored solution files
```

## Good to know

- **All data is synthetic.** No real people, customers, credentials, or tenant details appear in the code or the demos.
- **Azure costs stay contained.** Each Microsoft solution deploys into its own resource group, and its README's clean-up steps remove everything it created: `azd down --purge` for the resource group, plus the Microsoft Entra app registration and GitHub environment it set up, which live outside the resource group.
- **Agentic workflows need a Copilot token.** The AI release summary in [06-release-github](solutions/06-release-github/) and the incident triage in [07-operate-github](solutions/07-operate-github/) are GitHub Agentic Workflows. In a personal repository they authenticate with a `COPILOT_GITHUB_TOKEN` secret, a fine-grained personal access token with **Copilot Requests: Read**. Their READMEs show how to create it, and how to carry on with the rest of the demo without it.
- **Some GitHub security features depend on your plan.** CodeQL code scanning (including running CodeQL in a workflow), Copilot Autofix, secret scanning, and push protection are free on public repositories. On a private repository they need GitHub Code Security or GitHub Secret Protection, which require a GitHub Team or Enterprise plan. Solutions that use them say what runs without them.
- **Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md) for how solutions are structured and validated.
