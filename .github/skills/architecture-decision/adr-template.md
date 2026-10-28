# ADR NNNN: <decision title>

- **Status:** Proposed
- **Date:** YYYY-MM-DD
- **Deciders:** to be named in the design review (people, never an agent)
- **Related:** <the brief, issue, or pull request this ADR answers>

## Context

<The problem, for whom, and the constraints. Name the brief and the code you read, with real paths in backticks.>

## Decision drivers

- <driver, citing the standard that sets it, for example STD-ARCH-001 v1.0>

## Options considered

### Option A: <option name>

<How it works in this code base. Pros. Cons. The standards that favour or block it, for each operating profile.>

### Option B: <option name>

<Same structure as option A.>

## Decision

<The recommended option for each operating profile, and why. While the status is Proposed, this is a recommendation, not a sign-off.>

## Architecture

```mermaid
flowchart LR
  %% components, trust boundaries, and data flows of the recommended option
```

```mermaid
sequenceDiagram
  %% one request, end to end, including the failure path. No ";" inside a message: it ends the statement.
```

## API impact

<The report from the contract-impact skill, and the endpoints and fields the design relies on. A needed change must be additive (STD-API-001 v1.0).>

## Threat model checklist

- [ ] Only <fields> are sent to the AI service; no attachments or personal data (STD-SEC-002 v1.1)
- [ ] Service-to-service calls use a managed identity, never keys (STD-SEC-001 v2.0)
- [ ] Agent tools are read-only, scoped to the record being processed, and audited (STD-AI-001 v1.0)
- [ ] Instructions hidden in request text cannot trigger approvals or reads of other records
- [ ] Timeouts and outages are visible to the user, and manual routing keeps working (STD-OBS-001 v1.2)

## Consequences

<Positive, negative, and follow-up work.>

## Implementation tasks

1. <bounded task with an owner role and an observable acceptance criterion>

## Open questions

<Conflicts between standards and unknowns that a person must decide. Write "None" only if there are none.>
