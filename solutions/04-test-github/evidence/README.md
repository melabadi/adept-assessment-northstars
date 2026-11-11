# Evidence from the runs

These are the two proofs from the run in [See it work](../README.md#see-it-work), on pull request [#101](https://github.com/melabadi/adept-assessment-northstars/pull/101), 28 October 2026, and the record of the CI failure investigation's runs of 11 November 2026 (step 10). Each proof folder holds four files from one proof run's `regression-proof` artifact, copied unchanged. The runs and their artifacts need a GitHub sign-in, and the artifacts expire on 26 January 2027; these copies stay.

| Folder | Proof run (UTC) | Head | Verdict |
| --- | --- | --- | --- |
| [`proof-a92d4b313`](proof-a92d4b313/proof.md) | 40710461621, 15:06 to 15:08 (step 5) | `a92d4b313`, Copilot's fix | Proven: 5 of 7 selected tests fail at the tests-only commit `8de3d60fb`, and 7 of 7 pass at the head |
| [`proof-e1d52334d`](proof-e1d52334d/proof.md) | 40716499194, 15:58 to 16:00 (step 8) | `e1d52334d`, the review-loop commit | Proven: the same 5 of 7 fail at `8de3d60fb`, and 7 of 7 pass at the head |

Each folder contains:

- `proof.md`: the verdict, as the check's job summary showed it.
- `proof.json`: the same proof, machine-readable: the commits, the selected tests, and each run's results.
- `tests-only-8de3d60fb.ctrf.json` and `head-<sha>.ctrf.json`: every selected test's result, failure message, and stack trace at each commit, as [CTRF](https://ctrf.io/) test reports. Each report's `reportId` is a random ID that the test run generated for that report; it identifies nothing else.

The artifacts also hold each run's console log, which isn't copied here. While an artifact lasts, compare a file with it from the repository root:

```powershell
gh run download 40716499194 -R melabadi/adept-assessment-northstars --name regression-proof --dir out/proof-e1d52334d
(Get-FileHash out/proof-e1d52334d/proof.json).Hash -eq (Get-FileHash solutions/04-test-github/evidence/proof-e1d52334d/proof.json).Hash
```

## The CI failure investigation

[`ci-investigation-2026-11-11.md`](ci-investigation-2026-11-11.md) records the four runs of the agentic CI failure investigation on pull requests [#359](https://github.com/melabadi/adept-assessment-northstars/pull/359) and [#360](https://github.com/melabadi/adept-assessment-northstars/pull/360), in step 10. It holds when each run started and ended, each job's time, the threat detection's verdict, the AI credits of the agent and the detection, and the agent's tool calls in the two runs whose comments stay on the pull requests. The times come from the GitHub API. The rest is copied unchanged from the runs' `agent`, `detection`, and `usage` artifacts, which expire on 9 February 2027. The file ends with the commands that compare it with GitHub.
