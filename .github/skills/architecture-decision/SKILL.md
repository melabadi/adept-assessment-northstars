---
name: architecture-decision
description: Write an Architecture Decision Record (ADR) for RequestHub that compares at least two options against the approved standards and the real code, with mermaid architecture and sequence diagrams, an API impact section, a threat-model checklist, and bounded tasks; then check it deterministically. Use for design questions and design reviews.
---

# Architecture decision

## When to use
- A design question needs a recorded decision (for example "how do we add a live AI triage provider?").
- Reviewing an ADR in a pull request.

## Inputs
- The question and reviewed brief (`phases/02-design/inputs/reviewed-brief.md`).
- Approved standards (`phases/02-design/standards/STD-*.md`) with ids, versions, and scopes.
- The real system: `app/contracts/openapi.json`, `app/src/RequestHub.Core/Triage/ITriageProvider.cs`,
  `app/src/RequestHub.Core/Services/RequestWorkflow.cs`, `infra/core.bicep`.
- Template: `adr-template.md` in this folder.

## Procedure
1. Read the brief, every standard, and the code listed above. Note which standards apply to the small-team and enterprise profiles.
2. Copy `adr-template.md` to `docs/adr/NNNN-<slug>.md` (next free number).
3. Compare at least two concrete options. For each: pros, cons, and the standards that favour or block it.
4. Recommend one option. Keep **Status: Proposed**; only a person can accept an ADR.
5. Draw the architecture (`flowchart`) and the request flow (`sequenceDiagram`) in mermaid.
6. Fill **API impact** with the contract-impact skill (or state "No contract change" and why).
7. Fill the threat-model checklist for the real data flow and list bounded implementation tasks.
8. Run `python .github/skills/architecture-decision/check_adr.py docs/adr/NNNN-<slug>.md` until it prints `PASS`.

## Expected output
- `docs/adr/NNNN-<slug>.md` passing `check_adr.py`, ready for a design review PR.

## Failure handling
- `cites unknown standard`: use only ids that exist in `phases/02-design/standards/`.
- `references missing path`: fix the path or remove it; never reference code that does not exist.
- `an Accepted ADR must name human deciders`: set Status back to Proposed; acceptance happens in review.
