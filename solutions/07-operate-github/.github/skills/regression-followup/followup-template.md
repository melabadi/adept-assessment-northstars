# Follow-up Issue template

The incident triage opens **exactly one** follow-up per incident, with this structure. The `operate-github` agent expects it, and a person can read it in a minute.

**Title:** the behavior that must hold, in the imperative, at most 80 characters, without the incident number. For example: `Count a timed-out delivery as a failed attempt instead of stalling the queue`. The workflow adds the `[follow-up] ` prefix and links the incident.

**Body:**

```markdown
## Why
Incident #<number> (severity <N>): <one sentence on what users saw>.
Hypothesis H1 from the triage: <one sentence>, see `<path>:<lines>`.

## Failure mode to reproduce
<The smallest situation that triggers the failure in RequestHub's code, and what happens today. Plain words, no stack traces.>

## Acceptance criteria
- [ ] Given <state>, when <action>, then <observable outcome>.
- [ ] Given <state>, when <action>, then <observable outcome>.
- [ ] The new test fails on the current `main` and passes with the change: the **Operate · GitHub · prove the regression test** check reports PROVEN.
- [ ] Every existing test still passes. No test, guard, or validation is weakened.

## Scope
- Test: `<test file>` (reuse its fixtures and helpers).
- Code, only if the test fails: `<production file>`.
- Out of scope: <tempting but unrequested work, for example a new sender, new configuration, or an API change>.

## Evidence from the incident
- <observed fact that supports H1, with its source>
```

Rules for the author:

- Acceptance criteria describe behavior a test can check, not implementation steps.
- Name real files. Check that they exist.
- Keep it to one failure mode. Other ideas go in the triage comment as *not created*.
