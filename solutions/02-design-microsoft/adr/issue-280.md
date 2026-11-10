# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #280
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v2, model `gpt-5.4-mini`
- **Evidence:** response `resp_09c3b3958d852fa7006af29cf2d84c81969d851e7926de90d7` at 2026-11-10T04:26:26+00:00. Its 1 knowledge call(s) retrieved STD-AI-001, STD-DATA-002, STD-OBS-002, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

A separate AI triage service is the better fit, because it can isolate AI-specific identity, data-minimization, retention, and audit behavior from the existing RequestHub API while still keeping `ITriageProvider` as the integration seam. That said, the logging standard for AI troubleshooting conflicts with the data-minimization standard, so the logging approach must be resolved before implementation. The balance is tipped by STD-SEC-002 v1.1 and STD-SEC-001 v2.0: the live AI provider should minimize data sent to the model and use managed identity/workload identity rather than secrets.

## Options considered

### Inside the existing RequestHub API behind ITriageProvider

Implement the live AI provider as another in-process `ITriageProvider` inside the ASP.NET Core API, using the existing API deployment and calling the AI backend directly from the API process.

- ✅ Simpler deployment and fewer moving parts.
- ✅ Lower operational overhead for a small team.
- ✅ Keeps the interface boundary exactly where it already exists.
- ⚠️ Harder to isolate AI-specific data handling, logging, and retention from the rest of the API.
- ⚠️ In-process code makes it easier to accidentally mix broader request data with AI inputs, which is risky under the data-minimization standard.
- ⚠️ Any AI troubleshooting logging policy is harder to scope cleanly without affecting broader application logs.
- Standards: STD-SEC-002 v1.1, STD-OBS-002 v1.0, STD-AI-001 v1.0, STD-SEC-001 v2.0, STD-DATA-002 v1.0

### New separate AI triage service

Create a dedicated AI triage service that implements the triage logic externally, while the RequestHub API continues to depend on `ITriageProvider` and calls the service over service-to-service authentication.

- ✅ Cleaner boundary for sending only the fields the AI use case needs.
- ✅ Easier to enforce managed identity/workload identity and avoid secrets in code or configuration.
- ✅ Better separation for auditing AI tool calls and keeping AI recommendations on their own retention policy.
- ✅ Reduces blast radius if the AI integration changes or needs special observability controls.
- ⚠️ Adds another service to deploy, monitor, and secure.
- ⚠️ More operational complexity than an in-process provider.
- ⚠️ Requires explicit design for what data crosses the boundary and how the service logs it.
- Standards: STD-SEC-002 v1.1, STD-SEC-001 v2.0, STD-AI-001 v1.0, STD-DATA-002 v1.0, STD-OBS-002 v1.0

## Recommendation

Prefer a new separate AI triage service behind the existing `ITriageProvider` interface, with the RequestHub API calling it over managed identity. This better fits the standards because it keeps the AI boundary narrow, makes it easier to ensure only needed fields are sent, and lets you enforce advisory-only behavior plus auditing at the service boundary. Keep the current deterministic provider as the fallback or non-AI implementation behind the same interface. The standard that most strongly tips the balance is STD-SEC-002 v1.1, because it explicitly requires minimizing the data sent to AI services and documenting the data flow.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-SEC-002 | 1.1 | Send only the fields the AI use case needs, never attachments or personal data, and do not persist raw prompts or completions that contain free text entered by users. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | Do not send attachments or personal data to the AI service. | "Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | Do not persist raw prompts or completions that contain user-entered free text. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | Document the AI data flow in the architecture decision record. | "Document the data flow in the ADR." |
| STD-OBS-002 | 1.0 | Log the full prompt and completion of every AI call for 30 days in the application log workspace. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |
| STD-AI-001 | 1.0 | Keep AI output advisory unless an approved exception exists, and require human decisions for approvals, rejections, payments, and access grants. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Use only read-only or narrowly scoped tools for the agent, and audit every tool call. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-SEC-001 | 2.0 | Authenticate service-to-service calls with managed identity or workload identity federation, and do not store API keys, connection-string secrets, or shared keys in configuration or code. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | Do not store API keys, connection-string secrets, or shared keys in configuration or code. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Disable local key authentication on AI and data services where supported. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-DATA-002 | 1.0 | Retain AI recommendations for 90 days and then delete them. | "AI recommendations are retained for 90 days, then deleted." |
| STD-DATA-002 | 1.0 | Apply the organization-wide seven-year rule to business decisions. | "Business decisions follow the organisation-wide seven-year rule." |

## Conflicts needing a decision

- STD-SEC-002 v1.1, STD-OBS-002 v1.0: One standard forbids persisting raw prompts or completions containing user-entered free text, while the other requires logging the full prompt and completion of every AI call for 30 days. These requirements conflict for any AI call that includes user text.

## Unknowns

- Whether the AI triage provider will ever need attachments, which the data-minimization standard forbids sending.
- Whether the organization intends to treat triage outputs as AI recommendations under the 90-day retention rule in every case.
- How the team plans to reconcile the observability requirement with the prohibition on persisting raw prompts and completions.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
