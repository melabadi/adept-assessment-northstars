# Evidence: the run of 11 November 2026 on gh-aw v1.2.2

What GitHub and Copilot recorded the first time the changes made since [the recorded run](2026-10-28-recorded-run.md) ran on `main`. Times are UTC.

- **What changed since the recorded run:**
  - The agentic release summary was renamed *Release · GitHub · agentic release summary* and compiled with gh-aw v1.2.2 ([#341](https://github.com/melabadi/adept-assessment-northstars/pull/341)).
  - Its trigger also checks the candidate's workflow file. Copilot has no GitHub tools and reads only what a step before it collects, with pull request titles only from the owner, members, collaborators, or Copilot ([#364](https://github.com/melabadi/adept-assessment-northstars/pull/364)).
  - The candidate's browser tests install Chromium without packages from Ubuntu's mirrors ([#364](https://github.com/melabadi/adept-assessment-northstars/pull/364)).
  - The web stage of the API image builds on Node 26 ([#330](https://github.com/melabadi/adept-assessment-northstars/pull/330)).
- **Exported** on 11 November 2026, read-only. The run pages open without signing in. The logs and artifacts need a GitHub sign-in, and the artifacts expire on 9 February 2027.
  - The job and step times, with `gh api repos/{owner}/{repo}/actions/runs/<run id>/jobs`.
  - The logs of the candidate's jobs and of the summary's agent job.
  - The summary run's `info`, `usage`, `detection`, `agent-output-fallback`, and `safe-outputs-items` artifacts, with `gh run download 43049916687 -n <name>`.
- **Reproduced** on the owner's machine, read-only: what Copilot read, with `python .github/skills/release-evidence/release_evidence.py summary-inputs --run-id 43049509629 --out <folder>`. It took 15.6 s and listed the same 15 pull requests.
- **No longer on GitHub:** the draft *RequestHub demo-v1.1.0 (demo)*. It was never published and had no tag, and the reset deleted it after the run.

## The first candidate, which Ubuntu's mirrors stopped

| UTC | What happened | Source |
| --- | --- | --- |
| 14:45:15 | The owner started the candidate, version `1.1.0`, on `main` at [`fba32b1`](https://github.com/melabadi/adept-assessment-northstars/commit/fba32b105db080499a852149c0ed4c37cc070083) | [run 43041521237](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43041521237/attempts/1) |
| 14:45:21 to 14:46:39 | Preflight, the API and worker tests, the web UI tests, and both images passed. The API image's web stage built `FROM docker.io/library/node:26-alpine` | [run 43041521237](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43041521237/attempts/1) |
| 14:46:35 to 14:57:18 | The deployment check. The smoke test passed, 9 of 9. Then the browser tests' `npx playwright install --with-deps chromium` couldn't resolve `archive.ubuntu.com`, `security.ubuntu.com`, or `azure.archive.ubuntu.com`, kept retrying Ubuntu's package mirrors for 10 minutes, and failed. No draft was created | [run 43041521237](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43041521237/attempts/1) |
| 14:57:24 | The summary run started and skipped every job: its candidate had failed | [run 43043493747](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43043493747) |
| 14:59:59 to 15:11:23 | `gh run rerun 43041521237 --failed`: the deployment check failed the same way, from 15:00:23 to 15:11:22 | [run 43041521237, attempt 2](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43041521237/attempts/2) |
| 15:11:26 | The summary run skipped every job again | [run 43045846724](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43045846724) |

After the second failure, GitHub's status page showed no incident, and from the owner's machine `archive.ubuntu.com` resolved through one public DNS server but not through another. The repository's CI already installed Chromium without `--with-deps`. [#364](https://github.com/melabadi/adept-assessment-northstars/pull/364) made the candidate do the same, with a check that Chromium launches.

## The run

| UTC | What happened | Source |
| --- | --- | --- |
| 15:33:17 | The owner started the candidate, version `1.1.0`, on `main` at [`c27740e`](https://github.com/melabadi/adept-assessment-northstars/commit/c27740e850d1b86167ef530d6abe052b939c154b), with the README's command, `gh workflow run release-github-candidate.yml -f version=1.1.0` | [run 43049509629](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049509629) |
| 15:33:20 to 15:33:27 | Preflight: the first demo release, deployments from `main` only, and a required reviewer approves | [run 43049509629](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049509629) |
| 15:33:29 to 15:34:24 | In parallel: the API and worker tests (53 s), the web UI tests (25 s), and the API and worker images (47 s and 38 s). The web stage built `FROM docker.io/library/node:26-alpine` | [run 43049509629](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049509629) |
| 15:34:20 to 15:35:21 | The deployment check (1 min 1 s). The images started by digest, and the smoke test passed, 9 of 9, at 15:34:58. The browser tests ran from 15:34:58 to 15:35:13: `npm ci`, Chromium downloaded from Playwright's CDN, `Chromium launches` at 15:35:08, then 6 of 6 passed in 4.2 s | [run 43049509629](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049509629) |
| 15:35:23 to 15:35:38 | The draft. The gate passed: 67 API and worker, 14 web UI, 9 smoke, and 6 browser tests, none failed. *RequestHub demo-v1.1.0 (demo)* was created at 15:35:31 with 11 files and the tag name `demo-v1.1.0` | [run 43049509629](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049509629) |
| 15:35:42 | The candidate finished at 15:35:39, after 2 min 22 s, and its success started the agentic release summary | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) |
| 15:35:45 to 15:36:29 | `pre_activation` checked the actor's role, and `activation` prepared the prompt | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) |
| 15:36:31 to 15:39:26 | The agent job. From 15:36:42 to 15:36:55, `summary-inputs` collected [what Copilot read](#what-copilot-read). The step that runs Copilot started at 15:38:09, the firewall's containers by 15:38:46, and Copilot CLI at 15:38:55. Copilot's first request was at 15:39:01, and at 15:39:10 it asked to append [its summary](#copilots-summary-as-it-wrote-it) to the draft | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687), [usage](#what-copilot-used) |
| 15:39:29 to 15:41:09 | Threat detection checked that request: no prompt injection, no secret leak, no malicious patch | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) |
| 15:41:21 to 15:41:46 | The `safe_outputs` job appended the summary to the draft at 15:41:44, 8 min 27 s after the candidate started | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) |
| 15:42:14 | The agentic release summary finished, after 6 min 32 s | [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) |

## What Copilot read

The `summary-inputs` step's line in the agent job's log:

```text
Collected the summary's inputs in /tmp/gh-aw/agent/release: 15 pull requests for `demo-v1.1.0` (draft); titles withheld: none
```

GitHub's generated notes listed 15 pull requests: #328, #329, #330, #331, #332, #334, #341, #342, #344, #352, #353, #358, #361, #362, and #364. The owner wrote all of them (`author_association` `OWNER`), so every title reached Copilot. `changed-files.txt` had 139 lines. The other files were `release-manifest.json`, `test-summary.json`, `smoke-results.json`, and `status.txt`, which said `draft`.

Copilot ran three commands with its read-only shell, as the agent job's log shows:

```text
● Read release inputs (shell)
  │ cd /tmp/gh-aw/agent/release && cat status.txt release-manifest.json test-summary.json
  │ smoke-results.json pull-requests.json; wc -l changed-files.txt
● Search risky paths (shell)
  │ cd /tmp/gh-aw/agent/release && grep -E
  │ "Migrations/|openapi.json|app/|infra|RequestWorkflow|Dockerfile" changed-files.txt | head -30;
  │ grep -ciE "ignore|instruction|automation" changed-files.txt
● Check match (shell)
  │ cd /tmp/gh-aw/agent/release && grep -iE "ignore|instruction|automation" changed-files.txt
```

The one match was a file name, `solutions/05-secure-microsoft/infra/automation.bicep`. Copilot noted "Just a filename; no injection." and made its one `update_release` call.

## Copilot's summary, as it wrote it

The agent's one request, from `agent_output.json` in the `agent-output-fallback` artifact of [run 43049916687](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687): `update_release`, operation `append`, tag `demo-v1.1.0`, with this body.

```markdown
### AI summary for the approver

**In one sentence:** This first demo release mostly updates runtime pins and adds agentic GitHub workflows and demo tooling, with only build-level changes to the RequestHub app itself.

**Notable changes**
- Runtime pins: Node 26 LTS, setup-dotnet v6.1.0, CodeQL Action v4.39.3; touches the app Dockerfile and web package files (#330).
- Agentic release summary on gh-aw v1.2.2, plus author-checked summary inputs and a workflow path guard (#341, #364).
- Agentic incident triage and its first run (#334, #352).
- Agentic design review and its recorded runs (#342, #362).
- Agentic CI failure investigation and link fix (#353, #361).
- Microsoft-solution package and model updates, and links repointed to rewritten commit ids (#329, #331, #332, #344, #358, #328).

**Risks to check**
- `app/Dockerfile` and `app/web/package.json` / `package-lock.json` changed (#330): review the Node pin and dependency changes.
- Infrastructure: `solutions/05-secure-microsoft/infra/automation.bicep` (#344) and `solutions/01-plan-microsoft/infra/main.bicep` (#358).
- No database migrations, `app/contracts/openapi.json` changes, or authorization/approval rule changes found in the changed files.

**Evidence:** 67 API and worker and 14 web UI tests passed on commit c27740e, and 9 smoke and 6 browser tests passed on the images built from it, with 0 failures.
```

Checked against what it read: it named all 15 pull requests, and every path it names is in `changed-files.txt`. None of the 15 changed a migration, `app/contracts/openapi.json`, or anything under `app/src/`. Its numbers are the manifest's, and its evidence line puts only the smoke and browser tests on the images.

On the draft, gh-aw added a footer below the summary, and a hidden HTML comment that names the workflow and the run:

```markdown
> Generated by [Release · GitHub · agentic release summary](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43049916687) · copilot · auto (Claude Sonnet 5.5) · \~14 AIC · ⌖ \~1 AIC · ⊞ 7.8K
```

## What Copilot used

From `agent/token_usage.jsonl` and `detection/token_usage.jsonl` in the `usage` artifact. The `info` artifact's `aw_info.json` records gh-aw `v1.2.2`, Copilot CLI `1.0.103`, and the firewall `v0.29.11`. The workflow sets no model, and `auto` resolved to claude-sonnet-5.5.

| Job | Model | Requests | AI credits |
| --- | --- | --- | --- |
| agent | claude-sonnet-5.5 | 5 | 13.42 |
| detection | claude-haiku-5.5 | 2 | 0.62 |
| **Total** | | **7** | **14.04** |

The workflow's budgets are 50 AI credits for the agent and 10 for threat detection. Six runs on gh-aw v0.93.5, from 27 October to 10 November, used 13.64 to 15.61 for the agent and 0.52 for threat detection.

Runner time: the candidate's 7 jobs took 4.1 minutes, 8 minutes as billed in a private repository, where each job is rounded up to a whole minute. The summary's 6 jobs took 6.1 minutes, 9 as billed. The first candidate's deployment check ran 10 min 43 s and 10 min 59 s in its two attempts before it failed.

## What GitHub did with the update

- **The tag name.** Before the update, the draft's tag name was `demo-v1.1.0`. After it, GitHub listed the draft as `untagged-d97cdbe3a1f2d4506cad`, and `gh release view demo-v1.1.0` answered `release not found`. gh-aw v1.2.2's `update_release` removes a draft's pending tag name, as v0.93.5's did in the recorded run. The draft kept its title, which is how the approval workflow finds it.
- **The notes above the summary.** The append also rewrote the draft's notes above the AI marker:
  - `@melabadi` became `` `@melabadi` ``;
  - the numeric columns of the evidence table lost their right alignment;
  - GitHub's `*` list became a `-` list;
  - bare links became Markdown links.

  Nothing was removed: every line, the marker, and the 11 files stayed. In the recorded run, on gh-aw v0.93.5, the notes kept their original form, as [the draft's screenshot](../images/04-draft-evidence.png) shows. The approval workflow writes the notes above the marker again from the evidence when it publishes, and keeps what follows the marker.

## The reset

After the run, the README's [reset commands](../README.md#reset-the-copy-for-another-run) deleted the draft, `untagged-d97cdbe3a1f2d4506cad`. Then `gh release list` and `git ls-remote --tags origin 'demo-v*'` printed nothing. The images stay in GitHub Container Registry, and their `demo-v1.1.0` tag now points to this run's images: API `sha256:e858cc97…` and worker `sha256:15fc18ba…`.
