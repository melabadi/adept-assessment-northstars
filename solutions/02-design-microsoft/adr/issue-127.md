# ADR draft: Should the live AI triage provider run inside the API or as a separate service?

| | |
| --- | --- |
| Status | **Proposed**. An architect accepts or rejects it in review. |
| Drafted by | Microsoft Foundry agent `architecture-advisor-small-team` v1, model `gpt-5.4-mini` |
| Evidence | Response `resp_0c4deb696e82b54e006ae21b97093c81979b59ddf759a0dec6`, 3 search call(s) that retrieved STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-001, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002, 2026-10-28T15:58:14+00:00 |
| Operating profile | small-team: standards with scope all, small-team in the `architecture-standards` index |
| Deterministic checks | Passed |

## Context

Should the live AI triage provider run inside the API or as a separate service?

Should the live AI triage provider run inside the existing API or as a separate service?

## Summary

The standards favor keeping the live AI triage provider inside the existing API behind the existing ITriageProvider extension point, unless you can justify a separate runtime for independent scaling, a different security boundary, or a separate release cadence. The current standards also require managed identity for the AI call, advisory-only behavior, OpenTelemetry instrumentation, and careful data minimization. One important standards conflict remains unresolved: one standard asks for full prompt/completion logging for 30 days, while another forbids persisting raw prompts or completions containing user free text.

## Options considered

### In-process inside the existing API

Implement the live AI triage provider within the ASP.NET Core API, behind ITriageProvider, using the existing app runtime and calling Foundry from the API process.

- ✅ Matches the standard preference to extend an existing service rather than add a new deployable component.
- ✅ Avoids introducing an extra runtime component, which fits the small-team operating budget.
- ✅ Keeps the triage extension close to the existing request data and workflow.
- ✅ Simplifies deployment, operations, and release coordination.
- ⚠️ Shares the API runtime and release cadence with triage logic.
- ⚠️ May be harder to isolate if the AI capability later needs independent scaling or a different security boundary.
- ⚠️ Requires careful control of what data is sent to the AI service and what is logged.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-AI-001 v1.0, STD-OBS-001 v1.2, STD-OBS-002 v1.0, STD-DATA-002 v1.0

### Separate AI triage service

Implement the live AI triage provider as a dedicated service called by the API, with its own deployment and runtime boundary.

- ✅ Can provide independent scaling for AI workloads.
- ✅ Can provide a separate security boundary if the AI processing needs stricter isolation.
- ✅ Can support a separate release cadence for triage logic.
- ⚠️ Adds a new runtime component, which the operating standard discourages for small teams.
- ⚠️ Conflicts with the standard preference to extend the existing service unless there is a clear justification.
- ⚠️ Adds service-to-service operational and observability overhead.
- ⚠️ Requires additional network calls and more complex failure handling.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-AI-001 v1.0, STD-OBS-001 v1.2, STD-OBS-002 v1.0, STD-DATA-002 v1.0

## Recommendation

Prefer running the live AI triage provider inside the existing API as an extension behind ITriageProvider, not as a separate service. STD-ARCH-001 tips the balance toward extending the existing service, and STD-OPS-001 also discourages adding another runtime component unless there is a strong operating reason. If the design later needs independent scaling, a different security boundary, or a separate release cadence, then a separate service could be justified, but that justification must be recorded in an ADR. In either case, the AI behavior must remain advisory and every tool call must be audited.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-ARCH-001 | 1.0 | Prefer extending an existing service behind a stable interface over introducing a new deployable component. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence. | "A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence." |
| STD-OPS-001 | 1.0 | Small teams should avoid adding runtime components and prefer managed services. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-OPS-001 | 1.0 | Small teams should avoid gateways, queues, or clusters unless an existing platform team operates them. | "Avoid gateways, queues, or clusters unless an existing platform team operates them." |
| STD-SEC-001 | 2.0 | Service-to-service calls must use managed identities or workload identity federation, not stored secrets. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | API keys, connection-string secrets, and shared keys must not be stored in configuration or code. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Local key authentication should be disabled on AI and data services when supported. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-SEC-002 | 1.1 | AI services should receive only necessary fields and must not receive attachments or personal data. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | Attachments and personal data must not be sent to AI services. | "Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | Raw prompts or completions containing user free text must not be persisted; only structured results and identifiers may be stored. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | The data flow must be documented in the ADR. | "Document the data flow in the ADR." |
| STD-AI-001 | 1.0 | AI triage output must remain advisory unless an exception is approved. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Approvals, rejections, payments, and access grants always require a human decision. | "Approvals, rejections, payments, and access grants always require a human decision." |
| STD-AI-001 | 1.0 | Agent tools must be read-only or narrowly scoped to the record being processed, and every tool call must be audited. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-OBS-001 | 1.2 | Every call to a new dependency must emit OpenTelemetry spans and metrics. | "Every call to a new dependency emits OpenTelemetry spans and metrics." |
| STD-OBS-001 | 1.2 | A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency. | "A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency." |
| STD-OBS-002 | 1.0 | AI calls should be logged with full prompts and completions for 30 days to troubleshoot behavior. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |
| STD-DATA-002 | 1.0 | AI recommendations must be retained for 90 days and then deleted. | "AI recommendations are retained for 90 days, then deleted." |

## Conflicts needing a decision

- STD-SEC-002 v1.1, STD-OBS-002 v1.0: STD-SEC-002 forbids persisting raw prompts or completions containing user free text, while STD-OBS-002 requires logging the full prompt and completion of every AI call for 30 days.

## Unknowns

- Whether the AI triage workload truly needs independent scaling, a distinct security boundary, or a separate release cadence; those are the only standard-approved reasons to split it into a separate service.
- Whether the organisation will treat the AI provider as a new runtime component within the small-team operating limit.
- How the conflicting logging and data-minimization standards will be reconciled for the production design.
- What specific fields the triage model needs, which must be minimized before sending to the AI service.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
