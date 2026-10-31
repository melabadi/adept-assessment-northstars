# ADR draft: Should the live AI triage provider run inside the existing RequestHub API behind…

- **Status:** Proposed. An architect accepts or rejects it in review.
- **Issue:** #231
- **Drafted by:** Microsoft Foundry agent `architecture-advisor-small-team` v2, model `gpt-5.4-mini`
- **Evidence:** response `resp_0e0ccb01d2de9c44006ae677a1b2f481939c2cc18050565564` at 2026-10-31T23:20:01+00:00. Its 3 knowledge call(s) retrieved STD-AI-001, STD-ARCH-001, STD-DATA-002, STD-OBS-002, STD-OPS-001, STD-SEC-001, STD-SEC-002.
- **Operating profile:** small-team, which may retrieve the standards with scope all, small-team in the `architecture-standards` index
- **Deterministic checks:** passed

## Context

Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service?

## Summary

The standards favour running the live AI triage provider inside the existing RequestHub API behind ITriageProvider, unless you can justify a separate service for independent scaling, a different security boundary, or a separate release cadence.

## Options considered

### In-process live AI triage behind ITriageProvider

Keep the AI triage implementation inside the existing RequestHub API and call it through the current extension point.

- ✅ Matches the standard preference to extend an existing service behind a stable interface.
- ✅ Avoids adding a new runtime component, which fits the small-team operating budget.
- ✅ Keeps the architecture simpler to operate and deploy.
- ⚠️ Shares the API's release cadence and scaling profile.
- ⚠️ Does not create a separate security boundary if one is later needed.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-DATA-002

### Separate AI triage service

Create a new deployable service for the live AI triage provider and have RequestHub call it over a service boundary.

- ✅ Provides an independent release cadence.
- ✅ Can provide a different security boundary.
- ✅ Can support independent scaling if that becomes necessary.
- ⚠️ Introduces a new runtime component, which is disfavoured for a small team.
- ⚠️ Requires a stronger justification under the architecture standard.
- ⚠️ Adds operational overhead and another service to secure and observe.
- Standards: STD-ARCH-001, STD-OPS-001, STD-SEC-001, STD-SEC-002, STD-AI-001, STD-DATA-002

## Recommendation

Choose the in-process option first: implement the live AI triage provider behind the existing ITriageProvider inside the current RequestHub API. STD-ARCH-001 tips the balance because it says to extend an existing service behind a stable interface rather than introduce a new deployable component, and STD-OPS-001 also pushes toward avoiding a new runtime component. A separate service is only justified if you can document one of the allowed reasons in an ADR: independent scaling, a different security boundary, or a separate release cadence. For either option, use managed identity/workload identity for service-to-service calls, send only the minimum required fields, do not send attachments or personal data, do not persist raw prompts or completions, and keep AI output advisory with human review for the triage decision.

## Constraints from approved standards

| Standard | Version | Requirement | Source excerpt |
| --- | --- | --- | --- |
| STD-ARCH-001 | 1.0 | Prefer extending an existing service behind a stable interface over introducing a new deployable component. | "Prefer extending an existing service behind a stable interface over introducing a new deployable component." |
| STD-ARCH-001 | 1.0 | A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence. | "A new service is justified only when the capability needs independent scaling, a different security boundary, or a separate release cadence." |
| STD-ARCH-001 | 1.0 | Record the justification in an ADR. | "Record the justification in an ADR." |
| STD-OPS-001 | 1.0 | Small teams introduce at most one new runtime component per quarter and prefer fully managed services. | "Small teams introduce at most one new runtime component per quarter and prefer fully managed services." |
| STD-OPS-001 | 1.0 | Avoid gateways, queues, or clusters unless an existing platform team operates them. | "Avoid gateways, queues, or clusters unless an existing platform team operates them." |
| STD-AI-001 | 1.0 | AI output is advisory unless a documented exception is approved by the architecture board. | "AI output is advisory unless a documented exception is approved by the architecture board." |
| STD-AI-001 | 1.0 | Approvals, rejections, payments, and access grants always require a human decision. | "Approvals, rejections, payments, and access grants always require a human decision." |
| STD-AI-001 | 1.0 | Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited. | "Tools exposed to an agent are read-only or narrowly scoped to the record being processed, and every tool call is audited." |
| STD-SEC-001 | 2.0 | Service-to-service calls authenticate with managed identities or workload identity federation. | "Service-to-service calls authenticate with managed identities or workload identity federation." |
| STD-SEC-001 | 2.0 | API keys, connection-string secrets, and shared keys must not be stored in configuration or code. | "API keys, connection-string secrets, and shared keys must not be stored in configuration or code." |
| STD-SEC-001 | 2.0 | Disable local (key) authentication on AI and data services where the service supports it. | "Disable local (key) authentication on AI and data services where the service supports it." |
| STD-SEC-002 | 1.1 | Send AI services only the fields the use case needs. | "Send AI services only the fields the use case needs." |
| STD-SEC-002 | 1.1 | Attachments and personal data must not be sent. | "Attachments and personal data must not be sent." |
| STD-SEC-002 | 1.1 | Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers. | "Do not persist raw prompts or completions that contain free text entered by users; persist only structured results and identifiers." |
| STD-SEC-002 | 1.1 | Document the data flow in the ADR. | "Document the data flow in the ADR." |
| STD-DATA-002 | 1.0 | AI recommendations are retained for 90 days, then deleted. | "AI recommendations are retained for 90 days, then deleted." |
| STD-DATA-002 | 1.0 | Business decisions follow the organisation-wide seven-year rule. | "Business decisions follow the organisation-wide seven-year rule." |

## Conflicts needing a decision

- STD-SEC-002, STD-OBS-002: STD-SEC-002 forbids persisting raw prompts or completions that contain user free text, while STD-OBS-002 requires logging the full prompt and completion of every AI call for 30 days. These requirements conflict on how much AI text may be retained.

## Unknowns

- Whether the live AI triage provider needs independent scaling, a different security boundary, or a separate release cadence is not stated, so a separate service cannot be justified from the retrieved standards alone.
- The standards do not specify the exact shape of the AI triage input/output contract or which fields the use case needs, so the ADR must document the data flow and minimal payload.
- The standards do not resolve the logging conflict between prompt/completion retention and data minimization; an architect must decide how to comply without violating either standard.

## Review

- [ ] Citations, versions, and excerpts checked against the standards
- [ ] Each conflict and unknown has an owner
- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)
