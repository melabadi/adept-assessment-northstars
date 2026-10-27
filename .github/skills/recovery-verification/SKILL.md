---
name: recovery-verification
description: Decide whether RequestHub's notification worker has really recovered after an incident - fault removed, backlog drained, a new request's notifications delivered, alert resolved, SRE Agent investigation on record - and record the evidence. Use after a mitigation, before closing an incident, and before resetting the drill.
---

# Recovery verification

Recovery is a set of checks against the live services, not an impression from a dashboard. The script reads the worker's
configuration, the backlog from RequestHub's Admin API, the alert from Azure Monitor, and the investigation from Azure
SRE Agent, and submits one synthetic request to prove that notifications flow again.

## Procedure
1. Run `python solutions/07-operate-microsoft/incident.py verify` (about one minute).
2. Read each line:

   | Check | PASS means | If not |
   | --- | --- | --- |
   | Fault removed | The worker's active revision has no `Faults__` settings. | The mitigation did not run, or a new revision is still starting. Check `az containerapp revision list`. |
   | Backlog drained | No pending notifications and the oldest is younger than the threshold. | Wait a minute after the new revision is ready, then rerun. If it stays, use **telemetry-investigation**. |
   | New request notified | A synthetic request's notifications were delivered within a minute. | The worker is not processing. Escalate with the evidence. |
   | Alert resolved | Azure Monitor resolved the backlog alert. | `WAIT`: metric alerts resolve after three healthy minutes. Rerun. |
   | SRE Agent investigated | An investigation thread exists for this drill. | Check the response plan with `configure_sre_agent.py` and the agent's **Incidents** page. |

3. Exit code 0 means every check passed. The results are added to `solutions/07-operate-microsoft/out/drill.json`.
4. Write the incident summary: `python solutions/07-operate-microsoft/incident.py summary` (add `--issue` to file it
   as a GitHub Issue). The summary is sanitized: no subscription, tenant, or object ids, and no email addresses.

## Rules
- Never mark an incident recovered on missing data: no telemetry is not a healthy signal.
- Never edit `drill.json` by hand; it is the evidence.
- After the checks pass and the summary is filed, run `incident.py reset` so no fault or synthetic data is left behind.
