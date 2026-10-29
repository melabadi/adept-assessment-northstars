# Contributing

This repository holds fourteen independent solutions built on one shared app. This guide explains how a solution is put together, so every solution looks and works the same way.

## Ground rules

- **Human approval is sacred.** Only a person with the Approver role approves or rejects a request. No agent, tool, or workflow gets an approval path.
- **Never weaken a test, guard, or validation to make a check pass.** Fix the code, or explain in the pull request why the test is wrong.
- **The API contract `requesthub.v1` only grows.** Additive changes only; regenerate [`app/contracts/openapi.json`](app/contracts/openapi.json) and say so in the pull request.
- **Synthetic data only.** No real people, customers, secrets, tenant ids, or subscription ids in code, docs, or commit messages.
- **Demos are live.** A demo passes only when it ran against the real service (Copilot, Foundry, Azure). Mocks, fixtures, and canned output are fine in tests, never as demo evidence.
- **AI helps the people, not the product.** Every demo shows AI helping the people who plan, design, build, test, secure, release, and operate RequestHub. No demo is about an AI feature inside RequestHub.

## Two tracks, two toolsets

- **GitHub solutions** show GitHub Copilot and GitHub Enterprise: Copilot custom agents, skills, the cloud agent, code review, Copilot CLI, GitHub Actions, Issues, and environments.
- **Microsoft solutions** show AI that runs in Azure: Microsoft Foundry agents, knowledge, and evaluations; Copilot in Azure; Azure Load Testing; Defender for Cloud and Azure Policy; Azure SRE Agent. Their orchestration lives in Azure too: Logic Apps, Azure Monitor alerts and action groups, Event Grid, Container Apps jobs, scheduled tests. From GitHub they use only the code, pull requests, Issues, and a thin GitHub Actions trigger where Azure has no native trigger. They ship no Copilot agents, skills, or instructions, and no step of a Microsoft demo depends on GitHub Copilot.
- When an Azure service needs GitHub access (for example a Logic Apps GitHub connection or Azure SRE Agent's GitHub connector), a person authorizes it once, with the least access that works: this repository only, and only the permissions the demo uses.

## Anatomy of a solution

```text
solutions/<NN>-<phase>-<github|microsoft>/
├── README.md                     follows the outline below
├── .github/                      GitHub solutions: agent, skills, workflows, issue templates. Microsoft solutions: only thin workflows and issue templates
│   ├── agents/<phase>-<track>.agent.md
│   ├── skills/<skill>/SKILL.md   plus the skill's scripts and reference files
│   ├── instructions/<name>.instructions.md   optional path-specific Copilot instructions (for example for code review)
│   ├── workflows/<phase>-<track>-*.yml
│   └── ISSUE_TEMPLATE/<NN>-<phase>-<track>-*.yml
├── azure.yaml                    Microsoft solutions: azd project for the solution's resource group
├── infra/                        Microsoft solutions: main.bicep (subscription scope) and parameters
├── requirements.txt              Python packages for the solution's scripts
└── ...                           scripts, prompts, inputs, evaluation cases
```

1. **Self-contained.** Everything the demo needs lives in its folder. The exceptions are the app (`app/`) and the Bicep modules that host it (`app/infra/`). Small helpers are copied into each solution that needs them rather than shared.
2. **Root `.github/` is a mirror.** GitHub only reads agents, skills, instructions, workflows, and issue templates from the root `.github/` folder. Edit the solution's copy, then run `python tools/sync_solutions.py`. For files generated at the root, such as `gh aw compile` output, copy them back with `python tools/sync_solutions.py --pull <path>`. The *Repository checks* workflow fails if the copies drift.
3. **Unique names.** Two solutions may only ship a file with the same path if the contents are identical. Name workflows `<phase>-<track>-<what>.yml` (for example `test-microsoft-load.yml`) with a display name such as `Test · Microsoft · load test RequestHub`, issue templates `<NN>-<phase>-<track>-<what>.yml`, and agents `<phase>-<track>`.
4. **Paths.** Workflows and agents refer to solution files by their repository path (`solutions/03-develop-microsoft/...`). Skills refer to their own files through `.github/skills/<skill>/...`, which works both here and in an adopter's repository.
5. **Repository-wide files belong to no solution:** `.github/copilot-instructions.md`, `.github/workflows/ci.yml`, `.github/workflows/copilot-setup-steps.yml`, and `.github/workflows/repo-checks.yml`.
6. **Workflows only act on their own demo.** Every workflow in this repository sees every pull request. A solution's pull-request workflow must recognize its own demo (paths inside its solution folder, a `lab/<phase>-*` base branch, or an Issue labeled `phase:<phase>`) and skip, never fail, everything else. A check that fails on another solution's demo pull request is a defect.

## Microsoft solutions on Azure

Each Microsoft solution is its own [azd](https://learn.microsoft.com/azure/developer/azure-developer-cli/) project, deployed from its folder into its own resource group.

- **Names.** azd environment `ai-sdlc-<phase>` (for example `ai-sdlc-develop`), resource group `rg-ai-sdlc-<phase>`, GitHub environment `<phase>-microsoft`.
- **`infra/main.bicep`** is subscription-scoped. It creates the resource group and deploys the solution's resources into it through modules.
- **GitHub Actions sign in with OIDC**, never with stored credentials. The solution's Bicep creates a user-assigned identity with a federated credential for its GitHub environment. Repositories that use immutable OIDC subjects (this one does) pass the subject prefix from `gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix`.
- **The GitHub environment** holds `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` as secrets, and so is every value that names a deployed resource: endpoints, host names, URLs, and resource names with their random suffix. GitHub masks secrets wherever they appear in a log; variables are printed in every step's environment listing, and anyone can read the logs of a public repository. Variables are only for values that identify nothing, such as a model deployment name. An azd `postprovision` hook publishes them from the azd outputs, so `azd up` leaves both Azure and GitHub ready.
- **Workflows and reports never print tenant details.** Before a step that may print a derived value (a host name without its `https://`, a subscription name), mask it with `echo "::add-mask::$value"`. Job summaries, artifacts, Issues, and comments use names such as "the API" and placeholders instead of host names, resource names, or GUIDs.
- **Scripts** read settings from environment variables first, then from the solution's azd environment (`azd env get-values`, run in the solution folder). Nobody has to export values by hand after `azd up`.

### Solutions that run RequestHub

Compose the shared hosting module and point the `api` and `worker` services at the shared deploy-time modules:

```bicep
module app '../../../app/infra/requesthub.bicep' = {
  name: 'requesthub'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    githubRepository: githubRepository
    githubOidcSubjectPrefix: githubOidcSubjectPrefix
    githubEnvironment: 'test-microsoft'
    automationRoleDefinitionIds: []   // extra roles on the resource group, only if the workflows need them
    tags: tags
  }
}
```

```yaml
# azure.yaml
services:
  api:
    project: ../../app
    language: docker
    host: containerapp
    module: ../../../app/infra/api        # relative to this solution's infra/ folder
    docker: { path: ./Dockerfile, context: ., remoteBuild: true }
  worker:
    project: ../../app
    language: docker
    host: containerapp
    module: ../../../app/infra/worker
    docker: { path: ./Dockerfile.worker, context: ., remoteBuild: true }
```

`main.bicep` must output the values that [`app/infra/api.parameters.json`](app/infra/api.parameters.json) and [`worker.parameters.json`](app/infra/worker.parameters.json) read: `AZURE_CONTAINER_REGISTRY_ENDPOINT`, `AZURE_CONTAINER_REGISTRY_NAME`, `AZURE_CONTAINER_ENVIRONMENT_NAME`, `APP_IDENTITY_ID`, `APP_IDENTITY_CLIENT_ID`, `APP_IDENTITY_NAME`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `POSTGRES_HOST`, `POSTGRES_DATABASE`, `STORAGE_BLOB_ENDPOINT`, `API_APP_NAME`, `WORKER_APP_NAME`, `API_URL`, `API_CLIENT_ID`, `API_IDENTIFIER_URI`, and `AUTOMATION_CLIENT_ID`. Optional: `FOUNDRY_PROJECT_ENDPOINT`, `TRIAGE_PROVIDER`, `DEMO_INDUSTRY`.

In its cleanup, a solution that runs RequestHub must also delete the Microsoft Entra app registration that `requesthub.bicep` creates for sign-in: `azd down` deletes the resource group, but no resource group contains Microsoft Entra objects. Delete it and empty it from the recycle bin, as [06-release-microsoft](solutions/06-release-microsoft/README.md#reset-and-clean-up) does, or the next `azd up` with the same environment name cannot create it again for 30 days.

## Python scripts

- Start with a module docstring that says what the script does and how to run it. `--help` documents every option.
- Use the standard library plus packages pinned in the solution's `requirements.txt` (Python 3.12+).
- Print readable progress for the presenter. Write machine-readable results under the solution's `out/` folder, which git ignores.
- Keep wrapper scripts to a minimum. Prefer a documented `gh`, `az`, `azd`, or `copilot` command when one exists.

## Solution READMEs

Write for someone who has never seen the repository and will present the demo to an audience. Be complete: every step says what to do, what appears on screen (with a screenshot), and what to point out. No project-status sections. Write commands for PowerShell 7 (`pwsh`) and paste-test them; quote `gh api` paths that contain `{owner}/{repo}`, because PowerShell reads unquoted braces as a script block.

1. **Title and summary.** One paragraph: the problem and what AI changes. Follow it with the one screenshot that best shows the result.
2. **Where it fits.** The SDLC phase, and how teams work today compared with this solution.
3. **How it works.** A diagram (Mermaid renders on GitHub) and who does what: Copilot or Foundry, GitHub Actions or Azure, and the human.
4. **What's in this folder.** An annotated file tree.
5. **Prerequisites.**
6. **Set up.** One-time steps, copy-paste ready, with what you should see when each one worked.
7. **Before each session.** A checklist: how to confirm the demo is in its starting state, what to open in advance (tabs, terminals, files), what to start early because it takes long (Copilot sessions, deployments, load tests), and the timings.
8. **Run the demo.** Numbered steps. Each step has the click path or command, a screenshot of what appears, how long it takes, and **Point out:** the one thing the audience should notice.
9. **What to observe.** The impact to point out to the audience.
10. **Reset and clean up.**
11. **Use it in your own repository.** What to copy and what to change.
12. **Troubleshooting.** Only problems someone actually hit.

## Screenshots

Screenshots go in the solution's `images/` folder, named after the step they illustrate (`images/05-proof-check.png`), and are linked with alt text that says what the image shows: `![The proof check: the new test fails before the fix and passes after it](images/05-proof-check.png)`. Capture them from a real run of the demo.

**Capture every screenshot with [`tools/screenshot.mjs`](tools/screenshot.mjs)**, never with another screenshot tool. It masks what identifies your tenant and account before the image is saved: your subscription and tenant, your account and tenant domain, resource host names and the unique tokens in resource names, GUIDs, e-mail addresses, and user profile paths. It refuses to save an image when anything is left, and reads every image back with OCR. One-time setup:

```powershell
npm ci --prefix app/web                      # Playwright, used by the tool
pip install pillow                           # image check and compression
python tools/redact.py init                  # your redaction list, stored outside the repository
node tools/screenshot.mjs browser            # a separate Chrome profile: sign in to GitHub and Azure there
```

Run `python tools/redact.py init` again after you deploy a solution, so its new resources are on the list. Then:

```powershell
# A web page (GitHub, the Azure portal, the Foundry portal, RequestHub): crop to the part that matters.
node tools/screenshot.mjs page "https://github.com/<owner>/<repo>/pull/12" solutions/04-test-github/images/05-proof-check.png `
  --selector ".merge-status-list" --width 1200
# Command output, rendered as a terminal window.
gh pr checks 12 *> out.txt
node tools/screenshot.mjs terminal solutions/04-test-github/images/05-checks.png --input out.txt --title "PowerShell 7"
```

`node tools/screenshot.mjs` without arguments lists every option. Steps (`--wait`, `--click`, `--select`, `--type`, `--press`, `--frame`) run in the order you give them, so you can open a pane, type a question, press Enter, and wait for the answer, for example to capture Azure Copilot. Then `--selector`, `--clip`, or `--full` chooses what to capture; `--remove` and `--pick-account` help with clutter and sign-in.

In the Azure portal, crop below the top bar (`--clip` or `--selector`): it shows your account and directory, and a crop keeps them out even if masking misses one. Prefer deeper pages to the portals' Home and Overview pages, which show endpoints and subscription details.

Before you commit, run `python tools/redact.py check --changed`; it must print `OK`. It checks every image and every text file, whatever its extension, and lists any other binary file for you to look at. Then look at every image yourself, and make sure each caption says only what its image shows. A pushed commit stays reachable through its pull request even after you remove the file, so an image must be clean before its first push. The same rule applies to text: never paste host names, subscription or tenant details, or e-mail addresses into Issues, pull requests, or comments.

## Definition of done

A solution is done when:

- The demo runs end to end against the real services, following its README from a clean state.
- Every step of *Run the demo* that shows something on screen has a screenshot from a real run, captured with `tools/screenshot.mjs`, and `python tools/redact.py check --changed` prints `OK`.
- The *Repository checks* workflow passes, and the app's CI passes if the app changed.
- The pull request links the live evidence: workflow runs, Issues and pull requests the demo created, evaluation results, and screenshots where they help. When a step only works from the default branch (issue templates, label- or dispatch-triggered workflows), run it right after merging and add the evidence as a comment on the pull request.
- It ships in its own pull request.
