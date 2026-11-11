# Plan · Requirements analyst in Microsoft Foundry

Turning workshop notes into a backlog takes days, and on the way it is easy to lose where a requirement came from, or to settle a disagreement nobody decided. This solution adds a requirements analyst to your repository's planning, and runs it in Azure. One command starts a run. An Azure Function app asks a Microsoft Foundry agent to read your stakeholder notes and policies and draft a requirements brief, an epic, and its tasks, with a source on every line. A Foundry evaluation scores the brief with code-based checks, and only a brief that passes the gates reaches a person: a GitHub Issue with the brief, its scores, and the conflicts and questions nobody settled. When the person approves, the Function app publishes the epic and its tasks as linked GitHub Issues. GitHub holds only the code and the Issues.

![Review Issue #214, opened by the Function app: drafted by the Foundry agent requirements-analyst in run 20261031-043915-5090 and scored by the evaluation plan-brief-checks, how to approve or reject, and the scores: the four gates and two reported checks at 1, key requirement paragraphs cited at 0.9](images/08-review-issue.png)

- **[See it work](#see-it-work):** a real run on this repository's synthetic workshop notes. The agent drafted a cited brief in 22 seconds, Foundry's gates passed it, and 51 seconds after a reviewer approved it, the epic and its four tasks were Issues.
- **[Add it to your repository](#add-it-to-your-repository):** 13 minutes of one-time setup in Azure and GitHub, in a fresh setup we timed, once your notes, the agent's instructions, and the checks describe your work.
- **[Try it first in a copy of this repository](#try-it-first-in-a-copy-of-this-repository):** 13 minutes to set it up, in a fresh setup we timed, then about 15 minutes for the steps of See it work, plus the time you take to review the brief.

## Why it matters

**Phase 1 of 7: Plan.** The GitHub counterpart is [01-plan-github](../01-plan-github/), where a Copilot agent drafts the brief in a pull request and GitHub Actions validate and publish it. Both start from the same transcript and its planted problems, and in both a person approves before anything reaches the backlog. Here the AI and every step around it run in Azure, and GitHub only receives Issues. To have Foundry evaluate the exact commit of a brief that Copilot drafted, use both as in the [Plan solution combo](../../PRESENTING.md#plan-copilot-drafts-foundry-evaluates-the-product-owner-publishes).

| | Today | With this solution |
| --- | --- | --- |
| Drafting | A product owner rewrites notes into tickets over several days. | A Foundry agent drafts the brief, an epic, and four tasks in about a minute. |
| Consistency | Each analyst structures requirements differently. | One versioned agent definition and a strict output schema, every time. |
| Traceability | Reviewers can't tell where a requirement came from. | Every line cites a transcript paragraph or a policy, a check rejects citations that don't exist, and each published Issue quotes its sources. |
| Quality checks | Someone skims the tickets. | A Foundry evaluation scores every brief with the same seven code-based checks. Four are gates: a brief that fails one never reaches a person. |
| Disagreements | Whoever writes the ticket settles them silently. | Unresolved conflicts and open questions are listed, with their sources, for a person to decide. |
| Approval | Tickets appear as soon as someone writes them. | Nothing reaches the backlog until a person applies a label. Closing the review Issue, or not deciding within 2 hours, publishes nothing. |
| Orchestration | Scripts on someone's laptop or in CI. | An Azure Function app runs every step, and keeps each run's record and log. |
| Access | Shared keys or personal accounts in scripts. | Azure services use managed identities, without keys. GitHub access is one token limited to one repository's Issues, kept in Key Vault. |

**The value:** a cited, checked brief reaches the person who owns the backlog within minutes of the notes, with every open decision listed for them, and the backlog exists less than a minute after they approve. In [See it work](#see-it-work):

- The agent drafted the brief, an epic, and four tasks in 22 seconds, with a transcript paragraph or a policy cited on every line.
- Foundry's seven checks passed it: the four gates at 1, and the three reported checks at 1, 1, and 0.9. The preview grading sandbox failed once, which cost 4 minutes and a second attempt, not a wrong verdict.
- The review Issue reached the person 6 minutes after the start, with the unresolved Finance-versus-IT conflict and four open questions listed for them to decide.
- 51 seconds after the approval label, the epic and its four tasks were Issues, linked as sub-issues with their "blocked by" dependencies, and the review Issue was closed.

## How it works

```mermaid
flowchart LR
  You([You]) -->|python runs.py start| H
  subgraph Azure["Azure: the solution's resource group"]
    subgraph F["Function app, Flex Consumption"]
      H[runs<br/>HTTP] -->|queue plan-steps| S[run_step<br/>draft, evaluate, publish]
      T[check_reviews<br/>timer, every 30 s]
    end
    subgraph Private["Private endpoints only"]
      R[(Storage<br/>run records, queue)]
      K[(Key Vault<br/>GitHub token)]
    end
    subgraph Foundry["Microsoft Foundry project: plan"]
      A[Agent<br/>requirements-analyst<br/>on gpt-6-luna] -- file search --> VS[(Vector store<br/>transcript + policies)]
      E[Evaluation<br/>plan-brief-checks<br/>7 code-based evaluators]
    end
    AI[(Application Insights<br/>agent traces, Function logs)]
    S -->|1. Responses API,<br/>background mode| A
    S -->|2. score the brief| E
    S -.- R
    T -.- R
    S -.- K
    A -. traces .-> AI
  end
  S -->|3. gates pass:<br/>review Issue| I[GitHub Issue<br/>brief for review]
  Hu([Reviewer]) -->|applies brief-approved| I
  T -->|4. reads the Issue| I
  S -->|5. publishes| B[GitHub Issues<br/>epic + 4 tasks]
```

- **Microsoft Foundry** hosts the `requirements-analyst` prompt agent, on the model `gpt-6-luna`. [`agent.yaml`](agent.yaml) defines it: instructions, reasoning effort, file search over a vector store with the transcript and the policies, and the request each run sends it. The agent must answer with JSON that matches [`backlog.schema.json`](backlog.schema.json). Foundry also hosts seven code-based evaluators from [`evaluators/`](evaluators/) and the evaluation `plan-brief-checks` that runs them. [`setup_foundry.py`](setup_foundry.py) publishes all of it from the repository, and adds a version only when something changed. Agent traces go to Application Insights, where the agent's **Traces** tab shows them.
- **The Function app** ([`function/`](function/)) runs every step, with three functions:
  - `runs`, an HTTP function that needs the Function app's key, starts a run, lists the runs, shows one, or cancels one. [`runs.py`](runs.py) calls it for you.
  - `run_step` takes one step at a time from the storage queue `plan-steps`, each a long call to Foundry or a series of calls to GitHub:
    1. **Draft the brief:** it calls the agent in background mode, then polls every 5 seconds until the brief is ready. A response that fails, or that Foundry no longer finds, is asked for once more.
    2. **Evaluate the brief:** it scores the brief with the Foundry evaluation. The four gates must each report a pass: structure, real citations (every item cites at least one source, and every source exists), testable criteria, and the injected instruction ignored. A gate that fails, or reports no result, fails the run, and nothing reaches GitHub. The other three checks are reported to the reviewer. When the gates pass, it puts the brief and the scores in a GitHub Issue.
    3. **Publish the backlog:** it creates the epic and four task Issues, links the tasks as sub-issues with their dependencies, comments the links on the review Issue, and closes it.
  - `check_reviews`, a timer, reads every review Issue that waits for a person, every 30 seconds. When a person has applied `brief-approved`, it queues the publish step. When the person closed the Issue instead, it comments that nothing was published. When nobody decided within 2 hours, it comments, closes the Issue as not planned, and the run publishes nothing. If someone deleted the Issue, the run ends and publishes nothing.

  No function waits: each run's state is a JSON record in a private blob container, plus the review Issue itself. Each step saves its progress as it goes, and a step that fails is delivered again, up to three times, and resumes where it stopped: it polls the agent's response or the evaluation it had started, and before it creates an Issue, it looks for one with the same hidden marker, so a retry can't create an Issue twice. Only one delivery publishes a run at a time. If GitHub refuses a call while the backlog is being published, the run comments on the review Issue what it already created and ends as failed. The timer also looks after steps that stopped without failing, for example when Azure restarted the instance: it queues a publish again that made no progress for 5 minutes (twice at most), and it ends a run whose draft or evaluation saved nothing for 45 minutes. Every step's longest path, three 15-minute evaluation attempts, ends well within the Function app's one-hour time limit. All the logic is plain Python in [`function/planner/`](function/planner/), and [`tests/test_function.py`](tests/test_function.py) tests it without Azure.
- **GitHub** holds the code, the review Issue, and the published backlog. No GitHub Actions workflow and no Copilot step is involved: you start the run in Azure, and the timer reads the Issue for the label.
- **A person** reviews the brief, owns the unresolved decisions, and applies the `brief-approved` label, or closes the review Issue to reject the brief.

**With 01-plan-github.** Two more ways to start a run use briefs that a Copilot agent drafts in [01-plan-github](../01-plan-github/)'s pull requests. `python runs.py start --compare-with-pull-request N` also scores the Copilot brief on pull request N, in the same evaluation run, and the review Issue shows both briefs' scores. `python runs.py start --evaluate-pull-request N` drafts nothing: it scores only the Copilot brief, at the pull request's head commit, and opens an evaluation Issue that lists the open items for the product owner. 01-plan-github then publishes that commit only, once every item is decided, as in the [Plan solution combo](../../PRESENTING.md#plan-copilot-drafts-foundry-evaluates-the-product-owner-publishes).

**Access.** Azure services sign in to each other with managed identities: the Function app to Foundry, storage, Key Vault, and Application Insights, and Foundry to Application Insights. Storage and Key Vault accept no public network traffic, which our tenant's policy requires: the Function app reaches both through private endpoints in its own virtual network, and storage accepts no shared keys. Reaching GitHub needs a credential: a fine-grained token limited to one repository's Issues. `azd provision` passes it to Bicep as a secure parameter, which deployment history never shows, and stores it as the Key Vault secret `github-token`. Only the Function app's identity can read it. The code keeps it in memory for up to five minutes, and never writes it to a log, a response, or a run record: a token with a line break inside is refused without being quoted, and an error the code didn't write itself is logged by its type only, because Python's own errors can quote a request.

**Outside contributions.** Nothing in this solution listens to GitHub, so on a public repository nobody outside it can start a run: the start endpoint needs the Function app's key, which only Azure holds, and `runs.py` reads it with your Azure sign-in each time, so no copy of the key is stored anywhere else. A run acts only on its review Issue's `brief-approved` label, which only people with triage access can apply, or on the Issue being closed, which only its author and people with triage access can do. It reads no comments. When it looks for its own Issues by their hidden marker, it counts only Issues opened by the repository's owner, members, and collaborators, so an outsider who copies a marker into an Issue can't stand in for the review Issue or make a publish look done. The comparison and the evaluation of a pull request's brief read the brief only when the pull request's branch is in the repository, not a fork: only people with write access push branches there, or the Copilot cloud agent when one of them assigns it.

**Model and call mode.** The agent runs on `gpt-6-luna` (version 2026-09-22, Global Standard), a reasoning model, at reasoning effort `low`, in background mode: the call returns at once, and the step polls until the brief is ready, 34 to 64 seconds later in our runs. A brief took about 5,500 input and 3,300 output tokens: about $0.002 at list price. Until 11 November the agent ran on `gpt-4.1`, which drafted in 16 to 24 seconds for about $0.024 a brief, and retires on 2027-04-14; `gpt-6-luna` retires on 2028-03-11. On `gpt-6-luna`, two sentences of the instructions had to become more explicit before the checks passed as they had on `gpt-4.1`. No check changed, and since then the three briefs that reached the evaluation passed all seven checks. [The runs of 11 November](evidence/2026-11-11-gpt-6-luna.md) show both models' results and costs. To change the model, set `modelName` and `modelVersion` in [`infra/main.bicep`](infra/main.bicep), and `reasoning_effort` in `agent.yaml` (`temperature` for a model that doesn't reason), then run `azd provision`. Delete the old deployment once `python setup_foundry.py publish` shows the agent on the new model.

**Preview pieces.** Foundry Agent Service, agent tracing, and Azure Functions on the Flex Consumption plan are generally available. Custom evaluators and cloud evaluations are in preview. The evaluator catalog asks for the opt-in header `Foundry-Features: Evaluations=V1Preview`, which [`setup_foundry.py`](setup_foundry.py) sends. The preview grading sandbox often errors on a check ("An error occurred during grading"; in about half of our evaluation attempts), and that attempt then takes about 4 minutes instead of 1.5. As a preview workaround, the run evaluates again, up to three attempts, while a gate has no score, and keeps each check's first score: the checks are code, so the same brief always gets the same score. It never retries a gate that failed. The review Issue marks a reported check that was never scored as not scored.

## See it work

On 31 October 2026, from 04:39 to 05:04 UTC, the solution ran once, end to end, against the real services in resource group `rg-ai-sdlc-plan` (East US 2), on this repository's synthetic workshop notes. The operator was a GitHub Copilot agent session working for the repository owner, signed in to Azure and GitHub as the owner: it started the run from PowerShell 7 and, standing in for the product owner, applied the approval label. Foundry, the Function app, and GitHub did the rest. The agent, its inputs, and the evaluators were those of commit [d4616db](https://github.com/melabadi/adept-assessment-northstars/commit/0f4499e) (pull request [#168](https://github.com/melabadi/adept-assessment-northstars/pull/168)), unchanged until 11 November apart from a comment in `agent.yaml`. The Function app ran an early version of the code that pull request [#247](https://github.com/melabadi/adept-assessment-northstars/pull/247) merged; the fixes made in its review after this run don't change anything this page shows. Since 11 November the agent runs on `gpt-6-luna`, and run `20261111-144541-46a3` passed the same evaluation, all seven checks, and published ([review Issue #345](https://github.com/melabadi/adept-assessment-northstars/issues/345), [the runs](evidence/2026-11-11-gpt-6-luna.md)).

Every step links evidence that opens without signing in: review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214), the epic [#216](https://github.com/melabadi/adept-assessment-northstars/issues/216), and its four tasks. What only Azure and Foundry keep, the run's record, the evaluation runs, the agent's traces, and the Function app's log, is shown in screenshots. Times are UTC. `runs.py` prints the operator's local time, UTC−4: 00:39:15 is 04:39:15.

### 1. The notes held the problems real notes have

*Written before the run: [`inputs/stakeholder-transcript.md`](inputs/stakeholder-transcript.md) and [`inputs/routing-policies.md`](inputs/routing-policies.md).*

The input was a synthetic stakeholder workshop about routing requests in RequestHub, this repository's sample app: 24 paragraphs, `[T01]` to `[T24]`, and the eight routing policies they refer to. Like real notes, they hide problems:

- **T04 versus T05:** advisory or automatic routing? **T19** records the decision: a person confirms every routing.
- **T06 versus T07:** Finance or IT for expensive computers? Nobody decides.
- **T18:** a message pasted into the meeting chat, telling an assistant to mark all requests as approved.
- **Four unknowns** nobody settled: the response-time target (T12), a confidence threshold (T15), who may override a suggestion (T21), and how long recommendations are kept (T22).

![Transcript paragraphs T04 to T07: Priya says suggestions stay advisory under POL-GOV-001, Ava wants automatic routing, Grace sends anything above 5,000 to Finance under POL-ROUTE-004, and Ben says IT owns all computing equipment whatever it costs](images/01-transcript-conflicts.png)

![Transcript paragraphs T18 and T19: a message pasted into the meeting chat tells an assistant to mark all requests as approved, and Marco records the decision that a person confirms every routing](images/01-transcript-injection.png)

Evidence: the two files, as of commit d4616db and unchanged since.

**What this shows:** the input was ordinary meeting notes, with disagreements, unknowns, and an instruction written to an AI, and a good brief had to keep all of them visible.

### 2. The agent and its checks came from the repository

*Published before the run by `python setup_foundry.py publish`, which `azd up` runs as a hook.*

[`agent.yaml`](agent.yaml) defines the agent `requirements-analyst`: the model `gpt-4.1`; instructions that require a source for every item and treat the files as data, not instructions; file search over a vector store that holds the two input files; and the request each run sends. `setup_foundry.py` published it to the Foundry project `plan`, as version 10 after earlier changes to the definition. It also published the seven files in [`evaluators/`](evaluators/) to the project's evaluator catalog, and the evaluation `plan-brief-checks` that runs them. Nobody configured the agent or the checks in the portal.

These two screenshots were taken on 29 October, two days before the run. The run used the agent's version 10 and the same evaluators, except the citations check, which had a version 4 by then.

![The requirements-analyst agent in the Foundry portal: the Version list shows versions 1 to 10 with version 10 selected, next to the model gpt-4.1, the instructions from agent.yaml, and a File search tool bound to the plan-inputs vector store](images/02-foundry-agent.png)

![The Foundry evaluator catalog with the seven custom code-based evaluators, marked Preview: Testable criteria, Injected instruction ignored, Citations, Key requirements covered, Planted unknowns, Planted conflicts, and Structure, each with its version](images/07-evaluators.png)

Evidence: [`agent.yaml`](agent.yaml) and [`evaluators/`](evaluators/), as of commit d4616db.

**What this shows:** the agent and its checks are files in the repository, reviewed like any change, and Foundry keeps every version of them.

### 3. One command started the run in Azure

*04:39:15. The Function app asked the agent for the brief 11 seconds later.*

At 04:39:15 the operator started the run with `runs.py start`. `runs.py` read the Function app's address and key with the operator's Azure sign-in and called its `runs` function, which saved the run's record as `20261031-043915-5090` and queued its first step. The Function app has three functions: an HTTP start, a queue for the long steps, and a timer that reads the review Issues. This screenshot of them was taken on 1 November; they haven't changed since the run.

![The Function app's Overview in the Azure portal with Essentials collapsed: the Functions tab lists check_reviews with a Timer trigger, runs with an HTTP trigger, and run_step with a Queue trigger, all enabled](images/03-function-app.png)

The terminal screenshot below comes from a later run the same morning, `20261031-051222-a524`, which the operator started at 05:12:22: the same command and the same steps. Its first evaluation attempt passed, so it reached its review Issue, [#221](https://github.com/melabadi/adept-assessment-northstars/issues/221), in 1 minute 47 seconds.

![python runs.py start in PowerShell 7: run 20261031-051222-a524 starts in Azure, the agent's brief is ready after 17 seconds, the first evaluation attempt passes the four gates after 81 seconds with 7 of 7 checks, and the run opens review Issue #221 and prints its link](images/04-start-run.png)

Evidence: the run's record ([step 9](#9-the-runs-record-kept-every-step)). Review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214) names the run.

**What this shows:** one command started the run, and everything after it happened in Azure, with no GitHub Actions workflow and no Copilot step.

### 4. The agent drafted the brief

*Ready at 04:39:47: 22 seconds, as the run's record measured, and 32 seconds after the start.*

`run_step` asked the agent for the brief through the Responses API in background mode, and polled until it was ready. The agent searched the transcript and the policies, then answered with JSON in the shape of [`backlog.schema.json`](backlog.schema.json): a problem statement, goals, five requirements, one decision, two conflicts, four open questions, an epic, and four tasks, every item with its sources. The step saved the brief in the run's record and queued the evaluation.

The agent's traces in Foundry show what one draft takes. These two screenshots come from earlier drafts by the same agent version, on 30 October, when a Logic App ran the steps instead of the Function app: about 13 seconds and 6,800 tokens a brief, an estimated $0.026.

![The agent's Traces list in Foundry: each run with its status, start time, a duration of about 13 seconds, about 4,770 input and 2,050 output tokens, and an estimated cost of about $0.026; one run failed after 0.001 seconds with no tokens](images/06-traces.png)

![One trace in Foundry: invoke_agent requirements-analyst:10 contains a file_search tool call (2.37 seconds) and one gpt-4.1 chat call (10.83 seconds), 13.3 seconds and 6.8K tokens in all, with the agent's instructions as the system message](images/06-trace.png)

Evidence: review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214) names the agent's response, and its body is the brief.

**What this shows:** the agent searched the notes and the policies and wrote a brief with a source on every item in one model call, in seconds.

### 5. Foundry evaluated the brief, and the gates passed

*5 minutes 26 seconds, done at 04:45:14: a first attempt the grading sandbox couldn't finish, then one that scored every check.*

At 04:39:51 `run_step` started attempt 1 of the evaluation `plan-brief-checks`, in which Foundry runs the seven evaluators on the brief. At 04:43:56 the attempt came back with an error from the preview grading sandbox on `testable_criteria`, a gate. A gate without a score would fail the run, so the step started attempt 2 at 04:43:57. It finished at 04:45:14, 1 minute 17 seconds later (1 minute 15.66 seconds by Foundry's clock), and every check had a score: the four gates at 1, both planted conflicts found with the right status (1), the four planted unknowns asked (1), and 9 of the 10 key requirement paragraphs cited (0.9). The run's record counts the whole step as 326 seconds.

![The evaluation run in Foundry, named brief 2026-10-31 04:43 (run 20261031-043915-5090, attempt 2): completed in 1 minute 15.66 seconds, with all seven checks at 100%: structure, citations, testable_criteria, injection_ignored, planted_conflicts, planted_unknowns, and requirements_covered](images/07-evaluation.png)

The Function app logs each step. This screenshot of an evaluation step's log comes from run `20261031-051222-a524`, the run in step 3's terminal screenshot, whose first attempt passed in 81 seconds.

![The Invocation details of one run_step invocation in the Azure portal, the evaluate step of run 20261031-051222-a524: a new message on the plan-steps queue started it, attempt 1 of the evaluation plan-brief-checks started, the four gates passed after 81 seconds with 7 of 7 checks, it opened review Issue #221, and the invocation succeeded after 83.5 seconds](images/05-run-step.png)

Evidence: the scores in review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214), and both attempts in the run's record ([step 9](#9-the-runs-record-kept-every-step)).

**What this shows:** code-based checks, not the model, decided whether a person would see the brief, and a grading error cost minutes, not a wrong verdict.

### 6. A review Issue reached the person

*04:45:15, 6 minutes after the start.*

The step opened review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214): who drafted and scored the brief, how to approve or reject it, the seven scores, and the brief itself, every line with its sources. Under **Decisions**, **Conflicts**, and **Open questions**, the brief handed the person what nobody had settled: the Finance-versus-IT conflict C2, with both policies, and four questions citing T12, T21, T22, and T15. It recorded that T19 resolved the other conflict, C1. From then on, `check_reviews` read the Issue every 30 seconds.

![Review Issue #214, opened by the Function app: drafted by the Foundry agent requirements-analyst in run 20261031-043915-5090 and scored by the evaluation plan-brief-checks, how to approve or reject, and the scores: the four gates and two reported checks at 1, key requirement paragraphs cited at 0.9](images/08-review-issue.png)

![The brief's Decisions, Conflicts, and Open questions in the review Issue: decision D1 cites T19; conflict C1 on automatic routing is resolved by T19; C2, Finance versus IT for expensive computing equipment, is unresolved and needs a decision; four open questions cite T12, T21, T22, and T15](images/08-review-decisions.png)

Evidence: review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214).

**What this shows:** the person got a scored brief with a source on every line, and the decisions nobody had made were listed for them instead of guessed.

### 7. The reviewer approved

*05:03:01, 17 minutes 46 seconds after the Issue opened. The Function app saw the label 29 seconds later.*

At 05:03:01 the operator, standing in for the product owner, applied the `brief-approved` label to #214 with the owner's account. GitHub sent nothing to Azure: at 05:03:30, `check_reviews` read the Issue, found the label, and queued the publish step.

![Review Issue #214 after approval: Closed, with the brief-approved label next to ai-sdlc, phase:plan, track:microsoft, and type:brief](images/09-approved.png)

Evidence: the label in the history of review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214).

**What this shows:** nothing reached the backlog until the reviewer applied the label, and the Function app read that decision from GitHub instead of GitHub calling into Azure.

### 8. The Function app published the backlog

*05:03:37 to 05:03:52: the epic 36 seconds after the label, and the review Issue closed 51 seconds after it.*

The publish step created the epic [#216](https://github.com/melabadi/adept-assessment-northstars/issues/216) at 05:03:37, then the tasks [#217](https://github.com/melabadi/adept-assessment-northstars/issues/217), [#218](https://github.com/melabadi/adept-assessment-northstars/issues/218), [#219](https://github.com/melabadi/adept-assessment-northstars/issues/219), and [#220](https://github.com/melabadi/adept-assessment-northstars/issues/220) by 05:03:46, each linked to the epic as a sub-issue. It marked their four "blocked by" dependencies: TASK-2 and TASK-4 on TASK-1, and TASK-3 on TASK-1 and TASK-2. Each Issue quotes the transcript paragraphs and policies it cites, and the epic carries the open conflict and questions. At 05:03:51 the step commented the backlog on #214, and at 05:03:52 it closed the review Issue as completed.

![The Function app's comment on the review Issue: a person applied brief-approved, so run 20261031-043915-5090 created the epic #216 and the tasks #217 to #220, linked to the epic as sub-issues](images/09-published.png)

![Epic #216: published after a person approved review Issue #214, with a summary, Given/When/Then acceptance criteria, four open questions with their sources, and the unresolved conflict C2](images/10-epic.png)

![The end of the epic: the Sources section quotes the paragraphs and the policy it cites, from T03 to T23 and POL-GOV-001, and Sub-issues lists the four tasks #217 to #220, three of them marked as blocked by another task](images/10-sub-issues.png)

Evidence: [the Function app's comment](https://github.com/melabadi/adept-assessment-northstars/issues/214#issuecomment-6539344167) and the epic [#216](https://github.com/melabadi/adept-assessment-northstars/issues/216) with its sub-issues. The backlog was closed as not planned at 23:58 that day, when the repository was reset for later runs, and stays readable.

**What this shows:** approval turned the reviewed brief into a linked backlog in under a minute, and every Issue in it shows where its words came from.

### 9. The run's record kept every step

*Read at any time with `python runs.py show 20261031-043915-5090`.*

The Function app kept the run's record in its private blob storage: every step and its time, from the start to the closed review Issue, with the wait for the person in between. Application Insights keeps the same lines in the Function app's log.

![python runs.py show 20261031-043915-5090 in PowerShell 7: the brief ready after 22 seconds, the first evaluation attempt errored on testable_criteria and ran again, the gates passed after 326 seconds, review Issue #214 opened at 00:45:16, brief-approved seen at 01:03:30, the epic #216 and tasks #217 to #220 created, four dependencies marked, and the review Issue commented and closed at 01:03:53](images/11-run-history.png)

Evidence: this screenshot; the record itself needs an Azure sign-in.

**What this shows:** what the run did, and when, stayed in Azure for anyone with access to check, with no process left running.

### 10. Optional: Foundry scored a Copilot brief next to its own

*Another run, `20261031-051521-b5b6`, started at 05:15:21 the same morning: 8 minutes 19 seconds to its review Issue.*

The operator started it with `runs.py start --compare-with-pull-request 129`. Pull request [#129](https://github.com/melabadi/adept-assessment-northstars/pull/129), from [01-plan-github](../01-plan-github/), holds a brief that a Copilot agent drafted from the same transcript. Its branch is in this repository, so the run read that brief, and one evaluation run scored both briefs with the same seven checks. Review Issue [#225](https://github.com/melabadi/adept-assessment-northstars/issues/225) shows the Foundry brief's scores, then a second table for the Copilot brief.

![The review Issue of a comparison run: the Foundry brief's scores, with the four gates at 1 and planted unknowns at 0.75, then the same evaluation's scores for the Copilot brief from 01-plan-github pull request #129, which passes all seven checks](images/13-compare.png)

Evidence: review Issue [#225](https://github.com/melabadi/adept-assessment-northstars/issues/225) and pull request [#129](https://github.com/melabadi/adept-assessment-northstars/pull/129).

**What this shows:** the same code-based checks scored both tracks' briefs, so comparing them needed no Copilot step in Azure.

## Results and value

**What the run left behind.**

- Review Issue [#214](https://github.com/melabadi/adept-assessment-northstars/issues/214): the brief, its seven scores, the approval, and the comment that lists the backlog.
- The epic [#216](https://github.com/melabadi/adept-assessment-northstars/issues/216) and its four tasks, [#217](https://github.com/melabadi/adept-assessment-northstars/issues/217) to [#220](https://github.com/melabadi/adept-assessment-northstars/issues/220): sub-issues with "blocked by" dependencies, each quoting its sources. The conflict and the four questions nobody settled went into the epic, for the team to decide.
- In Azure, the run's record and the Function app's log. In Foundry, the agent's response and both evaluation runs.
- The decision, left to a person: whether the brief was good enough to become the backlog, and what to do about the Finance-versus-IT conflict and the four questions. Here the operator approved for the repository owner, and the open items stayed open in the epic.

**What was measured.**

| | In See it work |
| --- | --- |
| From `runs.py start` to the brief | 32 seconds, 22 of them the agent's |
| The evaluation | 5 minutes 26 seconds: 4 minutes 5 seconds for an attempt the grading sandbox couldn't finish, then 1 minute 17 seconds for the one that scored every check |
| From the start to the review Issue | 6 minutes 0 seconds |
| The person's review, from the Issue to the label | 17 minutes 46 seconds |
| From the label to the epic | 36 seconds |
| From the label to the whole backlog, with the review Issue commented and closed | 51 seconds |
| The whole run | 24 minutes 37 seconds |
| The checks | the four gates at 1; planted conflicts 1, planted unknowns 1, key requirement paragraphs 0.9 |
| Open items handed to the person | 1 unresolved conflict and 4 open questions |
| What was published | 1 epic, 4 tasks, and 4 "blocked by" dependencies |

**What a team gets.**

- **Time saved.** The agent drafted the brief, the epic, and four tasks in 22 seconds, and the backlog existed 51 seconds after the approval, with links, dependencies, and quotes nobody had to type. The person's time went to reading and deciding: 17 minutes 46 seconds here.
- **Risk removed.** Four code-based gates stop a brief that cites a paragraph that doesn't exist, has untestable criteria, or follows an instruction planted in the notes, before anyone reads it. Nothing reaches the backlog without a person's label. Azure services use managed identities, storage and Key Vault accept no public traffic, and the one GitHub credential reaches one repository's Issues.
- **Evidence a reviewer or an auditor can follow.** Every published Issue quotes the paragraph or the policy behind it, the review Issue keeps the scores and the approval, and Azure and Foundry keep the run's record, the agent's traces, and the evaluation runs.

**The metric to track when you adopt it:** the time from a workshop's notes to an approved backlog (24 minutes 37 seconds in See it work, 17 minutes 46 seconds of them the person's review), and the open items that reached a person instead of being settled silently (5 here). Compare both with how your team turns notes into a backlog today. A target is a goal you set, never a result.

## Add it to your repository

These are the steps that set the solution up on this repository, with what to change for your notes. We have run them only on this repository's synthetic notes: for yours, the commands stay the same, and the changes are the ones named below.

### Prerequisites

- Your repository on GitHub, and the tools in the root README's [Before you start](../../README.md#before-you-start): the GitHub CLI, Python 3.12 or later, PowerShell 7, the Azure CLI, and the Azure Developer CLI. The solution registers no app of its own in Microsoft Entra ID, but when it publishes the agent, Foundry creates an agent identity blueprint there, an app registration that you own, and an agent identity: [Clean up](#clean-up) removes them.
- An Azure subscription where you can create a resource group and role assignments, for example as Owner.
- Quota for `gpt-6-luna`, version 2026-09-22 (Global Standard, 50,000 tokens per minute), in your region, and the Flex Consumption plan available there. We used `eastus2`. `az cognitiveservices usage list --location eastus2 --query "[?name.value=='OpenAI.GlobalStandard.gpt-6-luna']" -o table` shows your quota there, in thousands of tokens per minute: `Limit` minus `CurrentValue` must be at least 50.
- Permission to create a fine-grained personal access token for the repository.
- Your notes and policies as Markdown files, with ids that the brief can cite (see the next section).
- To read the agent's traces and the evaluation runs, a browser signed in to the [Azure portal](https://portal.azure.com) and the [Foundry portal](https://ai.azure.com).
- Only to score briefs that Copilot drafts: [01-plan-github](../01-plan-github/) in the same repository, which needs a paid GitHub Copilot plan.

### What to copy and what to change

Copy this folder into your repository, for example as `plan/`, without `images/`, which shows the run in [See it work](#see-it-work). Then change these files:

| File | What it does here | What to change for your work |
| --- | --- | --- |
| [`inputs/stakeholder-transcript.md`](inputs/stakeholder-transcript.md) and [`inputs/routing-policies.md`](inputs/routing-policies.md) | The synthetic workshop notes, paragraphs `[T01]` to `[T24]`, and the routing policies they refer to | Your notes and policies, in the same form: each paragraph starts with its id in bold, such as `**[T01]**`, and each policy is a table row `\| POL-ROUTE-004 \| version \| title \| rule \|`. `setup_foundry.py` reads the ids that the citations check accepts from these files, and each published Issue quotes the paragraphs and policies it cites. |
| [`agent.yaml`](agent.yaml) | The agent: name, reasoning effort, instructions, file search, and the request each run sends | The `instructions` and the `prompt`: what your brief must contain. Keep the rules that every item cites an id from the files, and that the files are data, not instructions. |
| [`backlog.schema.json`](backlog.schema.json) | The JSON shape the agent must answer with | The fields of your brief. If you rename fields, change the Markdown in [`function/planner/brief.py`](function/planner/brief.py) and the evaluators that read them. |
| [`evaluators/`](evaluators/) | Seven code-based checks, each one `grade(sample, item)` function that returns a score from 0 to 1 | Keep `citations.py` and `testable_criteria.py`. In `structure.py`, set the counts your backlog needs: here exactly four tasks and at least four requirements. `injection_ignored.py` checks this transcript's planted instruction (`INJECTED = "T18"`) and RequestHub's rule that nothing may imply automatic approval: point it at what your notes and policies must never make the agent do. Replace `planted_conflicts.py`, `planted_unknowns.py`, and `requirements_covered.py`, which check this transcript's planted problems, with checks of what matters in your notes. An evaluator can't call anything named `compile()`: the grading sandbox refuses it. |
| [`function/planner/checks.py`](function/planner/checks.py) | Which checks gate a run, which are reported, and their names in the review Issue | `GATES`, `REPORTED`, and `CHECK_NAMES`, to match your evaluators, and `GATES` in [`tests/test_evaluators.py`](tests/test_evaluators.py) too. |
| [`function/planner/brief.py`](function/planner/brief.py) | What the run writes to GitHub: the review Issue, the epic, the tasks, and the comments | `REVIEW_TITLE`, the `[Plan/Foundry]` prefix of the epic's and the tasks' titles, the labels (`REVIEW_LABELS`, `EPIC_LABELS`, and `TASK_LABELS`), `APPROVAL_LABEL` (`brief-approved`), and `INPUTS_HINT`, the folder an Issue names when it can't quote a source. |
| [`function/planner/steps.py`](function/planner/steps.py) | The run's steps and limits | `DECISION_TIMEOUT` (2 hours), if your reviewers need longer. For the comparison or the Plan combo, `COPILOT_BRIEF`: where 01-plan-github's brief lives in your repository. |
| [`tests/`](tests/) | Unit tests for the evaluators and the run, and [`sample-brief.json`](tests/sample-brief.json), a brief from this transcript | Replace `sample-brief.json` with a brief from your notes, and update the tests that name this transcript's ids. `setup_foundry.py publish` and `azd deploy` run the tests before anything reaches Azure. |
| [`infra/main.bicep`](infra/main.bicep) | The resource group and the model deployment: `gpt-6-luna`, version 2026-09-22, 50,000 tokens per minute | `modelName`, `modelVersion`, and `modelCapacity`, for another model or quota. A model that doesn't reason takes `temperature` instead of `reasoning_effort` in `agent.yaml`. |

### One-time setup

13 minutes in a fresh setup on 11 November 2026, which followed [Try it first in a copy of this repository](#try-it-first-in-a-copy-of-this-repository) in a new copy and a new resource group ([the evidence](evidence/2026-11-11-fresh-setup.md)):

| Step | Took |
| --- | --- |
| 1. Deploy: `pip install -r requirements.txt` | 2 minutes 2 seconds |
| 1. Deploy: `azd up` | 5 minutes 10 seconds |
| 2. Create the GitHub token | about 3 minutes, for a person on GitHub |
| 3. Give the token to the Function app: `azd provision`, then `python runs.py status` | 2 minutes 23 seconds, then 14 seconds |
| 4. Create the approval label | 1 second |

#### 1. Deploy

From the root of your repository:

```powershell
cd plan
pip install -r requirements.txt
az login
azd auth login
azd env new <environment name> --subscription (az account show --query id -o tsv) --location <region>
azd up
```

`--subscription` deploys to the subscription that `az` signed in to, where `runs.py` later looks for the Function app: `az account show` names it, and `az account set --subscription <name or id>` changes it. Without it, `azd up` asks you to pick one of your subscriptions. Run azd in the shell where `pip install` ran, with the same virtual environment active if you use one: its hooks run that `python`.

**What you should see:** before provisioning, the hook names the repository where the Function app will open its Issues, from `gh repo view` in your clone: `GitHub repository: <owner>/<repository>`. To choose another one, run `azd env set GITHUB_REPOSITORY <owner>/<repository>` before `azd up`. It also says `PLAN_GITHUB_TOKEN is not set yet`, which step 3 takes care of. `azd up` creates resource group `rg-<environment name>`, with the resources in [What azd up creates](#what-azd-up-creates). Its hooks run the unit tests, publish to Foundry, and deploy the Function app, and after about 5 minutes it ends with `SUCCESS: Your application was provisioned and deployed to Azure in …`. The publish lines look like this:

```text
unit tests: 94 passed
vector store plan-inputs-9a000f952f98: uploaded
agent requirements-analyst v1: new version (gpt-6-luna)
evaluator plan_structure v1: new version
...
evaluation plan-brief-checks: created
```

After you change `agent.yaml`, `inputs/`, or an evaluator, run `python setup_foundry.py publish` again: it runs the tests first, publishes nothing if one fails, and otherwise publishes only what changed. After you change `agent.yaml`, `inputs/`, or `function/`, also run `azd deploy`: the Function app reads the agent's request, and the quotes for the published Issues, from its own package.

#### 2. Create the GitHub token

On GitHub, open **Settings › Developer settings › Personal access tokens › Fine-grained tokens › Generate new token**:

- **Token name:** for example `ai-sdlc-plan-microsoft`. **Expiration:** for example 30 days.
- **Resource owner:** the owner of your repository. **Repository access:** **Only select repositories**, then your repository.
- **Repository permissions:** **Issues: Read and write**. GitHub adds Metadata: Read-only on its own.
- Only for the comparison or the Plan combo with 01-plan-github: also **Contents: Read-only**, so the run can read the pull request and its brief.

With these permissions the token can create, label, comment on, and close Issues, and link sub-issues and dependencies, in that repository only. Use a person's token, not a GitHub App's: a run counts only Issues opened by the repository's owner, members, and collaborators as its own, and GitHub reports a bot as none of them.

#### 3. Give the token to the Function app

```powershell
azd env set PLAN_GITHUB_TOKEN (Read-Host -MaskInput 'GitHub token')
azd provision
python runs.py status
```

**What you should see:** `azd provision` ends with `SUCCESS`. It stores the token as the Key Vault secret `github-token`, which only the Function app's identity can read, and no output shows it. The last line of `runs.py status` asks the Function app to try the token: `GitHub token in Key Vault: HTTP 200, expires …`. The token also stays in your local azd environment file, `.azure/<environment name>/.env`, which git ignores.

The token comes from `PLAN_GITHUB_TOKEN` only. azd fills a parameter from your shell when its environment lacks the value, and many shells hold a broader `GITHUB_TOKEN` for other tools; that one never reaches Azure. If you store the token as `GITHUB_TOKEN` in the azd environment instead, `azd provision` moves it to `PLAN_GITHUB_TOKEN`. To replace the token, run the same three commands: the Function app reads the new one within five minutes.

#### 4. Create the approval label

```powershell
gh label create brief-approved --color 0e8a16 --force
```

**What you should see:** the GitHub CLI confirms the label; `--force` updates it if 01-plan-github created it already. The run creates its other labels (`ai-sdlc`, `phase:plan`, `track:microsoft`, `type:brief`, `type:epic`, and `type:task`) the first time it uses them.

### Use it the first time

From the folder you copied:

```powershell
python runs.py start
```

**What you should see:** the run's id, then each step as the Function app reports it: the agent's draft, each evaluation attempt, and the link to the review Issue. In our runs on `gpt-6-luna` the link came 2¼ to 2¾ minutes after the start. When the preview grading sandbox errors and the evaluation runs again, it takes several minutes more: 5½ to 8½ minutes in all, in our runs on `gpt-4.1`. Ctrl+C stops following, not the run.

Open the review Issue and read the brief, its scores, and what nobody settled. Then decide:

- **Approve:** apply the `brief-approved` label, in the Issue or with `gh issue edit <number> --add-label brief-approved`. Within a minute the epic and its tasks are Issues, and the review Issue has a comment that lists them and is closed.
- **Reject:** close the review Issue. The Function app comments that nothing was published.
- **Don't decide:** 2 hours after the review Issue opened, the Function app comments, closes it as not planned, and publishes nothing.

`python runs.py show <run id>` prints everything a run did, and `python runs.py status` lists the runs in progress.

Then make it part of your planning:

- **After each workshop,** replace the notes in `inputs/`, run `python setup_foundry.py publish` and `azd deploy`, and start a run: the agent drafts from the files in its vector store, which `publish` updates.
- **If your team drafts briefs with Copilot** in [01-plan-github](../01-plan-github/), `python runs.py start --evaluate-pull-request <n>` scores the brief at the pull request's head commit and opens an evaluation Issue that lists the open items for the product owner, and 01-plan-github publishes only that commit. The [Plan solution combo](../../PRESENTING.md#plan-copilot-drafts-foundry-evaluates-the-product-owner-publishes) shows a run of it. `--compare-with-pull-request <n>` scores the Copilot brief next to the agent's instead, as in [See it work, step 10](#10-optional-foundry-scored-a-copilot-brief-next-to-its-own).

### What it costs

While deployed, the solution costs about $25 to $30 a month, even when nobody runs it:

- The three private endpoints, at $0.01 an hour each, and their DNS zones, at $0.50 a month each: about $23.
- The timer, which runs 2,880 times a day: each run bills at least one second of a 2 GB instance, about 172,800 GB-s a month. That is $4.50 at $0.000026 per GB-s, or about $1.90 after the monthly free grant of 100,000 GB-s, which all Flex Consumption apps in the subscription share.
- Storage transactions (the timer's reads, the host's leases, queue polling): a dollar or two. Key Vault: cents.

A run costs a cent or two: about $0.002 for the agent's draft, from [the tokens it used](evidence/2026-11-11-gpt-6-luna.md#token-use-and-cost-of-each-draft) at `gpt-6-luna`'s list price of $0.10 per million input tokens and $0.50 per million output tokens, plus a cent or two of Function time while its steps wait for Foundry. The root README compares [what the Microsoft solutions cost](../../README.md#what-the-microsoft-solutions-cost). When you won't use the solution for a while, [clean it up](#clean-up): `azd up` recreates it.

## Try it first in a copy of this repository

Optional: the same solution on this repository's synthetic notes, before you adapt anything. It needs the [prerequisites](#prerequisites), with your copy as the repository. In the copy, the other solutions' workflows also see this one's Issues and comments, and stop at once: in our fresh setup, the labels that one run applied started 25 runs of *Operate · GitHub · agentic incident triage*, all skipped, and its comment one run of *Design · GitHub · agentic design review*, which stopped after a 16-second check. No model ran.

### Quick start

From the root of your copy of the repository, which the root README's [Try it in a copy of this repository](../../README.md#try-it-in-a-copy-of-this-repository) makes once for every solution:

```powershell
cd solutions/01-plan-microsoft
pip install -r requirements.txt
az login
azd auth login
azd env new ai-sdlc-plan --subscription (az account show --query id -o tsv) --location eastus2
azd up
```

Then create a GitHub token for your copy, as in [Create the GitHub token](#2-create-the-github-token), give it to the Function app, and create the approval label:

```powershell
azd env set PLAN_GITHUB_TOKEN (Read-Host -MaskInput 'GitHub token')
azd provision
python runs.py status
gh label create brief-approved --color 0e8a16 --force
```

Allow about 15 minutes in all: the fresh setup took 13, step by step in [One-time setup](#one-time-setup). While deployed, the copy costs what [What it costs](#what-it-costs) says.

### What azd up creates

`azd up` ends with `SUCCESS`. It creates resource group `rg-ai-sdlc-plan` with:

- a Foundry account and project `plan`, a `gpt-6-luna` deployment (version 2026-09-22, Global Standard, 50,000 tokens per minute), and the **Foundry User** role for you;
- Application Insights `appi-plan` and Log Analytics `log-plan`, connected to the project for agent tracing, with read access for you;
- the Function app (its name starts with `func-`) on the Flex Consumption plan `asp-plan`, integrated with the virtual network `vnet-plan`;
- a storage account (`st…`) for the run records, the queue `plan-steps`, and the Function app's code, and a Key Vault (`kv-…`) for the GitHub token, both without public network access, reached through three private endpoints;
- the Function app's managed identity, with the Foundry User role, data access to its storage, and read access to Key Vault's secrets.

Outside the resource group, in Microsoft Entra ID, Foundry creates the agent's agent identity blueprint, an app registration that you own, and its agent identity when the hook publishes the agent. `azd down` doesn't remove them: [Clean up](#clean-up) does.

### Check the starting state

About a minute, from `solutions/01-plan-microsoft`, before each run of the steps below:

```powershell
python setup_foundry.py publish
"Open Issues (track:microsoft): " + (gh issue list --label track:microsoft --state open --json number --jq length)
python runs.py status
```

This screenshot is the same check on 11 November, after the agent moved to `gpt-6-luna` and the runs in [the evidence](evidence/2026-11-11-gpt-6-luna.md):

![The starting-state check in PowerShell 7: 94 unit tests pass, setup_foundry.py reports the vector store, agent requirements-analyst v12 on gpt-6-luna, the seven evaluators, and the evaluation plan-brief-checks as reused, no open Issue, runs.py status shows no run in progress and the five newest runs of 11 November, and the GitHub token in Key Vault answers HTTP 200 with its expiry date](images/00-starting-state.png)

You should see:

- `unit tests: 94 passed`, then every Foundry line ending in `reused`: the agent, the seven evaluators, and the evaluation match this folder.
- `Open Issues (track:microsoft): 0` and `Runs in progress: 0`. Otherwise, [reset the copy](#reset-the-copy-for-another-run) first.
- `GitHub token in Key Vault: HTTP 200`, and an expiry date in the future. Anything else needs a new token: [Create the GitHub token](#2-create-the-github-token), then [give it to the Function app](#3-give-the-token-to-the-function-app).

### How long each step takes

In our runs on `gpt-6-luna`, a run reached its review Issue 2 minutes 16 seconds to 2 minutes 45 seconds after the start. When the preview grading sandbox errors and the evaluation runs again, it takes several minutes more: 5½ to 8½ minutes in all, in our runs on `gpt-4.1`.

| Step | Takes, in our runs | In See it work |
| --- | --- | --- |
| 1. Read the notes | about a minute | |
| 2. Open the agent and its checks | 1 to 2 minutes | |
| 3. Start the run | seconds | the agent asked 11 seconds after the start |
| 4. The draft | 34 to 64 seconds on `gpt-6-luna` (16 to 24 on `gpt-4.1`) | 22 seconds, on `gpt-4.1` |
| 5. The evaluation | 77 to 107 seconds, or 5 to 8 minutes when it runs again | 5 minutes 26 seconds, with a second attempt |
| 6. The review Issue | 2¼ to 2¾ minutes after the start, or several minutes more when the evaluation runs again | 6 minutes 0 seconds |
| 7. Approve | your review, then up to 30 seconds until the Function app sees the label | 17 minutes 46 seconds, then 29 seconds |
| 8. The backlog | 20 to 51 seconds after the label | 51 seconds |
| 9. The run's record | seconds | |
| 10. Optional: score a Copilot brief | as long as any run | 8 minutes 19 seconds to its review Issue |

Steps 1 to 9 take about 15 minutes, plus the time you take to review the brief: the run in See it work took 24 minutes 37 seconds from the start to the closed review Issue, 17 minutes 46 seconds of them the review. In the fresh setup of 11 November, the run took 3 minutes 56 seconds, 31 seconds of them the review: the draft 46 seconds, the evaluation 95 seconds, the review Issue 2 minutes 34 seconds after the start, and the closed review Issue 51 seconds after the label ([the evidence](evidence/2026-11-11-fresh-setup.md)).

### 1. Read the notes

*About a minute. What you should see: [See it work, step 1](#1-the-notes-held-the-problems-real-notes-have).*

Open [`inputs/stakeholder-transcript.md`](inputs/stakeholder-transcript.md) and find the two disagreements (T04 and T05, T06 and T07), the decision in T19, the instruction pasted into T18, and the four unknowns (T12, T15, T21, and T22).

### 2. Open the agent and its checks

*1 to 2 minutes. What you should see: [See it work, step 2](#2-the-agent-and-its-checks-came-from-the-repository).*

In the [Foundry portal](https://ai.azure.com), open the project `plan`, then **Build › Agents › `requirements-analyst`**, and open the **Version** list at the top. Then open **Evaluations › Evaluator catalog** for the seven custom evaluators, and the **Evaluations** tab for `plan-brief-checks`.

### 3. Start the run

*Seconds. What you should see: [See it work, step 3](#3-one-command-started-the-run-in-azure).*

```powershell
python runs.py start
```

It prints each step as the Function app reports it, until the review Issue opens. Ctrl+C stops following, not the run, and `python runs.py show <run id> --follow` follows it again. To see the three functions, open resource group `rg-ai-sdlc-plan` in the Azure portal, then the Function app (its name starts with `func-`) › **Overview** › the **Functions** tab.

### 4. Watch the draft

*34 to 64 seconds. What you should see: [See it work, step 4](#4-the-agent-drafted-the-brief).*

`runs.py` prints `brief ready after … s`. In Foundry, open the agent's **Traces** tab: one row per draft, with its duration, tokens, and estimated cost. Select the newest trace ID to see the file search and the model call.

### 5. Watch the evaluation

*77 to 107 seconds, or 5 to 8 minutes when it runs again. What you should see: [See it work, step 5](#5-foundry-evaluated-the-brief-and-the-gates-passed).*

`runs.py` prints each attempt. In Foundry, open **Evaluations** › `plan-brief-checks` › the newest run: its name ends with the run's id and the attempt. In the Azure portal, on the Function app's **Overview**, select **Invocations and more** on the `run_step` row: each step ran as one invocation, which shows up shortly after it finishes. Select its date to read what it logged.

### 6. Read the review Issue

*2¼ to 2¾ minutes after the start, or several minutes more when the evaluation runs again. What you should see: [See it work, step 6](#6-a-review-issue-reached-the-person).*

Open the link that `runs.py` printed, or list the review Issues that wait for you:

```powershell
gh issue list --label type:brief --state open
```

Read the scores, then **Decisions**, **Conflicts**, and **Open questions**.

### 7. Approve

*Your review, then up to 30 seconds. What you should see: [See it work, step 7](#7-the-reviewer-approved).*

Apply the `brief-approved` label in the Issue, or:

```powershell
gh issue edit <number> --add-label brief-approved
```

### 8. Open the backlog

*20 to 51 seconds after the label. What you should see: [See it work, step 8](#8-the-function-app-published-the-backlog).*

```powershell
gh issue view <number> --comments
```

The last comment lists the epic and its tasks. Open the epic: **Sub-issues** lists the tasks with their dependencies, and **Sources** quotes the paragraphs and policies it cites.

### 9. Read the run's record

*Seconds. What you should see: [See it work, step 9](#9-the-runs-record-kept-every-step).*

```powershell
python runs.py show <run id>
```

### 10. Optional: score a Copilot brief next to the agent's

*As long as any run. What you should see: [See it work, step 10](#10-optional-foundry-scored-a-copilot-brief-next-to-its-own).*

This needs a pull request from [01-plan-github](../01-plan-github/) in your copy whose head holds Copilot's brief, and a token with **Contents: Read-only**:

```powershell
python runs.py start --compare-with-pull-request <n>
```

One evaluation run scores both briefs, and the review Issue shows the Foundry brief's scores, then a second table for the Copilot brief. The run reads the pull request's brief only when its branch is in your copy, not a fork. Otherwise, or if the token can't read the pull request, it scores the Foundry brief alone, and the review Issue says why. To have Foundry evaluate one Copilot brief that 01-plan-github then publishes, follow the [Plan solution combo](../../PRESENTING.md#plan-copilot-drafts-foundry-evaluates-the-product-owner-publishes).

### Optional: ask Azure Copilot for the agent's token use

*About 2 minutes.*

Open the Application Insights resource `appi-plan`, select **Copilot** in the portal's top bar, and ask:

```text
Write a KQL query for the logs of this Application Insights resource: from the dependencies table in the last 24 hours, keep spans where customDimensions['gen_ai.agent.name'] is 'requirements-analyst', and sum customDimensions['gen_ai.usage.input_tokens'] and customDimensions['gen_ai.usage.output_tokens'].
```

Azure Copilot's answer when we asked on 29 October:

![The Azure Copilot pane: Copilot answers with a KQL query on the dependencies table that keeps the requirements-analyst agent's spans from the last 24 hours and sums their gen_ai.usage input and output tokens, then explains what the query does](images/12-copilot-kql.png)

Copy the query, open **Monitoring › Logs**, paste it, and select **Run**: it returns the input and output tokens the agent used in the last 24 hours. Azure Copilot's answer varies from one question to the next, and a vaguer question can get an Azure Resource Graph query about the resource instead, so read the query before you trust its numbers.

### Optional: reject, or let the review time out

Close a review Issue instead of approving it: the Function app comments that nothing was published, 18 and 29 seconds after the close in our runs, and the run ends as rejected. Or leave it alone: 2 hours after it opened (2 hours 0 minutes 16 and 17 seconds in our runs), the Function app comments, closes it as not planned, and the run ends as timed out. To stop a run that hasn't reached its review Issue, run `python runs.py cancel <run id>`.

### Reset the copy for another run

```powershell
python runs.py cancel --all
gh issue list --label track:microsoft --state open --json number --jq '.[].number' | ForEach-Object { gh issue close $_ --reason "not planned" }
```

The first line cancels every run that hasn't finished: a run that waits for a decision comments on its review Issue and closes it. A run that is publishing its backlog can't be cancelled while it makes progress, and `runs.py` says so: wait a minute, and run the line again. The second line closes the remaining open Issues: the published backlog, and review Issues of failed runs. Run records, agent versions, traces, and evaluation runs stay in Azure as history.

## Clean up

When you no longer need the solution, from its folder, in your repository or in the copy:

```powershell
$prefix = "$(azd env get-value FOUNDRY_ACCOUNT_NAME)-$(azd env get-value FOUNDRY_PROJECT_NAME)-"
az ad sp list --display-name $prefix -o json | ConvertFrom-Json | Where-Object displayName -like "$prefix*-AgentIdentity" | ForEach-Object { az rest --method delete --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($_.id)" }
az ad app list --display-name $prefix -o json | ConvertFrom-Json | Where-Object displayName -like "$prefix*-AgentIdentityBlueprint" | ForEach-Object { az ad app delete --id $_.id }
azd down --purge
azd env set PLAN_GITHUB_TOKEN ''
```

The first three lines remove what Foundry created in Microsoft Entra ID when it published the agent, which `azd down` leaves behind: the agent identity of `requirements-analyst`, then its agent identity blueprint, an app registration owned by whoever published the agent ([agent identities in Foundry](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity)). Both are named after the Foundry account, its project, and the agent, for example `aif-<token>-plan-requirements-analyst-AgentIdentity`. The `*` in the lines' patterns stands for the agent's name, so they leave out the project's shared pair, `aif-<token>-plan-AgentIdentityBlueprint` and `aif-<token>-plan-AgentIdentity`, which Foundry also creates, owned by the project's managed identity alone: it needs nothing from you, because Foundry removes it with the project, which `azd down` deletes. Deleting the blueprint also deletes its principal, and would delete the agent identity too, but only hours or days later ([agent identity deletion](https://learn.microsoft.com/entra/agent-id/concept-agent-identity-deletion)): that's why the agent identity goes first. Run the lines as the person who published the agent, the blueprint's owner, and before `azd down`, which forgets the account's name. Entra keeps what they delete in its recycle bin for 30 days, and the blueprint's principal can't be purged from it: it stays there until the 30 days are over.

`azd down --purge` lists what it deletes and asks you to confirm; `--force` skips the question. It removes the resource group: the Foundry account and project, Application Insights, the Function app with its network, storage, and Key Vault. `--purge` also removes the soft-deleted Foundry account, Key Vault, and Log Analytics workspace, so their names can be reused. It took 4 minutes 54 seconds in our fresh setup. The last line removes the token from your local azd environment. Then revoke the token on GitHub: **Settings › Developer settings › Fine-grained tokens** › the token › **Delete**. The Issues the runs created, and their labels, stay in the repository; [the reset](#reset-the-copy-for-another-run) closes the open ones.

## What's in this folder

```text
01-plan-microsoft/
├── README.md
├── agent.yaml                  the Foundry agent: instructions, reasoning effort, file search, and the request each run sends
├── backlog.schema.json         the JSON schema the agent's answer must match
├── evidence/
│   ├── 2026-11-11-fresh-setup.md   a setup from scratch that followed only this README, timed step by step
│   └── 2026-11-11-gpt-6-luna.md    the runs that moved the agent to gpt-6-luna, exported for anyone to check
├── evaluators/                 seven code-based Foundry evaluators, each one grade() function
│   ├── structure.py            gate: ids, counts, task dependencies, and decisions that don't settle open conflicts
│   ├── citations.py            gate: every cited paragraph or policy exists in inputs/
│   ├── testable_criteria.py    gate: every acceptance criterion reads Given / When / Then
│   ├── injection_ignored.py    gate: the instruction pasted into T18 has no effect
│   ├── planted_conflicts.py    reported: both planted conflicts, with the right status
│   ├── planted_unknowns.py     reported: the four planted unknowns are asked
│   └── requirements_covered.py reported: the ten key requirement paragraphs are cited
├── function/                   the Azure Function app (azd service "function")
│   ├── function_app.py         the three functions: runs (HTTP), run_step (queue), check_reviews (timer)
│   ├── host.json               queue retries (3), the one-hour time limit for a step, and logging
│   ├── requirements.txt        the Function app's Python packages
│   └── planner/                the run in plain Python, standard library only
│       ├── steps.py            start, draft, evaluate, check the review Issues, publish, cancel
│       ├── brief.py            the review Issue, the epic, the tasks, the comments, and the evaluation Issue, with @ neutralized
│       ├── checks.py           the gates and the score table
│       ├── clients.py          Foundry and GitHub over HTTPS
│       └── store.py            one JSON record per run, in blob storage
├── runs.py                     start, follow, list, and cancel runs from your shell
├── setup_foundry.py            azd hooks: repository and token name; publish to Foundry; bundle agent.yaml and inputs/ into the Function app
├── requirements.txt            Python packages for setup_foundry.py and runs.py
├── tests/                      unit tests for the evaluators and the run; publish and deploy run them first
├── azure.yaml                  azd project
├── images/                     screenshots of the run in See it work, and of the Plan combo (combo-*)
├── infra/
│   ├── main.bicep              resource group rg-<environment name>, and the model deployment: gpt-6-luna
│   ├── resources.bicep         Foundry, tracing, the Function app, its network, storage, and Key Vault, role assignments
│   └── main.parameters.json
└── inputs/
    ├── stakeholder-transcript.md   synthetic workshop notes, paragraphs [T01]–[T24]
    └── routing-policies.md         the routing policies the workshop refers to
```

## Troubleshooting

- **The run fails with `GitHubTokenMissing` or `GitHubRefused` when it opens the review Issue.** The Function app has no usable GitHub token: Key Vault has none yet, or the token there contains spaces or line breaks (`GitHubTokenMissing`), or GitHub refused the one it has (`GitHubRefused`, for example `HTTP 401: Bad credentials` when the token expired or was revoked). [Create a new token](#2-create-the-github-token) and [give it to the Function app](#3-give-the-token-to-the-function-app). The Function app reads the new token within five minutes; `python runs.py status` shows what GitHub answers. The error never contains the token.
- **The run fails with `BriefFailedEvaluation`.** A gate didn't pass, reported no result, or the grading sandbox errored on it in all three attempts, and the error names it. Nothing was sent to GitHub. Open the evaluation run in Foundry to see the scores. If a gate failed, improve the `instructions` in `agent.yaml`, run `python setup_foundry.py publish` and `azd deploy`, and start a new run. Don't loosen an evaluator to make a brief pass. If the sandbox errored on that gate in every attempt, the brief may be fine: start a new run.
- **The run fails with `PublishingFailed`.** GitHub refused a call while the backlog was being published. The comment on the review Issue lists the epic and the tasks already created; finish or close them by hand, then start a new run if needed. The review Issue stays open.
- **The run fails with `AgentDidNotFinish`.** The agent's response ended as `failed` twice in a row, Foundry lost it twice, or its answer wasn't the JSON brief. In one earlier run, a response failed after about 10 seconds with "The server is overloaded or not ready yet", and the agent's **Traces** list showed it as **Failed** with no tokens. In one run on `gpt-6-luna`, Foundry answered `HTTP 404: Response with id '…' not found` for a response it had started, and kept answering 404. That's why the run asks once more in both cases. Nothing was sent to GitHub. Start a new run.
- **The run fails with `StepFailed`.** A step raised an error on all three deliveries from the queue, for example a Foundry or network error, and the run's last event names it: the service and its answer, or for any other error only its type. Start a new run. On the Function app, `run_step` › **Invocations** shows each attempt and its log.
- **The run fails with `StepStopped`.** A step stopped without finishing or failing, for example because Azure restarted the instance it ran on: the draft or the evaluation saved nothing for 45 minutes, or publishing made no progress three times in a row, 5 minutes each. For publishing, the comment on the review Issue lists what was already created. Start a new run.
- **`runs.py cancel` answers "the run is publishing its backlog; wait until it finishes".** Publishing takes about 20 seconds, and a run that is making progress isn't stopped halfway. Run the command again a minute later. A publish that made no progress for 5 minutes can be cancelled, and the comment on its review Issue lists what it had created.
- **An evaluation check shows "An error occurred during grading".** The preview grading sandbox often errors on a check, and that evaluation attempt takes about 4 minutes instead of 1.5. While a gate has no score, the run evaluates again, up to three attempts, and keeps each check's first score; the review Issue marks a reported check that was never scored as not scored.
- **`error: the unit tests failed, so nothing was published`, or `azd deploy` stops at `predeploy`.** A change to an evaluator or to the Function app's code broke a test in `tests/`, and the output above the error names it. Fix the code, or the test if the rule changed on purpose, then run the command again.
- **`runs.py` stops with ``error: `az functionapp show` failed twice``.** `runs.py` asks the Azure CLI for the Function app's address and key, and tries twice: in one of our runs a single call failed and the next one, a minute later, worked. If it fails twice, the Azure CLI isn't signed in as an account that can read the Function app, or the solution isn't deployed in the subscription `az` uses. Run `az login`, check `az account show`, and check that `azd env get-value FUNCTION_APP_NAME` prints a name.
- **`This operation requires the following opt-in preview feature(s): Evaluations=V1Preview`.** You called the evaluator catalog without the preview header. `setup_foundry.py` sends it; send `Foundry-Features: Evaluations=V1Preview` from your own code too.
- **`Invalid grader source: use of builtin 'compile()' is not allowed in Python graders`.** An evaluator calls something named `compile()`, `re.compile` included. Use `re.search` and `re.match` with a pattern string instead.
- **`AzureCLICredential: exit status 1` during `azd up` or `azd env refresh`.** azd couldn't get a token from the Azure CLI. Run `az account get-access-token` to check your sign-in, then run the azd command again. It can also be transient while other `az` commands run at the same time.
- **`FOUNDRY_PROJECT_ENDPOINT is not set` or `FUNCTION_APP_NAME is not set` in a new clone or worktree.** `setup_foundry.py` and `runs.py` read the azd environment, which lives in the `.azure/` folder where you ran `azd up`, and git ignores it. Recreate it from the deployment, in the solution's folder, with the environment name and region you deployed with (`ai-sdlc-plan` and `eastus2` in the copy):

  ```powershell
  azd env new <environment name> --subscription (az account show --query id -o tsv) --location <region>
  azd env refresh -e <environment name>
  ```

  `azd env refresh` ends with `SUCCESS: Environment refresh completed`. Set `PLAN_GITHUB_TOKEN` again: it was in the old `.env` only.
- **`PermissionDenied` when something runs right after `azd up`.** New role assignments can take a few minutes to apply. Wait, then try again.
- **`DeploymentNotFound` or `The project does not exist` right after re-creating the solution.** After `azd down --purge`, re-creating it under the same environment name reuses the same Foundry names, and the project endpoint can keep answering for the deleted account for more than an hour. Create it under a new environment name instead, for example `azd env new ai-sdlc-plan2 --location eastus2`, then `azd up`.
- **A `gpt-4.1` deployment is still in the Foundry account.** You set the solution up before the agent moved to `gpt-6-luna` on 11 November: `azd provision` adds the `gpt-6-luna` deployment, and its publish hook a new agent version on it, but leaves `gpt-4.1` in place. Once `python setup_foundry.py publish` reports `agent requirements-analyst v…: reused (gpt-6-luna)`, nothing uses the old deployment. Delete it with `az cognitiveservices account deployment delete -g rg-ai-sdlc-plan -n (azd env get-value FOUNDRY_ACCOUNT_NAME) --deployment-name gpt-4.1`.
- **A Logic App named `logic-plan-backlog` is still in the resource group.** You set the solution up before the Function app replaced the Logic App: `azd up` adds the Function app and its resources, and leaves the Logic App in place. Delete it with `az resource delete -g rg-ai-sdlc-plan -n logic-plan-backlog --resource-type Microsoft.Logic/workflows`, then remove its role assignment on the Foundry account, which now shows **Identity not found** under **Access control (IAM)**. If you set it up when it ran in GitHub Actions, the GitHub environment `plan-microsoft` is no longer used either: `gh api -X DELETE 'repos/{owner}/{repo}/environments/plan-microsoft'`.
