# CI failure investigation, 11 November 2026

The runs of **Test · GitHub · agentic CI failure investigation** in [See it work](../README.md#see-it-work), step 10: on pull request [#359](https://github.com/melabadi/adept-assessment-northstars/pull/359), whose regression tests failed as intended, and on [#360](https://github.com/melabadi/adept-assessment-northstars/pull/360), whose fix broke four existing tests. The runs' logs and artifacts need a GitHub sign-in, and the artifacts expire on 9 February 2027; these copies stay.

## The runs

The first two comments sorted every failure as the later ones did, but their links to the failing lines and to the logs were broken: gh-aw escaped them as GitHub references ([Troubleshooting](../README.md#troubleshooting)). Pull request [#361](https://github.com/melabadi/adept-assessment-northstars/pull/361) fixed the links, test-first, and was merged at 15:21:17 UTC. At 15:22 the owner re-ran CI's failed job on both pull requests, and the new comments hid the first ones as outdated.

| Run | Pull request | CI run it investigated | CI failed (UTC) | The run's jobs (UTC) | Comment (UTC) | Label |
| --- | --- | --- | --- | --- | --- | --- |
| 43045257325 | #359 | 43045096515, attempt 1 | 15:07:54 | 15:08:02 to 15:13:13 | 15:12:44, links broken, hidden | `ci:defect-reproduced` |
| 43045265056 | #360 | 43045107541, attempt 1 | 15:07:57 | 15:13:16 to 15:18:23, after the first ended | 15:17:56, links broken, hidden | `ci:regression` |
| 43047893243 | #359 | 43045096515, attempt 2 | 15:23:28 | 15:23:35 to 15:29:51 | [15:29:12](https://github.com/melabadi/adept-assessment-northstars/pull/359#issuecomment-6799930281) | `ci:defect-reproduced` |
| 43047892065 | #360 | 43045107541, attempt 2 | 15:23:28 | 15:29:56 to 15:35:20, after the third ended | [15:34:46](https://github.com/melabadi/adept-assessment-northstars/pull/360#issuecomment-6800062263) | `ci:regression` |
| 43049932884 | #359 | 43049554798, which passed at 15:35:44 | | every job skipped | none | |

Each run was created 4 seconds after CI failed, and the runs go one at a time: the second and fourth waited for the one before them to end.

## Jobs

| Job | Runner | 43045257325 | 43045265056 | 43047893243 | 43047892065 |
| --- | --- | --- | --- | --- | --- |
| `pre_activation` | `ubuntu-slim` | 11 s | 10 s | 9 s | 12 s |
| `activation` | `ubuntu-slim` | 24 s | 22 s | 28 s | 36 s |
| `agent` | `ubuntu-latest` | 2 min 5 s | 2 min 24 s | 2 min 51 s | 2 min 18 s |
| `detection` | `ubuntu-latest` | 1 min 37 s | 1 min 19 s | 1 min 40 s | 1 min 10 s |
| `safe_outputs` | `ubuntu-slim` | 18 s | 14 s | 20 s | 24 s |
| `conclusion` | `ubuntu-slim` | 23 s | 20 s | 32 s | 26 s |
| All six | | 4 min 58 s | 4 min 49 s | 6 min 0 s | 5 min 6 s |

From the GitHub API:

```powershell
gh api 'repos/melabadi/adept-assessment-northstars/actions/runs/43047893243/jobs' --jq '.jobs[] | [.name, .labels[0], .started_at, .completed_at, .conclusion] | @tsv'
```

## Threat detection

The `detection` job's verdict on the agent's output, `detection_result.json` from each run's `detection` artifact. The four files are identical:

```json
{
  "prompt_injection": false,
  "secret_leak": false,
  "malicious_patch": false,
  "reasons": [],
  "warnings": []
}
```

## AI credits

`agent_usage.json` from each run's `usage` artifact and `detection_usage.json` from its `detection` artifact, unchanged after the run id and the job. The agent ran on Claude Sonnet 5.5, which `model: auto` chose, and the detection on Claude Haiku 5.5:

```text
43045257325 agent     {"input_tokens":4759,"output_tokens":1683,"cache_read_tokens":108930,"cache_write_tokens":40413,"ambient_context":7719,"ai_credits":13.82735,"primary_model":"claude-sonnet-5.5"}
43045257325 detection {"input_tokens":20310,"output_tokens":392,"cache_read_tokens":31445,"cache_write_tokens":30115,"ambient_context":22301,"ai_credits":0.615525,"primary_model":"claude-haiku-5.5"}
43045265056 agent     {"input_tokens":4761,"output_tokens":2106,"cache_read_tokens":152007,"cache_write_tokens":42302,"ambient_context":7718,"ai_credits":15.15377,"primary_model":"claude-sonnet-5.5"}
43045265056 detection {"input_tokens":20310,"output_tokens":369,"cache_read_tokens":31447,"cache_write_tokens":30472,"ambient_context":22302,"ai_credits":0.618661,"primary_model":"claude-haiku-5.5"}
43047893243 agent     {"input_tokens":4757,"output_tokens":1593,"cache_read_tokens":68677,"cache_write_tokens":40415,"ambient_context":7719,"ai_credits":13.33492,"primary_model":"claude-sonnet-5.5"}
43047893243 detection {"input_tokens":20298,"output_tokens":466,"cache_read_tokens":31443,"cache_write_tokens":30132,"ambient_context":22289,"ai_credits":0.619307,"primary_model":"claude-haiku-5.5"}
43047892065 agent     {"input_tokens":4759,"output_tokens":2121,"cache_read_tokens":109954,"cache_write_tokens":42352,"ambient_context":7718,"ai_credits":14.76034,"primary_model":"claude-sonnet-5.5"}
43047892065 detection {"input_tokens":20298,"output_tokens":452,"cache_read_tokens":31447,"cache_write_tokens":30478,"ambient_context":22290,"ai_credits":0.622763,"primary_model":"claude-haiku-5.5"}
```

| Run | Agent | Detection | Together |
| --- | --- | --- | --- |
| 43045257325 | 13.83 | 0.62 | 14.44 |
| 43045265056 | 15.15 | 0.62 | 15.77 |
| 43047893243 | 13.33 | 0.62 | 13.95 |
| 43047892065 | 14.76 | 0.62 | 15.38 |

## The agent's tool calls

From the re-runs, whose comments stay on the pull requests: lines 120 to 148 of run 43047893243's `agent-stdio.log` and lines 120 to 151 of run 43047892065's, from the runs' `agent` artifacts, unchanged. They hold every tool call, the agent's closing summary, and its session's time and tokens; the earlier lines set up the sandbox and its firewall. On #359 the facts settled all three failures, so Copilot read nothing else. On #360 it also read the pull request's diff, to find the change that broke the four tests.

Run 43047893243:

```text
● Read skill and facts (shell)
  │ cat .github/skills/ci-investigation/SKILL.md; ls /tmp/gh-aw/agent/ci/; cat
  │ /tmp/gh-aw/agent/ci/facts.md
  └ 195 lines…

All three are class (a).

● add_labels (MCP: safeoutputs) · labels: [1 item], item_number: "359"
  └ {"result":"success","output_id":"so_TXv3SkENQHGt"}

● add_comment (MCP: safeoutputs) · item_number: "359", body: "### CI failure investigation  [CI run…
  └ {"result":"success","temporary_id":"aw_N44OxLRd","comment":"#aw_N44OxLRd","ou...

[safeoutputs-cli] hasTerminalSafeOutput: terminal entry found in /home/runner/work/_temp/gh-aw/safeoutputs/outputs.jsonl: type=add_labels
[copilot-harness] attempt 1: post-result watchdog armed inactivityTimeout=120000ms
I labelled PR 359 `ci:defect-reproduced` and posted the investigation comment. I didn't open `pr.patch` or the logs, because the facts settled all three failures.

All 3 failing tests are in class (a): this PR adds each one, none fails on main, and each asserts the duplicate-decision behaviour:
- `Second_decision_returns_conflict_with_the_existing_decision`
- `Retried_decision_with_same_idempotency_key_returns_original_result`
- `Concurrent_double_click_records_exactly_one_decision`

The facts list no build errors or other failures. The comment gives one next step per test: fix the code, don't change the test.



Changes    +0 -0
Duration   13s
Tokens     ↑ 113.8k (68.7k cached) • ↓ 1.6k
```

Run 43047892065:

```text
● Read skill and facts (shell)
  │ cat .github/skills/ci-investigation/SKILL.md; ls /tmp/gh-aw/agent/ci/; cat
  │ /tmp/gh-aw/agent/ci/facts.md
  └ 229 lines…

● Read PR diff (shell)
  │ cat /tmp/gh-aw/agent/ci/pr.patch
  └ 30 lines…

The change dropped the `Rejected` condition, so approvals without comments now return BadRequest. All four are regressions.

● add_labels (MCP: safeoutputs) · labels: [1 item]
  └ {"result":"success","output_id":"so_1vjVWzAiQ-aL"}

● add_comment (MCP: safeoutputs) · body: "### CI failure investigation  [CI run 43045107541](https:…
  └ {"result":"success","temporary_id":"aw_8fFqWjDq","comment":"#aw_8fFqWjDq","ou...

[safeoutputs-cli] hasTerminalSafeOutput: terminal entry found in /home/runner/work/_temp/gh-aw/safeoutputs/outputs.jsonl: type=add_labels
[copilot-harness] attempt 1: post-result watchdog armed inactivityTimeout=120000ms
I labelled the pull request `ci:regression` and posted the investigation comment. All four failing tests are regressions from this change.

- **Cause:** the diff in `RequestWorkflow.cs` removed the `Rejected` condition from the comment check. Every decision without a comment now returns 400, including approvals.
- **Failures:** four existing tests fail, and all four pass on main. They are `Admin_cleanup_deletes_only_requests_owned_by_load_test_identities`, `Reviewer_without_approver_role_cannot_decide`, `Requester_cannot_approve_their_own_request` and `Approver_cannot_decide_outside_their_departments`. Each gets BadRequest where it expects Created or Forbidden.
- **Next step in the comment:** restore the `Rejected` condition and keep the `Trim()`.

I did not rerun anything or open the CI logs. The cause comes from the facts and `pr.patch`.



Changes    +0 -0
Duration   17s
Tokens     ↑ 157.1k (110.0k cached) • ↓ 2.1k
```

While the artifacts last, compare a file with GitHub from the repository root, signed in to `gh`:

```powershell
gh run download 43047892065 -R melabadi/adept-assessment-northstars --name usage --dir out/evidence/usage
Get-Content out/evidence/usage/agent_usage.json
gh run download 43047892065 -R melabadi/adept-assessment-northstars --name detection --dir out/evidence/detection
Get-Content out/evidence/detection/detection_result.json
```
