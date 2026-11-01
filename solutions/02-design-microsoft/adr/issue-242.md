# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #242
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v2, model `gpt-5.4-mini`
- **Evidence:** response `resp_0a49f2eb8c636a19006ae68ae7a6648195b6b45e5ae7e95d8c` at 2026-11-01T00:42:15+00:00. Its 2 knowledge call(s) retrieved STD-AI-001, STD-API-001, STD-ARCH-001, STD-DATA-002, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

The standards favor running the live AI triage provider inside the existing RequestHub API behind ITriageProvider, with a stable extension point and managed-identity calls to the AI service. A separate service is only justified if you need independent scaling, a different security boundary, or a separate release cadence, and that justification should be recorded in an ADR.

## Options considered

### In-process AI triage inside RequestHub API

Add the live AI triage implementation behind the existing ITriageProvider extension point in the ASP.NET Core API, using Foundry from the API process and returning structured triage recommendations to the app.

- ✅ Matches the standard preference to extend an existing service behind a stable interface.
- ✅ Avoids adding a new runtime component, which fits the small-team operating budget.
- ✅ Keeps the integration simpler for request context, logging, and contract compatibility.
- ✅ Easier to keep AI output advisory and ensure a human makes final approval decisions.
- ⚠️ Shares the API deployment lifecycle with AI triage changes.
- ⚠️ May be less suitable if the AI path needs independent scaling or a separate security boundary.
- ⚠️ Requires careful handling of data minimization and logging to avoid storing free text prompts/completions.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-AI-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-DATA-002 v1.0, STD-API-001 v1.0

### Separate AI triage service

Create a new deployable service for live AI triage, and have the RequestHub API call it as an internal dependency while ITriageProvider becomes a client wrapper.

- ✅ Provides an independent security boundary if AI processing must be isolated.
- ✅ Allows independent scaling of AI traffic if triage load grows significantly.
- ✅ Can support a separate release cadence for AI-specific changes.
- ⚠️ Introduces a new runtime component, which the small-team standard discourages.
- ⚠️ Adds operational overhead and another service to secure, deploy, observe, and troubleshoot.
- ⚠️ Needs a stronger justification under the standards, not just a preference for modularity.
- ⚠️ Still must follow the same AI data minimization, identity, advisory-output, and retention rules.
- Standards: STD-ARCH-001 v1.0, STD-OPS-001 v1.0, STD-AI-001 v1.0, STD-SEC-001 v2.0, STD-SEC-002 v1.1, STD-DATA-002 v1.0, STD-API-001 v1.0

## Recommendation

Recommended option: implement the live AI triage provider inside the existing RequestHub API behind ITriageProvider, not as a separate service. STD-ARCH-001 tips the balance toward extending the existing service, and STD-OPS-001 reinforces avoiding a new runtime component. Use managed identity/workload identity for calls to the AI service, send only the fields needed for triage, persist only structured results and identifiers, and keep the AI output advisory with a human decision for approvals/rejections. A separate service becomes appropriate only if the team can justify independent scaling, a distinct security boundary, or a separate release cadence in an ADR.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-AI-001 | 1.0 | The live AI triage can advise, but humans must make the final approval, rejection, payment, or access decision, and every tool call must be audited. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-OPS-001 | 1.0 | Do not add more than one new runtime component this quarter and prefer managed services over extra self-operated infrastructure. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-SEC-001 | 2.0 | Use managed identities or workload identity federation for service-to-service calls and do not store API keys, connection strings, or shared keys in config or code. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-ARCH-001 | 1.0 | Prefer extending RequestHub behind a stable interface, and justify any new service only for independent scaling, a different security boundary, or a separate release cadence. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-SEC-002 | 1.1 | Send only the fields the triage use case needs, never send attachments or personal data, and persist only structured results and identifiers. | "Send AI services only the fields the use case needs." |
| STD-DATA-002 | 1.0 | Retain AI recommendations for 90 days and then delete them, while business decisions follow the seven-year rule. | "AI recommendations are retained for 90 days, then deleted." |
| STD-API-001 | 1.0 | Any public API change must stay additive within the major version unless a new major version and migration plan are introduced. | "Public API changes are additive within a major contract version: new optional fields and new endpoints are allowed; renaming or removing fields, changing types, or tightening validation requires a new major version and a migration plan." |
| STD-OBS-002 | 1.0 | AI call prompts and completions must be logged for 30 days in the application log workspace for troubleshooting. | "To troubleshoot AI behaviour, log the full prompt and completion of every AI call for 30 days in the application log workspace." |

## Conflicts needing a decision

- STD-SEC-002 v1.1, STD-OBS-002 v1.0: One standard forbids persisting raw prompts or completions that contain free text entered by users, while the other requires logging the full prompt and completion of every AI call for 30 days. An architect must resolve this before finalizing the logging design.

## Unknowns

- Whether the live triage workload needs independent scaling in practice.
- Whether the AI path requires a separate security boundary from the rest of the API.
- Whether the organization expects a separate release cadence for AI triage changes.
- How the team will reconcile troubleshooting needs with the prohibition on persisting raw prompts/completions.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
