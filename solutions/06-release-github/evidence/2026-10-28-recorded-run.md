# Evidence: the recorded run of 28 October 2026

What GitHub and Copilot recorded during [the run in See it work](../README.md#see-it-work), kept here because most of it needs a GitHub sign-in or no longer exists. Times are UTC.

- **Exported** on 11 November 2026, read-only: the job times with `gh run view <run id> --json jobs`, and Copilot's summary and its usage from the AI summary run's artifacts, with `gh run download 40711045694 -n agent-output-fallback` and `gh run download 40711045694 -n usage`. Those artifacts need a GitHub sign-in to download, and expire on 26 January 2027.
- **Saved from the terminal** during the run: the two Copilot CLI sessions, which started at the times in the timeline, and the check of the published release. Their durations are the ones Copilot CLI printed at the end of each session, next to its AI credits. One local temporary folder is shortened to `<temp>`, and Copilot CLI's last line, which resumes a session on that machine, is left out.
- **No longer on GitHub:** the draft and the published release `demo-v1.0.0` and its tag, deleted when the run was reset so that the version could be used again, and the candidate run's artifacts, kept for 7 days. The [README's screenshots](../README.md#see-it-work) show the release.

## Timeline

| UTC | What happened | Source |
| --- | --- | --- |
| 14:53:49 | The owner started the release candidate, version `1.0.0`, on `main` at [`fc79733`](https://github.com/melabadi/adept-assessment-northstars/commit/fc79733f46f2fdafff8282c12858707711383a94) | [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) |
| 14:53:53 to 14:54:01 | Preflight | [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) |
| 14:54:03 to 14:55:29 | In parallel: the API and worker tests (1 min 26 s), the web UI tests (36 s), and the API and worker images (1 min 20 s and 51 s) | [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) |
| 14:55:26 to 14:56:56 | The deployment check on the pushed images: smoke and browser tests | [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) |
| 14:56:58 to 14:57:13 | The draft release, with 11 files attached | [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) |
| 14:57:17 | The candidate's success started the AI release summary | [run 40711045694](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40711045694) |
| 14:58:10 to 14:59:56 | The agent job. At 14:59:36 Copilot asked to append [its summary](#copilots-summary-as-it-wrote-it) to the draft | [run 40711045694](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40711045694), [usage](#what-copilot-used) |
| 14:59:58 to 15:01:20 | Threat detection checked that request | [run 40711045694](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40711045694) |
| 15:01:37 | The `safe_outputs` job appended the summary to the draft | [usage](#what-copilot-used) |
| 15:02:09 | The AI release summary finished | [run 40711045694](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40711045694) |
| 16:21:41 | The owner asked the `release-github` agent in Copilot CLI for [a brief](#the-brief-before-the-approval); Copilot CLI reported 3 min 20 s | terminal |
| 16:26:28 to 16:26:50 | An approval from the branch `demo/not-main`: the evidence verified, and the environment refused the publish job | [run 40725978777](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40725978777) |
| 16:32:46 to 16:33:02 | An approval after one report on the draft was edited: verify refused it | [run 40727011991](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40727011991) |
| 16:34:41 | Copilot CLI [explained the refusal](#why-the-approval-failed); it reported 1 min 11 s | terminal |
| 16:36:54 to 16:37:53 | The approval: verify (17 s), then record and publish (35 s). The approval was recorded at 16:37:39, and the release was published by 16:37:44 | [run 40727695904](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40727695904) |
| 16:46:30 | The owner [verified the published release](#the-check-of-the-published-release) | terminal |

## Copilot's summary, as it wrote it

The agent's one request, from `agent_output.json` in the `agent-output-fallback` artifact of [run 40711045694](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40711045694): `update_release`, operation `append`, tag `demo-v1.0.0`, with this body.

```markdown
### AI summary for the approver

**In one sentence:** This first demo release ships the RequestHub request-and-approval app (API, worker, web UI) together with the per-phase demo solutions, one fix to request search, and screenshot tooling.

**Notable changes**
- Initial RequestHub app plus the Plan, Design, and Develop phases (#1).
- Search now treats `%` and `_` as literal characters (#69).
- CI and Copilot setup install Chromium without OS packages (#74).
- Private link for attachment storage was enabled (#72) and then reverted (#76).
- Solutions for the Test, Secure, Release, and Operate phases on GitHub and Microsoft (#27, #41, #46, #58, #61, #73, #89).
- Screenshot tooling that masks tenant details (#98, #107).

**Risks to check**
- This is the first release, so the app (#1) includes the full database schema and migrations under `app/src/RequestHub.Core/Data/Migrations/` and the `requesthub.v1` contract in `app/contracts/openapi.json`. I did not inspect them in detail.
- The search change (#69) alters query behaviour for `%` and `_`.
- Infrastructure changes were made and reverted (#72, #76), and several Bicep and workflow changes are included, such as the Test, Release, and Operate solutions and the OIDC and Easy Auth fixes (#4).
- No instructions aimed at automation were found in the pull request text I read.

**Evidence:** 60 of 60 API and worker, 14 of 14 web UI, 9 of 9 smoke, and 6 of 6 browser tests passed, with 0 failures, on images built from fc79733.
```

The evidence line follows the prompt's template, which puts every suite "on images built from" the commit. Only the smoke and browser tests ran against the images; the API, worker, and web UI tests ran on the source at the same commit, as the release's own evidence table says.

## What Copilot used

From `agent/token_usage.jsonl` and `detection/token_usage.jsonl` in the run's `usage` artifact. Copilot read the evidence that the workflow had downloaded for it, with one shell command, then made its one `update_release` call.

| Job | Model | Requests | AI credits |
| --- | --- | --- | --- |
| agent | claude-sonnet-5.5 | 3 | 15.28 |
| detection | claude-haiku-5.5 | 2 | 0.52 |
| **Total** | | **5** | **15.79** |

The run's `safe-outputs-items` artifact records the one change it made: `update_release` on the draft, at 15:01:37. GitHub then listed the draft as `untagged-1005610938af0d9fbbae`, because the update left out the draft's tag name; the approval workflow found the draft by its title and set the tag again when it published.

## The brief before the approval

```text
PS> copilot --agent release-github --allow-all-tools -p "Brief me on draft release demo-v1.0.0 before I approve it."
● skill(release-evidence)

I’ll verify the draft’s evidence and read its release notes, without changing or approving it.

● Read release_evidence.py
  │ .github\skills\release-evidence\release_evidence.py
  └ L1:220 (220 lines read)

● Find candidate runs and draft release (shell)                                                   5s
  │ gh run list --workflow release-github-candidate.yml --limit 5 --json
  │ databaseId,headSha,status,conclusion; gh release list --limit 20 --json
  │ name,tagName,isDraft,isPrerelease
  └ 2 lines…

/ Search (grep)                                                                                   5s
  │ "def verify|workdir|TemporaryDirectory|add_parser\("verify|--out|--json" in release_evidence.py
  │ (.github\skills\release-evidence)
  └ 8 lines found

● Read draft release notes and asset listing (shell)                                             12s
  │ gh release view untagged-1005610938af0d9fbbae --json name,tagName,isDraft,body,assets
  └ 1 line…

● Verify draft release evidence integrity (shell)                                                27s
  │ python .github\skills\release-evidence\release_evidence.py verify --tag demo-v1.0.0 --expect
  │ draft
  └ 11 lines…

● Read release-manifest.json
  │ <temp>\release-39rt1ipl\release-manifest.json
  └ 150 lines read

● Read test-summary.json                                                                          8s
  │ <temp>\release-39rt1ipl\test-summary.json
  └ 64 lines read

● Clean up downloaded temporary release evidence (shell)
  │ Remove-Item -LiteralPath '<temp>\release-39rt1ipl' -Recurse
  │ -Force
  └ No Content

**Evidence passes; approval remains yours.** `demo-v1.0.0` builds commit `fc79733` on `main`, now 7 commits behind; candidate succeeded. AI summary: first RequestHub demo release, SDLC solutions, literal-search fix, screenshot tooling.
**Image digests:** API `sha256:612fe973170ecbc7a50929bfe121e4c5b780b1a52ca4c576cedbeec5e56e8363`; worker `sha256:4aaea7ed173ba01884e9e1a93e7f4cabf31e105af8c17b6b63417883d3eba79d`.
**Tests:** API/worker 60/60; web 14/14; release-image smoke 9/9; browser 6/6. Verify: **7 passed, 2 skipped, 0 failed**; checksums match. Skips: registry access unavailable locally and approval pending; approval workflow checks images.
**Human review:** accept the older commit, initial schema/migrations and API contract, `%`/`_` search behavior, and infrastructure/workflow changes including the private-link revert. AI did not inspect schema/contract in detail.
`gh workflow run release-github-approve.yml -f tag=demo-v1.0.0 -f comment="<their note>"`

Changes    +0 -0
AI Credits 8.48 (3m 20s)
Tokens     ↑ 122.3k (95.9k cached, 26.4k written) • ↓ 913 (61 reasoning)
```

The answer says the commit was 7 commits behind `main`: that count grows as `main` moves.

## Why the approval failed

```text
PS> copilot --agent release-github --allow-all-tools -p "Why did the last release-github-approve.yml run fail?"
● skill(workflow-investigation)

● Read investigate_run.py
  │ .github\skills\workflow-investigation\investigate_run.py
  └ L1:240 (240 lines read)

● Find latest release approval run (shell)
  │ gh run list --workflow release-github-approve.yml --limit 1 --json
  │ databaseId,status,conclusion,url,headSha,createdAt
  └ 1 line…

● Read release-github-approve.yml
  │ solutions\06-release-github\.github\workflows\release-github-approve.yml
  └ 112 lines read

● Digest failed approval run logs and annotations (shell)                                         9s
  │ python .github\skills\workflow-investigation\investigate_run.py 40727011991
  └ 19 lines…

/ Search (grep)
  │ "SHA-256 mismatch|checksums|def verify" in *.py
  │ (solutions\06-release-github\.github\skills\release-evidence)
  └ 63 lines found

● Get failed verification and skipped publication job links (shell)
  │ gh run view 40727011991 --json jobs --jq '.jobs[] | {name,conclusion,url}'
  └ 2 lines…

The [latest run](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40727011991) failed in **[Verify the evidence](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40727011991/job/122952891405)** for `demo-v1.0.0`:

> `FAIL checksums: browser-tests.junit.xml changed after the candidate run (SHA-256 mismatch)`

The attached browser-test report does not match its recorded checksum. This is an **evidence-integrity failure**, not a reported browser-test failure; the logs don’t establish who or what changed the file.

Publication was skipped, leaving the release as a draft. The next step is to compare that asset with the original candidate artifact and investigate the discrepancy—not update the checksum merely to pass approval.

Changes    +0 -0
AI Credits 5.67 (1m 11s)
Tokens     ↑ 84.9k (67.4k cached, 17.5k written) • ↓ 610
```

## The check of the published release

```text
PS> python .github/skills/release-evidence/release_evidence.py verify --tag demo-v1.0.0 --workdir out/verify
Verify demo-v1.0.0 in melabadi/adept-assessment-northstars (assets in out\verify)
  PASS  release: `demo-v1.0.0` is published
  PASS  manifest: commit `fc79733`, 9 evidence files, 2 images
  PASS  checksums: 10 files match SHA256SUMS
  PASS  tests: no failures: api 60/60, web 14/14, smoke 9/9, browser 6/6
  PASS  commit on main: `fc79733` is on `main` (11 commits behind its tip)
  PASS  candidate run: [run 40710469161](https://github.com/melabadi/adept-assessment-northstars/actions/runs/40710469161) succeeded on `main`
  SKIP  images: no registry token (set GHCR_TOKEN to a token that can read packages)
  PASS  git tag: `demo-v1.0.0` points to `fc79733`
  PASS  approval record: approved by @melabadi at 2026-10-28T16:37:39Z
8 passed, 1 skipped, 0 failed
```

The image check was skipped because the owner's local token couldn't read packages. The approval workflow checked both images with its own token.
