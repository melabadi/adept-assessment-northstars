# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #245
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v2, model `gpt-5.4-mini`
- **Evidence:** response `resp_056d0c03970cd811006ae691b33d50819086446c18b1ade4fd` at 2026-11-01T01:11:15+00:00. Its 3 knowledge call(s) retrieved STD-AI-001, STD-ARCH-001, STD-DATA-002, STD-OBS-001, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

The standards favor implementing the live AI triage provider inside the existing RequestHub API behind ITriageProvider, not as a new separate service, unless you can justify independent scaling, a different security boundary, or a separate release cadence in an ADR. The main balance-tipping standard is STD-ARCH-001 v1.0, reinforced by the small-team runtime budget in STD-OPS-001 v1.0. There is also a standards conflict between AI troubleshooting logging and AI data minimization that must be resolved before finalizing the logging design.

## Options considered

### Inside existing RequestHub API behind ITriageProvider

Implement the live AI triage logic in the current ASP.NET Core API, behind the existing triage abstraction, and call Foundry as an outbound dependency from that API.

- ✅ Matches the standard preference to extend an existing service rather than introduce a new deployable component.
- ✅ Uses no additional runtime component, which fits the small-team operating budget.
- ✅ Keeps the triage integration close to the existing request data and approval flow.
- ✅ Simplifies service-to-service identity, audit, and operational ownership.
- ⚠️ The API becomes responsible for AI integration, timeout handling, and any logging/telemetry concerns.
- ⚠️ If the AI workload later needs separate scaling or a different security boundary, a refactor may be needed.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-OBS-001, STD-DATA-002

### New separate AI triage service

Create a dedicated service that implements triage and have the RequestHub API call it, while that service calls Foundry.

- ✅ Can support independent scaling if the AI workload grows.
- ✅ Can create a clearer security boundary between core RequestHub and AI processing.
- ✅ Can support a separate release cadence for AI changes.
- ⚠️ Introduces a new deployable component, which the standards discourage for small teams unless justified.
- ⚠️ Adds operational overhead and another service to monitor, secure, and deploy.
- ⚠️ Uses up limited small-team runtime capacity.
- ⚠️ Does not remove the need to apply the same AI data-minimization, identity, and audit rules.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-OBS-001, STD-DATA-002

## Recommendation

Recommend the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, using the Microsoft Foundry project as a dependency. This best matches the standards’ preference to extend an existing service rather than add a new deployable component, and it avoids consuming one of the small team’s limited new-runtime-component slots. Use managed identity/workload identity for Foundry calls, minimize the request fields sent to the model, keep AI output advisory, and add OpenTelemetry spans/metrics plus timeout handling for the new dependency. If the team later needs independent scaling, a different security boundary, or a separate release cadence, record that justification in an ADR and revisit a separate service then.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-AI-001 | 1.0 | The triage output must remain advisory, and any agent tools must be read-only or narrowly scoped with every tool call audited. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Any tools exposed to the AI triage provider must be read-only or narrowly scoped to the record being processed, and all tool calls must be audited. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-SEC-001 | 2.0 | Calls from RequestHub to Foundry must use managed identity or workload identity federation, with no API keys or shared keys stored in code or configuration. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | Local key authentication must be disabled on AI and data services where supported. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-SEC-002 | 1.1 | The AI integration must send only the fields needed, must not send attachments or personal data, and must not persist raw prompts or completions with free text; only structured results and identifiers may be persisted. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | The AI data flow must be documented in the ADR. | "Document the data flow in the ADR." |
| STD-OPS-001 | 1.0 | The design should avoid adding a new runtime component unless there is a strong operating reason; managed services are preferred. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-OPS-001 | 1.0 | Avoid gateways, queues, or clusters unless an existing platform team operates them. | "Avoid gateways, queues, or clusters unless an existing platform team operates them." |
| STD-ARCH-001 | 1.0 | Prefer extending the existing RequestHub API behind ITriageProvider rather than adding a new deployable component. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | A new separate service is justified only if the capability needs independent scaling, a different security boundary, or a separate release cadence, and that justification must be recorded in an ADR. | "A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence." |
| STD-OBS-001 | 1.2 | The live AI provider is a new dependency, so its calls must emit OpenTelemetry spans and metrics, and dependency timeouts must surface a user-facing unavailable state within two seconds while the core flow continues. | "Every call to a new dependency emits OpenTelemetry spans and metrics." |
| STD-OBS-002 | 1.0 | AI troubleshooting logging must retain full prompts and completions for 30 days in the application log workspace. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |
| STD-DATA-002 | 1.0 | AI recommendations must be retained for 90 days and then deleted. | "AI recommendations are retained for 90 days, then deleted." |

## Conflicts needing a decision

- STD-SEC-002, STD-OBS-002: STD-SEC-002 forbids persisting raw prompts or completions that contain free text entered by users, while STD-OBS-002 requires logging the full prompt and completion of every AI call for 30 days. These cannot both be followed as written for user-free-text prompts/completions.

## Unknowns

- Whether RequestHub’s triage inputs contain attachments or personal data, which determines how much can be sent to Foundry under STD-SEC-002.
- Whether the live AI triage workload truly needs independent scaling, a different security boundary, or a separate release cadence; those are the only stated justifications for a separate service under STD-ARCH-001.
- How the team intends to reconcile the logging conflict between STD-SEC-002 and STD-OBS-002 in the ADR and logging design.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
