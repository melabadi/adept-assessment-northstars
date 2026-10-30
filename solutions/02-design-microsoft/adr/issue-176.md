# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #176
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v2, model `gpt-5.4-mini`
- **Evidence:** response `resp_092aa9f8f0ec64eb006ae4e303daa8819498733a706bfabca9` at 2026-10-30T18:33:39+00:00. Its 1 knowledge call(s) retrieved STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-001, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

The standards favour implementing the live AI triage provider inside the existing RequestHub API behind ITriageProvider, using the stable extension point and managed identity to call the Foundry AI service. A separate service is only justified if the AI triage capability needs independent scaling, a different security boundary, or a separate release cadence.

## Options considered

### In-process provider inside existing RequestHub API

Implement the live AI triage provider as a new ITriageProvider implementation in the existing ASP.NET Core API, calling Foundry directly from the API process or its hosted components.

- ✅ Best matches the existing stable extension point.
- ✅ Avoids adding a new runtime component.
- ✅ Simpler operations and deployment for a small team.
- ✅ Keeps the triage flow close to the request domain model.
- ⚠️ Shares deployment and scaling with the API.
- ⚠️ Any AI-specific faults must be isolated carefully so the core flow continues.
- ⚠️ May blur responsibilities if the AI workflow grows substantially.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-OBS-001, STD-OBS-002, STD-DATA-002

### Separate AI triage service

Create a new deployable service that RequestHub API calls through ITriageProvider, with the service owning AI prompting, response handling, and triage logic.

- ✅ Can scale independently from the main API.
- ✅ Can establish a separate security boundary if needed.
- ✅ Allows an independent release cadence for AI changes.
- ⚠️ Adds a new runtime component and operational burden.
- ⚠️ Not the preferred default under the small-team operating profile.
- ⚠️ Requires stronger cross-service observability and failure handling.
- ⚠️ Needs a clear justification recorded in an ADR.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-OBS-001, STD-OBS-002, STD-DATA-002

## Recommendation

Prefer the live AI triage provider inside the existing RequestHub API behind ITriageProvider. STD-ARCH-001 explicitly prefers extending an existing service over introducing a new deployable component, and STD-OPS-001 discourages adding runtime components in a small-team operating model. Keep the AI call outbound to Foundry with managed identity, send only the minimum fields needed, and persist only structured triage results and identifiers. Choose a separate service only if an architect can show one of the STD-ARCH-001 justifications: independent scaling, different security boundary, or separate release cadence.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-ARCH-001 | 1.0 | Prefer extending an existing service behind a stable interface over introducing a new deployable component. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence. | "A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence." |
| STD-OPS-001 | 1.0 | Small teams should introduce at most one new runtime component per quarter and prefer fully managed services. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-OPS-001 | 1.0 | Avoid gateways, queues, or clusters unless an existing platform team operates them. | "Avoid gateways, queues, or clusters unless an existing platform team operates them." |
| STD-SEC-001 | 2.0 | Service-to-service calls must use managed identities or workload identity federation. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | API keys, connection-string secrets, and shared keys must not be stored in configuration or code. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Disable local (key) authentication on AI and data services where supported. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-AI-001 | 1.0 | AI output must remain advisory unless a documented exception is approved by the architecture board. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Approvals, rejections, payments, and access grants always require a human decision. | "Approvals, rejections, payments, and access grants always require a human decision." |
| STD-AI-001 | 1.0 | Tools exposed to an agent must be read-only or narrowly scoped, and every tool call must be audited. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-SEC-002 | 1.1 | Send AI services only the fields the use case needs and do not send attachments or personal data. | "Send AI services only the fields the use case needs. Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | Document the data flow in the ADR. | "Document the data flow in the ADR." |
| STD-OBS-001 | 1.2 | Every call to a new dependency must emit OpenTelemetry spans and metrics. | "Every call to a new dependency emits OpenTelemetry spans and metrics." |
| STD-OBS-001 | 1.2 | A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency. | "A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency." |
| STD-OBS-002 | 1.0 | To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |
| STD-DATA-002 | 1.0 | AI recommendations are retained for 90 days, then deleted. | "AI recommendations are retained for 90 days, then deleted." |

## Conflicts needing a decision

- STD-SEC-002, STD-OBS-002: STD-SEC-002 forbids persisting raw prompts or completions that contain free text entered by users, while STD-OBS-002 requires logging the full prompt and completion of every AI call for 30 days. Both cannot be followed literally for user-free-text prompts without an architect deciding how to reconcile logging with data minimization.

## Unknowns

- Whether the live AI triage workload needs independent scaling beyond the existing API.
- Whether the AI triage capability needs a different security boundary from the current RequestHub API.
- Whether a separate release cadence is required for AI changes.
- How the organisation wants to resolve the logging versus data-minimization conflict for AI prompts and completions.
- Whether any public API contract changes are required when exposing AI triage results to callers.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
