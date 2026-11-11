# Copilot CLI 1.0.109 drafted the triage

On 11 November 2026, option B's drafting ran again with GitHub Copilot CLI 1.0.109, then the latest stable release, on the repository owner's machine. It used the commands in [Use it the first time](../README.md#use-it-the-first-time), step 2B, from `Remove-Item` on, with `$incident = 252`: the incident that the run of 1 November filed. Its author is the owner, so the commands exported its title and description. Nothing was filed on GitHub; the two drafts stayed on the machine.

- The `copilot` command ran for 129 seconds, from 14:18:31 to 14:20:40 UTC. Copilot reported 2 minutes 3 seconds and 9.72 AI credits.
- It used only file tools: the skill, reads, searches, and one edit that created the two drafts. No tool call was refused.
- It gave the same labels as the run of 1 November: `severity:3` and `area:worker`.

## The transcript

Copilot CLI's output, unchanged except for two lines. The first listed the 169 tools that `--available-tools` and `--disable-builtin-mcps` disabled, by name, including this machine's other tools; it is shortened to its count. The last gave a local session id to resume the session; it is left out.

```text
 ● Disabled tools: … (169 tools in all: the shell, web access, subagents, the CLI's other built-in tools, and every MCP server's tools)

 ● skill(incident-evidence)

 {} Read out\operate\incident.json 1 line read

 MD Read .github\skills\regression-followup\followup-template.md 36 lines read

 MD Read .github\skills\incident-evidence\severity-rubric.md 26 lines read

 ● List directory out\operate 1 file found

 / Search "app\**\*Notification*.cs" 1 file found

 C# Read app\src\RequestHub.Core\Notifications\NotificationProcessor.cs 119 lines read

 / Search "app\tests\RequestHub.Tests\*.cs" 9 files found

 / Search "notifications/backlog|NotificationBacklog|workerDelayFaultActive" in *.cs … 2 lines found

 / Search "app\src\RequestHub.Worker\*.cs" 1 file found

 C# Read app\tests\RequestHub.Tests\WorkerAndContractTests.cs 164 lines read

 C# Read app\tests\RequestHub.Tests\ApiFixture.cs L1:180 (111 lines read)

 C# Read app\src\RequestHub.Worker\Program.cs 93 lines read                                       5s

 / Search "^" (app\src\RequestHub.Core\Notifications\NotificationProcessor.cs) 119 lines found    5s

 / Search "^" (app\src\RequestHub.Worker\Program.cs) 93 lines found

 ● Edit  Create out\operate\followup-issue.md (+29)  Create out\operate\triage-comment.md (+47)

Drafted triage and one bounded regression follow-up for #252.

**Labels:** `severity:3`, `area:worker`

**Drafts:** `out/operate/triage-comment.md` and `out/operate/followup-issue.md`. Nothing filed on GitHub.



Changes    +76 -0
AI Credits 9.72 (2m 3s)
Tokens     ↑ 126.3k (102.9k cached, 23.4k written) • ↓ 2.8k (120 reasoning)
```

## The drafts

Both files as Copilot wrote them. A person reads them before filing them with the three `gh` commands in step 2B.

`out/operate/followup-issue.md`:

```markdown
[follow-up] Treat sender timeouts as failed attempts without stalling the batch

## Why
Incident #252 (severity 3): IT and Facilities reviewers and approvers reported delayed and repeated notifications while core request flows continued working.
Hypothesis H1 from the triage: a sender timeout escapes the cancellation-excluding catch and aborts the transaction, losing delivery progress and retry accounting; see `app/src/RequestHub.Core/Notifications/NotificationProcessor.cs:53-106`.

## Failure mode to reproduce
Queue an ordered batch with a successful delivery before a notification whose sender throws a timeout-shaped `TaskCanceledException`, and another successful delivery after it. Keep the processor's cancellation token uncanceled. Today the exception escapes before the batch is saved or committed, leaving notifications pending in the database; a later batch can resend the earlier successful delivery without advancing the timed-out notification's persisted attempts.

## Acceptance criteria
- [ ] Given that batch and an uncanceled processor token, when processing completes, then both successful notifications are persisted as Sent, the timed-out notification remains Pending with one persisted attempt, a recorded error and a future retry time, and another batch does not resend either successful notification.
- [ ] Given repeated sender timeouts without processor cancellation, when eligible retries reach MaxAttempts, then the notification is persisted as Failed with its attempt count and processing time, and is not delivered again.
- [ ] Given cancellation of the processor's token during delivery, when the sender throws a cancellation exception, then cancellation propagates rather than being recorded as an ordinary delivery failure; the batch does not commit partial progress.
- [ ] The new test fails on the current `main` and passes with the change: the **Operate · GitHub · prove the regression test** check reports PROVEN.
- [ ] Every existing test still passes. No test, guard, or validation is weakened.

## Scope
- Test: `app/tests/RequestHub.Tests/WorkerAndContractTests.cs` (reuse WorkerTests, ApiFixture and its processor/options helpers; exercise a multi-item batch and reload persisted state).
- Code, only if the test fails: `app/src/RequestHub.Core/Notifications/NotificationProcessor.cs`.
- Out of scope: the external relay adapter, a new sender, worker telemetry changes, configuration, infrastructure, migrations, API/contract changes, approval behavior, and exactly-once delivery guarantees.

## Evidence from the incident
- Signals and logs, 2026-10-20 13:58:29 UTC: sender `TaskCanceledException` caused by the configured 10-second HTTP timeout escapes through ProcessBatchAsync to the worker.
- Signals and logs: iteration warnings recur about every 15 seconds; the relay team's summary reports six notification IDs received about 130 times each and one delivery never completing.
- Backlog responses: pending rises from 97 at 14:05 to 212 at 14:20, with failed=0 at both readings. Full relay logs and deployed-source correspondence remain unverified.

Related to #252

> Drafted with Copilot CLI (`operate-github` agent, `incident-evidence` skill) and filed by the person who ran it. The agentic workflow did not run.
```

`out/operate/triage-comment.md`:

```markdown
### Incident triage

**Severity 3** · area: worker · status: Mitigated
IT and Facilities reviewers and approvers reportedly received notifications up to 35 minutes late and repeatedly; submission, review and human approval continued without reported data loss. Rollback to the built-in log-only sender cleared the pending backlog, but does not demonstrate restored external delivery; the relay remains disabled.
The severity rubric assigns severity 3 to delayed or duplicated supporting functions when core flows work and no data loss is reported.

#### Timeline (UTC)
| Time | Event | Source |
|---|---|---|
| 2026-10-19 16:30 | API revision deployed; report says no notification changes | Recent changes |
| 2026-10-20 13:46 | Staging switched to external relay adapter with a 10-second timeout | Recent changes |
| 2026-10-20 13:52 | Relay-enabled worker revision active | Recent changes; Timeline |
| 2026-10-20 13:58 | Last backlog log: pending=3, failed=0, delay fault inactive | Signals and logs, 13:58:12 |
| 2026-10-20 13:58 | First iteration warning: HTTP timeout surfaced as TaskCanceledException | Signals and logs, 13:58:29 |
| 2026-10-20 14:05 | Synthetic alert; pending=97, oldest age=412 seconds, failed=0 | Detected at; Timeline; backlog response |
| 2026-10-20 14:09 | Reviewers/approvers reported late and repeated notifications | Timeline |
| 2026-10-20 14:12 | Relay team reported repeated IDs and one noncompleting delivery | Timeline |
| 2026-10-20 14:20 | Endpoint pending=212, failed=0; worker pending gauge still 3 | Timeline; Signals and logs |
| 2026-10-20 14:31 | Rollback to log-only sender started | Timeline; Mitigation so far |
| 2026-10-20 14:33 | Endpoint pending=0; report marks incident mitigated | Signals and logs, 14:33:10; Timeline |

#### Observed facts
- Logs show a sender timeout escaping ProcessBatchAsync; warnings recur about every 15 seconds (Signals and logs).
- Relay summary reports six IDs received about 130 times each; full receiver logs are absent (Signals and logs; Evidence links).
- Backlog grows while failed stays zero; backlog logs stop and the pending gauge stays at 3 (Signals and logs).
- Core flows, human approval and data retention reportedly remained intact (Impact).

#### Hypotheses
| | Hypothesis | Supported by | Not explained or against | Confidence |
|---|---|---|---|---|
| H1 | Likely timeout escapes the catch excluding OperationCanceledException, preventing batch commit and replaying earlier successful sends (`app/src/RequestHub.Core/Notifications/NotificationProcessor.cs:53-106`). | TaskCanceledException is a cancellation exception; save/commit follow the loop. Explains duplicates, uncounted retries and 10-second timeout plus 5-second worker retry (`app/src/RequestHub.Worker/Program.cs:81-89`). | Does not establish why the relay hangs; deployed source, cancellation state and row history unavailable. | high |
| H2 | Likely stale worker telemetry because processing exceptions bypass backlog refresh/logging (`app/src/RequestHub.Worker/Program.cs:64-73`, `:85-89`). | Flat gauge and absent backlog logs while the endpoint grows. | Does not cause the delivery timeout or duplication; dashboard/exporter evidence absent. | high |

The logged inactive delay fault argues against injected worker delay at the sampled time; it does not establish fault settings throughout the incident. At-least-once delivery is intentional (`app/src/RequestHub.Core/Notifications/NotificationProcessor.cs:36-39`); H1 concerns unbounded replay without persisted retry progress, not an exactly-once guarantee.

#### Missing evidence
- Platform team: full relay logs and timeout diagnostics to explain the hung delivery and verify duplicate counts/order.
- Release owner/worker logs: deployed source and effective options, processor-token state, and fault-setting history to confirm H1 and exclude shutdown or later injection.
- Database history: affected rows' Attempts, Status and NextAttemptAt to confirm rollback rather than ordinary retries.
- Operations: dashboard/exporter history to verify H2; end-to-end receiver evidence to establish external delivery recovery after log-only rollback.

#### Follow-up
One follow-up Issue was opened for H1: [follow-up] Treat sender timeouts as failed attempts without stalling the batch.
Not created: independent backlog freshness monitoring; external relay timeout diagnostics and receiver deduplication review.
A person decides whether to assign it to Copilot.

> Drafted with Copilot CLI (`operate-github` agent, `incident-evidence` skill) and filed by the person who ran it. The agentic workflow did not run.
```
