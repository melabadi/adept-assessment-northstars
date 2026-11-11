# Evidence: the sandbox's setup on 11 November 2026

Why [`run_change.sh`](../sandbox/run_change.sh) stopped installing PostgreSQL with apt, and the runs that checked the change, exported so that anyone can check them without signing in to Azure. Times are UTC, all on 11 November 2026.

- **Exported** on 11 November 2026 from resource group `rg-ai-sdlc-develop`, with the command shown below, run in PowerShell 7 from `solutions/03-develop-microsoft` after `azd env select ai-sdlc-develop`. It keeps only times, pull request numbers, review ids, and the Function's own log lines. Application Insights keeps 30 days of data, so the query returns nothing after 11 December 2026.
- **Measured in throwaway sessions:** every other number comes from a run-pool session created for one check and deleted afterwards, so this file is their only record. The numbers are the checks' own output.

## The dry runs that waited for apt

At 14:28, `python eval_reviewer.py` started its first four dry runs, on [#268](https://github.com/melabadi/adept-assessment-northstars/pull/268) to [#271](https://github.com/melabadi/adept-assessment-northstars/pull/271). Their run sessions took `run_change.sh` from `main` at [387789e](https://github.com/melabadi/adept-assessment-northstars/blob/387789e/solutions/03-develop-microsoft/sandbox/run_change.sh), unchanged since #205, which installed PostgreSQL with `apt-get` from Ubuntu's package archive. The Function's log:

```powershell
$appi = azd env get-value APPLICATIONINSIGHTS_NAME
$kql = "traces | where timestamp between (datetime(2026-11-11T14:28:00Z) .. datetime(2026-11-11T14:49:00Z)) | where message has 'dry run of' or message has 'build and tests:' | project utc = format_datetime(timestamp, 'HH:mm:ss'), message | order by utc asc"
(az monitor app-insights query --app $appi -g rg-ai-sdlc-develop --offset 30d --analytics-query $kql | ConvertFrom-Json).tables[0].rows | ForEach-Object { $_ -join ' | ' }
```

| Pull request | Review | Queued | Build and tests, as the Function logged them | The same pull request on 10 November ([evidence](2026-11-10-evaluation.md#the-dry-runs)) |
| --- | --- | --- | --- | --- |
| #268 | `39f9e0d4adac` | 14:28:20 | API 108 of 117 failed, web 15 of 15 passed in 19 min 37 s | API 63 of 63 passed, web 15 of 15 passed in 2 min 34 s |
| #269 | `8cb1a24589f2` | 14:28:19 | API 98 of 107 failed, web 14 of 14 passed in 19 min 00 s | API 58 of 58 passed, web 14 of 14 passed in 3 min 21 s |
| #270 | `f9135dffdad9` | 14:28:17 | API 82 of 91 failed, web 14 of 14 passed in 19 min 27 s | API 50 of 50 passed, web 14 of 14 passed in 2 min 31 s |
| #271 | `31c5754bd1ed` | 14:28:20 | API 86 of 95 failed, web 14 of 14 passed in 19 min 23 s | API 52 of 52 passed, web 14 of 14 passed in 2 min 00 s |

Each build ran for 19 to 20 minutes, close to the 20 minutes the Function waits for a build, and the API tests ran without a database. The API totals are larger than each change's number of tests; the sessions' logs, which would show why, were deleted with the sessions. The evaluation was stopped before it started another dry run.

## Why apt waited instead of failing

Measured in run-pool sessions that afternoon:

- The sessions use Azure's resolver, 168.63.129.16, in `/etc/resolv.conf`.
- Ubuntu's archive didn't resolve: `archive.ubuntu.com`, `security.ubuntu.com`, and `azure.archive.ubuntu.com`, nor `ubuntu.com`, `canonical.com`, or `launchpad.net`. A probe every 5 to 6 minutes got no answer for any of them from 14:53 to 15:33. The hosts that the new setup uses did resolve: `nodejs.org`, `builds.dotnet.microsoft.com`, the npm and NuGet registries, and `repo1.maven.org`.
- A lookup didn't fail at once; it timed out. `getaddrinfo()` gave up with `EAI_AGAIN` ("temporary failure in name resolution") after 9.7 s for `archive.ubuntu.com` and 6.1 s for `canonical.com`, where a name that doesn't exist (`.invalid`) failed with `EAI_NONAME` in 0.1 s.
- So apt kept trying: `apt-get update` exited with code 0 after 163 s, with 5 warnings, and `apt-get install postgresql` then failed with exit code 100 after 887 s: 17 and a half minutes for a database that never came. With `Acquire::Retries=0`, the install still took 240 s to fail.

## The change, and the runs that checked it

`run_change.sh` now installs PostgreSQL 16.15.0 from Maven Central (the zonky project's builds of PostgreSQL), pinned by SHA-256, with no apt, and gives each setup step a time limit: 5 minutes for Node 26 and for the .NET 10 SDK, 2 for PostgreSQL. When a step fails, the tests that need it don't run, and the review says why.

Each check gave a new run-pool session the head of #268, [dc78297](https://github.com/melabadi/adept-assessment-northstars/commit/dc78297588fe584a71a504bd8de65ae06846e1f0), as the Function packs it (GitHub's archive of that commit), and ran the script as the Function does: `start`, then `status` every 20 seconds, then `run/summary.json`. The Function's code turned each summary into its log line and the review's sandbox section. Every session was deleted at the end.

| Session | Started | Script | Setup: Node 26, .NET 10, PostgreSQL | API | Web | Total |
| --- | --- | --- | --- | --- | --- | --- |
| `build-check-ae906633` | 15:33:16 | the change, first version | 5 s, 9 s, 5 s: "PostgreSQL 16.15.0 didn't start" | error | 15 of 15 passed | 46 s |
| `build-wrongsha-77c8021a` | 15:33:16 | the first version, with a wrong SHA-256 | 6 s, 9 s, 1 s: "the download of PostgreSQL 16.15.0 doesn't match its pinned SHA-256" | error | 15 of 15 passed | 43 s |
| `build-check-aacf1ac9` | 15:36:09 | with the fix below | 5 s, 9 s, 6 s | 63 of 63 passed in 42 s | 15 of 15 passed in 28 s | 1 min 30 s |

**The first version had a bug, and the new error path reported it.** `pg_ctl` runs as the `postgres` user and couldn't create the server's log in the run folder, which root owns. A diagnostic session (`pg-diag-423cace1`, 15:35) showed its error: `/bin/sh: 1: cannot create /mnt/data/run/postgres.log: Permission denied`. The run still ended in 46 s, said why, and ran the web tests. The script now creates the log and hands it to `postgres`.

**The fixed run.** Its `summary.json`, without the list of logs:

```json
{
 "setup": {
  "node": {"exit_code": 0, "seconds": 5, "reason": null},
  "dotnet": {"exit_code": 0, "seconds": 9, "reason": null},
  "postgres": {"exit_code": 0, "seconds": 6, "reason": null}
 },
 "setup_seconds": 20,
 "api": {"status": "passed", "exit_code": 0, "seconds": 42, "total": 63, "passed": 63, "failed": 0, "skipped": 0, "failed_tests": []},
 "web": {
  "status": "passed", "install_exit_code": 0, "typecheck": "passed",
  "tests": {"total": 15, "passed": 15, "failed": 0, "skipped": 0, "failed_tests": []},
  "rerun": null, "seconds": 28
 },
 "seconds": 90
}
```

The log line: `build and tests: API 63 of 63 passed, web 15 of 15 passed in 1 min 30 s`. The review's sandbox section:

> - API integration tests: ✅ 63 of 63 passed (42 s)
> - Web UI: typecheck ✅ passed · unit tests ✅ 15 of 15 passed
> - Toolchain setup 20 s · total 1 min 30 s

With apt, the same pull request's build and tests took 2 min 34 s on 10 November, and the recorded run's reviews of [#212](https://github.com/melabadi/adept-assessment-northstars/pull/212) on 31 October say *Toolchain setup 33 s* and *34 s*.

**The wrong SHA-256.** The log line: `build and tests: API error (PostgreSQL isn't running: the download of PostgreSQL 16.15.0 doesn't match its pinned SHA-256), web 15 of 15 passed in 43 s`. The review's sandbox section:

> - API integration tests: ❌ error: PostgreSQL isn't running: the download of PostgreSQL 16.15.0 doesn't match its pinned SHA-256. No API test ran.
> - Web UI: typecheck ✅ passed · unit tests ✅ 15 of 15 passed
> - Toolchain setup 16 s · total 43 s
