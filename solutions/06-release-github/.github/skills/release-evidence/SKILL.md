---
name: release-evidence
description: Build, check, and explain the evidence of a RequestHub release on GitHub - gated test reports, a smoke test of the release images, a release manifest with image digests and SHA-256 checksums, and the approval record. Use when preparing a release candidate, before anyone approves a draft release, after publishing, or when someone asks what exactly was tested and approved.
---

# Release evidence

## When to use
- "Prepare release 1.2.0", "is demo-v1.2.0 ready for approval?", "what was tested in this release?", "verify this release".
- Before a person approves a draft release, and after publishing to show the release is intact.

## Inputs
- A version such as `1.2.0`; its tag is `demo-v1.2.0`.
- `.github/workflows/release-github-candidate.yml` builds the evidence and stops at a draft release. `.github/workflows/release-github-approve.yml` records a person's approval and publishes.
- The scripts in this folder (standard library only, Python 3.12+; each has `--help`):
  - `summarize_tests.py`: counts every JUnit report and fails the gate on a missing report, zero tests, or any failure.
  - `smoke_test.py`: runs the business flow against running release images (health, build SHA, submit, triage, decision, history, self-approval refused, notifications delivered).
  - `release_evidence.py`: `preflight`, `assemble`, `verify`, and `approve`.

## Procedure
1. Start a candidate from `main`: `gh workflow run release-github-candidate.yml -f version=1.2.0`. Follow it with `gh run watch <run-id>`. Preflight refuses other branches, versions already released, and a missing `release-github` environment.
2. When it succeeds, verify the draft:
   `python .github/skills/release-evidence/release_evidence.py verify --tag demo-v1.2.0 --expect draft`
   It downloads the draft's assets, checks them against `SHA256SUMS`, recounts every test report, and checks that the commit is on `main` and that the candidate run succeeded. The image check needs a token that can read packages (`GHCR_TOKEN`); without one it is skipped locally.
3. Brief the approver from `release-manifest.json` and the verify output: commit, image digests, tests per suite, and anything the AI summary flags under **Risks to check**.
4. Hand over. The person approves by running `gh workflow run release-github-approve.yml -f tag=demo-v1.2.0 -f comment="..."`. Never run it for them.
5. After approval: `python .github/skills/release-evidence/release_evidence.py verify --tag demo-v1.2.0 --expect published` also checks the git tag and `approval-record.json`.

## Expected output
- A draft release with `release-manifest.json`, `SHA256SUMS`, `test-summary.json`, four JUnit reports (`api`, `web`, `smoke`, `browser`), `smoke-results.json`, two SPDX SBOMs, and `whats-changed.md`.
- Verify output ending in `0 failed`, for example `9 passed, 1 skipped, 0 failed`.
- After approval: `approval-record.json` with the approver, time, note, environment rules, and the SHA-256 of the manifest they approved.

## Failure handling
- `built from main: FAIL`: dispatch the candidate on `main` (`gh workflow run ... --ref main`).
- `new version: FAIL`: the version exists or is not higher than the latest demo release; pick a higher version or reset the demo.
- `environment: FAIL`: create the `release-github` environment and restrict it to `main` (see the solution README, Set up).
- `checksums: FAIL ... changed after the candidate run`: an asset was edited or replaced. Do not approve; build a new candidate.
- `tests: FAIL`: a report disagrees with the manifest, or a suite failed. Investigate with the workflow-investigation skill.
- `candidate run: FAIL ... in_progress`: wait for the run to finish, then verify again.
- `images: SKIP` (no token, or a token without `read:packages`): the local check proves nothing either way. Refresh the scope with `gh auth refresh -s read:packages`, then `$env:GHCR_TOKEN = gh auth token`, or rely on the approval workflow, which checks the images with its own token. A local HTTP 401, 403, or 404 from the registry means the same; never report the images as missing from a local check.
