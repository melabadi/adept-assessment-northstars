"""What the run writes to GitHub: the review Issue, the epic, its tasks, and the comments on the review Issue.

The agent's answer is untrusted text. parse_brief() decodes the JSON first, so an @ the model wrote as \\u0040 is an @ by
then, and then puts a zero-width space after every @ in every string, so nothing the model writes can mention a person
or a team. The quoted sources get the same treatment. Table cells escape | and line breaks so a value can't break the
table. The evaluation scores the agent's unchanged text; only what reaches GitHub is neutralized.

Every Issue the run creates ends with an HTML comment marker (review_marker(), backlog_marker()). Before it creates an
Issue, the run looks for one that already ends with the same marker, so a retried step never creates an Issue twice.
Only an Issue opened by the repository's owner, a member, or a collaborator counts (steps.existing_issue()): anyone can
copy a marker into an Issue of their own.
"""
from __future__ import annotations

import json

from . import checks

ZERO_WIDTH_SPACE = "\u200b"
EXCERPT_LENGTH = 220
INPUTS_HINT = "see solutions/01-plan-microsoft/inputs/"
REVIEW_LABELS = ["ai-sdlc", "phase:plan", "track:microsoft", "type:brief"]
EPIC_LABELS = ["ai-sdlc", "phase:plan", "track:microsoft", "type:epic"]
TASK_LABELS = ["ai-sdlc", "phase:plan", "track:microsoft", "type:task"]
APPROVAL_LABEL = "brief-approved"
REVIEW_TITLE = "Plan: requirements brief for review (Foundry)"


def neutralize(value):
    """Every @ in every string gets a zero-width space after it: GitHub then mentions nobody."""
    if isinstance(value, str):
        return value.replace("@", "@" + ZERO_WIDTH_SPACE)
    if isinstance(value, list):
        return [neutralize(item) for item in value]
    if isinstance(value, dict):
        return {key: neutralize(item) for key, item in value.items()}
    return value


def parse_brief(text: str) -> dict:
    """The agent's answer as a neutralized JSON object. Raises ValueError when it isn't one."""
    brief = json.loads(text)
    if not isinstance(brief, dict):
        raise ValueError("the answer is JSON, but not an object")
    return neutralize(brief)


def excerpt(text: str) -> str:
    return text if len(text) <= EXCERPT_LENGTH else text[:EXCERPT_LENGTH - 3] + "..."


def source_excerpts(transcript: str, policies: str) -> dict[str, str]:
    """The quote each published Issue shows for a source id: transcript lines start with **[Tnn]**, and each policy is a
    table row | id | version | title | rule |."""
    quotes = {}
    for line in transcript.replace("\r", "").split("\n"):
        if line.startswith("**[T") and len(line) > 9:
            quotes[line[3:6]] = excerpt(line[9:].strip())
    for row in policies.replace("\r", "").split("\n"):
        if row.startswith("| POL-"):
            cells = [cell.strip() for cell in row.split("|")]
            if len(cells) >= 6:
                quotes[cells[1]] = excerpt(f'Policy "{cells[3]}" v{cells[2]}: {cells[4]}')
    return neutralize(quotes)


def cell(text) -> str:
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


def cites(item: dict) -> str:
    return ", ".join(item.get("sources") or [])


def lines_or(lines: list[str], empty: str) -> str:
    return "\n".join(lines) if lines else empty


def checklist(items: list[str], indent: str = "") -> str:
    return "\n".join(f"{indent}- [ ] {item}" for item in items)


def review_marker(run_id: str) -> str:
    return f"<!-- plan-microsoft run: {run_id} -->"


def backlog_marker(review_issue: int, item: str) -> str:
    return f"<!-- plan-microsoft: review #{review_issue}, {item} -->"


def task_section(task: dict) -> str:
    depends = ", ".join(task.get("dependsOn") or []) or "none"
    return (f"### {task.get('id')} · {task.get('title')}\n\n"
            f"{task.get('description')} _({cites(task)})_\n\n"
            f"- **Owner role:** {task.get('ownerRole')}\n"
            f"- **Depends on:** {depends}\n"
            f"- **Acceptance criteria:**\n"
            f"{checklist(task.get('acceptanceCriteria') or [], '  ')}")


def comparison_section(pull_request: int | None, copilot: list[dict] | None, copilot_error: str | None) -> str:
    if not pull_request:
        return ""
    if copilot is None:
        return (f"The Copilot brief from 01-plan-github pull request #{pull_request} couldn't be scored "
                f"({copilot_error or 'no result'}), so this run scored the Foundry brief alone.\n\n")
    rows = "\n".join(checks.score_rows(copilot, with_role=False))
    return (f"The same evaluation scored the Copilot brief from 01-plan-github pull request #{pull_request}:\n\n"
            f"| Check | Copilot |\n| --- | --- |\n{rows}\n\n")


def review_issue_body(*, run_id: str, agent: str, response_id: str, evaluation: str, brief: dict,
                      foundry: list[dict], pull_request: int | None = None, copilot: list[dict] | None = None,
                      copilot_error: str | None = None) -> str:
    """The review Issue: who drafted and scored the brief, how to decide, the scores, then the brief itself."""
    summary = brief.get("brief") or {}
    problem = summary.get("problem") or {}
    epic = brief.get("epic") or {}
    goals = [f"- {goal.get('text')} _({cites(goal)})_" for goal in summary.get("goals") or []]
    requirements = [f"| {cell(r.get('id'))} | {cell(r.get('priority'))} | {cell(r.get('text'))} | {cell(cites(r))} |"
                    for r in summary.get("requirements") or []]
    decisions = [f"- **{d.get('id')}** {d.get('decision')} _({cites(d)})_" for d in brief.get("decisions") or []]
    conflicts = []
    for conflict in brief.get("conflicts") or []:
        outcome = ("**unresolved: needs a decision**" if not conflict.get("resolution")
                   else f"resolved: {conflict.get('resolution')} ({conflict.get('resolvedBy') or ''})")
        conflicts.append(f"- **{conflict.get('id')}** {conflict.get('summary')} _({cites(conflict)})_ → {outcome}")
    questions = [f"- **{q.get('id')}**{' (blocking)' if q.get('blocking') is True else ''} {q.get('question')} _({cites(q)})_"
                 for q in brief.get("openQuestions") or []]
    out_of_scope = [f"- {item.get('text')} _({cites(item)})_" for item in summary.get("outOfScope") or []]
    measures = [f"- {item.get('text')} _({cites(item)})_" for item in summary.get("successMeasures") or []]
    tasks = "\n\n".join(task_section(task) for task in brief.get("tasks") or [])
    return (
        f"> Drafted by the Microsoft Foundry agent **{agent}** (response `{response_id}`) and scored by the Foundry "
        f"evaluation **{evaluation}**, in run `{run_id}` of the Azure Function app. Every line cites the transcript "
        f"paragraph (Tnn) or policy it comes from.\n\n"
        f"**To approve**, apply the `{APPROVAL_LABEL}` label: the Function app then creates the epic and its four tasks "
        f"as Issues. **To reject**, close this Issue. The Function app checks this Issue every 30 seconds, for up to "
        f"2 hours.\n\n"
        f"## Evaluation in Microsoft Foundry\n\n"
        f"Gates must pass before a brief reaches a reviewer. The other checks are reported for the reviewer. A check "
        f"marked not scored hit an error in the preview grading sandbox, which says nothing about the brief.\n\n"
        f"| Check | Role | Result |\n| --- | --- | --- |\n"
        f"{chr(10).join(checks.score_rows(foundry))}\n\n"
        f"{comparison_section(pull_request, copilot, copilot_error)}"
        f"## Problem\n\n{problem.get('text')} _({cites(problem)})_\n\n"
        f"## Goals\n\n{lines_or(goals, '- None stated.')}\n\n"
        f"## Requirements\n\n| ID | Priority | Requirement | Sources |\n| --- | --- | --- | --- |\n"
        f"{chr(10).join(requirements)}\n\n"
        f"## Decisions\n\n{lines_or(decisions, '- None recorded.')}\n\n"
        f"## Conflicts\n\n{lines_or(conflicts, '- None found.')}\n\n"
        f"## Open questions\n\n{lines_or(questions, '- None.')}\n\n"
        f"## Out of scope\n\n{lines_or(out_of_scope, '- Nothing stated.')}\n\n"
        f"## Success measures\n\n{lines_or(measures, '- Not defined.')}\n\n"
        f"## Engineering backlog: {epic.get('title')}\n\n"
        f"{epic.get('summary')} _({cites(epic)})_\n\n"
        f"{tasks}\n\n"
        f"{review_marker(run_id)}\n"
    )


def source_lines(ids: list[str], excerpts: dict[str, str]) -> str:
    return "\n".join(f"- **{source}**: {excerpts.get(source, INPUTS_HINT)}" for source in ids)


def epic_title(brief: dict) -> str:
    return f"[Plan/Foundry] {(brief.get('epic') or {}).get('title')}"


def epic_body(*, review_issue: int, brief: dict, excerpts: dict[str, str]) -> str:
    epic = brief.get("epic") or {}
    questions = [f"- [ ] **{q.get('id')}**{' (blocking)' if q.get('blocking') is True else ''}: {q.get('question')} ({cites(q)})"
                 for q in brief.get("openQuestions") or []]
    unresolved = [f"- **{c.get('id')}**: {c.get('summary')} ({cites(c)})"
                  for c in brief.get("conflicts") or [] if not c.get("resolution")]
    return (
        f"> Published by the Plan phase (Microsoft track) after a person approved review Issue #{review_issue}. The four "
        f"tasks are linked as sub-issues.\n\n"
        f"## Summary\n\n{epic.get('summary')}\n\n"
        f"## Acceptance criteria\n\n{checklist(epic.get('acceptanceCriteria') or [])}\n\n"
        f"## Open questions\n\n{lines_or(questions, '- None.')}\n\n"
        f"## Unresolved conflicts\n\n{lines_or(unresolved, '- None.')}\n\n"
        f"## Sources\n\n{source_lines(epic.get('sources') or [], excerpts)}\n\n"
        f"{backlog_marker(review_issue, 'epic')}\n"
    )


def task_title(task: dict) -> str:
    return f"[Plan/Foundry] {task.get('title')}"


def task_body(*, review_issue: int, epic_issue: int, task: dict, excerpts: dict[str, str]) -> str:
    depends = ", ".join(task.get("dependsOn") or []) or "none"
    return (
        f"**Epic:** #{epic_issue} · **Owner role:** {task.get('ownerRole')} · **Depends on:** {depends} · "
        f"**Backlog id:** `{task.get('id')}`\n\n"
        f"## Description\n\n{task.get('description')}\n\n"
        f"## Acceptance criteria\n\n{checklist(task.get('acceptanceCriteria') or [])}\n\n"
        f"## Sources\n\n{source_lines(task.get('sources') or [], excerpts)}\n\n"
        f"{backlog_marker(review_issue, task.get('id'))}\n"
    )


def published_comment(run_id: str, epic_issue: int, task_issues: list[int]) -> str:
    tasks = ", ".join(f"#{number}" for number in task_issues)
    return (f"### Backlog published after review\n\nA person applied `{APPROVAL_LABEL}`, so run `{run_id}` of the Azure "
            f"Function app created the backlog:\n\n- Epic: #{epic_issue}\n"
            f"- Tasks, linked to the epic as sub-issues: {tasks}\n")


def publishing_stopped_comment(run_id: str, epic_issue: int | None, task_issues: list[int], error: str) -> str:
    epic = f"epic #{epic_issue}" if epic_issue else "no epic"
    tasks = ", ".join(f"#{number}" for number in task_issues) or "none"
    return (f"### Publishing stopped\n\nRun `{run_id}` of the Azure Function app failed while publishing the backlog "
            f"({error}), so this review stays open. Created so far: {epic}; tasks: {tasks}. Their sub-issue links and "
            f"dependencies may be incomplete: finish or close them by hand, then start a new run if needed.\n")


def rejected_comment(run_id: str) -> str:
    return f"Closed without the `{APPROVAL_LABEL}` label, so run `{run_id}` of the Azure Function app published nothing."


def timed_out_comment(run_id: str) -> str:
    return (f"No decision within 2 hours, so run `{run_id}` of the Azure Function app stopped and published nothing. "
            f"Start a new run to try again.")


def cancelled_comment(run_id: str, epic_issue: int | None = None, task_issues: list[int] | None = None) -> str:
    if not epic_issue and not task_issues:
        return f"Run `{run_id}` was cancelled in Azure, so it published nothing."
    epic = f"epic #{epic_issue}" if epic_issue else "no epic"
    tasks = ", ".join(f"#{number}" for number in task_issues or []) or "none"
    return (f"Run `{run_id}` was cancelled in Azure while it was publishing, after it had made no progress for 5 minutes. "
            f"Created so far: {epic}; tasks: {tasks}. Finish or close them by hand.")
