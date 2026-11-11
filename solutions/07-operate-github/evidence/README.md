# Evidence from the recorded run

These files back [See it work](../README.md#see-it-work): the run of 28 October 2026, from incident [#109](https://github.com/melabadi/adept-assessment-northstars/issues/109) to its follow-up [#111](https://github.com/melabadi/adept-assessment-northstars/issues/111) and Copilot's pull request [#114](https://github.com/melabadi/adept-assessment-northstars/pull/114). The workflow runs' logs, summaries, and artifacts need a GitHub sign-in and expire on 26 January 2027; these copies stay.

| File | What it holds | Where it comes from |
| --- | --- | --- |
| [`triage-run-40711748423.md`](triage-run-40711748423.md) | The triage run's six jobs and their times, the threat detection's verdict, the AI credits of the agent and the detection, and the agent's tool calls, including the command that was refused (steps 2 and 3) | The GitHub API, and the run's `agent`, `detection`, and `usage` artifacts, copied unchanged |
| [`proof-run-40713746544.md`](proof-run-40713746544.md) | The three runs on Copilot's commit: when a person started them and how long each job took, then the proof's output (steps 6 and 7) | The GitHub API, and the proof job's log |

While the artifacts and logs last, compare a file with GitHub from the repository root, signed in to `gh`:

```powershell
gh run download 40711748423 -R melabadi/adept-assessment-northstars --name detection --dir out/evidence/detection
Get-Content out/evidence/detection/detection_result.json
gh run view 40713746544 -R melabadi/adept-assessment-northstars --job 122941547880 --log | Select-String -Pattern 'Regression proof: PROVEN' -Context 0,18
```
