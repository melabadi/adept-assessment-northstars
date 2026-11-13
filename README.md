# AI across the software development lifecycle

Fourteen working solutions add AI to each phase of the software development lifecycle (SDLC). Every phase has two, both applied to the same app, [RequestHub](app/README.md):

- **GitHub**: GitHub Copilot, with GitHub Enterprise.
- **Microsoft**: AI that runs in Azure, with Microsoft Foundry, Azure Copilot, and Azure services. GitHub only holds the code, pull requests, and Issues.

In every solution, AI does the tedious part and a person keeps the decision. Each solution's README says what it uses, what it does and how it works, how to install it in your repository, and which files to edit to tweak it, then shows a real run.

## Technologies used

**GitHub solutions**

| Technology | What it does in the solutions | Used by |
| --- | --- | --- |
| [Copilot cloud agent](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github) | Works on an Issue unattended, on its own branch, and opens a pull request for a person to review | 01, 02, 03, 04, 05, 07 |
| [Custom agents](https://docs.github.com/en/copilot/concepts/customizations/custom-agents) and [agent skills](https://docs.github.com/en/copilot/concepts/customizations/agent-skills) | Give Copilot each solution's role, rules, procedures, and scripts | All seven |
| [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-cli) | Runs the same agents from a terminal | 01, 02, 03, 04, 06, 07 |
| [Copilot code review](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-code-review) | Reviews a pull request: an ADR, a fix, or a security repair | 02, 04, 05 |
| [GitHub Agentic Workflows](#the-agentic-workflows) | Run Copilot on a GitHub event, with read-only access and only the writes the workflow allows | 02, 04, 06, 07 |
| [GitHub Actions](https://docs.github.com/en/actions) | Runs the checks that decide, and Copilot's sessions | All seven |
| Issues, with [issue forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms) and labels | Start the work: notes to refine, a design question, a feature, a defect, a remediation, or an incident | 01, 02, 03, 04, 05, 07 |
| [Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) | Make the checks required before a merge | 03, and optionally 02 |
| [Environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-protection-rules) and GitHub Container Registry | Gate the release's approval, and hold its images | 06 |
| CodeQL and Copilot Autofix | Optional code scanning, on public or licensed repositories | 05 |

**Microsoft solutions**

| Technology | What it does in the solutions | Used by |
| --- | --- | --- |
| [Microsoft Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/overview) | Hosts each solution's agent, published from a file in the repository | 01, 02, 03, 05 |
| [Foundry evaluations](https://learn.microsoft.com/azure/foundry/concepts/observability) | Score an agent's answers with code-based checks | 01, 02, 03 |
| Foundry IQ and Azure AI Search | Ground the advisor's answers in your standards, with each team's access enforced | 02 |
| [Azure Functions](https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan), on the Flex Consumption plan, in Python | Orchestrate each solution's runs in Azure | 01, 02, 03, 04, 05, 06 |
| [Azure Container Apps dynamic sessions](https://learn.microsoft.com/azure/container-apps/sessions) and jobs | Sandboxes that check and build a pull request; jobs that preview a fix and run each release step | Sessions in 03; jobs in 05 and 06 |
| Azure Load Testing | Runs the user journey and judges it against pass/fail criteria | 04 |
| Defender for Cloud and Azure Policy | Find the misconfiguration | 05 |
| Azure Copilot | Explains a finding, a failed revision, or the telemetry to a person in the portal | 04, 05, 06 |
| Azure SRE Agent | Investigates an alert and proposes a fix that runs only after a person approves it | 07 |
| Event Grid and Azure Container Registry tasks | Build every commit of `main` and start its release | 06 |
| [Key Vault](https://learn.microsoft.com/azure/key-vault/general/overview) and [private endpoints](https://learn.microsoft.com/azure/private-link/private-endpoint-overview) | Keep each Function's storage, and its secrets where it has any, off the internet | 01, 02, 03, 04, 05, 06 |
| [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/) and [Bicep](https://learn.microsoft.com/azure/azure-resource-manager/bicep/overview) | Deploy each solution into its own resource group with `azd up` | All seven |
| GitHub: a fine-grained token, a GitHub App, or a webhook | The one connection each solution makes to your repository | All seven |

## What the solutions do and how they work

### The fourteen solutions

| Phase | GitHub | Microsoft |
| --- | --- | --- |
| **1. Plan** | [**Backlog refinement with Copilot**](solutions/01-plan-github/)<br/>A Copilot agent turns a stakeholder transcript into a traceable backlog. Actions validate it and publish GitHub Issues. | [**Requirements analyst in Foundry**](solutions/01-plan-microsoft/)<br/>An Azure Function asks a Foundry agent to draft a brief from the same transcript, scores it with a Foundry evaluation, and publishes the backlog as GitHub Issues after a person approves. |
| **2. Design** | [**Architecture review with Copilot**](solutions/02-design-github/)<br/>An [agentic workflow](#the-agentic-workflows) answers `/design-review` with the standards that apply, their conflicts, and whether a change needs an architecture decision record (ADR). A Copilot agent drafts the ADR, and Actions check it and its API contract impact on every design pull request. | [**Architecture advisor in Foundry**](solutions/02-design-microsoft/)<br/>A design question filed as an Issue goes to Azure. An Azure Function asks a Foundry agent grounded in your standards through Foundry IQ, checks every citation, and opens an ADR draft. A Foundry evaluation scores the agent on labelled cases. |
| **3. Develop** | [**Issue to pull request with the Copilot cloud agent**](solutions/03-develop-github/)<br/>Assign a bounded feature Issue to Copilot. It opens a tested pull request for human review. | [**Pull request reviewer in Azure**](solutions/03-develop-microsoft/)<br/>Label a pull request: an Azure Function checks it against the team's rules, builds and tests it in an Azure sandbox, and posts a Foundry agent's review. A person still decides. |
| **4. Test** | [**Regression lab with Copilot**](solutions/04-test-github/)<br/>Copilot reproduces a duplicate-decision defect, writes the failing test, and fixes the code. When CI fails on the fix's pull request, an [agentic workflow](#the-agentic-workflows) explains each failure: a new test failing as intended, a regression, or a failure that isn't the change's. | [**Performance lab with Azure Load Testing**](solutions/04-test-microsoft/)<br/>Azure Load Testing's pass/fail criteria catch an injected slowdown, an Azure Function opens the Issue, and Azure Copilot helps find the cause. |
| **5. Secure** | [**Code security remediation**](solutions/05-secure-github/)<br/>Copilot code review flags an injection flaw on a lab branch. The Copilot cloud agent fixes it with a regression test that fails before the fix. CodeQL and Copilot Autofix join on public or licensed repositories. | [**Cloud posture remediation**](solutions/05-secure-microsoft/)<br/>Defender for Cloud and Azure Policy flag a storage misconfiguration, and Azure Copilot explains it. An Azure Function asks a Foundry agent for the Bicep fix and opens it as a pull request, previewed with what-if in Azure and verified after a person deploys it. |
| **6. Release** | [**Release evidence on GitHub**](solutions/06-release-github/)<br/>A gated release workflow produces release notes, test evidence, and an approval record. An [agentic workflow](#the-agentic-workflows) summarizes the evidence for the person who approves. | [**Safe rollout on Container Apps**](solutions/06-release-microsoft/)<br/>Azure builds each merge, and an Azure Function starts its release: a candidate revision, tested before a person promotes it. A bad revision never gets traffic, Azure Copilot helps explain why, and a rollback is one traffic change. |
| **7. Operate** | [**Incident follow-up with Copilot**](solutions/07-operate-github/)<br/>An [agentic workflow](#the-agentic-workflows) triages an incident Issue in about 5 minutes, or Copilot CLI drafts the triage for a person to file. The Copilot cloud agent then opens a regression-test pull request, proven to fail without the fix. | [**Incident investigation with Azure SRE Agent**](solutions/07-operate-microsoft/)<br/>An alert on the worker's backlog starts an Azure SRE Agent investigation. The agent finds the cause, proposes a fix that runs only after a person approves it, and drafts the incident record for a person to file as a GitHub Issue. |

### How a solution is packaged

Everything a solution needs lives in its folder. The only shared piece is the app.

```text
solutions/04-test-microsoft/
├── README.md          what it uses and does, how to install it and which files to edit, a real run, and how to try it first
├── .github/           GitHub solutions: Copilot custom agent, skills, workflows, and issue templates. Microsoft solutions: at most an issue form
├── azure.yaml         (Microsoft solutions) azd project for the solution's own resource group
├── infra/             (Microsoft solutions) Bicep for that resource group
├── requirements.txt   Python packages for the solution's scripts
└── ...                scripts, prompts, inputs, and evaluation cases
```

GitHub only reads agents, skills, workflows, and issue templates from the repository's root `.github/` folder. The root therefore holds a synchronized copy of every solution's `.github/` files.

### The agentic workflows

Four of the GitHub solutions add a [GitHub Agentic Workflow](https://github.com/github/gh-aw): a Markdown file that GitHub Agentic Workflows (gh-aw), [generally available](https://github.blog/changelog/2026-10-28-github-agentic-workflows-generally-available) since 28 October 2026, compiles into a GitHub Actions workflow that runs Copilot. Each starts on a GitHub event, gives Copilot only what it should read, and applies only the few writes the workflow allows. None can push code, approve, merge, or publish: a person still decides.

| Solution and workflow | Starts when | Copilot reads | It can write | Measured |
| --- | --- | --- | --- | --- |
| [02-design-github](solutions/02-design-github/)<br/>*Design · GitHub · agentic design review* | Someone with write access comments `/design-review` on an Issue that your team filed, or on a pull request that your team or Copilot opened from a branch of the repository | The approved standards, the brief, and the API contract from the default branch; a pull request's diff and the contract tool's verdict; Issues and pull requests through read-only GitHub tools that show only your team's content | One comment, and the labels `adr-needed` and `standards-conflict` | About 5 minutes from the command to the review, and 19 to 24 AI credits for Copilot, in [three reviews](solutions/02-design-github/README.md#the-agentic-design-review-recorded-on-11-november-2026) |
| [04-test-github](solutions/04-test-github/)<br/>*Test · GitHub · agentic CI failure investigation* | CI fails on a fix's pull request that your team or Copilot opened from a branch of the repository | Facts that a script from the default branch collects: each failing test's message and line, whether the pull request adds the test, and whether it fails on main too; the logs and the diff; no GitHub tools | One comment, and one of the labels `ci:defect-reproduced`, `ci:regression`, or `ci:infrastructure` | About 5 minutes from CI's failure to the comment, or 10 to 11 when it waited behind another run, and 13.3 to 15.2 AI credits for Copilot, in [four runs](solutions/04-test-github/README.md#10-added-since-an-agentic-workflow-explained-two-red-ci-runs-11-november-2026) |
| [06-release-github](solutions/06-release-github/)<br/>*Release · GitHub · agentic release summary* | A release candidate that a person started succeeds | The candidate's evidence and the release's pull requests, with a title only where your team or Copilot wrote it, collected by a script from the default branch; no GitHub tools | One summary, appended to the draft release | 4 min 52 s, starting 3 s after the candidate, and 15.28 AI credits for Copilot, in [the recorded run](solutions/06-release-github/README.md#3-copilot-appended-a-summary-for-the-approver) |
| [07-operate-github](solutions/07-operate-github/)<br/>*Operate · GitHub · agentic incident triage* | An Issue that your team filed gets the `incident` label | The incident and the code, through read-only GitHub tools and shell commands | One comment, labels from an allow-list, and one follow-up Issue | 4 min 52 s from filing to the triage comment, and 23.84 AI credits for Copilot, in [the recorded run](solutions/07-operate-github/README.md#2-the-agentic-workflow-triaged-it) |

*Your team* means the repository's owner, members, and collaborators: each workflow checks who wrote the text before Copilot reads it. The four also share gh-aw's protections. Only people with write access start a run. Copilot works with a read-only token, behind a firewall that allows only gh-aw's default hosts. Threat detection checks what Copilot asks to write, and a run it flags writes nothing. Each run stops at an AI-credit cap set from measured usage, and threat detection used about 1 AI credit or less a run.

**What they need.** The `gh aw` extension of GitHub CLI at the version the solutions pin, v1.2.2 (`gh extension install github/gh-aw --pin v1.2.2`), to compile a workflow after you change it: each solution's checks fail a pull request whose compiled workflow isn't what v1.2.2 compiles from its source. And a `COPILOT_GITHUB_TOKEN` repository secret, which the four share: a fine-grained personal access token with **Copilot Requests: Read**, whose owner's Copilot plan pays for the runs. In an organization with centralized Copilot billing, `copilot-requests: write` in a workflow's permissions can replace the token. Each of the four READMEs shows how to create the token, and how to use the rest of its solution without it.

## Install a solution in your repository

Each solution works on its own: start with the phase you want to improve.

### Getting started

1. **Check your tools** against [Before you start](#before-you-start). Each line prints a version:

   ```powershell
   gh --version; gh auth status                                         # every solution; the token's scopes include workflow
   python --version; $PSVersionTable.PSVersion.ToString()               # every solution: 3.12 or later, and 7.4 or later
   copilot --version                                                    # the GitHub solutions
   gh aw version                                                        # the four agentic workflows: v1.2.2 compiles them
   "az: " + (az version | ConvertFrom-Json).'azure-cli'; azd version   # the Microsoft solutions
   ```

2. **Choose a solution** in [Choose where to start](#choose-where-to-start): what it needs, what your code must already have, how long its setup took, and the metric to track. A Microsoft solution deploys into its own Azure resource group with `azd up`: see [what the Microsoft solutions cost](#what-the-microsoft-solutions-cost).
3. **Try it first, if you like,** in [a copy of this repository](#try-it-in-a-copy-of-this-repository), where it runs on RequestHub before you change anything.
4. **Follow its README's install steps.** [03-develop-github](solutions/03-develop-github/README.md#getting-started) and [03-develop-microsoft](solutions/03-develop-microsoft/README.md#getting-started) list them as commands in order, under *Getting started*: copy the files on a new branch, edit them for your code, set them up once, merge, and use it. The other READMEs have the same steps under *Add it to your repository*. Keep [the licence](#license) with the files, and note the commit you copied from, to [take updates later](#take-updates-later).
5. **Edit the files to tweak it** as your team learns: [Files you edit to tweak a solution](#files-you-edit-to-tweak-a-solution) names the ones that matter most.

### Before you start

Every solution needs:

- A GitHub repository: yours, or [a copy of this one](#try-it-in-a-copy-of-this-repository). The GitHub solutions need a paid **GitHub Copilot** plan, and solutions that assign work to Copilot also need the **Copilot cloud agent** allowed in the repository.
- [GitHub CLI](https://cli.github.com/), signed in with the `workflow` scope: `gh auth login --scopes workflow`, or `gh auth refresh --scopes workflow` if you are already signed in. Solutions add workflow files, and GitHub refuses a push of workflow files from a token without that scope. The GitHub solutions also use [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli) (`copilot`); Visual Studio Code with GitHub Copilot works for their interactive steps too.
- Python 3.12 or later for the solution scripts (`pip install -r requirements.txt` in the solution folder, when it has one).
- [PowerShell 7.4 or later](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) (`pwsh`). The READMEs' commands are written for it. Windows PowerShell 5.1 handles quotes and file encodings differently, and some commands fail there.

Microsoft solutions also need:

- An Azure subscription where you can create resource groups, Microsoft Entra app registrations, and role assignments (for example Owner on the subscription).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`) and [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) (`azd auth login`).
- Admin rights on the repository. Each Microsoft solution's setup connects it to GitHub once, limited to that repository: a fine-grained token, a GitHub App, or a webhook.

[Choose where to start](#choose-where-to-start) lists what else each solution needs.

### Choose where to start

Each row links to the solution's install steps. *Setup* is what its README measured, and the metric is the one it suggests you track when you adopt it.

**GitHub solutions**

| Solution | Needs, beyond [Before you start](#before-you-start) | Your code or process must have | Setup | Metric to track |
| --- | --- | --- | --- | --- |
| [01-plan-github](solutions/01-plan-github/README.md#add-it-to-your-repository) | Copilot, with the cloud agent or Copilot CLI | Notes whose paragraphs and policies have ids a brief can cite | Copy 15 files, install one Python package, three labels, a settings page, and a pull request | Lead time from a request to a reviewed, published backlog |
| [02-design-github](solutions/02-design-github/README.md#add-it-to-your-repository) | Copilot, with code review and the cloud agent or Copilot CLI; for `/design-review`, gh-aw and `COPILOT_GITHUB_TOKEN` | Approved standards in Markdown, each with an id, a version, and a scope; an OpenAPI contract, for the API impact report | Copy 13 files, write down your standards, four labels, compile the agentic design review, a token, and a pull request | Time from a design question to a reviewable ADR with green checks |
| [03-develop-github](solutions/03-develop-github/README.md#install-it-in-your-repository) | Copilot, with the cloud agent in a session on GitHub Actions | A CI workflow that runs your tests on pull requests | Copy 10 files, two labels, a settings page, a pull request, and a ruleset | Lead time from a feature Issue to a pull request that passes its checks |
| [04-test-github](solutions/04-test-github/README.md#add-it-to-your-repository) | Copilot, with code review and the cloud agent in a session on GitHub Actions; for the CI failure investigation, gh-aw and `COPILOT_GITHUB_TOKEN` | An API you can run with a test sign-in, integration tests, and CI on pull requests | Copy 19 files, labels, a settings page, a token, and a pull request | Lead time from a defect report to a proven fix |
| [05-secure-github](solutions/05-secure-github/README.md#add-it-to-your-repository) | Copilot, with code review and the cloud agent in a session on GitHub Actions; GitHub Code Security for the optional CodeQL path on a private repository | Integration tests with a disposable database, and deployments that exclude `lab/secure-*` and `copilot/*` | Copy the package and adapt it; not timed outside RequestHub | Time from detection to an independently verified repair |
| [06-release-github](solutions/06-release-github/README.md#add-it-to-your-repository) | GitHub Container Registry, and an environment that can restrict branches; Copilot only for the AI parts | A release built as container images, and test suites that write JUnit XML | Copy 18 files, an environment and its reviewers, a token, and a pull request | Lead time from a release candidate to a published release |
| [07-operate-github](solutions/07-operate-github/README.md#add-it-to-your-repository) | Copilot, with the cloud agent in a session on GitHub Actions; gh-aw and `COPILOT_GITHUB_TOKEN`, or Copilot CLI | Tests that a GitHub-hosted runner can run, with your database as a service | Copy 12 files, a token, 14 labels, a settings page, and a pull request | Time from an incident to a proven regression test |

**Microsoft solutions.** Each also needs an Azure subscription where you can create a resource group and role assignments, for example as Owner.

| Solution | Needs, beyond [Before you start](#before-you-start) | Your code or platform must have | Setup | Metric to track |
| --- | --- | --- | --- | --- |
| [01-plan-microsoft](solutions/01-plan-microsoft/README.md#add-it-to-your-repository) | Quota for `gpt-6-luna`, 50,000 tokens per minute; a fine-grained token for the repository | Notes and policies in Markdown, with ids a brief can cite | 13 minutes, timed in a fresh setup | Time from a workshop's notes to an approved backlog |
| [02-design-microsoft](solutions/02-design-microsoft/README.md#add-it-to-your-repository) | Quota for `gpt-6-luna`, 250,000 tokens per minute, and for Azure AI Search Basic; a GitHub App you can create and install; admin rights on the repository | Approved standards, one file per standard, and design questions whose right answers you know | About half an hour, 20 minutes of it for Azure AI Search to start | Time from a design question to a reviewable ADR draft |
| [03-develop-microsoft](solutions/03-develop-microsoft/README.md#install-it-in-your-repository) | Quota for `gpt-6-luna`, 150,000 tokens per minute; admin rights on the repository; the Azure Developer CLI 1.37 or later | A build and tests that run on Linux in a fresh shell | About 15 minutes | Time from the label to the first review |
| [04-test-microsoft](solutions/04-test-microsoft/README.md#add-it-to-your-repository) | The Azure CLI's `load` extension; a Microsoft Entra role that can assign your API's app roles; Azure Copilot | An API in Azure with Entra ID sign-in and app roles, Application Insights, and a way to delete what a test creates | About 20 minutes | Performance regressions caught before release, and the time from a regression to its Issue |
| [05-secure-microsoft](solutions/05-secure-microsoft/README.md#add-it-to-your-repository) | Quota for `gpt-6-luna`, 50,000 tokens per minute; Defender for Cloud; Azure Copilot; the Azure CLI 2.76 or later; admin rights on the repository | Your app's Azure resources in Bicep, deployed with azd, with the fix as a module parameter | About 30 minutes, then up to a day for Defender for Cloud to assess new resources | Time from a finding to a verified fix |
| [06-release-microsoft](solutions/06-release-microsoft/README.md#add-it-to-your-repository) | Admin rights on the repository, for the build task's token; Azure Copilot | An API on Azure Container Apps in multiple-revision mode, with a readiness probe, an endpoint that reports its commit, Entra ID sign-in, and Log Analytics | About 15 minutes | Failed builds that reached users, and the time to restore service |
| [07-operate-microsoft](solutions/07-operate-microsoft/README.md#add-it-to-your-repository) | A region that offers Azure SRE Agent; optionally, a read-only token for your code | A service in Azure with Application Insights and a metric that shows the problem | About 20 minutes | Time from an alert to a proposed mitigation, and to its resolution |

### Adopt several solutions

Each solution works on its own, and several can share one repository. They share these pieces:

- **Labels.** The GitHub solutions, and 07-operate-microsoft, create `ai-sdlc` with the same command, and each phase adds its own `phase:<phase>` label. `gh label create --force` updates a label that already exists.
- **One token for the agentic workflows,** `COPILOT_GITHUB_TOKEN`: see [what they need](#the-agentic-workflows).
- **Skills.** `contract-impact` comes with 02-design-github, 03-develop-github, and 04-test-github, and `regression-validation` with 03-develop-github and 04-test-github. The copies are identical, so copying a second solution writes the same files again.
- **Copilot's environment.** 03-develop-github, 04-test-github, 05-secure-github, and 07-operate-github run your tests in Copilot's session, which one `copilot-setup-steps.yml` prepares for all of them.

The two solutions of a phase can also work on one change: [Solution combos](PRESENTING.md#solution-combos) lists what passes between them and who decides. [Follow one requirement from Plan to Test](PRESENTING.md#follow-one-requirement-from-plan-to-test) takes one decision from a stakeholder's notes through Develop and Test.

### Take updates later

A solution's copy step prints the commit it copied from. To see what changed in the solution since then, list the pull requests that touched its folder, and the files they changed:

```powershell
$copied = '<the commit you copied from>'
$solution = 'solutions/03-develop-github'
$src = Join-Path ([IO.Path]::GetTempPath()) 'ai-sdlc-updates'
git clone --quiet https://github.com/melabadi/adept-assessment-northstars.git $src
git -C $src log --oneline "$copied..main" -- $solution
git -C $src diff --stat $copied main -- $solution
Remove-Item -Recurse -Force $src
```

Each commit on `main` is one pull request, titled after what it changed, with its number. Bring what you want into your edited copy by hand, or copy the solution again on a new branch and compare it with yours.

## Files you edit to tweak a solution

Each row links to the solution's full list, with what each setting does as shipped and what to change it to.

| Solution | The files that shape it most |
| --- | --- |
| [01-plan-github](solutions/01-plan-github/README.md#what-to-copy-and-what-to-change) | Your notes and policies; the agent, `plan-github.agent.md`, and its `requirements-traceability` skill; the backlog's schema and validator |
| [02-design-github](solutions/02-design-github/README.md#what-to-copy-and-what-to-change) | Your standards; the agent, `design-github.agent.md`; the ADR template; the agentic design review, `design-github-agentic-review.md` |
| [03-develop-github](solutions/03-develop-github/README.md#files-to-edit-to-tweak-it) | The agent, `develop-github.agent.md`; the boundary checker, `scope_check.py`; the test runner, `run_regression.py` |
| [04-test-github](solutions/04-test-github/README.md#what-to-copy-and-what-to-change) | The agent, `test-github.agent.md`; the scenario runner, `repro.py`; the proof, `prove_fix.py`; the CI failure investigation, `test-github-ci-investigation.md` |
| [05-secure-github](solutions/05-secure-github/README.md#what-to-copy-and-what-to-change) | The agent, `secure-github.agent.md`; the replay check, `verify_remediation.py`, and its workflow, `secure-github-verify.yml`; your lab's patch and regression test |
| [06-release-github](solutions/06-release-github/README.md#what-to-copy-and-what-to-change) | The release candidate workflow, `release-github-candidate.yml`; the evidence, `release_evidence.py`; the smoke test, `smoke_test.py` |
| [07-operate-github](solutions/07-operate-github/README.md#what-to-copy-and-what-to-change) | The agentic triage, `operate-github-incident-triage.md`; the agent, `operate-github.agent.md`; the severity rubric; the proof, `prove_regression.py` |
| [01-plan-microsoft](solutions/01-plan-microsoft/README.md#what-to-copy-and-what-to-change) | Your notes and policies; the agent, `agent.yaml`; the evaluators, and the gates in `function/planner/checks.py` |
| [02-design-microsoft](solutions/02-design-microsoft/README.md#what-to-copy-and-what-to-change) | Your standards; the agent and its profiles, `agent.yaml`; the labelled cases, `eval_cases.jsonl` |
| [03-develop-microsoft](solutions/03-develop-microsoft/README.md#files-to-edit-to-tweak-it) | The rule checker, `sandbox/review_rules.py`; the build and tests, `sandbox/run_change.sh`; the agent, `reviewer-agent.yaml`; the labelled cases |
| [04-test-microsoft](solutions/04-test-microsoft/README.md#what-to-copy-and-what-to-change) | The user journey, `loadtest/locustfile.py`; its pass/fail criteria, `requesthub-journey.yaml`; the guardrails, `sync_test.py`; the report's query, `report.kql` |
| [05-secure-microsoft](solutions/05-secure-microsoft/README.md#what-to-copy-and-what-to-change) | Your Bicep, `infra/resources.bicep`; the agent's instructions, `posture-remediator.md`; the checks of its edit, `function/posture/checks.py`; the preview, `whatif.py` |
| [06-release-microsoft](solutions/06-release-microsoft/README.md#what-to-copy-and-what-to-change) | The release steps and smoke test, `release.py`; the build, `acr-build.yaml`; your platform, in `infra/main.bicep` |
| [07-operate-microsoft](solutions/07-operate-microsoft/README.md#what-to-copy-and-what-to-change) | The alert, `infra/monitoring.bicep`; the agent, `sre-agent/agent.yaml` and `instructions.md`; its skills and runbook |

Whichever solutions you adopt, three files of your own shape them too: `.github/copilot-instructions.md`, your repository's instructions for Copilot; `.github/workflows/copilot-setup-steps.yml`, Copilot's environment; and your CI workflow, whose tests the checks rely on.

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

Everything else bills for what you use: Foundry models and evaluations, Azure Functions, 05-secure-microsoft's Logic App, Container Apps jobs and dynamic sessions (03-develop-microsoft's Shell session pools, which are in preview), Azure Load Testing, and Defender for Cloud. Delete a solution's resource group when you won't use it for a while: `azd up` recreates it.

## Good to know

- **Azure costs stay contained.** Each Microsoft solution deploys into its own resource group, and its README's clean-up steps remove everything it created: `azd down --purge` for the resource group, plus any Microsoft Entra app registration, which lives outside it. To revoke a solution's GitHub access, delete its token or GitHub App on GitHub; its README says which.
- **Outsiders start nothing that costs you.** On a public repository, Issues, comments, and fork pull requests from people outside it start no model, no Azure resource, and nothing that uses your tokens. Each solution checks who asked where it runs. Before you make a repository with these solutions public, change the settings listed in [CONTRIBUTING.md](CONTRIBUTING.md#settings-for-a-public-copy).
- **Some GitHub security features depend on your plan.** CodeQL code scanning (including running CodeQL in a workflow), Copilot Autofix, secret scanning, and push protection are free on public repositories. On a private repository they need GitHub Code Security or GitHub Secret Protection, which require a GitHub Team or Enterprise plan. Solutions that use them say what runs without them.

## License

The [MIT License with the Commons Clause](LICENSE). You may download, fork, use, and change the solutions and RequestHub, including at work, and share them free of charge. You may not sell them, or sell hosting, consulting, or support whose value comes entirely or substantially from them. Keep the LICENSE file with anything you copy: every copy must carry its notice. Because it forbids selling, it is a source-available license, not an open source license as the [Open Source Initiative defines one](https://opensource.org/osd).

When you copy a solution, put the LICENSE file where it travels with the files without replacing your own: `.github/LICENSE-ai-sdlc` for a GitHub solution, or `LICENSE` in a Microsoft solution's folder, as the copy steps of [03-develop-github](solutions/03-develop-github/README.md#getting-started) and [03-develop-microsoft](solutions/03-develop-microsoft/README.md#getting-started) do. GitHub reads a repository's own licence only from its root, so yours doesn't change.

## See them work, and try them in a copy

Each solution's README shows a real run, step by step, in *See it work*, what it measured, in *Results and value*, and how to repeat it on RequestHub, in *Try it first in a copy of this repository*. [PRESENTING.md](PRESENTING.md) suggests how to present them: formats, an order, the combos that put a phase's two solutions on one change, and one requirement followed from Plan to Test.

- **All data is synthetic.** No real people, customers, credentials, or tenant details appear in the code or in the runs the READMEs show.
- **Commit ids changed on 11 November 2026.** The repository's history was rewritten that day to change commit author metadata, which gave every earlier commit a new id. Screenshots, logs, and evidence captured before then show the old ids; the links point to the same commits under their new ids.

### Try it in a copy of this repository

To try the solutions on RequestHub before you adapt them, make one copy of this repository for all of them, private or public, in your account or organization. In PowerShell 7, with `<owner>` your account or organization:

```powershell
git clone https://github.com/melabadi/adept-assessment-northstars.git ai-sdlc
cd ai-sdlc
git remote remove origin
gh repo create <owner>/ai-sdlc --private --source . --push
git remote -v
```

`git remote -v` lists only `origin`, your copy, so the solutions' scripts and `gh` commands act on it. Don't add this repository back as a remote named `upstream`: `gh` prefers that name over `origin`, and would file your Issues here. For a public copy, use `--public`, after changing the [settings for a public copy](CONTRIBUTING.md#settings-for-a-public-copy).

To take later updates, pull without a remote, then push them to your copy:

```powershell
git pull --no-rebase --no-edit https://github.com/melabadi/adept-assessment-northstars.git main
git push
```

`--no-rebase` merges the updates with any commits your copy's `main` has of its own, such as the one 02-design-microsoft's step 1 merges: with git's default settings, a plain `git pull` stops there with `Need to specify how to reconcile divergent branches`. `--no-edit` keeps the merge's default message. The push matters to the solutions that read files from your copy's `main`, such as 02-design-microsoft's standards and 03-develop-microsoft's rule checker. A copy with the ruleset of the [settings for a public copy](CONTRIBUTING.md#settings-for-a-public-copy) refuses a push to `main`: there, run `git switch -c updates` before the pull, then `git push -u origin updates`, `gh pr create --base main --fill`, and `gh pr merge --merge --delete-branch`. Merge with a merge commit, not a squash, which would drop the shared history and make the next pull merge the same updates again.

The push can run your copy's four push workflows once (CI, Repository checks, Copilot setup steps, and the Secure lab tooling checks), each only when the push changes files it watches: at most about 5 minutes of GitHub-hosted runners, 10 as billed in a private repository. Nothing else runs until you set a solution up.

Then follow the solution's *Try it first in a copy of this repository*. The runs in the READMEs keep their links to this repository's Issues and pull requests.

When you no longer need your copy, follow the *Clean up* of each solution you tried: a Microsoft solution's clean-up removes its Azure resources and says which GitHub token to revoke. Then delete the copy: `gh auth refresh --scopes delete_repo`, then `gh repo delete <owner>/ai-sdlc --yes`.
