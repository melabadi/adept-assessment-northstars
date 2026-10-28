# Reviewed brief: assisted request triage (input to the Design phase)

> Synthetic, already-reviewed requirements so the Design phase can run on its own. Source: Plan phase workshop, review sign-off by the product owner.

## Problem
Reviewers reroute many requests by hand because requesters pick the wrong department. RequestHub needs an assistant that proposes the department and priority, cites the routing policy it used, and leaves every decision to people.

## Accepted requirements
| ID | Requirement |
| --- | --- |
| BR-1 | A reviewer can ask for a triage recommendation on any request they can see. The recommendation includes department, priority, rationale, cited policy IDs and versions, and a confidence value. |
| BR-2 | Recommendations are advisory. A reviewer confirms routing; only an approver approves or rejects (POL-GOV-001). |
| BR-3 | Only the request title, description, category, and approved routing policies may be sent to the AI service. No attachments or personal data. |
| BR-4 | Every recommendation and every tool call made by the assistant is audited with who asked, when, and what was returned. |
| BR-5 | When the AI service is unavailable or slow, the UI says so and manual routing keeps working. |
| BR-6 | The recommendation appears within 8 seconds at the 95th percentile (agreed during review). |
| BR-7 | English and French. |

## Constraints
- RequestHub runs on Azure Container Apps with PostgreSQL; the public API contract is `requesthub.v1` (see `app/contracts/openapi.json`).
- The app already has a triage extension point: `ITriageProvider` in `app/src/RequestHub.Core/Triage/ITriageProvider.cs`.
- Two operating profiles must be considered: a **small team** (one squad, minimal operations) and an **enterprise** rollout (several departments, central platform team).

## Open design question
How should RequestHub add a live AI triage provider while preserving access controls, human approval, observability, and a low-complexity deployment?
