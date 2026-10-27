---
name: foundry-tools
description: Define, change, and verify the tools of the in-app Microsoft Foundry triage agent (get_request, get_routing_policies). Use when adding or changing an agent tool, changing what data the agent can read, or publishing a new agent version. Keeps tools read-only, scoped to the request being triaged, audited, and aligned with the API that executes them.
---

# Foundry tools

The RequestHub triage agent runs in Microsoft Foundry Agent Service, but its tools run **inside the RequestHub API**.
The agent asks for a tool call; the API executes it with the signed-in reviewer's permissions, writes an audit entry,
and returns only permitted fields. There is no approval tool, so the agent cannot approve anything.

| Piece | File |
|---|---|
| Agent definition: instructions, tool schemas, strict output schema | `solutions/03-develop-microsoft/triage-agent.yaml` |
| Publisher (new version only when the definition changes) | `solutions/03-develop-microsoft/publish_triage_agent.py` |
| Tool loop, timeout, output parsing | `app/src/RequestHub.Api/Triage/FoundryTriageProvider.cs` |
| Tool implementations (scoping, data minimization, audit) | `ScopedTriageTools` in `app/src/RequestHub.Core/Services/RequestWorkflow.cs` |
| Deterministic guards (citations, approval claims, policy conflicts) | `RecommendAsync` and `ValidateRecommendation` in `RequestWorkflow.cs` |

## When to use
- Adding a tool, changing a tool's parameters, or changing which request fields the agent can read.
- Changing the agent's instructions or output schema.
- Before publishing a new agent version.

## Inputs
- The change you want, for example "let the agent read the request's attachment names".
- Azure access to the Foundry project (Foundry User role, formerly Azure AI User) to publish.

## Procedure
1. Declare the tool in `triage-agent.yaml` with a closed schema (`additionalProperties: false`, every property in `required`).
2. Execute it in `FoundryTriageProvider.ExecuteToolAsync` by calling a method on `ITriageTools`; implement that method in
   `ScopedTriageTools`. It must:
   - read only the request being triaged (return `not_permitted` for any other id),
   - return only the fields the agent needs (no comments, no people data),
   - write a `triage.tool_call` audit entry with the outcome.
3. Run the contract check: `python .github/skills/foundry-tools/check_tools.py`.
4. Add or update an integration test in `app/tests/RequestHub.Tests/TriageTests.cs` (see `MisbehavingTriageProvider`).
5. Publish: `python solutions/03-develop-microsoft/publish_triage_agent.py`, then run the **triage-evaluation** skill.

## Expected output
```
declared tools: get_request, get_routing_policies
executed tools: get_request, get_routing_policies
PASS tool contract is aligned, read-only, and strict
published new version: requesthub-triage v5 (model gpt-4.1-mini)
```

## Failure handling
- `declared ... but FoundryTriageProvider does not execute it`: the agent would call a tool the API ignores. Implement it or remove it.
- `looks state-changing`: stop. Approvals, rejections, and routing changes stay with people through authorized API operations.
- `strict mode needs every property in required`: make optional values nullable (`type: [string, "null"]`) and list them in `required`.
- Publishing fails with 401/403: run `az login` and confirm the Foundry User role (formerly Azure AI User) on the Foundry account.
