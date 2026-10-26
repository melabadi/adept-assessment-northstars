# RequestHub routing policies (general profile)

> Approved synthetic policies. The same IDs and versions ship in the app (`app/src/RequestHub.Core/Profiles/general.json`) and are returned by `GET /api/policies`.

| ID | Version | Title | Rule |
| --- | --- | --- | --- |
| POL-ROUTE-001 | 1.2 | Computing equipment | Laptops, monitors, docking stations, keyboards, headsets, tablets and other computing peripherals route to IT Services (IT). Use High priority only when the requester cannot work without the item. |
| POL-ROUTE-002 | 1.0 | Software and business application access | Software licences, SaaS subscriptions, cloud storage, and access to business applications such as CRM or booking systems route to IT Services (IT). |
| POL-ROUTE-003 | 2.1 | Workplace and building services | Desks, chairs, projectors, meeting rooms, building access badges, parking, cleaning and repairs route to Facilities (FAC). |
| POL-ROUTE-004 | 1.1 | Spend threshold | Any request with an estimated cost above 5,000 must route to Finance (FIN) for budget review. |
| POL-ROUTE-005 | 1.0 | People changes | Onboarding, offboarding, role changes and training requests route to People (HR). |
| POL-ROUTE-006 | 1.0 | Safety first | Any reported safety hazard, such as exposed wiring, a water leak, or a blocked exit, is Urgent and routes to Facilities (FAC) regardless of category. |
| POL-ROUTE-007 | 1.0 | Unclear requests | When a request lacks the information needed to determine the owning department, keep its current department, mark it for human review, and ask one clarifying question. |
| POL-GOV-001 | 1.0 | Human approval | Triage recommendations are advisory. Only an authorized approver may approve or reject a request. A recommendation must never state or imply that a request is approved. |

Note: POL-ROUTE-001 and POL-ROUTE-004 do not say which one wins for expensive computing equipment. That gap is intentional.
