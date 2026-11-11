# What Azure recorded during the run in See it work

The records behind the numbers in the README's [See it work](../README.md#see-it-work), for anyone who can't sign in to the Azure or Foundry portal. They were exported on 11 November 2026 with the read-only queries in [How these records were exported](#how-these-records-were-exported). Application Insights provided the Function's log lines, its invocations, and the agent's spans; the Foundry evaluation API provided the evaluation. Times are UTC.

Each section lists the records of one run. GitHub's delivery ids are replaced with `<delivery>`; nothing else is changed. A GitHub event's time comes from GitHub, and the Function logs a step after GitHub's API answers, so its lines come about a second after GitHub's time for the same event.

## The code that ran

- **The standards run, on 31 October**, ran a working version of the code in pull request [#244](https://github.com/melabadi/adept-assessment-northstars/pull/244), deployed with `azd deploy` at 23:14.
- **The advisor run, on 1 November**, ran the code deployed at 00:24. Its `function/` folder is the one in #244's final commit [`eef52f1`](https://github.com/melabadi/adept-assessment-northstars/tree/eef52f1418038b33164b689d39b81c6fc9e2fff1/solutions/02-design-microsoft/function), which merged as `786e099`.
- **The agents** were `architecture-advisor-small-team` and `architecture-advisor-enterprise`, version 2 each, published from [`agent.yaml`](../agent.yaml) before these runs. The standards run kept them, because `agent.yaml` hadn't changed.
- **The evaluators** were version 4 of the five code-based evaluators, which embed the gate's checks as they were then.

## The standards run

Pull request [#238](https://github.com/melabadi/adept-assessment-northstars/pull/238) merged at 23:23:48 on 31 October as commit [`74e59ec`](https://github.com/melabadi/adept-assessment-northstars/commit/1baf5004d0cc6a447b5163649359b1b77d1c8d61). It added the keyword *Application Insights* to STD-OBS-001.

| Time | Record |
| --- | --- |
| 23:23:50.104 | The webhook received GitHub's push delivery and answered HTTP 202 in 242 ms. |
| 23:23:50.346 | `standards run 0f62ae9e0177: 74e59ec queued (push to the default branch, 1 file(s) in the solution)` |
| 23:23:59.915 | The queue function `publish_standards` started. It ran for 11.9 seconds and succeeded. |
| 23:24:01.640 | `standards run 0f62ae9e0177: 74e59ec is on main; 1 changed file(s) in the solution` |
| 23:24:04.275 | `standards run 0f62ae9e0177: re-indexed architecture-standards: 12 standards (0 new, 1 changed, 0 removed, 0 failed)` |
| 23:24:06.666 | `standards run 0f62ae9e0177: agents architecture-advisor-small-team v2 (reused), architecture-advisor-enterprise v2 (reused)` |
| 23:24:11.763 | `standards run 0f62ae9e0177: evaluation started in Foundry: 2 run(s), 10 case(s); done in 12 s` |

## The evaluation

The standards run started two Foundry evaluation runs, one per operating profile, on the ten labelled cases in [`eval_cases.jsonl` as of `74e59ec`](https://github.com/melabadi/adept-assessment-northstars/blob/1baf5004d0cc6a447b5163649359b1b77d1c8d61/solutions/02-design-microsoft/eval_cases.jsonl). In Foundry they are under the evaluation that was created on 29 October and is now named *Architecture advisor · labelled cases (earlier evaluators)*: when newer evaluator versions were registered on 10 November, it was renamed.

| Run | Started | Results recorded | Cases passed | Checks passed | Checks not graded |
| --- | --- | --- | --- | --- | --- |
| `architecture-advisor-small-team v2 · commit 74e59ec` (`evalrun_a8f45fc33f2f43cc9eac562ef05c2fbe`) | 23:24:10 | 23:26:27 | 5 of 5 | 25 of 25 | 0 |
| `architecture-advisor-enterprise v2 · commit 74e59ec` (`evalrun_454dc78da1d844049e752badce417615`) | 23:24:11 | 23:30:34 | 5 of 5 | 25 of 25 | 0 |

Every case passed all five checks: citations, access, grounding, abstention, and conflicts. What each case expected, and what its answer took:

| Case | Profile | Question | Expected | Answer took | Tokens in, out |
| --- | --- | --- | --- | --- | --- |
| E01 | small-team | Should the live AI triage provider run inside the existing RequestHub API behind ITriageProvider, or as a new separate service? | cites STD-ARCH-001 and STD-OPS-001, never STD-OPS-002 | 9.4 s | 2,123, 1,715 |
| E02 | enterprise | How should RequestHub call the model endpoint for live triage in production? | cites STD-OPS-002, never STD-OPS-001 | 13.6 s | 4,305, 1,903 |
| E03 | small-team | How should the RequestHub API authenticate to Microsoft Foundry and PostgreSQL? | cites STD-SEC-001 | 9.1 s | 2,871, 1,195 |
| E04 | enterprise | Which request fields may we send to the AI model, and can we include attachments? | cites STD-SEC-002 | 12.1 s | 3,000, 1,841 |
| E05 | small-team | Can the triage agent approve low-risk requests automatically when its confidence is above 95%? | cites STD-AI-001 | 10.9 s | 2,707, 1,512 |
| E06 | enterprise | What telemetry and evaluation evidence must the AI triage feature produce before release? | cites STD-AI-002 and STD-OBS-001 | 12.6 s | 3,262, 1,975 |
| E07 | small-team | Should we store the full prompts and model responses of triage calls so we can troubleshoot bad recommendations? | cites STD-OBS-002 and STD-SEC-002, and flags their conflict | 12.2 s | 3,917, 1,476 |
| E08 | enterprise | What is the approved monthly budget ceiling for Foundry token spend for RequestHub? | abstains: no standard sets a budget | 260.8 s | 1,566, 317 |
| E09 | small-team | How long must we keep AI triage recommendations? | cites STD-DATA-002, never STD-DATA-001 | 7.6 s | 1,936, 902 |
| E10 | enterprise | Can we rename the recommendation fields in the RequestHub API response to make them clearer? | cites STD-API-001 | 14.2 s | 3,648, 980 |

The ten answers used 29,335 input and 13,816 output tokens. The enterprise run's results waited for E08, whose answer took 260.8 seconds; the other nine took 7.6 to 14.2 seconds.

## The advisor run

The operator filed Issue [#242](https://github.com/melabadi/adept-assessment-northstars/issues/242) at 00:42:01 on 1 November, with the labels `ai-sdlc`, `phase:design`, and `design-advisor`. GitHub sent one delivery for the new Issue and one for each label.

| Time | Record |
| --- | --- |
| 00:42:04.150 | The webhook received the `issues.opened` delivery and answered HTTP 200 in 380 ms. |
| 00:42:04.529 | `delivery <delivery> (issues) ignored: issues.opened is not the design-advisor label being added` |
| 00:42:06.929 and 00:42:06.985 | The webhook received two `issues.labeled` deliveries and answered HTTP 200 in 1,217 and 1,242 ms. |
| 00:42:07.170 | The webhook received the `issues.labeled` delivery for `design-advisor` and answered HTTP 202 in 1,567 ms. |
| 00:42:08.143 and 00:42:08.224 | `delivery <delivery> (issues) ignored: issues.labeled is not the design-advisor label being added`, twice |
| 00:42:08.734 | `advisor run d8edae524e0e: #242 queued (issues.labeled, small-team profile)` |
| 00:42:13.740 | The queue function `advise` started. It ran for 20.7 seconds and succeeded. |
| 00:42:26.255 | `advisor run d8edae524e0e: #242 asked architecture-advisor-small-team v2: completed in 12 s` |
| 00:42:28.710 | `advisor run d8edae524e0e: #242 the gate passed the answer: 8 standard(s) cited, 8 retrieved, all in the small-team scope` |
| 00:42:30.881 | `advisor run d8edae524e0e: #242 branch design/advisor-issue-242 created` |
| 00:42:32.150 | The webhook received a push delivery for the advisor's branch and answered HTTP 200 in 84 ms. |
| 00:42:32.231 | `delivery <delivery> (push) ignored: not a push to the default branch` |
| 00:42:32.232 | `advisor run d8edae524e0e: #242 ADR draft committed at b3d0e0f` |
| 00:42:33.369 | The webhook received a second push delivery for the advisor's branch and answered HTTP 200 in 61 ms. |
| 00:42:33.429 | `delivery <delivery> (push) ignored: not a push to the default branch` |
| 00:42:33.486 | `advisor run d8edae524e0e: #242 pull request #243 opened` |
| 00:42:34.297 | `advisor run d8edae524e0e: #242 commented the answer; done in 20 s` |

On GitHub, the ADR draft's commit [`b3d0e0f`](https://github.com/melabadi/adept-assessment-northstars/commit/b3d0e0f819e52ac62d254d2fe983311934d02ad0) is dated 00:42:31, pull request [#243](https://github.com/melabadi/adept-assessment-northstars/pull/243) was opened at 00:42:32, and [the advisor's comment](https://github.com/melabadi/adept-assessment-northstars/issues/242#issuecomment-6551311653) is dated 00:42:33: 32 seconds after the Issue.

## The agent's trace

Application Insights, connected to the Foundry project, recorded the agent run as spans of response `resp_0a49f2eb8c636a19006ae68ae7a6648195b6b45e5ae7e95d8c`, agent version 2:

| Started | Span | Took | Tokens in, out |
| --- | --- | --- | --- |
| 00:42:16.283 | `invoke_agent architecture-advisor-small-team:2` | 9.7 s | |
| 00:42:16.641 | `execute_tool mcp_standards.knowledge_base_retrieve` | 1.5 s | |
| 00:42:18.636 | `execute_tool mcp_standards.knowledge_base_retrieve` | 1.4 s | |
| 00:42:21.076 | `chat gpt-5.4-mini-2026-03-17` | 4.4 s | 3,443, 1,577 |

## How these records were exported

From the solution folder, signed in with read access to the solution's Application Insights resource and Foundry project. Application Insights searches only the last hour unless you widen the search with `--offset`, so each query names its own window and the command widens the search to 260 hours. Save a query in a file, then run it:

```powershell
$query = Join-Path $env:TEMP "evidence.kql"
# Save one of the queries below in $query, then:
az monitor app-insights query --app (azd env get-value APPLICATIONINSIGHTS_NAME) -g (azd env get-value AZURE_RESOURCE_GROUP) `
  --analytics-query "@$query" --offset 260h --query "tables[0].rows" -o tsv
```

The log lines of the advisor run:

```kusto
traces
| where timestamp between (datetime(2026-11-01T00:41:50Z) .. datetime(2026-11-01T00:43:00Z))
| where message startswith "advisor run " or message startswith "delivery "
| project timestamp, message
| order by timestamp asc
```

For the standards run, use the window from `2026-10-31T23:23:30Z` to `2026-10-31T23:31:00Z`, with `"standards run "` in place of `"advisor run "`.

The Function's invocations:

```kusto
requests
| where timestamp between (datetime(2026-10-31T23:23:30Z) .. datetime(2026-10-31T23:25:00Z))
     or timestamp between (datetime(2026-11-01T00:41:50Z) .. datetime(2026-11-01T00:43:00Z))
| project timestamp, name, duration, success, resultCode
| order by timestamp asc
```

The agent's spans:

```kusto
dependencies
| where timestamp between (datetime(2026-11-01T00:42:08Z) .. datetime(2026-11-01T00:42:30Z))
| where name startswith "invoke_agent" or name startswith "chat " or name startswith "execute_tool"
| extend dims = todynamic(customDimensions)
| project timestamp, name, duration,
    inputTokens = tostring(dims["gen_ai.usage.input_tokens"]), outputTokens = tostring(dims["gen_ai.usage.output_tokens"])
| order by timestamp asc
```

The evaluation, from the Foundry project's evaluation API with the `azure-ai-projects` package that [`evaluate.py`](../evaluate.py) uses. Replace `<FOUNDRY_PROJECT_ENDPOINT>` with the value of `azd env get-value FOUNDRY_PROJECT_ENDPOINT`. The latency and token usage of each answer are in the same output items, under `sample`.

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(endpoint="<FOUNDRY_PROJECT_ENDPOINT>", credential=DefaultAzureCredential())
openai = project.get_openai_client()
for evaluation in openai.evals.list(limit=100):
    if evaluation.name.startswith("Architecture advisor · labelled cases"):
        for run in openai.evals.runs.list(eval_id=evaluation.id, limit=100):
            if "commit 74e59ec" in run.name:
                for item in openai.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id):
                    print(run.name, item.datasource_item["id"], [(r.name, r.passed) for r in item.results])
```
