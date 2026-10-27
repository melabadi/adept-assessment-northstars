---
name: foundry-requirements-agent
description: Run and iterate the Microsoft Foundry "requirements-analyst" agent that turns the Plan-phase stakeholder files into a cited requirements package (vector store + versioned prompt agent + strict JSON output + validator-guided repair). Use to run the Plan Microsoft demo, debug Foundry errors, or publish a new agent version.
---

# Foundry requirements agent

## When to use
- Running the Plan phase Microsoft track, locally or from the `Plan · Microsoft · run the Foundry requirements analyst` workflow.
- The Foundry output fails validation or misses issues and the agent definition needs improving.

## Inputs
- `solutions/01-plan-microsoft/agent.yaml`: versioned agent definition (instructions, prompt, sampling, file-search settings). It sets `temperature` for non-reasoning models such as gpt-4.1; reasoning models (gpt-5 family) reject temperature and take `reasoning_effort` instead.
- `solutions/01-plan-microsoft/inputs/*.md`: uploaded to a Foundry vector store (re-used while unchanged).
- Azure: `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT` (from `azd env get-values`), identity with the **Foundry User** role (formerly Azure AI User).

## Procedure
1. `az login` (once), then `pip install -r solutions/01-plan-microsoft/requirements.txt`.
2. Run: `python solutions/01-plan-microsoft/requirements_analyst.py`.
   - Publishes a new agent version only when `agent.yaml`, the model, or the inputs change (hash stored in version metadata).
   - Calls the agent via the Responses API with `agent_reference` (name + version).
   - Validates with `.github/skills/requirements-traceability/validate_backlog.py`; if invalid, prints the findings and sends them back once (`--max-repairs 1`) using `previous_response_id`.
3. Check `solutions/01-plan-microsoft/brief/run.json` (`responseId`, `agent.version`, `fileSearchCalls`, `valid`).
4. To improve quality, change only `agent.yaml` (instructions, or the model in `infra/main.bicep`). Models are not deterministic, so judge a change on several runs, not one:
   ```
   python solutions/01-plan-microsoft/requirements_analyst.py --out solutions/01-plan-microsoft/out/run1   # repeat for run2, run3...
   python .github/skills/brief-compare/compare_briefs.py solutions/01-plan-microsoft/out/run1/backlog.json solutions/01-plan-microsoft/out/run2/backlog.json solutions/01-plan-microsoft/out/run3/backlog.json
   ```
   Keep the change only if validity and the planted-issue scores improve. Prefer generic analysis guidance (for example "look for disagreements before writing") over hints about this transcript.
5. In the Foundry portal (ai.azure.com → your project → Agents → `requirements-analyst`), show the versions.

## Expected output
```
agent requirements-analyst v5 (reused), vector store vs_... (reused)
attempt 1: response resp_...: VALID
```
Files: `backlog.json`, `brief.md`, `run.json` in `solutions/01-plan-microsoft/brief/`.

## Failure handling
- `FOUNDRY_PROJECT_ENDPOINT is not set`: run `azd up` in `solutions/01-plan-microsoft`, or export the value.
- `401/403 PermissionDenied`: your identity lacks the **Foundry User** role on the Foundry account; re-run `azd provision` in the solution folder or wait a few minutes for role propagation.
- `Unsupported parameter: 'temperature'`: the model is a reasoning model; replace `temperature` with `reasoning_effort: low` in `agent.yaml`.
- `invalid_json_schema`: the schema adapter (`strict_schema`) must keep property names; do not loosen the validator.
- Still invalid after repair: exit code 1. Read the problems, improve `agent.yaml`, re-run. Never hand-edit `backlog.json`.
