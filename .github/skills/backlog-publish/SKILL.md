---
name: backlog-publish
description: Publish a validated Plan-phase backlog.json to GitHub Issues as one epic with four linked task sub-issues, idempotently (re-runs never duplicate), with labels, dependencies, source excerpts, and an optional GitHub Project. Use after a person has reviewed the brief, or to reset the demo by closing published issues.
---

# Backlog publish

## When to use
- After the brief pull request was reviewed and labelled `brief-approved` (each Plan solution's review workflow runs this automatically).
- Locally, to publish or re-publish a backlog, add it to a GitHub Project, or reset the demo.

## Inputs
- A backlog that passes `requirements-traceability` validation, inside its solution folder (for example `solutions/01-plan-github/brief/backlog.json`). The transcript excerpts quoted in each issue come from that solution's `inputs/` folder.
- `--track github` (Copilot output) or `--track microsoft` (Foundry output). Each track publishes its own issue set.
- GitHub access: your `gh` login locally, or `GH_TOKEN` with `issues: write` in Actions.

## Procedure
1. Preview: `python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track <track> --dry-run`
2. Publish: same command without `--dry-run`.
3. Prove idempotency: run it again; every line must say `unchanged`.
4. Optional Project board (local only, needs `gh auth refresh -s project`): add `--project-title "AI-SDLC Plan demo"`.
5. Reset after a demo: `python .github/skills/backlog-publish/publish_backlog.py --track <track> --close`.

## Expected output
```
owner/repo · assisted-triage-brief · track github: 5 created
       created  EPIC-TRIAGE    #21  https://github.com/owner/repo/issues/21
       created  TASK-1         #22  ...
  sub-issues newly linked: 4 · dependencies: api
```
Each issue contains the backlog id, owner role, acceptance criteria as a checklist, and the quoted source paragraphs.

## Failure handling
- `Refusing to publish: the backlog is not valid`: fix the backlog with the requirements-traceability skill first.
- `gh api … 403`: the token lacks `issues: write`; in Actions check the workflow `permissions`.
- `dependencies: text-only`: the issue-dependencies API is unavailable for this repository; dependencies stay as `#links` in each task body.
- Project errors: `GITHUB_TOKEN` cannot use Projects; run the command locally after `gh auth refresh -s project`.
