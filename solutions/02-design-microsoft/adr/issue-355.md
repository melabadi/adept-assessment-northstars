# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #355
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v5, model `gpt-6.1-sol`
- **Evidence:** response `resp_08aa75b8e5513e8a006af483a24c5481939915775457782e8b` at 2026-11-11T15:02:58+00:00. Its 2 knowledge call(s) retrieved STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-001, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

Prefer running the live AI triage provider inside the existing RequestHub API behind ITriageProvider. STD-ARCH-001 v1.0 explicitly favours extending an existing service; a separate service needs a demonstrated scaling, security-boundary, or release-cadence justification. There is also an unresolved conflict between AI logging and data-minimization requirements.

## Options considered

### Foundry-backed provider inside the existing API

Implement live AI triage behind the existing ITriageProvider interface, with the API calling Foundry directly.

- ✅ Matches the explicit preference to extend an existing service behind a stable interface.
- ✅ Avoids introducing another deployable runtime component, aligning with the small-team operating standard.
- ⚠️ Does not provide a separate deployment, security boundary, or independently scaled triage service; a demonstrated need for one would justify reconsidering placement.
- ⚠️ Still requires dependency telemetry, timeout handling, and continuation of the core business flow without AI.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-DATA-002 v1.0, STD-AI-001 v1.0, STD-OBS-001 v1.2, STD-OBS-002 v1.0, STD-API-001 v1.0

### Separate AI triage service

Keep ITriageProvider in the API as an adapter calling a separately deployed triage service, which calls Foundry.

- ✅ Can accommodate independent scaling, a different security boundary, or a separate release cadence when one is genuinely required.
- ⚠️ Requires a qualifying justification recorded in an ADR; none has been established in the question.
- ⚠️ Introduces a runtime component subject to the small-team quarterly limit and managed-service preference.
- ⚠️ Adds an API-to-triage-service dependency that also needs workload authentication, telemetry, and timeout handling.
- ⚠️ Does not resolve the conflicting prompt/completion persistence requirements.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-DATA-002 v1.0, STD-AI-001 v1.0, STD-OBS-001 v1.2, STD-OBS-002 v1.0, STD-API-001 v1.0

## Recommendation

For architect review: implement a Foundry-backed ITriageProvider within the existing API rather than introducing a separate deployable. STD-ARCH-001 v1.0 tips the balance, reinforced by STD-OPS-001 v1.0. Before finalizing the design, an architect must resolve the conflict between STD-OBS-002 v1.0, which requires full prompt/completion logging, and STD-SEC-002 v1.1, which forbids persisting them when they contain user-entered free text. Neither rule can be treated as settled for that case. Both placement options must use workload identity, minimize AI inputs, preserve human decisions, instrument dependency calls, and let the core business flow continue when AI is unavailable. Reconsider a separate service only if an independent scaling need, different security boundary, or separate release cadence is established and documented in an ADR.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-ARCH-001 | 1.0 | Prefer the existing API and stable ITriageProvider interface over another deployable. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | Introduce a separate service only for independent scaling, a different security boundary, or a separate release cadence. | "A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence." |
| STD-ARCH-001 | 1.0 | Record any new-service justification in an ADR. | "Record the justification in an ADR." |
| STD-OPS-001 | 1.0 | Under the small-team profile, stay within one new runtime component per quarter and prefer fully managed services. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-OPS-001 | 1.0 | Avoid adding gateways, queues, or clusters unless an existing platform team operates them. | "Avoid gateways, queues, or clusters unless an existing platform team operates them." |
| STD-SEC-001 | 2.0 | Authenticate service-to-service calls using managed identities or workload identity federation. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | Do not store API keys, connection-string secrets, or shared keys in configuration or code. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Disable local key authentication on AI and data services where supported. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-SEC-002 | 1.1 | Send Foundry only fields needed for triage. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | Exclude attachments and personal data from AI inputs. | "Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | This standard prohibits persisting raw prompts or completions containing user-entered free text and limits persistence to structured results and identifiers, but its conflict with STD-OBS-002 requires architect resolution. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | Document the AI data flow in the ADR. | "Document the data flow in the ADR." |
| STD-DATA-002 | 1.0 | Retain AI recommendations for 90 days and then delete them under the small-team profile. | "AI recommendations are retained for 90 days, then deleted." |
| STD-DATA-002 | 1.0 | Apply the organisation-wide seven-year retention rule to business decisions rather than treating them as AI recommendations. | "Business decisions follow the organisation-wide seven-year rule." |
| STD-AI-001 | 1.0 | Keep AI triage advisory unless the architecture board approves a documented exception. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Always require human decisions for approvals, rejections, payments, and access grants. | "Approvals, rejections, payments, and access grants always require a human decision." |
| STD-AI-001 | 1.0 | If agent tools are exposed, make them read-only or narrowly record-scoped and audit every tool call. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-OBS-001 | 1.2 | Emit OpenTelemetry spans and metrics for every call to each new dependency. | "Every call to a new dependency emits OpenTelemetry spans and metrics." |
| STD-OBS-001 | 1.2 | Surface a user-facing unavailable state within two seconds of a dependency timeout and keep the core business flow working without that dependency. | "A dependency timeout must surface a user-facing unavailable state within two seconds of the timeout, and the core business flow must continue without the dependency." |
| STD-OBS-002 | 1.0 | This standard requires full prompt/completion logging for every AI call for 30 days, but its conflict with STD-SEC-002 requires architect resolution before implementation. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |
| STD-API-001 | 1.0 | If live triage changes the public API, keep changes additive within the major version or provide a new major version and migration plan for breaking changes. | "Public API changes are additive within a major contract version: new optional fields and new endpoints are allowed; renaming or removing fields, changing types, or tightening validation requires a new major version and a migration plan." |

## Conflicts needing a decision

- STD-SEC-002 v1.1, STD-OBS-002 v1.0: For AI calls whose prompts or completions contain user-entered free text, STD-SEC-002 forbids persisting that raw content, while STD-OBS-002 requires logging the full prompt and completion of every call for 30 days in the application log workspace. These requirements cannot both be met for those calls. An architect must resolve the conflict; moving triage into a separate service does not remove it.

## Unknowns

- Whether triage has a demonstrated independent scaling need, different security boundary, or separate release cadence that would justify a new service.
- Whether the small team's quarterly runtime-component allowance has already been used, if a separate service is proposed.
- Which request fields triage actually needs, whether they include user-entered free text, and how prohibited personal data and attachments will be excluded.
- The architect's resolution of the conflicting raw prompt/completion persistence requirements.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
