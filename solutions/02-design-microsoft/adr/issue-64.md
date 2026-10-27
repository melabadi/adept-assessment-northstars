# ADR draft: Should the live AI triage provider run inside the API or as a separate service?

| | |
| --- | --- |
| Status | **Proposed**. An architect accepts or rejects it in review. |
| Drafted by | Microsoft Foundry agent `architecture-advisor-small-team` v1, model `gpt-5.4-mini` |
| Evidence | Response `resp_0bbce3e922d51329006ae0b9e9bdc48194ac7ff9cbeadabeee`, 3 search call(s) that retrieved STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002, 2026-10-27T14:49:13+00:00 |
| Operating profile | small-team: standards with scope all, small-team in the `architecture-standards` index |
| Deterministic checks | Passed |

## Context

Should the live AI triage provider run inside the API or as a separate service?

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

The standards favor keeping the live AI triage provider inside the existing RequestHub API behind ITriageProvider, unless you have a clear need for independent scaling, a different security boundary, or a separate release cadence. For the current setup, the in-process option better matches the extend-before-you-add and small-team operating standards.【5:0†source】【5:4†source】

## Options considered

### In-process provider in the existing API

Implement the live AI triage provider as another ITriageProvider implementation inside the RequestHub API, calling Foundry directly from the API with managed identity and minimal request payloads.

- ✅ Matches the standard preference to extend an existing service behind a stable interface.
- ✅ Keeps operational overhead low by avoiding a new runtime component.
- ✅ Simplifies deployment, observability, and versioning because the triage logic ships with the API.
- ⚠️ Shares scaling, availability, and release cadence with the API.
- ⚠️ Less isolation if AI triage becomes noisy, expensive, or needs a different security boundary.
- ⚠️ May be harder to tune independently if the AI path grows in complexity.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-AI-001 v1.0, STD-DATA-002 v1.0, STD-OBS-002 v1.0

### Separate AI triage service

Create a new service that implements live AI triage and have the API call it over service-to-service authentication.

- ✅ Provides an independent security boundary for AI processing.
- ✅ Allows separate scaling and a separate release cadence.
- ✅ Can isolate AI-specific operational concerns from the core API.
- ⚠️ Adds a new runtime component, which the small-team standard discourages.
- ⚠️ Violates the default preference to extend the existing service unless a justified need exists.
- ⚠️ Introduces more operational and integration complexity.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-AI-001 v1.0, STD-DATA-002 v1.0, STD-OBS-002 v1.0

## Recommendation

Recommend implementing the live AI triage provider inside the existing RequestHub API behind ITriageProvider, using a narrow adapter to the Foundry project. This satisfies the standards’ preference to extend an existing service rather than introduce a new deployable component, and it avoids adding another runtime component for a small team. A separate service would only be the preferred choice if the triage workload needs independent scaling, a distinct security boundary, or a separate release cadence; STD-ARCH-001 is the standard that tips the balance toward staying inside the API for now.【5:0†source】【5:4†source】

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-ARCH-001 | 1.0 | Prefer extending the existing RequestHub API behind ITriageProvider rather than adding a new service, unless independent scaling, a different security boundary, or a separate release cadence is needed. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | If a new triage service is introduced, its justification must be recorded in an ADR. | "Record the justification in an ADR." |
| STD-OPS-001 | 1.0 | Avoid adding a new runtime component unless there is a strong operating reason and prefer fully managed services. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-SEC-001 | 2.0 | Any API-to-AI or API-to-service call must use managed identity or workload identity federation, with no stored shared secrets. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | Do not store API keys, connection strings, or shared keys in code or configuration, and disable local key auth where supported. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Where supported, AI and data services should not allow local key authentication. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-SEC-002 | 1.1 | Send only the fields the triage use case needs, and do not send attachments or personal data. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | Do not send attachments or personal data to the AI service. | "Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | Do not persist raw prompts or completions that contain user-entered free text; keep only structured results and identifiers. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | Document the AI data flow in the ADR. | "Document the data flow in the ADR." |
| STD-AI-001 | 1.0 | Treat AI triage as advisory unless a documented exception is approved, and keep human decision-making for approvals, rejections, payments, and access grants. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | If tools are exposed to the AI agent, they must be read-only or narrowly scoped and every tool call must be audited. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-DATA-002 | 1.0 | Retain AI recommendations for 90 days and then delete them. | "AI recommendations are retained for 90 days, then deleted." |
| STD-OBS-002 | 1.0 | Log the full prompt and completion of every AI call for 30 days in the application log workspace for troubleshooting. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |

## Conflicts needing a decision

- None found.

## Unknowns

- Whether the live AI triage workload will need independent scaling, a distinct security boundary, or a separate release cadence is not specified.
- Whether RequestHub already has platform support for operating an additional service is not specified.
- The standards do not say whether the AI provider must be in-process for latency reasons; that is an implementation consideration, not a stated rule.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
