# The switch to gpt-6.1-sol, on 11 November 2026

The records behind what the README says about the model the advisor runs today and what it costs, for anyone who can't sign in to the Azure or Foundry portal. On 11 November 2026, the agents moved from `gpt-5.4-mini` to a newer model, in the same resource group as [See it work](../README.md#see-it-work). `gpt-6-luna` was tried first and failed a labelled case in both of its evaluations; `gpt-6.1-sol` passed every case, so it became the default. Later that day, case E02 was given one more claim, both models were evaluated again, and `gpt-6-luna` became the default: see [Case E02's added claim and the model choice](2026-11-11-e02-claim.md). Times are UTC. The records were exported the same day with the read-only queries in [How these records were exported](#how-these-records-were-exported).

## What changed

- **The model:** `gpt-6.1-sol` version 2026-09-29, Global Standard, 250,000 tokens per minute, in East US 2 ([`infra/main.bicep`](../infra/main.bicep)), instead of `gpt-5.4-mini` version 2026-03-17. Azure lists its retirement for inference on 11 March 2028.
- **The agents:** version 5 of `architecture-advisor-small-team` and `architecture-advisor-enterprise`. They differ from version 2, which answered in See it work, only in the model: the same instructions, reasoning effort (`low`), knowledge base, and output schema.
- **The evaluation:** the same checks, in version 7 of the five code-based evaluators. Their criteria name the model deployment, so the evaluation *Architecture advisor · labelled cases* is now created again for a new deployment, and the one it replaces keeps its runs under a name that gives its model, such as *Architecture advisor · labelled cases (earlier model gpt-6-luna)*. The evaluation that holds the morning's `gpt-5.4-mini` runs was renamed *(earlier evaluators)* before this naming existed.
- **The Python packages:** `azure-ai-projects` 2.10.0, `azure-identity` 1.27.0, `azure-search-documents` 12.1.0, `openai` 3.45.0, and, for the Function on Python 3.12, `azure-functions` 1.26.0 ([`function/requirements.txt`](../function/requirements.txt)).

## The order of events

| Time | What happened |
| --- | --- |
| 05:17:50 | `python evaluate.py` on `gpt-5.4-mini`, agents version 2: 10 of 10 cases passed on the first attempt, in 169 seconds. The comparison. |
| 14:22:45 | `azd provision` created the `gpt-6-luna` deployment (version 2026-09-22) and published agents version 3 on it, in 1 minute 51 seconds. |
| 14:26:21 | `azd deploy` deployed the Function's code in 39 seconds. |
| 14:29:25 | The `gpt-5.4-mini` deployment was deleted. |
| 14:29:53 | `python evaluate.py` on `gpt-6-luna`: 9 of 10, in 225 seconds. E02 failed grounding. |
| 14:37:01 | Agents version 4: one instruction added, to name each required component, path, or control in the words of the standard that requires it. |
| 14:37:14 | `python evaluate.py` on version 4: 8 of 10, in 210 seconds. E02 and E04 failed grounding. The instruction was removed again. |
| 14:44:01 | `azd provision` with `gpt-6.1-sol` created its deployment and published agents version 5 on it, in 1 minute 56 seconds. |
| 14:47:50 | `python evaluate.py` on `gpt-6.1-sol`: 10 of 10 on the first attempt, in 291 seconds. |
| 14:52:58 | `python evaluate.py --held-out` on `gpt-6.1-sol`: 6 of 6 on the first attempt, in 190 seconds. |
| 15:00:15 | The `gpt-6-luna` deployment was deleted. |
| 15:00:43 | `azd deploy` deployed the Function's final code in 35 seconds; the deployment finished at 15:01:32. |
| 15:02:40 | Issue [#355](https://github.com/melabadi/adept-assessment-northstars/issues/355) asked the question of See it work again; [the live answer](#the-live-answer) came 72 seconds later. |
| 15:09:00 | `python evaluate.py --local` on `gpt-6.1-sol`: 10 of 10, in 430 seconds. |

## The evaluations

Each `python evaluate.py` started one Foundry evaluation run per operating profile, on the ten labelled cases in [`eval_cases.jsonl`](../eval_cases.jsonl), or with `--held-out` on the six in [`eval_heldout.jsonl`](../eval_heldout.jsonl). Every run used the same checks and labels, Foundry graded every check, and `evaluate.py` started no run again. The `gpt-5.4-mini` held-out runs are from 10 November, with the same agents and evaluators.

| Run | Run id | Started | Model | Cases passed |
| --- | --- | --- | --- | --- |
| `architecture-advisor-small-team v2 · evaluate.py` | `evalrun_7a716886fb7b4b419888415c168438cb` | 11 Nov 05:18:19 | `gpt-5.4-mini` | 5 of 5 |
| `architecture-advisor-enterprise v2 · evaluate.py` | `evalrun_f79eac2f9fb04c78902f0dcf87b4a6e2` | 11 Nov 05:18:20 | `gpt-5.4-mini` | 5 of 5 |
| `architecture-advisor-small-team v2 · evaluate.py, held-out` | `evalrun_16a5180cfa9340c7885d6a587bec3630` | 10 Nov 03:24:16 | `gpt-5.4-mini` | 2 of 3 |
| `architecture-advisor-enterprise v2 · evaluate.py, held-out` | `evalrun_9d0868da09c040618dc46c506eafd256` | 10 Nov 03:24:17 | `gpt-5.4-mini` | 3 of 3 |
| `architecture-advisor-small-team v3 · evaluate.py` | `evalrun_76b38a6342e94992b626519df7a7089e` | 11 Nov 14:30:11 | `gpt-6-luna` | 5 of 5 |
| `architecture-advisor-enterprise v3 · evaluate.py` | `evalrun_b36c7516390146018184954c4b216bab` | 11 Nov 14:30:12 | `gpt-6-luna` | 4 of 5 |
| `architecture-advisor-small-team v4 · evaluate.py` | `evalrun_ef55ee836163450fb00e8bbc2ff45b82` | 11 Nov 14:37:31 | `gpt-6-luna` | 5 of 5 |
| `architecture-advisor-enterprise v4 · evaluate.py` | `evalrun_a8fea5390618422d938a2d5f96b6d571` | 11 Nov 14:37:32 | `gpt-6-luna` | 3 of 5 |
| `architecture-advisor-small-team v5 · evaluate.py` | `evalrun_8abebdadc53b44799537cebb1438fb21` | 11 Nov 14:48:09 | `gpt-6.1-sol` | 5 of 5 |
| `architecture-advisor-enterprise v5 · evaluate.py` | `evalrun_788146f5e9c040eaa8b5b997177d158a` | 11 Nov 14:48:09 | `gpt-6.1-sol` | 5 of 5 |
| `architecture-advisor-small-team v5 · evaluate.py, held-out` | `evalrun_4239c15381a14344abad2eb5b09f197a` | 11 Nov 14:53:11 | `gpt-6.1-sol` | 3 of 3 |
| `architecture-advisor-enterprise v5 · evaluate.py, held-out` | `evalrun_aa737723257b448ab8d41566f4539e43` | 11 Nov 14:53:12 | `gpt-6.1-sol` | 3 of 3 |

Each case's result, with how long its answer took:

| Case | `gpt-5.4-mini`, v2 | `gpt-6-luna`, v3 | `gpt-6-luna`, v4 | `gpt-6.1-sol`, v5 |
| --- | --- | --- | --- | --- |
| E01 | passed, 11.4 s | passed, 26.3 s | passed, 24.6 s | passed, 51.5 s |
| E02 | passed, 16.2 s | **failed grounding**, 24.6 s | **failed grounding**, 24.9 s | passed, 53.4 s |
| E03 | passed, 11.4 s | passed, 20.2 s | passed, 17.2 s | passed, 42.7 s |
| E04 | passed, 9.0 s | passed, 24.5 s | **failed grounding**, 21.9 s | passed, 42.9 s |
| E05 | passed, 6.4 s | passed, 21.3 s | passed, 21.5 s | passed, 40.3 s |
| E06 | passed, 12.4 s | passed, 22.3 s | passed, 21.5 s | passed, 42.2 s |
| E07 | passed, 12.4 s | passed, 20.2 s | passed, 18.7 s | passed, 36.1 s |
| E08 | passed, 8.7 s | passed, 13.2 s | passed, 12.4 s | passed, 13.4 s |
| E09 | passed, 10.4 s | passed, 13.4 s | passed, 15.5 s | passed, 19.2 s |
| E10 | passed, 7.8 s | passed, 12.2 s | passed, 19.7 s | passed, 24.4 s |
| H01 | passed, 6.6 s | | | passed, 35.5 s |
| H02 | passed, 8.6 s | | | passed, 46.5 s |
| H03 | passed, 7.9 s | | | passed, 24.0 s |
| H04 | passed, 8.3 s | | | passed, 22.7 s |
| H05 | passed, 10.8 s | | | passed, 39.7 s |
| H06 | **failed grounding**, 10.7 s | | | passed, 36.2 s |

The `gpt-6.1-sol` answers' tokens:

| Case | Profile | Answer took | Tokens in (cached), out |
| --- | --- | --- | --- |
| E01 | small-team | 51.5 s | 3,384 (0), 3,062 |
| E03 | small-team | 42.7 s | 2,501 (1,158), 2,243 |
| E05 | small-team | 40.3 s | 3,249 (1,158), 2,485 |
| E07 | small-team | 36.1 s | 3,158 (1,158), 1,940 |
| E09 | small-team | 19.2 s | 2,968 (1,158), 901 |
| E02 | enterprise | 53.4 s | 3,670 (0), 2,960 |
| E04 | enterprise | 42.9 s | 3,675 (1,157), 2,568 |
| E06 | enterprise | 42.2 s | 3,938 (1,157), 2,406 |
| E08 | enterprise | 13.4 s | 2,467 (1,157), 372 |
| E10 | enterprise | 24.4 s | 3,401 (1,157), 1,147 |
| H02 | small-team | 46.5 s | 2,889 (1,158), 2,581 |
| H04 | small-team | 22.7 s | 3,651 (1,158), 980 |
| H06 | small-team | 36.2 s | 2,850 (1,158), 2,051 |
| H01 | enterprise | 35.5 s | 3,410 (1,157), 1,909 |
| H03 | enterprise | 24.0 s | 3,630 (1,157), 1,058 |
| H05 | enterprise | 39.7 s | 3,551 (1,157), 2,382 |

## Why gpt-6-luna failed

Each failed answer passed the gate: every citation existed, was in the profile's scope, had the indexed version, and quoted its standard word for word. Each failed grounding because its summary and recommendation didn't state the conclusion its case requires in words the check accepts. The check looks for a claim's words in order, within one clause, with at most three other words between one and the next (`conclusion_misses` in [`checks.py`](../function/advisor_core/checks.py)).

- **E02, version 3.** The question: *How should RequestHub call the model endpoint for live triage in production?* The answer must state one of `through* gateway`, `via* gateway`, `gateway path`, `use* gateway`, or `behind* gateway`. The recommendation said *"the provider calling the Foundry model endpoint through the central Azure API Management AI gateway"*, where six words separate *through* from *gateway*, and the summary said *"route calls through Azure API Management"*, without *gateway*.
- **E02, version 4.** The summary said *"have the API call the Foundry model endpoint through Azure API Management, the central AI gateway—not directly"*: the comma ends the clause before *gateway*. The recommendation said *"through Azure API Management"*, without *gateway*.
- **E04, version 4.** The question: *Which request fields may we send to the AI model, and can we include attachments?* The answer must state one of `only* field*`, `minimal* payload`, `minimum* field*`, `minimal* field*`, or `minimum* payload`. The summary said *"send only fields the use case needs and exclude personal data"*: *exclude* is one of the words that negate a clause, so the check read the clause as denying *only fields*. The recommendation asked for *"a use-case-specific set of necessary, non-personal fields"*.

Neither the checks nor the labels were changed to let a model pass. Later that day, after the same miss on `gpt-6.1-sol`, E02 also accepted `through* api management`, once that was shown to pass no wrong answer. With it, `gpt-6-luna` passed all ten labelled cases and became the default: see [Case E02's added claim and the model choice](2026-11-11-e02-claim.md).

## The live answer

Issue [#355](https://github.com/melabadi/adept-assessment-northstars/issues/355) asked the question of See it work again, with the small-team profile, at 15:02:40. The Function ran the code deployed at 15:00:43. The Function's log lines for the advisor run, and its invocations:

| Time | Record |
| --- | --- |
| 15:02:43.993 | The webhook received the `issues.labeled` delivery for `design-advisor` and answered HTTP 202 in 557 ms. |
| 15:02:44.548 | `advisor run ec10099c9a44: #355 queued (issues.labeled, small-team profile)` |
| 15:02:56.444 | The queue function `advise` started. It ran for 56.7 seconds and succeeded. |
| 15:03:45.197 | `advisor run ec10099c9a44: #355 asked architecture-advisor-small-team v5: completed in 48 s` |
| 15:03:47.323 | `advisor run ec10099c9a44: #355 the gate passed the answer: 9 standard(s) cited, 9 retrieved, all in the small-team scope` |
| 15:03:49.656 | `advisor run ec10099c9a44: #355 branch design/advisor-issue-355 created` |
| 15:03:50.780 | `advisor run ec10099c9a44: #355 ADR draft committed at 3499905` |
| 15:03:52.173 | `advisor run ec10099c9a44: #355 pull request #357 opened` |
| 15:03:53.001 | `advisor run ec10099c9a44: #355 commented the answer; done in 56 s` |

The Function also logged the deliveries it ignored: the Issue's other events and pushes to branches other than the default branch.

On GitHub, the ADR draft's commit [`3499905`](https://github.com/melabadi/adept-assessment-northstars/commit/3499905cb9d2c23633843a8d53372637f76e9d08) is dated 15:03:50, pull request [#357](https://github.com/melabadi/adept-assessment-northstars/pull/357) was opened at 15:03:51, and [the advisor's comment](https://github.com/melabadi/adept-assessment-northstars/issues/355#issuecomment-6799337560) is dated 15:03:52: 72 seconds after the Issue. Like the answer in See it work, it recommends extending the existing API behind `ITriageProvider`, with STD-ARCH-001 tipping the balance and STD-OPS-001 reinforcing it, and leaves the conflict between STD-SEC-002 and STD-OBS-002 to an architect. It cited nine standards. Pull request #357 was closed unmerged at 15:06, and the Issue as not planned.

Application Insights recorded the agent run as spans of response `resp_08aa75b8e5513e8a006af483a24c5481939915775457782e8b`, agent version 5:

| Started | Span | Took | Tokens in, out |
| --- | --- | --- | --- |
| 15:02:58.792 | `invoke_agent architecture-advisor-small-team:5` | 46.2 s | |
| 15:03:00.536 | `execute_tool mcp_standards.knowledge_base_retrieve` | 3.7 s | |
| 15:03:04.189 | `execute_tool mcp_standards.knowledge_base_retrieve` | 2.6 s | |
| 15:03:08.698 | `chat gpt-6-astra-minor-2026-09-29` | 36.1 s | 3,533, 3,014 |

The model call's span names the model `gpt-6-astra-minor-2026-09-29`, as the Foundry Agent Service reported it; the deployment, the response, and the evaluation name it `gpt-6.1-sol`, version 2026-09-29. The response records 3,533 input tokens, 1,188 of them cached, and 3,121 output tokens, 62 of them for reasoning. Azure Monitor's token counts for the deployment in that five-minute interval are the same 3,533 and 3,121.

## The fallback evaluation

`python evaluate.py --local`, started at 15:09:00, asked agents version 5 the ten labelled questions one at a time and scored the answers on this machine with the same checks. All ten passed, in 430 seconds, with 20.9 to 55.0 seconds per answer. Azure Monitor counted 10 requests to the deployment from 15:10 to 15:20, with 33,909 input and 20,573 output tokens.

## Cost

Azure's retail prices for Global Standard deployments in East US 2, per million tokens, from the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) on 11 November 2026:

| Model | Input | Cached input | Output |
| --- | --- | --- | --- |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |
| `gpt-6-luna` | $0.10 | $0.01 | $0.50 |
| `gpt-6.1-sol` | $2.00 | $0.10 | $10.00 |

What the runs above cost at these prices: input tokens that weren't cached at the input price, cached ones at the cached-input price, and output tokens at the output price.

| Runs | Answers | Tokens in (cached), out | Cost | Per answer |
| --- | --- | --- | --- | --- |
| `gpt-5.4-mini`, labelled cases, 05:18 | 10 | 31,091 (0), 14,239 | $0.087 | $0.0087 |
| `gpt-6-luna`, version 3, labelled cases | 10 | 32,976 (9,260), 14,903 | $0.0099 | $0.0010 |
| `gpt-6-luna`, version 4, labelled cases | 10 | 33,343 (9,564), 15,989 | $0.0105 | $0.0010 |
| `gpt-6.1-sol`, labelled cases | 10 | 32,411 (9,260), 20,084 | $0.248 | $0.025 |
| `gpt-6.1-sol`, held-out cases | 6 | 19,981 (6,945), 10,961 | $0.136 | $0.023 |
| `gpt-6.1-sol`, the answer to #355 | 1 | 3,533 (1,188), 3,121 | $0.036 | $0.036 |
| `gpt-6.1-sol`, `--local` | 10 | 33,909 (not reported), 20,573 | at most $0.274 | at most $0.028 |

Of the sixteen `gpt-6.1-sol` answers in Foundry's evaluations, the cheapest, E08's abstention, cost $0.0065, and the most expensive, E01's, $0.037. Azure Monitor's estimated cost for the `gpt-6-luna` deployment was $0.00998 and $0.01053 for its two evaluations, within $0.0001 of the figures above. It reported no estimated cost for `gpt-6.1-sol` by the time of export, but its token counts for that deployment from 14:45 to 15:05, 55,925 input and 34,166 output, equal the sum of the labelled, held-out, and #355 rows.

## How these records were exported

From the solution folder, signed in with read access to the solution's Application Insights resource, Foundry account, and Foundry project. Application Insights searches only the last hour unless you widen the search with `--offset`, so each query names its own window. Save a query in a file, then run it:

```powershell
$query = Join-Path $env:TEMP "evidence.kql"
# Save one of the queries below in $query, then:
az monitor app-insights query --app (azd env get-value APPLICATIONINSIGHTS_NAME) -g (azd env get-value AZURE_RESOURCE_GROUP) `
  --analytics-query "@$query" --offset 24h --query "tables[0].rows" -o tsv
```

The advisor run's log lines, and the Function's invocations:

```kusto
traces
| where timestamp between (datetime(2026-11-11T15:02:30Z) .. datetime(2026-11-11T15:04:10Z))
| where message startswith "advisor run " or message startswith "delivery "
| project timestamp, message
| order by timestamp asc
```

```kusto
requests
| where timestamp between (datetime(2026-11-11T15:02:30Z) .. datetime(2026-11-11T15:04:10Z))
| project timestamp, name, duration, success, resultCode
| order by timestamp asc
```

The agent's spans:

```kusto
dependencies
| where timestamp between (datetime(2026-11-11T15:02:40Z) .. datetime(2026-11-11T15:03:50Z))
| where name startswith "invoke_agent" or name startswith "chat " or name startswith "execute_tool"
| extend dims = todynamic(customDimensions)
| project timestamp, name, duration,
    inputTokens = tostring(dims["gen_ai.usage.input_tokens"]), outputTokens = tostring(dims["gen_ai.usage.output_tokens"])
| order by timestamp asc
```

The deployment's token counts, in five-minute intervals (also `OutputTokens`, `ModelRequests`, and `FoundryModelEstimatedCost`):

```powershell
$account = az cognitiveservices account list -g (azd env get-value AZURE_RESOURCE_GROUP) --query "[0].id" -o tsv
az monitor metrics list --resource $account --metric InputTokens --filter "ModelDeploymentName eq 'gpt-6.1-sol'" `
  --start-time 2026-11-11T14:40:00Z --end-time 2026-11-11T15:30:00Z --interval PT5M --aggregation Total -o table
```

The evaluation runs, the agents' versions, and the answer's tokens, from the Foundry project with the `azure-ai-projects` package that [`evaluate.py`](../evaluate.py) uses. Replace `<FOUNDRY_PROJECT_ENDPOINT>` with the value of `azd env get-value FOUNDRY_PROJECT_ENDPOINT`. The latency and token usage of each answer are in the output items, under `sample`.

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(endpoint="<FOUNDRY_PROJECT_ENDPOINT>", credential=DefaultAzureCredential())
openai = project.get_openai_client()
for evaluation in openai.evals.list(limit=100):
    if evaluation.name.startswith("Architecture advisor · labelled cases"):
        for run in openai.evals.runs.list(eval_id=evaluation.id, limit=100):
            for item in openai.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id):
                print(evaluation.name, run.id, run.name, item.datasource_item["id"],
                      [(r.name, r.passed) for r in item.results], item.sample.latency_ms, item.sample.usage)
for version in project.agents.list_versions(agent_name="architecture-advisor-small-team"):
    print(version.version, version.definition["model"])
print(openai.responses.retrieve("resp_08aa75b8e5513e8a006af483a24c5481939915775457782e8b").usage)
```

The prices, with the meters `6.1-sol ShortCo Inp Std Gl`, `6.1-sol ShortCo Cd Inp Std Gl`, and `6.1-sol ShortCo Opt Std Gl` (and `6-luna` or `5.4 mini` in place of `6.1-sol`):

```powershell
$filter = "serviceName eq 'Foundry Models' and armRegionName eq 'eastus2' and contains(meterName, '6.1-sol')"
(Invoke-RestMethod "https://prices.azure.com/api/retail/prices?`$filter=$([uri]::EscapeDataString($filter))").Items |
  Select-Object meterName, retailPrice, unitOfMeasure
```
