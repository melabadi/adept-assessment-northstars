# Recorded remediation evidence

This is a one-time, unchanged snapshot of **secure-remediation-evidence** from
[Actions run 41266391843](https://github.com/melabadi/adept-assessment-northstars/actions/runs/41266391843),
completed on 2026-11-01 UTC. It replays the recorded Copilot repair in
[PR #105](https://github.com/melabadi/adept-assessment-northstars/pull/105), even though its lab branches were deleted.

Actions logs and artifacts expire after 90 days here, and viewing job logs requires signing in.
These committed files remain readable without signing in and do not expire with the Actions run.
They preserve one execution, not the latest nightly result or proof that all vulnerabilities are absent.

| File | What it records |
| --- | --- |
| [results.json](results.json) | Immutable base, tests-only and repair commits; six failures before, ten passes after, full suite passed |
| [before-test.log](before-test.log) | Actual baseline assertions, including injected search returning unintended records |
| [after-test.log](after-test.log) | The identical ten regression cases passing after repair |
| [after-full-suite.log](after-full-suite.log) | All 70 API/worker/contract tests passing |
| [before/search.junit.xml](before/search.junit.xml) | Machine-readable baseline cases and six failures |
| [after/search.junit.xml](after/search.junit.xml) | Machine-readable repaired cases with no failures, errors or skips |

PR metadata and build logs are deliberately omitted. The nightly workflow only reads source and publishes
Actions evidence; it never commits, comments, pushes, calls Copilot or creates new lab resources.
