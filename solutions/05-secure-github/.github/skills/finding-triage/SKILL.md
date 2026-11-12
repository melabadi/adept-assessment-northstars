---
name: finding-triage
description: Triage a real Copilot review or CodeQL SQL injection finding and verify scanner entitlement without inventing evidence.
---

# Finding triage

## Triggers and inputs
Use before accepting a security lab Issue. For Copilot code review, require the review comment URL and reviewed
SHA. Read the comment and confirm it identifies user-controlled search concatenated into SQL
in `ListAsync`. AI review is advisory and nondeterministic, not a scanner. If it misses the issue, record FAIL;
do not manufacture a finding. Request a fresh review after repair.
Use the cloud agent's built-in read-only `github` tools, not unauthenticated shell `gh`, for private repository
reads. If those tools are unavailable, a presenter can provide an authenticated **same-run** export containing
comment URL, author, reviewed SHA, path, line and body. Match that SHA to the local lab source and explicitly
record the inability to re-fetch it. Never substitute a previous demo's comment or invented review.

For the CodeQL path, inputs are repository, lab ref, alert URL, scan URL, immutable scanned SHA, SARIF downloaded
from that run, and expected state (`present` before repair, `absent` after).

## Procedure (CodeQL path only)
1. Run `python .github/skills/finding-triage/finding_triage.py preflight --repo OWNER/REPO --ref lab/secure-RUN --out out/preflight.json`.
   Requires authenticated `gh`. A private unlicensed repo returns BLOCKED and nonzero **before** CodeQL executes.
   Disabling SARIF upload is not a license workaround.
2. `secure-github-scan.yml` analyzes every pull request into a lab branch and every push to one, and uploads the
   results to code scanning, which flags new alerts on the pull request. A person can also dispatch it from `main`
   with an explicit expectation. Read the job summary, download `secure-codeql-evidence` with `gh run download`,
   and check the recorded `scanned_sha`. Do not substitute fixture SARIF or cached results for a live scan.
3. Summarize the SARIF with
   `python .github/skills/finding-triage/finding_triage.py sarif --input out/scan --expect present --sha FULL_SHA --out out/finding.json`.
   The workflow invokes this itself. The JSON contains query, location, tool version, expectation and timestamp.
4. Read the actual source and the alert's code flow. `cs/sql-injection` is CWE-89, high precision, security severity 8.8.
   The flow starts at the `q` parameter of `ApiEndpoints.ListRequests`, which the model pack in
   `.github/codeql/extensions` marks as remote input. Distinguish query injection, unescaped LIKE wildcards, and
   role/department scope. Do not claim authorization was bypassed merely because the SQL predicate changed.
5. Put the real alert URL, run URL, SHA, query, path, line and artifact in the remediation Issue; use the solution's
   task text. Link a Copilot Autofix suggestion if one was offered: it is a suggestion, verified only when the
   supplied regression passes.

## Expected output
`PASS: cs/sql-injection present (N finding(s))` with source location(s); after a fix, `PASS: ... absent (0 finding(s))`.
The parser is only a reporter; passing its unit tests is NOT CodeQL acceptance.

## Failure handling
Missing/malformed/empty SARIF, unsuccessful invocations, wrong tool or wrong expectation fail closed.
A BLOCKED preflight is not a clean scan. Resume only once the repository is public or an organization has enabled
Code Security. Never change visibility or buy/enable a product without the owner's decision.
A clean scan proves nothing if CodeQL can't see the API's input: the models in `.github/codeql/extensions` must
match the handlers in `ApiEndpoints.cs` (the solution's unit tests check them).
