#!/usr/bin/env python3
"""Render a validated backlog.json into a human-readable requirements brief (brief.md).

Both Plan solutions render with this script so reviewers compare like with like.
Every statement keeps its source citations, e.g. "(T04, POL-GOV-001)".

Usage
  python .github/skills/requirements-traceability/render_brief.py --backlog solutions/01-plan-github/brief/backlog.json
  python .github/skills/requirements-traceability/render_brief.py --backlog <path> --producer "Microsoft Foundry agent"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cite(sources: list[str]) -> str:
    return f" _({', '.join(sources)})_" if sources else ""


def render(data: dict, title: str, producer: str) -> str:
    brief, epic = data["brief"], data["epic"]
    lines = [
        f"# {title}",
        "",
        f"> Scenario `{data['scenario']}` · produced by **{producer}** · every line cites the transcript paragraph (Tnn) or policy it comes from.",
        "> Review this brief before publishing issues: it is a draft, not a decision record.",
        "",
        "## Problem",
        "",
        f"{brief['problem']['text']}{cite(brief['problem']['sources'])}",
        "",
        "## Goals",
        "",
        *[f"- {g['text']}{cite(g['sources'])}" for g in brief["goals"]],
        "",
        "## Requirements",
        "",
        "| ID | Priority | Requirement | Sources |",
        "| --- | --- | --- | --- |",
        *[f"| {r['id']} | {r['priority']} | {r['text']} | {', '.join(r['sources'])} |" for r in brief["requirements"]],
        "",
        "## Decisions",
        "",
        *([f"- **{d['id']}** {d['decision']}{cite(d['sources'])}" for d in data["decisions"]] or ["- None recorded."]),
        "",
        "## Conflicts",
        "",
        *([f"- **{c['id']}** {c['summary']}{cite(c['sources'])} → "
           + (f"resolved: {c['resolution']} ({c['resolvedBy']})" if c.get("resolution") else "**unresolved — needs a decision**")
           for c in data["conflicts"]] or ["- None found."]),
        "",
        "## Open questions",
        "",
        *([f"- **{q['id']}**{' (blocking)' if q['blocking'] else ''} {q['question']}{cite(q['sources'])}" for q in data["openQuestions"]] or ["- None."]),
        "",
        "## Out of scope",
        "",
        *([f"- {o['text']}{cite(o['sources'])}" for o in brief["outOfScope"]] or ["- Nothing stated."]),
        "",
        "## Success measures",
        "",
        *([f"- {m['text']}{cite(m['sources'])}" for m in brief["successMeasures"]] or ["- Not defined."]),
        "",
        f"## Engineering backlog: {epic['title']}",
        "",
        f"{epic['summary']}{cite(epic['sources'])}",
        "",
    ]
    for task in data["tasks"]:
        deps = ", ".join(task["dependsOn"]) or "none"
        lines += [
            f"### {task['id']} · {task['title']}",
            "",
            f"{task['description']}{cite(task['sources'])}",
            "",
            f"- **Owner role:** {task['ownerRole']}",
            f"- **Depends on:** {deps}",
            "- **Acceptance criteria:**",
            *[f"  - [ ] {c}" for c in task["acceptanceCriteria"]],
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backlog", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Write the brief here (default: brief.md next to the backlog)")
    parser.add_argument("--title", default="Requirements brief: assisted request triage")
    parser.add_argument("--producer", default="GitHub Copilot (plan-github agent)")
    args = parser.parse_args(argv)
    data = json.loads(args.backlog.read_text(encoding="utf-8"))
    out = args.out or args.backlog.with_name("brief.md")
    out.write_text(render(data, args.title, args.producer) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
