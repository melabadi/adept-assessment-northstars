# Presenting the seven-phase demo

Each solution's README is the script for its own demo: every step has the command or click, a screenshot of what appears, and what to point out. This guide plans a whole session: which demos to show, what to start early, how to prepare, and what it costs while it runs.

## Pick a format

| Format | Length | What to show |
| --- | --- | --- |
| **Full show** | About 5 hours of demos: a full day with breaks, or two half days | All fourteen demos, phase by phase: the GitHub solution, then the Microsoft one. |
| **One track** | About 2½ hours | The seven GitHub demos (about 2 h 20 min) or the seven Microsoft demos (about 2 h 35 min), in phase order. |
| **One phase, side by side** | 30 to 50 minutes | The two solutions of one phase, for a team that cares about that phase. |
| **Highlights** | About 2 hours | One demo per phase. The [suggested set](#a-two-hour-highlights-run) below keeps the waiting off stage. |

Whatever the format, tell the same story: one app, RequestHub, goes through every phase, and in each phase AI does the tedious part while a person keeps the decision.

## Timings at a glance

"Start early" is what to launch before you need it, so that nobody waits on stage.

| Solution | On stage | Start early |
| --- | --- | --- |
| [01-plan-github](solutions/01-plan-github/) | 15 min (12 with the cloud agent's pull request) | If you show the cloud agent (option B), assign it about 10 minutes before: it finishes in about 5. |
| [01-plan-microsoft](solutions/01-plan-microsoft/) | 15 min (20 with the optional steps) | Start a backup run about 10 minutes before: a run reaches its review Issue in about 2¼ minutes, or 6 to 9 when the preview evaluation runs again. |
| [02-design-github](solutions/02-design-github/) | 25 min | If you show the cloud agent (option B), assign it at least 30 minutes before; it takes about 12. Request Copilot's code review early: it takes 4 to 5 minutes. |
| [02-design-microsoft](solutions/02-design-microsoft/) | 15 min | Run the Foundry evaluation (`python evaluate.py`, in the solution folder) about 15 minutes before step 8 and expect 10/10; it takes 3 to 6 minutes. If it reports COULD NOT GRADE, run it again. Open the agent's Playground in advance (it takes up to a minute to load). |
| [03-develop-github](solutions/03-develop-github/) | 25 min | Create the Issue and assign it to Copilot at least 30 minutes before: it works for 20 to 30. Run the Copilot CLI step (about 20 minutes) beforehand too. |
| [03-develop-microsoft](solutions/03-develop-microsoft/) | 20 min | Run the reviewer's dry run on pull request #36 (about 3 minutes) to confirm its GitHub token still works. For fresh evaluation results, start `eval_reviewer.py` about 20 minutes before. |
| [04-test-github](solutions/04-test-github/) | 20 min | Rebuild the lab branch and assign the Issue to Copilot 30 minutes before: it works for 15 to 30. The optional Copilot CLI step takes 12 to 18 minutes. |
| [04-test-microsoft](solutions/04-test-microsoft/) | 30 min (45 fully live) | Start the baseline Azure Load Testing run from the portal about 10 minutes before its step: a run reaches its verdict in 8 to 9 minutes, and the Logic App reports it about 2 minutes later. Start the final passing run during questions. |
| [05-secure-github](solutions/05-secure-github/) | 15 min | Prepare the lab and start the review and the cloud agent 30 to 45 minutes before: the review took about 6 minutes and the repair 15 in the screenshot run. |
| [05-secure-microsoft](solutions/05-secure-microsoft/) | 25 min (15 with step 7 from screenshots) | Reset at least a day before, so that Defender for Cloud reports the account Unhealthy again, and start the database if a tenant policy stopped it (about 2 minutes). Nothing else: the Issue, the agent's draft pull request, and its what-if preview follow the click in about 2 minutes, `azd provision` takes about 5, and `posture-verify` 2 to 15. |
| [06-release-github](solutions/06-release-github/) | 20 min | Start the release candidate about 15 minutes before: the candidate takes 3.5 to 7 minutes, and Copilot's summary 5 to 6 more. |
| [06-release-microsoft](solutions/06-release-microsoft/) | 20 min | Start `release.py watch` two minutes before, so the audience sees what users get. A release takes about 4 minutes: about 2 to build the commit, then about 2 for the release job to deploy and check the candidate. |
| [07-operate-github](solutions/07-operate-github/) | 20 min | In a short slot, run the triage (about 5 minutes) and Copilot's follow-up (4 to 10 more) before the audience arrives. |
| [07-operate-microsoft](solutions/07-operate-microsoft/) | 25 min | In a short slot, start the incident up to 10 minutes before you show the investigation (no more than 30: the fault switches itself off after 45); the alert fires about 6 minutes after the start. |

### A two-hour highlights run

One demo per phase, chosen for a short running time and a clear story, with the long waits started before the session (see the table above):

1. **Plan** (12 min): [01-plan-github](solutions/01-plan-github/), with the cloud agent's brief pull request already open.
2. **Design** (15 min): [02-design-microsoft](solutions/02-design-microsoft/), two operating profiles get different, grounded answers.
3. **Develop** (20 min): [03-develop-microsoft](solutions/03-develop-microsoft/), Azure reviews a risky pull request in minutes: the team's rules first, then a sandbox build, then a Foundry agent's commentary.
4. **Test** (20 min): [04-test-github](solutions/04-test-github/), with the failing tests and the fix already pushed.
5. **Secure** (15 min): [05-secure-github](solutions/05-secure-github/), from Copilot's review finding to a proven fix.
6. **Release** (20 min): [06-release-microsoft](solutions/06-release-microsoft/), a bad revision is caught before it gets traffic.
7. **Operate** (20 min): [07-operate-github](solutions/07-operate-github/), with the triage and Copilot's follow-up run beforehand.

To show the other offering of a phase, swap in its other solution; the table above shows what it adds to the time.

## Prepare

### Once

- Work through the root README's [Before you start](README.md#before-you-start), then each solution's **Set up**. The Microsoft solutions each deploy into their own resource group with `azd up`, which takes from 2 to 20 minutes depending on the solution.
- Connect each Microsoft solution to GitHub once, as its **Set up** describes: a fine-grained token limited to this repository (Plan, Develop, Test, Secure, Release), a private GitHub App (Design), or Azure SRE Agent's Code access (Operate). Their AI and automation run in Azure; no GitHub Actions workflow takes part.
- For the two agentic workflows (06-release-github and 07-operate-github), create the `COPILOT_GITHUB_TOKEN` secret as their READMEs describe.
- Use a demo tenant and a demo subscription. On stage, your audience sees your real Azure portal, your account, and your resource names.

### The day before

- Run each solution's **Before each session** checklist. It confirms the demo is in its starting state and lists what to open.
- Make sure the PostgreSQL servers of the Microsoft solutions that run RequestHub are running. Tenant governance policies can stop them on a schedule; when that happens the app fails its readiness check and requests time out. Each README's checklist has the check and the `az postgres flexible-server start` command, which takes 3 to 5 minutes.
- Run the quick self-checks the READMEs include, such as an evaluation run or a preflight. They catch an expired sign-in or a missing secret while there is still time to fix it.
- If you present from another machine, sign in there to GitHub, Azure CLI (`az login`), and Azure Developer CLI (`azd auth login`).

### One hour before

1. Sign in to GitHub and the Azure portal in the browser you present from.
2. Start the long-running parts in the order of the [timings](#timings-at-a-glance): Copilot tasks first, then the release candidate, then load tests and the incident.
3. Open the tabs and terminals each README lists under **Before each session**.

## During the session

- Narrate while things run. Every README says what to show while you wait: the input files, the agent's instructions, the workflow definition.
- Keep your account menu, the Foundry project's Home page, and Azure resources' Overview pages off the shared screen: they show your account, endpoints, and subscription. The READMEs' screenshots were captured with these details masked; a live screen isn't.
- If a live step is slow or fails, keep going with the screenshots in the README: they come from real runs of the same steps. Each README's **Troubleshooting** covers the failures we have seen.
- End each phase on its **What to observe**: what the AI did, what the person decided, and the evidence left behind.

## After the session

- Reset each solution you used, following its **Reset and clean up**. Resets close the Issues and pull requests the demo created, delete temporary branches, and put Azure resources back in their starting state.
- When you are done with a Microsoft solution, its clean-up section removes everything it created, including any Microsoft Entra app registration, and says how to revoke its GitHub access: delete its token or GitHub App on GitHub.

## What it costs while it is deployed

The GitHub demos use your Copilot plan and Actions minutes. The Microsoft solutions bill while their resource groups exist, even when nobody presents:

| Bills by the hour while deployed | Solutions |
| --- | --- |
| A PostgreSQL flexible server and two container apps kept at one replica each (RequestHub) | 04-test, 05-secure, 06-release, and 07-operate (Microsoft) |
| Azure AI Search, Basic tier, and two private endpoints: about $90 a month | 02-design-microsoft |
| Two private endpoints and their DNS zones, for the reviewer Function's storage: about $16 a month | 03-develop-microsoft |
| Azure SRE Agent: 4 Azure Agent Units (AAUs) an hour while it exists (about $292 a month), plus roughly 10 to 35 AAUs per investigation (capped at 1,000 a month) | 07-operate-microsoft |

Everything else bills for what you use: Foundry models and evaluations, Logic Apps, Azure Functions, Container Apps jobs and dynamic sessions, Azure Load Testing, and Defender for Cloud. 01-plan-microsoft costs close to nothing while nobody runs it. Delete a solution's resource group when you won't present it for a while: `azd up` recreates it.
