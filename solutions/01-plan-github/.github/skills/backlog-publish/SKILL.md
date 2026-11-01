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
- GitHub access: your `gh` login locally, or `GH_TOKEN` with `issues: write` in Actions. Publish as one of the identities the publisher recognizes on a re-run: GitHub Actions' bot (the workflow's `GITHUB_TOKEN`), or the repository's owner, a member, or a collaborator. In an organization, GitHub reports a member whose organization visibility is private as `NONE`, so publish locally as the owner, a collaborator, or a member with public visibility, or let the workflow publish. To publish with another identity, such as a GitHub App, add its bot login to `PUBLISHER_BOTS` in `publish_backlog.py`, or each run creates the issues again.

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
A re-run finds the issues it published by their hidden marker, and counts only issues that GitHub Actions' bot or the repository's owner, a member, or a collaborator opened: anyone can open an issue with the `phase:plan` label and the same marker, and such an issue is never updated, reopened, closed, or linked.
Publishing again keeps the "blocked by" links in step with the backlog: a link between two of its own issues that `dependsOn` no longer lists is removed, and the last line adds `stale dependencies removed: N`. Links to any other issue are never touched.

## Failure handling
- `Refusing to publish: the backlog is not valid`: fix the backlog with the requirements-traceability skill first.
- `gh api … 403`: the token lacks `issues: write`; in Actions check the workflow `permissions`.
- `dependencies: text-only`: the issue-dependencies API is unavailable for this repository; dependencies stay as `#links` in each task body.
- `note: ignored #N …` on stderr: someone other than the workflow, the owner, a member, or a collaborator opened an issue that carries this backlog's marker. The publisher leaves it alone and publishes its own; check that issue and close it if it isn't yours.
- Every run says `created` for issues that already exist: they were opened by an identity the publisher doesn't recognize, such as a GitHub App. Add its bot login to `PUBLISHER_BOTS`.
- Project errors: `GITHUB_TOKEN` cannot use Projects; run the command locally after `gh auth refresh -s project`.
