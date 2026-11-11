# The agentic design review: three recorded runs, 11 November 2026

What GitHub Actions and gh-aw recorded for the three `/design-review` runs in the README's [The agentic design review, recorded on 11 November 2026](../README.md#the-agentic-design-review-recorded-on-11-november-2026). Anyone can open the Issue, the pull requests, the review comments, and each run's page, which shows its jobs and their times. The exact AI credits and the step's output below need a sign-in, so they are copied here.

## How it was collected

- **AI credits, model, and requests:** `gh aw audit <run-id> --json` with gh-aw v1.2.2, on 11 November 2026 (its `firewall_token_usage`).
- **Threat detection:** the model and requests from the same audit (`detection_model_usage`). Its AI credits come from each review comment's footer (`⌖ ~1 AIC`), which rounds up to whole credits.
- **Times:** the comments' and reactions' timestamps from the GitHub API, and each run's jobs from `gh run view <run-id> --json jobs`. Times are UTC.
- **The contract step's output:** `gh run view 43044381144 --log`, step *Keep the approved inputs and compare the pull request's API contract*.

## The runs

| | A design question | An ADR pull request | A breaking contract change |
| --- | --- | --- | --- |
| Item | Issue [#348](https://github.com/melabadi/adept-assessment-northstars/issues/348) | Pull request [#354](https://github.com/melabadi/adept-assessment-northstars/pull/354) | Pull request [#356](https://github.com/melabadi/adept-assessment-northstars/pull/356) |
| Run | [43042077185](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43042077185) | [43043368208](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43043368208) | [43044381144](https://github.com/melabadi/adept-assessment-northstars/actions/runs/43044381144) |
| `main` when the run started | `197d71a` | `03ea485` | `640f3e5` |
| `/design-review` comment | 14:48:37 | 14:56:32 | 15:02:43 |
| 👀 reaction | 14:49:08 (31 s) | 14:57:10 (38 s) | 15:03:18 (35 s) |
| Review comment | 14:53:43 (5 min 6 s) | 15:01:37 (5 min 5 s) | 15:08:01 (5 min 18 s) |
| Run, start to end | 14:48:41 to 14:54:13 (5 min 32 s) | 14:56:36 to 15:02:13 (5 min 37 s) | 15:02:46 to 15:08:31 (5 min 45 s) |
| `pre_activation` | 10 s | 14 s | 8 s |
| `activation` | 18 s | 23 s | 33 s |
| `agent` | 2 min 46 s | 2 min 27 s | 2 min 38 s |
| `detection` | 1 min 16 s | 1 min 20 s | 1 min 27 s |
| `safe_outputs` | 21 s | 22 s | 19 s |
| `conclusion` | 22 s | 27 s | 23 s |
| Job time | 313 s; 9 min as billed in a private repository | 313 s; 9 min as billed | 328 s; 9 min as billed |
| Agent | Claude Sonnet 5.5 (model `auto`), 8 requests, 20.28 AI credits | Claude Sonnet 5.5, 12 requests, 23.91 AI credits | Claude Sonnet 5.5, 9 requests, 19.14 AI credits |
| Threat detection | Claude Haiku 5.5, 2 requests, about 1 AI credit | Claude Haiku 5.5, 2 requests, about 1 AI credit | Claude Haiku 5.5, 2 requests, about 1 AI credit |
| Footer total | ~21 AIC | ~24 AIC | ~20 AIC |
| Labels added | `adr-needed`, `standards-conflict` | `standards-conflict` | `adr-needed` |

The workflow file was the same in all three runs. Its `max-ai-credits` was then 150 for the agent and 10 for detection.

A comment that isn't the command starts a run that ends after `pre_activation`. Between the merge and the reset, ten such runs took 9 to 22 seconds of job time each, and 13 to 30 seconds from start to end.

## The contract step's output in run 43044381144

The workflow's deterministic step ran `contract_diff.py` from `main`, before gh-aw checked out the pull request's branch, and printed this report. The review's *API contract* section copies its verdict and counts.

```text
## API contract impact (requesthub.v1 vs merge base 640f3e5db134)

**Breaking change**: requires a new major contract version and a migration plan (STD-API-001).

- Breaking changes: 1
- Additive changes: 0

### Breaking

- ❌ schema RecommendationDto: property `providerTraceId` removed
```
