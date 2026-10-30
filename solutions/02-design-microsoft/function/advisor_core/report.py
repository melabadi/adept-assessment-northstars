"""Markdown the advisor posts to GitHub: the issue comment, the ADR draft, and the pull request text.

Everything here is plain text built from the checked answer, so the Function stays the only place that talks to
GitHub. Nothing names an Azure host, resource, or tenant: only the agent, the model, the response id, and the
Logic App run name, which identify the evidence without exposing where it lives.

The model's text reaches GitHub only when the gate passed. A rejected answer's comment says which checks failed,
inside a code block (so nothing in it renders as a link or notifies anyone), and shows none of the answer. In an
accepted answer, @mentions are neutralized so the model can't notify people.
"""
from __future__ import annotations

import re

from . import checks

ADVISORY = "Advisory only: an architect accepts or rejects the ADR draft."
HEADING = "### Foundry architecture advisor"


def cell(text) -> str:
    return " ".join(quiet(text).split()).replace("|", "\\|")


def quiet(text) -> str:
    """Wrap @mentions in backticks: GitHub renders them as code and notifies nobody. GitHub also mentions after an
    underscore or a non-ASCII letter (_@name_, é@name), so only an ASCII letter or digit in front (an e-mail address)
    leaves the text alone."""
    return re.sub(r"(?<![A-Za-z0-9`])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))", r"`@\1`", str(text))


def checks_line(run: dict) -> str:
    if not run["checks"]:
        return (f"✅ Deterministic checks passed: every citation exists in the index, is inside the {run['profile']} scope, "
                "matches the indexed version, and quotes the standard word for word.")
    problems = "\n".join(f"- {problem}" for problem in run["checks"]).replace("```", "'''")
    return f"❌ The deterministic checks rejected this answer:\n\n```text\n{problems}\n```"


def evidence_line(run: dict) -> str:
    seconds = f" · {run['durationSeconds']} s" if run.get("durationSeconds") is not None else ""
    workflow = f" · Logic App run `{run['workflowRun']}`" if run.get("workflowRun") else ""
    return (f"Agent `{run['agent']['name']}` v{run['agent']['version']} · model `{run['model']}` · response "
            f"`{run['responseId']}` · {run['knowledgeCalls']} knowledge call(s){seconds}{workflow}")


def summary_markdown(run: dict) -> str:
    """The accepted answer, as the issue comment shows it."""
    data = run["result"]
    lines = [f"{HEADING} · {run['profile']} profile", ""]
    if data["answerable"]:
        lines += [f"**Recommendation:** {quiet(data.get('recommendation') or '_none_')}", ""]
    else:
        lines += ["**Abstained:** the approved standards do not answer this question.", ""]
    lines += [quiet(data.get("summary", "")), ""]
    if data["constraints"]:
        if not data["answerable"]:
            lines += ["Related standards it found, none of which answers the question:", ""]
        lines += ["| Standard | Version | Requirement |", "| --- | --- | --- |"]
        lines += [f"| {cell(c['standardId'])} | {cell(checks.bare_version(c['version']))} | {cell(c['requirement'])} |"
                  for c in data["constraints"]]
        lines += [""]
    if data["conflicts"]:
        lines += ["**Conflicts needing a decision:**", ""]
        lines += [f"- {quiet(', '.join(c['standards']))}: {quiet(c['description'])}" for c in data["conflicts"]] + [""]
    if data["unknowns"]:
        lines += ["**Unknowns:**", ""] + [f"- {quiet(u)}" for u in data["unknowns"]] + [""]
    lines += [checks_line(run), ""]
    return "\n".join(lines)


def comment_markdown(run: dict, pull_request: int | None = None) -> str:
    """The issue comment. Accepted: the answer, the ADR draft, the evidence. Rejected: only the failed checks."""
    if run["checks"]:
        lines = [f"{HEADING} · {run['profile']} profile", "", checks_line(run), "",
                 "The answer is not shown and no ADR draft was proposed. Rephrase the question or ask an architect.", ""]
    else:
        lines = [summary_markdown(run)]
        if pull_request:
            lines += [f"**ADR draft: #{pull_request}.** An architect accepts it by merging the pull request or rejects it "
                      "by closing it.", ""]
    lines += [f"<sub>{evidence_line(run)}. {ADVISORY}</sub>", ""]
    return "\n".join(lines)


def unavailable_markdown(workflow_run: str = "") -> str:
    """The issue comment when the advisor could not answer (service error), so the question is never left silent."""
    where = f" Logic App run `{workflow_run}` has the details." if workflow_run else ""
    return (f"{HEADING}\n\n⚠️ The advisor could not answer this question right now, so no ADR draft was proposed."
            f"{where} A maintainer can resubmit the run once the service is available.\n")


def incomplete_markdown(workflow_run: str = "") -> str:
    """The issue comment when the answer passed the gate but a GitHub step after it failed."""
    where = f" Logic App run `{workflow_run}` has the details." if workflow_run else ""
    return (f"{HEADING}\n\n⚠️ The advisor answered, but the ADR draft or its comment could not be completed.{where} "
            "A maintainer can resubmit the run: it reuses the branch and the pull request it already created.\n")


def adr_markdown(run: dict) -> str:
    """Architecture decision record with status Proposed, for an architect to accept or reject."""
    data = run["result"]
    first_line = run["question"].strip().splitlines()[0]
    title = first_line if len(first_line) <= 90 else first_line[:90].rsplit(" ", 1)[0] + "…"
    # Metadata as a list, not a table: GitHub renders a table's empty header row as a blank first row.
    metadata = ["- **Status:** Proposed. An architect accepts or rejects it in review."]
    if run.get("issue"):
        metadata.append(f"- **Issue:** #{run['issue']}")
    metadata += [
        f"- **Drafted by:** Microsoft Foundry agent `{run['agent']['name']}` v{run['agent']['version']}, model `{run['model']}`",
        f"- **Evidence:** response `{run['responseId']}` at {run['startedAt']}. Its {run['knowledgeCalls']} knowledge call(s) "
        f"retrieved {', '.join(run['retrievedStandards']) or 'no standards'}.",
        f"- **Operating profile:** {run['profile']}, which may retrieve the standards with scope "
        f"{', '.join(run['scopes'])} in the `{run['index']}` index",
        f"- **Deterministic checks:** {'passed' if not run['checks'] else 'failed: ' + '; '.join(run['checks'])}",
    ]
    lines = [f"# ADR draft: {title}", "", *metadata, "",
             "## Context", "", run["question"].strip(), "",
             "## Summary", "", data.get("summary", ""), ""]
    if data["options"]:
        lines += ["## Options considered", ""]
        for option in data["options"]:
            lines += [f"### {option['name']}", "", option["description"], ""]
            lines += [f"- ✅ {p}" for p in option["pros"]] + [f"- ⚠️ {c}" for c in option["cons"]]
            lines += [f"- Standards: {', '.join(option['standards']) or 'none'}", ""]
    lines += ["## Recommendation", "",
              data.get("recommendation") or "_No recommendation: the approved standards do not answer this question._", ""]
    lines += ["## Constraints from approved standards", "",
              "| Standard | Version | Requirement | Source excerpt |", "| --- | --- | --- | --- |"]
    lines += [f"| {cell(c['standardId'])} | {cell(checks.bare_version(c['version']))} | {cell(c['requirement'])} | "
              f"\"{cell(c['excerpt'])}\" |" for c in data["constraints"]] or ["| none | | | |"]
    lines += ["", "## Conflicts needing a decision", ""]
    lines += [f"- {', '.join(c['standards'])}: {c['description']}" for c in data["conflicts"]] or ["- None found."]
    lines += ["", "## Unknowns", ""] + ([f"- {u}" for u in data["unknowns"]] or ["- None."])
    lines += ["", "## Review", "",
              "- [ ] Citations, versions, and excerpts checked against the standards",
              "- [ ] Each conflict and unknown has an owner",
              "- [ ] Decision: accept (set Status to Accepted and merge) or reject (close the pull request)", ""]
    return "\n".join(lines)


def pull_request_text(run: dict, path: str) -> tuple[str, str]:
    """Title and body of the ADR draft pull request."""
    title = f"Design: ADR draft for #{run['issue']} (Foundry advisor)"
    body = "\n".join([
        f"Closes #{run['issue']}. ADR draft from the Microsoft Foundry agent **{run['agent']['name']}** "
        f"v{run['agent']['version']} (response `{run['responseId']}`). Its citations passed the deterministic checks "
        "against the standards index before this pull request was opened.",
        "",
        f"Review it like any ADR: check the citations, versions, and excerpts in `{path}` against "
        "`solutions/02-design-microsoft/standards/`, and give each conflict and unknown an owner. Merge to accept, "
        "close to reject.",
        "",
        f"<sub>Opened by the advisor's Azure Logic App{' run `' + run['workflowRun'] + '`' if run.get('workflowRun') else ''}. "
        f"{ADVISORY}</sub>",
    ])
    return title, body
