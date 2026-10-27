---
applyTo: "solutions/02-design-github/adr/**"
excludeAgent: "cloud-agent"
---

# Reviewing an architecture decision record (ADR)

An ADR here is a proposal from an agent or a person. Deterministic checks already verify its structure, its standard ids and versions, its file paths, and that no agent accepted it. Spend your review on the substance a person must decide:

- **Unstated assumptions.** Point out what the recommendation depends on but does not say: expected load and latency, what data leaves the app, who operates each component, failure behaviour, and cost.
- **Standards.** Check each claim against the standard it cites in `solutions/02-design-github/standards/`, and against the operating profile it applies to. Flag a standard that applies but is not discussed, and any conflict between standards that the ADR settles on its own instead of leaving to the reviewer.
- **API impact.** Compare the API impact section with `app/contracts/openapi.json`. Does the design rely on an endpoint, field, or error response that does not exist? Would the change it needs break `requesthub.v1` (STD-API-001)?
- **Real code.** Check that statements about the code match it, for example `app/src/RequestHub.Core/Triage/ITriageProvider.cs` and `app/src/RequestHub.Core/Services/RequestWorkflow.cs` (authorization, audit, timeouts).
- **Threat model.** It must follow the real data flow: instructions hidden in request text, reads of other records, data minimization, identity, audit, and what happens when the AI service is slow or down.
- **Human approval.** Only people approve or reject requests, and only people accept an ADR. Flag any design path that lets a provider, agent, or tool decide.
- **Tasks.** Each implementation task should be small enough for one pull request, with an owner role and an observable acceptance criterion.

Ask questions where the ADR is vague. Do not rewrite the ADR's recommendation; the reviewer decides.
