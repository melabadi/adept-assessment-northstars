# Design · Architecture review with GitHub Copilot

Design decisions often live in meeting notes and people's memories. Reviewers cannot tell which standards were considered, designs describe the system as people remember it, and an API break shows up only in integration testing. In this solution a custom Copilot agent reads the reviewed brief, the approved architecture standards, and RequestHub's real code and API contract, then proposes an architecture decision record (ADR) that compares two options. GitHub Actions checks the ADR and its API contract impact on the pull request, Copilot code review questions it, and an architect decides.

![Copilot's ADR compares the two options against the same constraints, citing each standard by id and version, for the small-team and the enterprise profile](images/05-adr-options.png)

## Where it fits

**Phase 2 of 7: Design and architect.** The Microsoft counterpart is [02-design-microsoft](../02-design-microsoft/).

| | Today | With this solution |
| --- | --- | --- |
| Drafting | An architect writes the decision from scratch, often after the code. | Copilot proposes an ADR with two options, diagrams, a threat model, and tasks in minutes. |
| Grounding | The design describes the system as people remember it. | Copilot reads the real extension point, workflow, contract, and Bicep. A check rejects references to files that do not exist. |
| Standards | Reviewers rely on memory to know which standards apply. | Every driver cites a standard by id and version. A check rejects ids and versions that do not exist, and conflicts between standards go to a person. |
| API changes | Breaking changes surface in integration testing. | Every design pull request gets an additive-or-breaking report for the `requesthub.v1` contract. A breaking change fails the check. |
| Sign-off | "Approved" in a chat thread, and nobody knows who decided. | Copilot can only propose. A check fails any accepted ADR that does not name the people who decided. |

## How it works

```mermaid
flowchart LR
  I[inputs/reviewed-brief.md<br/>standards/STD-*.md<br/>app code and contract] --> C[Copilot<br/>design-github agent]
  C -->|adr/0001-...md| PR[Pull request]
  PR --> A[Actions<br/>ADR checks<br/>API contract compatibility]
  PR --> R[Copilot code review]
  A --> H{Architect reviews}
  R --> H
  H -->|asks Copilot for changes| C
  H -->|accepts or rejects,<br/>named as decider| D[Recorded decision]
```

- **Copilot** runs the custom agent [`design-github`](.github/agents/design-github.agent.md) with two skills. [`architecture-decision`](.github/skills/architecture-decision/SKILL.md) provides the ADR template and a deterministic checker. [`contract-impact`](.github/skills/contract-impact/SKILL.md) classifies every change to `app/contracts/openapi.json` as additive or breaking. The agent reads the inputs and the code, writes the ADR, and runs the checker until it passes.
- **GitHub Actions** runs [`design-github-review.yml`](.github/workflows/design-github-review.yml) on every pull request that adds or changes an ADR, and on demand for any branch. It takes the checker, the contract tool, and the standards from the base branch, so a pull request cannot weaken them.
- **Copilot code review** follows [`design-github-adr-review.instructions.md`](.github/instructions/design-github-adr-review.instructions.md): unstated assumptions, standards the ADR missed, the API impact, and the threat model.
- **A person** reviews the ADR, asks Copilot for changes, settles the conflicts and open questions, and accepts or rejects it.

**Outside contributions.** On a public repository anyone can open an Issue with this solution's form, or a pull request from a fork. Neither starts Copilot: only people with write access can assign an Issue to Copilot or mention `@copilot`. A Copilot code review that someone else requests on their own pull request uses their Copilot plan, not yours. A fork's pull request that changes an ADR gets the ADR checks, with a read-only token and no secrets, once someone with write access approves the run; the checker comes from the base branch.

## What's in this folder

```text
02-design-github/
├── README.md
├── adr-task.md                         the task Copilot receives (CLI prompt; the issue template says the same)
├── images/                             screenshots from a live run, used in this README
├── inputs/
│   └── reviewed-brief.md               synthetic reviewed requirements and the open design question
├── standards/
│   ├── README.md                       how a standard is written: id, version, scope
│   └── STD-*.md                        twelve approved architecture standards (synthetic)
└── .github/
    ├── agents/design-github.agent.md   the custom Copilot agent
    ├── skills/
    │   ├── architecture-decision/      ADR template and check_adr.py
    │   └── contract-impact/            contract_diff.py: additive or breaking (shared with other solutions)
    ├── instructions/design-github-adr-review.instructions.md   what Copilot code review looks for in an ADR
    ├── workflows/design-github-review.yml   ADR checks and API contract compatibility on design pull requests
    └── ISSUE_TEMPLATE/02-design-github-adr.yml
```

Copilot's pull request adds `adr/0001-live-triage-provider.md` to this folder.

## Prerequisites

- GitHub Copilot Business or Enterprise with Copilot code review. Option B below also needs the Copilot cloud agent enabled for the repository.
- [GitHub CLI](https://cli.github.com/), signed in with permission to create Issues and pull requests.
- [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/set-up/install-copilot-cli) for option A.
- PowerShell 7 and Python 3.12 or later. The scripts use only the standard library.

## Set up

Nothing to install. The agent, skills, workflow, review instructions, and issue template are already active because the repository's root `.github/` folder mirrors them. In a fresh copy of the repository, create the labels the issue template applies:

```powershell
gh label create ai-sdlc --color 1D76DB --description "AI-SDLC demo work" --force
gh label create phase:design --color C5DEF5 --description "SDLC phase 2: Design" --force
```

`gh label list` then shows both labels.

## Before each session

Allow 30 minutes before the audience arrives if you show option B, 5 minutes otherwise.

1. **Confirm the starting state.** From the repository root, on an up-to-date `main` (`git switch main; git pull`), each of these commands prints nothing:

   ```powershell
   git ls-tree --name-only origin/main solutions/02-design-github/adr
   gh issue list --state open --search '"Design: how should RequestHub add a live AI triage provider?" in:title'
   gh pr list --state open --json number,title,files --jq '.[] | select(any(.files[]; .path | startswith("solutions/02-design-github/adr/"))) | "#\(.number) \(.title)"'
   git ls-remote --heads origin design/copilot-adr design/breaking-contract-demo
   ```

   If one prints something, a previous run was not cleaned up: follow [Reset and clean up](#reset-and-clean-up).

2. **Check your tools.** `gh auth status` shows you signed in, `copilot --version` prints a version, and `python --version` prints 3.12 or later.

3. **Open in advance:**
   - browser tabs on [`inputs/reviewed-brief.md`](inputs/reviewed-brief.md), [`standards/STD-OBS-002.md`](standards/STD-OBS-002.md), and [`standards/STD-SEC-002.md`](standards/STD-SEC-002.md), and on the repository's **Actions** tab filtered to *Design · GitHub · check the ADR and API impact*;
   - a PowerShell 7 terminal at the repository root, with a font the room can read.

4. **Start option B early.** Create the Issue and assign it to Copilot (step 2B) at least 30 minutes before you present. When Copilot asks for your review, start its workflows and request a Copilot code review (steps 3 and 4), so both are ready when you get there. Option A runs live in about 7 minutes; if you want a fallback, run it once beforehand and keep its pull request open.

5. **Timings from our runs:**

   | Step | Time |
   | --- | --- |
   | 1. Show the question and the standards | 2 minutes |
   | 2A. Copilot CLI writes the ADR | 5 to 7 minutes |
   | 2B. Copilot cloud agent writes the ADR | 12 minutes (environment ready in 2, then 10 of work); allow 30 |
   | 3. Checks | about 1 minute; each job takes about 10 seconds |
   | 4. Copilot code review | 4 to 5 minutes; request it early |
   | 5. Review the ADR | 3 minutes |
   | 6. Ask for changes | 1.5 minutes with the CLI, 4 minutes on the pull request, plus 1 minute of checks |
   | 7. Show that only people decide | 2 minutes, plus 1 minute of checks |
   | 8. Optional: a breaking API change | 1 minute locally, 1 minute more in Actions |

## Run the demo

About 20 minutes. Run the commands from the repository root.

1. **Show the question and the standards** (2 minutes). Open [`inputs/reviewed-brief.md`](inputs/reviewed-brief.md): seven accepted requirements (advisory only, data minimization, audit, an 8-second target, English and French), two operating profiles, and the open question: *how should RequestHub add a live AI triage provider?*

   ![The reviewed brief on GitHub: seven accepted requirements BR-1 to BR-7, the constraints with the two operating profiles, and the open design question](images/01-brief.png)

   Then open [`standards/`](standards/). Each standard has an id, a version, and a scope. Point out what a good design must notice, without telling Copilot:
   - **A conflict.** STD-OBS-002 says to log full prompts and completions for 30 days. STD-SEC-002 says never to persist raw prompts that contain user free text. Nobody has decided which wins.
   - **Profiles that pull apart.** STD-OPS-001 lets a small team add at most one new runtime component per quarter, and no gateway unless a platform team already runs one. STD-OPS-002 sends every enterprise model call through the central AI gateway.
   - **Extend before you add.** STD-ARCH-001 prefers the existing service, and RequestHub already has a triage extension point, `ITriageProvider`.

   ![STD-OBS-002 v1.0 requires logging the full prompt and completion of every AI call for 30 days, while STD-SEC-002 v1.1 forbids persisting raw prompts or completions that contain user free text](images/01-standards-conflict.png)

   **Point out:** Copilot gets the brief, the standards, and the code. Nothing tells it which standards conflict, or that the two profiles may need different answers. Watch whether it finds both.

2. **Ask Copilot for the ADR.** Pick one option.

   **A. Live in the terminal** (5 to 7 minutes).

   ```powershell
   git switch -c design/copilot-adr
   copilot --agent design-github --allow-all-tools -p (Get-Content solutions/02-design-github/adr-task.md -Raw)
   git add solutions/02-design-github/adr
   git commit -m "Design: Copilot ADR for the live triage provider"
   git push -u origin design/copilot-adr
   gh pr create --fill
   ```

   In bash, use `-p "$(cat solutions/02-design-github/adr-task.md)"`. Copilot lists each step as it works. The image below is shortened: in our run Copilot read the brief, all twelve standards, the contract, the triage code, and parts of the web UI before it wrote the ADR.

   ![The Copilot CLI run, shortened: the agent loads its two skills, reads the brief, the triage code, and the standards, runs the contract tool, writes the ADR, runs the checker, and summarizes the recommendation for the reviewer](images/02a-copilot-cli.png)

   **Point out:** the agent loads its two skills, reads the real code before it designs, and runs the contract tool and the ADR checker itself before it hands over.

   **B. Delegate to the Copilot cloud agent** (start it at least 30 minutes early). Select **Issues** → **New issue** → **Design: architecture decision with Copilot**. The form is filled in: the question, the inputs, and what to produce. Select **Create**.

   ![The issue form "Design: architecture decision with Copilot" with the design question, the input files, and what to produce already filled in, and the ai-sdlc and phase:design labels](images/02b-issue-form.png)

   On the new Issue, select **Assign to Agent** in the sidebar. In the dialog, open the custom-agent picker (the document icon, left of the model picker **Auto**), select **design-github**, and then **Assign**.

   ![The "Assign agent to issue" dialog with the custom agent menu open and design-github selected among the repository's custom agents](images/02b-assign-agent.png)

   Copilot opens a draft pull request within seconds and works in it. **View session** shows its progress live.

   ![The pull request timeline: Copilot started work on behalf of the person who assigned it, with a View session button](images/02b-copilot-working.png)

   When the ADR is ready, Copilot asks for your review. Workflows on Copilot's pull requests wait for a person: select **Approve workflows to run**, or re-run the waiting runs from a terminal with `gh run rerun <run-id>` (`gh run list --branch <copilot-branch>` shows the ids).

   ![The pull request's merge box: review requested, 3 workflows awaiting approval with an Approve workflows to run button, and the pull request still a draft](images/02b-approve-workflows.png)

   **Point out:** the same agent and skills run on GitHub, from an Issue, with nobody at a keyboard. Nothing Copilot pushes runs in Actions until a person approves it.

3. **Watch the gate** (about 1 minute). The **Design · GitHub · check the ADR and API impact** workflow adds two checks to the pull request:
   - **ADR checks**: the template's sections, at least two options, an architecture diagram and a sequence diagram (with no `;` inside a sequence message, which stops GitHub from rendering it), standards and versions that exist, real repository-relative paths, and Status Proposed.
   - **API contract compatibility**: compares `app/contracts/openapi.json` with the commit the branch started from. An ADR-only pull request reports `Breaking changes: 0` and `No contract changes.`

   ![The pull request's checks, expanded: ADR checks and API contract compatibility from the design workflow, plus the repository's other checks, all successful](images/03-pr-checks.png)

   Select either check, then **Summary** in the run's left menu. The run page shows how long each job took, about 10 seconds, and what each check found:

   ![The workflow run page: triggered via pull request #125 with status Success; ADR checks took 10 seconds and API contract compatibility 9 seconds; ADR checks prints PASS for the ADR, and the API contract impact report lists 0 breaking and 0 additive changes](images/03-run-summary.png)

   **Point out:** these checks are deterministic. They run the checker, the contract tool, and the standards from `main`, so the pull request under review cannot change its own gate.

4. **Ask Copilot for a code review** (4 to 5 minutes). Select **Reviewers** → **Copilot** on the pull request, or run `gh pr edit <number> --add-reviewer "@copilot"`. Copilot posts a review that summarizes the change and names what still needs people.

   ![Copilot's code review: Needs a closer look. Authorized reviewers must resolve the conflicting logging and privacy standards and approve the AI data boundary, while gateway compatibility and the latency budget still need runtime evidence](images/04-copilot-review.png)

   In our runs, both reviews flagged the prompt-logging versus privacy conflict and asked for evidence that the enterprise gateway works. On an earlier ADR, Copilot asked for changes with three inline comments: personal data typed into the allowed free-text fields, keeping the current department once it is no longer sent to the AI service, and the gateway's per-department quotas.

   **Point out:** Copilot code review questions the substance and names the decisions that belong to people. It is a reviewer, not an approver.

5. **Review like an architect** (3 minutes). Open the ADR from the pull request (**Files changed** → **⋯** → **View file**) so the mermaid diagrams render. Look for:
   - the options compared in one table against the same standards (the image at the top of this page), and under **Decision**, a recommendation for each profile:

   ![The Decision section of Copilot's ADR: recommend option A for the small team and option B for the enterprise, keeping business authority and tools in RequestHub, and calling itself a recommendation, not deployment approval](images/05-adr-decision.png)

   - what Copilot found by reading the code, not the brief: in every run, that the workflow's 45-second triage timeout cannot meet the 8-second target, and that the current prompt sends more than the title, description, and category that BR-3 allows;
   - the request flow, success and failure paths included (this diagram is from the cloud agent's ADR):

   ![The sequence diagram from the cloud agent's ADR, rendered on GitHub: the reviewer's request goes through RequestWorkflow and the in-process provider to Foundry, with the unauthorized, valid, invalid-output, and timeout paths, and manual routing that never depends on the AI](images/05-adr-sequence.png)

   - the open questions, starting with the conflict Copilot left for you:

   ![Open question 1 of the ADR: a blocking standards conflict. STD-OBS-002 v1.0 requires full prompts and completions in logs for 30 days, STD-SEC-002 v1.1 prohibits persisting them, and the ADR asks which standard the authorized reviewer will amend or formally except](images/05-adr-open-question.png)

   **Point out:** Copilot cites the conflict between STD-OBS-002 and STD-SEC-002 and asks a person to decide instead of choosing a winner.

6. **Ask for changes** (1.5 to 5 minutes). Take a review comment, or anything you want changed, and give it to Copilot. In our run, GitHub could not render either ADR's sequence diagram ("Unable to render rich display"): a `;` inside a mermaid sequence message ends the statement. The checker now catches that, and Copilot fixed it when asked.

   With option A, run `copilot` again with your request instead of the task file, then commit and push:

   ```powershell
   copilot --agent design-github --allow-all-tools -p 'The sequence diagram in solutions/02-design-github/adr/0001-live-triage-provider.md does not render on GitHub ("Unable to render rich display"). Run the ADR checker, fix what it reports, and keep the status Proposed.'
   ```

   ![The Copilot CLI revision, shortened: the ADR checker fails with seven lines where a semicolon ends a sequence-diagram statement, Copilot edits the ADR, the checker passes, and the status stays Proposed](images/06-revision-cli.png)

   With option B, comment on the pull request with `@copilot` and your request. Copilot pushes a revision and replies; select **Approve workflows to run** again so the checks rerun.

   ![Copilot's reply on the pull request: it replaced the semicolons in the sequence-diagram messages with commas, the ADR stays Proposed, the checker passes, and it names the fixing commit](images/06-revision-pr.png)

   **Point out:** the reviewer stays in control of the design. Copilot changes only what was asked, keeps the status Proposed, and runs the checker again before it hands back.

7. **Show that only people decide** (2 minutes, plus 1 minute of checks). On the pull request branch, let the agent "accept" its own ADR, and run the checker. Then decide as the architect: name yourself and your role, and run it again.

   ```powershell
   $adr = Resolve-Path -Relative (Get-ChildItem solutions/02-design-github/adr/*.md)[0]
   (Get-Content $adr -Raw) -replace '\*\*Status:\*\* Proposed', '**Status:** Accepted' -replace '\*\*Deciders:\*\*.*', '**Deciders:** GitHub Copilot' | Set-Content $adr -NoNewline
   python .github/skills/architecture-decision/check_adr.py $adr
   (Get-Content $adr -Raw) -replace '\*\*Deciders:\*\*.*', '**Deciders:** Morgan Patel (lead architect)' | Set-Content $adr -NoNewline
   python .github/skills/architecture-decision/check_adr.py $adr
   ```

   ![The checker fails the ADR accepted by GitHub Copilot with "status Accepted must name the people who decided … an agent can only propose", then passes once a person is named as decider](images/07-people-decide.png)

   Commit and push after each change to show the same result on the pull request. The agent's acceptance fails **ADR checks**, even if that commit also edits `check_adr.py` to always pass, because the workflow runs the checker from the base branch; the person's acceptance passes, and the pull request's history shows who decided. Run `git checkout -- $adr` instead if you only want to show the failure locally.

   ![The run that the agent's acceptance triggered on pull request #125: status Failure, ADR checks failed after 10 seconds with "status Accepted must name the people who decided … an agent can only propose", and no contract changes](images/07-failed-check.png)

   **Point out:** Copilot can propose, and only a named person can accept. The rule lives in a deterministic check, not in a prompt.

8. **Optional: catch a breaking API change** (1 to 2 minutes). Remove a response field from a copy of the contract and compare it with `main`:

   ```powershell
   $contract = Get-Content app/contracts/openapi.json -Raw | ConvertFrom-Json -AsHashtable
   $contract.components.schemas.RecommendationDto.properties.Remove('providerTraceId')
   $contract | ConvertTo-Json -Depth 100 | Set-Content $env:TEMP/openapi-breaking.json
   python .github/skills/contract-impact/contract_diff.py --base-ref origin/main --head $env:TEMP/openapi-breaking.json --fail-on-breaking
   ```

   ![The contract tool reports a breaking change, schema RecommendationDto property providerTraceId removed, and exits with code 1](images/08-breaking-change.png)

   Exit code 1 is what fails the **API contract compatibility** check. Adding a property instead reports `Compatible` with `➕`. To show the same failure in GitHub Actions without opening a pull request, write the edited contract to `app/contracts/openapi.json` on a scratch branch, push it, and run `gh workflow run design-github-review.yml -f ref=<branch>`. The run page names `main`, where the workflow file comes from; the branch you passed in `ref` is the one it checks:

   ![A run started on demand: manually triggered, on workflow_dispatch, status Failure. ADR checks finds no ADR added or changed, and API contract compatibility fails with one breaking change, property providerTraceId removed](images/08-dispatch-run.png)

   **Point out:** API compatibility is a deterministic report against `requesthub.v1`, not an opinion. Removing a field fails; adding one passes (STD-API-001).

## What to observe

- **Grounded in the real system.** Copilot reads the code before it designs. In every run it reused the existing `ITriageProvider` extension point, rejected a separate triage service under STD-ARCH-001, and found gaps the brief does not mention, such as the 45-second timeout. The check proves every file the ADR cites exists.
- **Standards, with versions.** Each driver cites `STD-xxx-nnn vX.Y`. The conflict between STD-OBS-002 and STD-SEC-002 reaches a person as a blocking open question instead of being settled silently.
- **One question, two answers.** The recommendation follows the operating profile where the standards do: direct calls for the small team (STD-OPS-001), the central AI gateway for the enterprise (STD-OPS-002).
- **Deterministic checks catch what reviewers miss.** Neither the first checker nor Copilot code review noticed that GitHub could not render the sequence diagrams, or that the cloud agent cited files by their absolute path on its runner. Rules in the checker now catch both, and the agent runs the checker until it passes. In our run, Copilot fixed the diagrams as soon as the checker reported them.
- **Contract impact as evidence.** The API impact is a deterministic report on every design pull request. Breaking changes fail; Copilot proposes any needed API change as an additive one.
- **People decide.** Copilot proposes and Copilot code review questions; only a named person accepts. The checker and the standards come from the base branch, so the proposal cannot weaken them.
- **Speed.** About 7 minutes from a reviewed brief to a reviewable design, and minutes for each revision.

## Reset and clean up

```powershell
git switch main                                          # first, so the next command can delete the demo branch
gh pr close <number> --delete-branch                     # each ADR pull request (options A and B) and its branch
gh issue close <number> --reason "not planned"           # option B: the design Issue
git push origin --delete design/breaking-contract-demo   # step 8 in Actions: the scratch branch
```

Do not merge the ADR into `main`. Keeping it out keeps the demo repeatable: the next run starts again from ADR 0001. The commands in [Before each session](#before-each-session) confirm the clean state. If they still list `design/copilot-adr`, delete it with `git push origin --delete design/copilot-adr`: `gh pr close` keeps a branch that is checked out somewhere, for example in another worktree.

## Use it in your own repository

1. Copy this folder's `.github/` contents into your repository's `.github/` folder.
2. Put your standards in a `standards/` folder, one Markdown file per standard with `id`, `version`, and `scope` in its front matter, and your brief in `inputs/`. The checker uses the nearest `standards/` folder above each ADR, or `--standards`.
3. Choose where ADRs live (for example `docs/adr/`, next to `docs/standards/`). Update the paths in the agent, `adr-task.md`, the issue template, the review instructions (`applyTo`), and the workflow (`paths`, `ADR_DIR`, and the standards folder it restores from the base branch).
4. Add your contract's path (for example `app/contracts/**`) to the workflow's `paths`, so every pull request that changes the API gets the report, not only design pull requests. In this repository the workflow runs only for its own demo.
5. Point the agent at your own extension points, contract, and infrastructure files, and adapt the threat-model checklist in `adr-template.md` to your standards.
6. `contract_diff.py` reads the contract from `app/contracts/openapi.json`. Change its `CONTRACT` constant if yours lives elsewhere.

## Troubleshooting

- **No checks on Copilot's pull request.** Workflows on pull requests from the cloud agent wait for a person. Select **Approve workflows to run**, or run `gh run rerun <run-id>`.
- **"Unable to render rich display" instead of a diagram.** GitHub could not parse the mermaid code. A semicolon in a sequence-diagram message is the usual cause: the checker reports it as `line N: ';' ends a statement in a mermaid sequence diagram`. Ask Copilot to fix it (step 6).
- **The cloud agent takes much longer than 12 minutes.** Before Copilot starts, the repository's Copilot setup steps prepare its environment. In one of our runs that took 17 minutes instead of 2. Start option B at least 30 minutes before you present.
