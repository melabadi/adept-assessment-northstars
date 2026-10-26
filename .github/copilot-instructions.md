# Copilot instructions for this repository

This repository is a hands-on demo of AI across the software development lifecycle (SDLC). Seven phases each show two offerings — one GitHub (GitHub Copilot + GitHub Enterprise) and one Microsoft (Azure, Microsoft Foundry) — applied to the same app, **RequestHub**.

## Repository map

| Path | What lives there |
| --- | --- |
| `app/` | RequestHub: ASP.NET Core 10 API (`src/RequestHub.Api`), domain + EF Core (`src/RequestHub.Core`), notification worker (`src/RequestHub.Worker`), React web UI (`web/`), integration tests (`tests/`), API contract (`contracts/`). |
| `infra/` | Bicep for the shared Azure baseline (`main.bicep`, `core.bicep`) and the deploy-time container apps (`api.bicep`, `worker.bicep`). Used by `azd`. |
| `phases/0N-*/` | One folder per SDLC phase: README with both demos, inputs, and Microsoft-track scripts. |
| `.github/agents/` | Custom Copilot agents, one per phase and track (`<phase>-github`, `<phase>-microsoft`). |
| `.github/skills/` | Agent skills used by those agents. Each skill folder has a `SKILL.md` and its scripts. |
| `.github/workflows/` | CI, deployment, and per-phase demo workflows. `*.md` + `*.lock.yml` pairs are GitHub Agentic Workflows. |

## Build and test

- API and worker: `dotnet test --solution app/RequestHub.slnx` (needs PostgreSQL on `localhost:5432`, user `requesthub`, password `devpass`; the Copilot cloud agent environment starts one automatically).
- Web UI: `npm ci --prefix app/web`, then `npm run typecheck --prefix app/web`, `npm test --prefix app/web`, `npm run build --prefix app/web`.
- Run locally: `dotnet run --project app/src/RequestHub.Api` (persona switcher, http://localhost:5080).
- Python demo scripts: `pip install -r requirements.txt` (Python 3.12+).

## Rules that keep the demos honest

- **Human approval is sacred.** Only a person with the Approver role can approve or reject. Never add an approval path to triage providers, agents, or tools. A requester can never decide their own request.
- **Authorization lives in the API** (`RequestWorkflow`), not only in the UI. Every new endpoint checks role and department access and has a negative test.
- **Never weaken a test, guard, or validation to make a check pass.** Fix the code, or explain why the test is wrong in the PR.
- **Contract `requesthub.v1` is additive-only.** If the API shape changes, regenerate `app/contracts/openapi.json` with `UPDATE_CONTRACT=1 dotnet test --solution app/RequestHub.slnx` and describe the change in the PR.
- **Synthetic data only.** No real people, customers, secrets, tenant ids, or subscription ids in code, tests, docs, or commit messages.
- Keep changes small and reviewable; add or update tests for every behavior change; update the relevant README when behavior or commands change.

## Code conventions

- C#: minimal APIs, `TypedResults`, problem details with a stable `code` (for example `decision.self_approval`). Business errors return `WorkflowError`. Audit every business action with `AuditEvent`.
- Tests: xUnit v3 integration tests against real PostgreSQL through `ApiFixture`; use personas (`u-ava` requester, `u-ben` reviewer, `u-chloe` approver, `u-dan` admin, `u-hugo` requester+approver) via the `X-RequestHub-User` header.
- Web: React + TypeScript, no UI framework, all strings in the EN/FR dictionaries, accessible markup (labels, landmarks, keyboard support).
- Python scripts: standard library + pinned packages in `requirements.txt`, a module docstring explaining what the script does, `--help` that documents every option.
