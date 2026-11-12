# Recorded remediation evidence

These files are unchanged copies of artifacts from the run in the [README](../README.md#see-it-work), on 12 November 2026.
Actions logs and artifacts expire after 90 days here, and viewing job logs requires signing in. These committed files remain
readable without signing in and do not expire with the Actions runs. They preserve single executions, not the latest nightly
result or proof that all vulnerabilities are absent.

The replay of Copilot's repair, [#389](https://github.com/melabadi/adept-assessment-northstars/pull/389), from
[Actions run 43283642097](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43283642097)
(**secure-remediation-evidence**):

| File | What it records |
| --- | --- |
| [results.json](results.json) | Immutable base, tests-only and repair commits; six failures before, ten passes after, full suite passed |
| [before-test.log](before-test.log) | The baseline assertions: injected searches returning unintended records, and a quote breaking the SQL |
| [after-test.log](after-test.log) | The identical ten regression cases passing after the repair |
| [after-full-suite.log](after-full-suite.log) | All 77 API, worker and contract tests passing |
| [before/search.junit.xml](before/search.junit.xml) | Machine-readable baseline cases and six failures |
| [after/search.junit.xml](after/search.junit.xml) | Machine-readable repaired cases with no failures, errors or skips |

CodeQL's checks of the expected result (`finding.json` from **secure-codeql-evidence**):

| File | What it records |
| --- | --- |
| [codeql/lab-pull-request.json](codeql/lab-pull-request.json) | The scan of lab pull request [#386](https://github.com/melabadi/adept-assessment-northstars/pull/386), [run 43278396034](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43278396034): `cs/sql-injection` present at `RequestWorkflow.cs:47` in its merge commit, CodeQL 2.27.4 |
| [codeql/repair.json](codeql/repair.json) | The trusted scan from `main` of the repair's head, [run 43285574924](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43285574924): `cs/sql-injection` absent |

The replay of Copilot Autofix's suggestion, [#391](https://github.com/melabadi/adept-assessment-northstars/pull/391), from
[Actions run 43281999895](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43281999895):

| File | What it records |
| --- | --- |
| [autofix/results.json](autofix/results.json) | `FAIL`: the regression still fails after the suggested change |
| [autofix/after-test.log](autofix/after-test.log) | The two failing cases: a literal `%` search returning 19 records instead of 1, and `_` returning 25 instead of 0 |
| [autofix/after/search.junit.xml](autofix/after/search.junit.xml) | Machine-readable cases: the four injection cases passing, two wildcard cases failing |

Pull request metadata and build logs are deliberately omitted. The nightly workflow only reads source and publishes
Actions evidence; it never commits, comments, pushes, calls Copilot or creates new lab resources.
