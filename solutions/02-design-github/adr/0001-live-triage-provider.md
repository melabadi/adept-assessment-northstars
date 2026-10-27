# ADR 0001: Live AI triage provider

- **Status:** Proposed
- **Date:** 2026-10-27
- **Deciders:** to be named in the design review (people, never an agent)
- **Related:** `solutions/02-design-github/inputs/reviewed-brief.md`

## Context

Reviewers need a fast, bilingual recommendation with policy citations, while humans retain routing and approval authority. BR-3 limits AI inputs to request title, description, category, and approved routing policies; BR-4 requires recommendation and tool-call auditing; BR-5 requires graceful manual fallback; BR-6 sets an 8-second p95 target.

The existing `ITriageProvider` is selected through `Triage:Provider` in `app/src/RequestHub.Api/Program.cs`. `RequestWorkflow` authorizes triage for staff of the current department, scopes tools to the current request, validates results, audits and stores recommendations, and currently uses a configurable 45-second timeout. The existing `FoundryTriageProvider` runs inside the API and authenticates with `TokenCredential`, but its outbound data flow does not yet meet BR-3: the initial prompt sends `requestId`, category, and a department list; the `get_request` tool response sends title, description, category, current department, and priority. Both prompt and tool-result content pass to the AI service. These fields must be narrowed to the permitted title, description, category, and approved routing policies; identifiers, department lists, and current routing state must not be sent outside the API. `app/infra/requesthub.bicep` already provisions the app identity and monitoring, but does not show an AI-service or gateway role assignment.

## Decision drivers

- Preserve the current API authorization, policy validation, human-controlled routing, and approval boundary (STD-AI-001 v1.0).
- Send only the allowed request fields and approved routing policies; do not persist raw free-text prompts or completions (STD-SEC-002 v1.1).
- Use managed identity, not keys, for service calls (STD-SEC-001 v2.0).
- Measure dependency calls and surface timeouts promptly without blocking manual routing (STD-OBS-001 v1.2).
- Keep a small-team deployment simple and managed (STD-ARCH-001 v1.0; STD-OPS-001 v1.0).
- Route enterprise model and agent traffic through the central AI gateway (STD-OPS-002 v2.0); trace and evaluate enterprise AI calls (STD-AI-002 v1.0).
- Apply the profile retention rules: 90 days for small-team recommendations (STD-DATA-002 v1.0); 13 months for enterprise recommendations and their audit entries, and seven years for business decisions (STD-DATA-001 v1.0).

## Options considered

### Option A: API-hosted provider calls the managed AI endpoint directly

### Option B: API-hosted provider calls the managed AI endpoint through central APIM

| Constraint | Option A: direct managed endpoint | Option B: central APIM gateway |
| --- | --- | --- |
| How it fits this code | Keep the provider in `RequestHub.Api`, implement `ITriageProvider`, and select it through the existing `Triage:Provider` setting. The provider calls a managed AI endpoint directly. | Keep the same in-process provider and selection point, but configure its endpoint through the central Azure API Management AI gateway before reaching the managed agent/model. |
| Small team | Lowest operational overhead; uses the existing API runtime and a managed endpoint. Fits STD-ARCH-001 v1.0 and STD-OPS-001 v1.0. | Adds a gateway dependency and its configuration/monitoring. STD-OPS-001 v1.0 says to avoid gateways unless an existing platform team operates them, so this is not preferred for this profile. |
| Enterprise | Fewer hops, but production direct model/agent calls are prohibited by STD-OPS-002 v2.0. Not acceptable for enterprise. | Central quotas, rate limits, and usage reporting meet STD-OPS-002 v2.0. The central platform team can operate the gateway; request processing remains in the existing API. |
| Security, data, and audit | Managed identity and an exact payload allowlist are required. The API can retain its scoped tools and audit workflow. | Same app-side controls, plus gateway identity, per-department policy, and gateway telemetry. Gateway logs must not persist disallowed free text. |
| Latency and failure | One fewer hop, but endpoint availability and throttling remain the app's responsibility. Must meet the 8-second p95 and timeout UX targets. | Extra hop and gateway throttling may affect latency; centrally governed quotas and usage are a benefit. The same end-to-end budget and fallback are required. |

## Decision

Recommend Option A for the small-team profile: it keeps the live provider inside the existing API and avoids an extra runtime dependency that the small-team standard discourages.

Recommend Option B for enterprise: the central gateway is mandatory under STD-OPS-002 v2.0 and the enterprise profile has a central platform team to operate it. This profile difference is intentional: operational simplicity wins for the small team; centrally enforced enterprise governance wins for enterprise.

For either option, keep the provider advisory and the synchronous request path. Use the existing workflow for authorization, policy/result validation, persistence, audit, and explicit failure responses. The API screens title and description, approved policy text, and every tool result before constructing or forwarding each outbound message. The screening gate detects direct identifiers and other personal data; a positive, uncertain, or failed screening blocks the AI call (fail closed). Do not redact and forward flagged content. This applies before both the direct endpoint and APIM, and does not rely on prompt instructions or the field allowlist as screening. Return a clear content-blocked/manual-routing response, make no AI call, and keep manual routing available. Change the internal provider/tool payload so the AI receives only screened title, description, category, and approved routing policies. Never send request identifiers, attachments, comments, current department/priority, or unrelated department data. Bind any read tool to the in-memory request being triaged and give it no caller-selectable record id.

The model must not infer the current department. Update its instructions and structured output schema with a `keep_current` abstention disposition: for insufficient context under POL-ROUTE-007 or conflicting routing policies, abstain from choosing a department, set human review, and provide one clarifying question when context is insufficient. The department field is absent for this disposition. Before workflow validation, the API-side provider adapter maps `keep_current` to the authorized request's in-memory current department and forces human review; that department remains local and is never included in the prompt or tool result. Existing workflow policy-conflict checks remain authoritative. Keep recommendation and tool audit metadata, but do not store raw user text in application or gateway logs. Tune the configured deadline to meet the end-to-end 8-second p95 target; a timeout must result in a user-visible unavailable response within two seconds, with manual routing unaffected.

## Architecture

```mermaid
flowchart LR
  reviewer[Reviewer] -->|authenticated recommendation request| api[RequestHub API]
  subgraph appBoundary["RequestHub trust boundary"]
    api --> workflow[RequestWorkflow: authorize, scope, validate, audit]
    workflow --> provider[ITriageProvider in API]
    workflow --> db[(PostgreSQL: recommendation and audit metadata)]
    workflow --> audit[Scoped read-only tools for current request]
  end
  audit -->|screened title, description, category; approved policy data| provider
  subgraph profileRoute["Profile-selected service route"]
    provider -->|small team: managed identity| model[Managed AI agent/model]
    provider -->|enterprise: managed identity + candidate API-derived quota scope (open)| apim[Central Azure API Management AI gateway]
    apim -->|strip quota scope; forward allowed payload| model
  end
  model -->|advisory result and trace id| provider
  provider --> workflow
  workflow -->|stored recommendation; explicit unavailable on failure| reviewer
  reviewer -->|human confirms routing| workflow
  reviewer -->|approver decides separately| api
```

```mermaid
sequenceDiagram
  actor Reviewer
  participant API as RequestHub API
  participant WF as RequestWorkflow
  participant Provider as ITriageProvider
  participant Route as Profile route (direct or APIM)
  participant AI as Managed agent/model
  participant Tool as Scoped read-only tool
  participant DB as PostgreSQL
  Reviewer->>API: POST /api/requests/{id}/triage-recommendations
  API->>WF: authenticated user and request id
  WF->>WF: authorize current-department staff; scope tools to this request
  WF->>WF: screen free text and approved policy content before egress
  alt personal data detected, uncertain, or screening fails
    WF-->>API: content blocked; no provider call
    API-->>Reviewer: manual routing remains available
  else screening passes
    WF->>Provider: local context, including current department for fallback only
    alt provider responds within deadline
      Provider->>Route: screened allowed fields and policies; candidate enterprise quota scope
      Note over Route,AI: APIM strips any approved gateway-only quota scope before model forwarding
      Route->>AI: recommendation request
      opt agent requests scoped tool
        AI-->>Route: tool call (no record id argument)
        Route-->>Provider: tool call
        Provider->>Tool: execute against current request only
        Tool->>DB: audit actor, time, tool, outcome, safe result metadata
        Tool-->>Provider: allowed fields or approved policies
        Note over Provider,Route: Screen every tool result; blocked or uncertain content returns manual fallback and is not forwarded
        Provider->>Route: screened scoped tool result
        Route->>AI: tool result
      end
      AI-->>Route: structured disposition (recommend or keep_current) and trace id
      Route-->>Provider: response
      alt agent abstains for insufficient context or policy conflict
        Provider->>Provider: map keep_current to local current department; force human review
      else agent recommends a route
        Provider->>Provider: retain suggested department
      end
      Provider-->>WF: result
      WF->>WF: validate mapped department, priority, cited policies; enforce policy-conflict human review
      WF->>DB: persist structured recommendation and audit metadata
      DB-->>WF: saved
      WF-->>API: 201 RecommendationDto
      API-->>Reviewer: recommendation; reviewer decides whether to route
    else timeout or unavailable
      Provider--xRoute: timeout or dependency failure
      WF->>DB: audit triage failure and save
      WF-->>API: 504 or 503; manual routing remains available
      API-->>Reviewer: unavailable; route manually
    end
  end
```

## API impact

## API contract impact (requesthub.v1 vs origin/main)
**Compatible**: additive-only changes are allowed within the current contract version (STD-API-001).

- Breaking changes: 0
- Additive changes: 0

No contract changes.

The design relies on:

- `POST /api/requests/{id}/triage-recommendations` for a recommendation; its `RecommendationDto` includes `suggestedDepartmentId`, `suggestedPriority`, `rationale`, `policyRefs` (policy id and version), `confidence`, `needsHumanReview`, and `providerTraceId`. Existing 403, 404, 409, 502, 503, and 504 responses support authorization and provider failure.
- `GET /api/requests/{id}/triage-recommendations` for previously stored recommendations.
- `GET /api/requests/{id}` for authorized request detail; the AI input is limited to `title`, `description`, and `category`, not other `RequestDetailDto` fields such as requester, comments, or attachments.
- `GET /api/policies` for approved policy identifiers, versions, and content. The provider sends only fields needed from approved policies.
- `GET /api/requests/{id}/history` for audit history, `PUT /api/requests/{id}/routing` for a human reviewer to change routing, and `POST /api/requests/{id}/decisions` for a separate human approval/rejection.

No public API change is needed for this design. If later work exposes a new locale or provider-control field publicly, add an optional field or endpoint under STD-API-001 v1.0; do not change the existing requesthub.v1 field types or validation.

## Threat model checklist

- [ ] Outbound AI payload contains only request title, description, category, and approved routing policies; no request id, requester identity, comments, attachments, or other personal data (STD-SEC-002 v1.1).
- [ ] Provider and gateway authenticate with managed identities; no API keys or shared secrets are configured, and local key authentication is disabled where supported (STD-SEC-001 v2.0).
- [ ] Any agent tools are read-only, scoped to the current request and approved policies, and audited for actor, time, tool, outcome, and safe result metadata (STD-AI-001 v1.0).
- [ ] Request text and policy content are treated as untrusted instructions; tool calls cannot read another record, change routing, approve, reject, or bypass the workflow.
- [ ] The user sees provider unavailability within two seconds after timeout; manual routing remains available, and the 8-second recommendation p95 is measured (STD-OBS-001 v1.2).
- [ ] Provider trace id is correlated with the recommendation and business record; enterprise release evidence includes a versioned evaluation dataset with at least ten labelled cases, including adversarial cases (STD-AI-002 v1.0).
- [ ] Recommendation and tool audit persistence follows the selected profile retention; application and gateway logs do not persist raw user-text prompts or completions (STD-DATA-001 v1.0; STD-DATA-002 v1.0; STD-SEC-002 v1.1).

## Consequences

- Positive: preserves current authorization and human decision boundaries; no new RequestHub runtime is added; enterprise usage controls are centralized.
- Negative: provider and internal tool changes are needed to remove extra prompt fields. Enterprise adds a gateway hop and platform dependency.
- Follow-up: add least-privilege managed-identity permissions and profile-specific endpoint configuration; instrument latency and dependency failures. No application, contract, or infrastructure changes are included in this ADR.
- The current workflow timeout defaults to 45 seconds, so configuration and tests must change to meet the brief's latency target.

## Implementation tasks

1. **API/provider engineer:** implement the profile-selected provider route, pre-egress screening for the initial prompt and every tool result, and an exact outbound field allowlist; bind tools to the current request without exposing a selectable request id. Update agent instructions/schema to represent `keep_current` without a department, and map that disposition to the local current department before workflow validation. Acceptance: tests place synthetic personal data separately in title and description and verify, on both direct and APIM routes, that positive/uncertain/failed screening makes no provider call and preserves manual routing; clean text tests capture every outbound message and show only allowed screened fields/policies, with no request id, current department, priority, attachments, or personal data. Additional tests prove insufficient-context and policy-conflict abstentions map to the current department, force human review, and (for insufficient context) carry one clarifying question.
2. **Platform engineer:** provision least-privilege managed-identity access for the direct managed endpoint and configure the enterprise APIM route. Acceptance: deployment uses no AI key; enterprise traffic is observed at APIM and direct production endpoint access is denied. Once the gateway-scope question below is resolved, integration tests prove two departments consume isolated quota/usage buckets, client-supplied scope is rejected, and gateway-only scope is absent from the model payload.
3. **Core workflow engineer:** set and test an end-to-end deadline, retain recommendation validation and human-only routing/approval, and surface timeout/unavailable states. Acceptance: deterministic tests cover timeout, invalid result, service outage, and continued manual routing; telemetry reports p95 and users receive unavailable within two seconds of timeout.
4. **Audit/privacy engineer:** audit recommendation and every tool invocation with actor, timestamp, request correlation, provider/tool, outcome, trace id, and only safe structured return metadata; implement profile retention. Acceptance: tests show no raw request free text in audit rows, application logs, or gateway logs; small-team recommendations expire at 90 days and enterprise recommendations/audit entries at 13 months.
5. **AI quality engineer:** validate English and French results, policy citations, and adversarial prompt handling; prepare enterprise release evaluation evidence. Acceptance: both languages pass the agreed labelled cases, and enterprise release evidence contains a versioned dataset of at least ten labelled cases including adversarial inputs (STD-AI-002 v1.0).

## Open questions

- **Conflicting logging standards:** STD-OBS-002 v1.0 requires full prompts and completions in the application log workspace for 30 days; STD-SEC-002 v1.1 prohibits persisting raw prompts or completions containing user free text. The proposed flow obeys data minimization and does not persist raw free text, but cannot meet both requirements when prompts or responses contain request text. A reviewer must decide whether to revise/interpret one standard or approve a safe alternative; this ADR does not resolve the conflict.
- **Audit detail:** BR-4 says audit what each tool returned, while STD-SEC-002 v1.1 prohibits persisting raw user-entered free text. Is structured field/policy metadata plus a response digest sufficient, or is an approved redacted audit representation required? This also affects whether recommendation rationale may be stored verbatim.
- **Small-team audit retention:** STD-DATA-002 v1.0 defines recommendation retention but not a retention period for tool-call audit entries. What retention applies to those entries in the small-team profile?
- **Enterprise gateway compatibility:** Can the central Azure API Management AI gateway front the selected managed agent endpoint while preserving managed identity, trace identifiers, the required tool-call flow, and the 8-second p95? The platform team must confirm before implementation.
- **Trusted department scope for gateway quotas:** STD-OPS-002 v2.0 requires per-department quotas and usage reporting, but the shared app managed identity does not distinguish departments and current department must not reach the model. Should the API derive a gateway-only quota scope from the authorized request's current department and attach it as trusted metadata for APIM to validate and strip before model forwarding? What mechanism binds that scope to the authenticated API call and rejects caller-supplied or spoofed scope? Leave this boundary unresolved for reviewer/platform-owner decision; accept only after a two-department quota-isolation test proves separation and verifies the scope is removed before model forwarding.
- **Personal-data screening effectiveness:** Which app-side screening implementation and evaluation threshold should be approved before launch? The proposed boundary fails closed on positive, uncertain, or failed screening; reviewers must confirm it catches the synthetic title/description cases and tool-result content without logging the rejected free text.
- **Bilingual behavior:** Where should English or French be selected (request language, reviewer preference, or explicit UI locale), given that the current provider context has no locale field? The decision must avoid sending additional personal data and keep any public contract change additive.
