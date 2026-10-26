---
name: foundry-requirements-agent
description: Run and iterate the Microsoft Foundry "requirements-analyst" agent that turns the Plan-phase stakeholder files into a cited requirements package (vector store + versioned prompt agent + strict JSON output + validator-guided repair). Use to run the Plan Microsoft demo, debug Foundry errors, or publish a new agent version.
---

# Foundry requirements agent

## When to use
- Running the Plan phase Microsoft track, locally or from the `Plan · Foundry requirements analyst` workflow.
- The Foundry output fails validation or misses issues and the agent definition needs improving.

## Inputs
- `phases/01-plan/microsoft/agent.yaml`: versioned agent definition (instructions, prompt, temperature, file-search settings).
- `phases/01-plan/inputs/*.md`: uploaded to a Foundry vector store (re-used while unchanged).
- Azure: `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT` (from `azd env get-values`), identity with **Azure AI User**.

## Procedure
1. `az login` (once), then `pip install -r requirements.txt`.
2. Run: `python phases/01-plan/microsoft/requirements_analyst.py`.
   - Publishes a new agent version only when `agent.yaml`, the model, or the inputs change (hash stored in version metadata).
   - Calls the agent via the Responses API with `agent_reference` (name + version).
   - Validates with `.github/skills/requirements-traceability/validate_backlog.py`; if invalid, sends the findings back once (`--max-repairs 1`) using `previous_response_id`.
3. Check `phases/01-plan/output/microsoft/run.json` (`responseId`, `agent.version`, `fileSearchCalls`, `valid`).
4. To improve quality, edit only the `instructions` in `agent.yaml`, re-run, and compare versions.
5. In the Foundry portal (ai.azure.com → your project → Agents → `requirements-analyst`), show the versions and traces.

## Expected output
```
agent requirements-analyst v5 (reused), vector store vs_... (reused)
attempt 1: response resp_...: VALID
```
Files: `backlog.json`, `brief.md`, `run.json` in `phases/01-plan/output/microsoft/`.

## Failure handling
- `FOUNDRY_PROJECT_ENDPOINT is not set`: run `azd provision` or export the value from `azd env get-values`.
- `401/403 PermissionDenied`: your identity lacks **Azure AI User** on the Foundry account; re-run `azd provision` or wait a few minutes for role propagation.
- `invalid_json_schema`: the schema adapter (`strict_schema`) must keep property names; do not loosen the validator.
- Still invalid after repair: exit code 1. Read the problems, improve `agent.yaml`, re-run. Never hand-edit `backlog.json`.
