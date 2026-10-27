---
name: deployment-recovery
description: Diagnose a Container Apps revision that is not serving (failing readiness, crash loop, image pull) from Azure's own evidence, then recover RequestHub - remove a candidate that never got traffic, or roll back to the previous revision with one traffic change - and verify production. Explains what a revision switch does not undo (database changes). Use when the release gate fails, when users report a problem after a release, or to rehearse a recovery.
---

# Deployment recovery

Two situations, two different moves:

| Situation | Users affected? | Move |
| --- | --- | --- |
| The gate failed: the candidate never became ready, or failed a smoke check | No: it had 0% of traffic | **Abort**: remove the candidate's label, deactivate it, verify production |
| A promoted release misbehaves | Yes | **Roll back**: one atomic traffic change to the previous revision, which is still running, then verify |

## When to use
- The `Release · Microsoft · roll out a candidate revision` run failed in its gate (the abort job already removed the
  candidate; use the diagnosis to explain why).
- Users report a problem after a promotion.
- Before a demo, to rehearse a bad release and a rollback.

## Inputs
- Settings from the solution's azd environment, or `AZURE_RESOURCE_GROUP`, `API_APP_NAME`, and `API_IDENTIFIER_URI`.
- An Azure CLI sign-in with Container Apps Contributor (or Operator to read logs) on the app.

## Procedure
1. Diagnose: `python .github/skills/deployment-recovery/diagnose.py` (default: the candidate; `--revision <suffix>` for
   another). It prints the revision's state, each container's readiness and restarts, the probes, Azure's warnings
   (for example `Probe of Readiness failed with status code: 503`), and the app's own error lines (for example
   `Health check fault-injection with status Unhealthy`). It changes nothing.
2. Recover, from `solutions/06-release-microsoft`:
   - Candidate with 0% of traffic: `python release.py abort`.
   - Users affected: `python release.py rollback`, or run `Release · Microsoft · roll back to the previous revision`
     (`gh workflow run release-microsoft-rollback.yml`). Running it again rolls forward.
   - Previous revision deactivated: `python release.py rollback --to <revision>` reactivates it and waits until it is
     ready before moving traffic. Or release an earlier image by digest:
     `python release.py deploy --image <registry>/requesthub-api@sha256:<digest>`, then `gate` and `promote`.
3. Verify: `python release.py verify` runs the production smoke test. `rollback` and `abort` run it themselves.
4. Record: `python release.py record` writes `out/release/release-record.md`. Attach it to the Issue or incident.
5. Fix the cause in code or configuration and release again through the gate.

## What a rollback does not undo
A rollback changes which code serves requests. It does not roll back the database: every revision shares one
PostgreSQL database, and a candidate applies its EF Core migrations when it starts, even if it never receives traffic.
Keep migrations backward compatible (expand first, remove old columns in a later release) so the previous revision keeps
working, and never assume a destructive migration reverses itself. Requests written while the newer revision served
traffic stay in the database.

## Expected output
```
4. Azure's warnings for this revision (system log stream)
   Probe of Readiness failed with status code: 503 (x9)
   Readiness Probe of Readiness reached failure threshold 3, changing status to Failure.
5. The app's own error lines (console log stream)
   Health check fault-injection with status Unhealthy with message 'Fault injection: readiness intentionally failing (Faults:FailReadiness).' (x11)
Next step
   It has no traffic, so no user reached it. Remove it: python solutions/06-release-microsoft/release.py abort

Roll back to the previous revision
  · Traffic: t1027140237 100% → ksuh29a 100% (one atomic change)
  · Users meanwhile: 28/28 calls to production succeeded (100.0%)
✓ Rolled back in 12 s: ksuh29a serves 100% of traffic and passed the smoke test.
```

## Failure handling
- `log stream unavailable`: your identity lacks log stream rights on the app; ask for Container Apps Operator.
- `Cannot roll back: ... is not ready`: the rollback target would fail too, so traffic stays where it is. Pick another
  revision with `--to`, or release a known-good digest through the gate.
- Never re-promote a candidate that failed, never relax a probe or the gate to recover faster, and never inject a fault
  into the stable revision.
