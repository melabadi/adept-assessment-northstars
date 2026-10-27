# Contributing

This repository holds fourteen independent solutions built on one shared app. This guide explains how a solution is put together, so every solution looks and works the same way.

## Ground rules

- **Human approval is sacred.** Only a person with the Approver role approves or rejects a request. No agent, tool, or workflow gets an approval path.
- **Never weaken a test, guard, or validation to make a check pass.** Fix the code, or explain in the pull request why the test is wrong.
- **The API contract `requesthub.v1` only grows.** Additive changes only; regenerate [`app/contracts/openapi.json`](app/contracts/openapi.json) and say so in the pull request.
- **Synthetic data only.** No real people, customers, secrets, tenant ids, or subscription ids in code, docs, or commit messages.
- **Demos are live.** A demo passes only when it ran against the real service (Copilot, Foundry, Azure). Mocks, fixtures, and canned output are fine in tests, never as demo evidence.

## Anatomy of a solution

```text
solutions/<NN>-<phase>-<github|microsoft>/
├── README.md                     follows the outline below
├── .github/
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
3. **Unique names.** Two solutions may only ship a file with the same path if the contents are identical. Name workflows `<phase>-<track>-<what>.yml` (for example `develop-microsoft-eval.yml`) with a display name such as `Develop · Microsoft · evaluate the triage agent`, issue templates `<NN>-<phase>-<track>-<what>.yml`, and agents `<phase>-<track>`.
4. **Paths.** Workflows and agents refer to solution files by their repository path (`solutions/03-develop-microsoft/...`). Skills refer to their own files through `.github/skills/<skill>/...`, which works both here and in an adopter's repository.
5. **Repository-wide files belong to no solution:** `.github/copilot-instructions.md`, `.github/workflows/ci.yml`, `.github/workflows/copilot-setup-steps.yml`, and `.github/workflows/repo-checks.yml`.
6. **Workflows only act on their own demo.** Every workflow in this repository sees every pull request. A solution's pull-request workflow must recognize its own demo (paths inside its solution folder, a `lab/<phase>-*` base branch, or an Issue labeled `phase:<phase>`) and skip, never fail, everything else. A check that fails on another solution's demo pull request is a defect.

## Microsoft solutions on Azure

Each Microsoft solution is its own [azd](https://learn.microsoft.com/azure/developer/azure-developer-cli/) project, deployed from its folder into its own resource group.

- **Names.** azd environment `ai-sdlc-<phase>` (for example `ai-sdlc-develop`), resource group `rg-ai-sdlc-<phase>`, GitHub environment `<phase>-microsoft`.
- **`infra/main.bicep`** is subscription-scoped. It creates the resource group and deploys the solution's resources into it through modules.
- **GitHub Actions sign in with OIDC**, never with stored credentials. The solution's Bicep creates a user-assigned identity with a federated credential for its GitHub environment. Repositories that use immutable OIDC subjects (this one does) pass the subject prefix from `gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix`.
- **The GitHub environment** holds `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` as secrets and non-sensitive endpoints as variables. An azd `postprovision` hook publishes them from the azd outputs, so `azd up` leaves both Azure and GitHub ready.
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
    githubEnvironment: 'develop-microsoft'
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

## Python scripts

- Start with a module docstring that says what the script does and how to run it. `--help` documents every option.
- Use the standard library plus packages pinned in the solution's `requirements.txt` (Python 3.12+).
- Print readable progress for the presenter. Write machine-readable results under the solution's `out/` folder, which git ignores.
- Keep wrapper scripts to a minimum. Prefer a documented `gh`, `az`, `azd`, or `copilot` command when one exists.

## Solution READMEs

Write for someone who has never seen the repository. Keep it short and adoption-focused, with no project-status sections.

1. **Title and summary.** One paragraph: the problem and what AI changes.
2. **Where it fits.** The SDLC phase, and how teams work today compared with this solution.
3. **How it works.** A diagram (Mermaid renders on GitHub) and who does what: Copilot or Foundry, GitHub Actions or Azure, and the human.
4. **What's in this folder.** An annotated file tree.
5. **Prerequisites.**
6. **Set up.** One-time steps, copy-paste ready.
7. **Run the demo.** Numbered steps, each with the command or click and what you should see.
8. **What to observe.** The impact to point out to the audience.
9. **Reset and clean up.**
10. **Use it in your own repository.** What to copy and what to change.
11. **Troubleshooting.** Only problems someone actually hit.

## Definition of done

A solution is done when:

- The demo runs end to end against the real services, following its README from a clean state.
- The *Repository checks* workflow passes, and the app's CI passes if the app changed.
- The pull request links the live evidence: workflow runs, Issues and pull requests the demo created, evaluation results, and screenshots where they help. When a step only works from the default branch (issue templates, label- or dispatch-triggered workflows), run it right after merging and add the evidence as a comment on the pull request.
- It ships in its own pull request.
