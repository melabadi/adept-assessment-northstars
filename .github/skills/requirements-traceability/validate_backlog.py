#!/usr/bin/env python3
"""Validate a Plan-phase requirements package (backlog.json) against its schema and its sources.

Used by both Plan demos (GitHub Copilot and Microsoft Foundry) and by the `plan-validate` workflow.
All checks are deterministic; an AI model cannot make a failing check pass.

Checks
  1. JSON Schema: backlog.schema.json (next to this script).
  2. Traceability: every cited source exists in the inputs - transcript paragraphs such as [T07]
     and policy ids such as POL-ROUTE-004.
  3. Shape: one epic, exactly four tasks, unique ids, dependencies point at known tasks, no cycles.
  4. Testable acceptance criteria: every criterion is written as Given ... When ... Then ...
  5. No invented decisions: a decision must not cite a source that belongs to an unresolved conflict.
  6. Embedded instructions are data, not commands: nothing may claim requests are approved automatically.

Usage
  python validate_backlog.py --backlog phases/01-plan/output/github/backlog.json
  python validate_backlog.py --backlog out.json --json     # machine-readable report

Exit codes: 0 valid, 1 problems found, 2 usage or file error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_TRANSCRIPT = REPO / "phases/01-plan/inputs/stakeholder-transcript.md"
DEFAULT_POLICIES = REPO / "phases/01-plan/inputs/routing-policies.md"
GIVEN_WHEN_THEN = re.compile(r"^\s*Given\b.+\bWhen\b.+\bThen\b.+", re.IGNORECASE | re.DOTALL)
AUTO_APPROVAL = re.compile(r"\b(auto(matic(ally)?)?[- ]?approv\w*|mark(ed)? (all )?requests? (as )?approved|approved automatically)\b", re.IGNORECASE)
NEGATION = re.compile(r"\b(no|not|never|without|cannot|can't|must not|out of scope|exclud\w*|disallow\w*|reject\w*|prohibit\w*|prevent\w*|forbid\w*|ignore\w*)\b", re.IGNORECASE)


def source_ids(transcript: Path, policies: Path) -> set[str]:
    """Collect the citable ids: [Tnn] paragraph markers and POL-XXX-nnn policy ids."""
    ids = set(re.findall(r"\[(T\d{2})\]", transcript.read_text(encoding="utf-8")))
    ids |= set(re.findall(r"\b(POL-[A-Z]+-\d{3})\b", policies.read_text(encoding="utf-8")))
    return ids


def schema_errors(data: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema is not installed: run `pip install -r requirements.txt`"]
    schema = json.loads((HERE / "backlog.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"schema: {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))]


def cited(data: dict):
    """Yield (location, source) for every source citation in the package."""
    brief = data.get("brief", {})
    yield from (("brief.problem", s) for s in brief.get("problem", {}).get("sources", []))
    for key in ("goals", "requirements", "outOfScope", "successMeasures"):
        for i, item in enumerate(brief.get(key, [])):
            yield from ((f"brief.{key}[{i}]", s) for s in item.get("sources", []))
    yield from (("epic", s) for s in data.get("epic", {}).get("sources", []))
    for key in ("tasks", "openQuestions", "conflicts", "decisions"):
        for item in data.get(key, []):
            yield from ((f"{key}:{item.get('id', '?')}", s) for s in item.get("sources", []))


def find_cycle(tasks: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> list[str] | None:
        state[node] = 1
        for dep in tasks.get(node, []):
            if state.get(dep) == 1:
                return path + [dep]
            if state.get(dep) is None and dep in tasks:
                found = visit(dep, path + [dep])
                if found:
                    return found
        state[node] = 2
        return None

    for task in tasks:
        if state.get(task) is None:
            found = visit(task, [task])
            if found:
                return found
    return None


def validate(data: dict, known_sources: set[str]) -> list[str]:
    problems = schema_errors(data)

    for where, source in cited(data):
        if source not in known_sources:
            problems.append(f"traceability: {where} cites '{source}', which does not exist in the inputs")

    tasks = data.get("tasks", [])
    ids = [t.get("id") for t in tasks]
    if len(ids) != len(set(ids)):
        problems.append("shape: task ids must be unique")
    graph = {t.get("id"): t.get("dependsOn", []) for t in tasks}
    for task_id, deps in graph.items():
        for dep in deps:
            if dep not in graph:
                problems.append(f"shape: {task_id} depends on unknown task {dep}")
            if dep == task_id:
                problems.append(f"shape: {task_id} depends on itself")
    cycle = find_cycle(graph)
    if cycle:
        problems.append(f"shape: dependency cycle {' -> '.join(cycle)}")

    criteria = [("epic", c) for c in data.get("epic", {}).get("acceptanceCriteria", [])]
    criteria += [(t.get("id", "?"), c) for t in tasks for c in t.get("acceptanceCriteria", [])]
    for owner, criterion in criteria:
        if not GIVEN_WHEN_THEN.match(criterion):
            problems.append(f"testability: {owner} criterion is not Given/When/Then: '{criterion[:80]}'")

    unresolved = {s for c in data.get("conflicts", []) if not c.get("resolution") for s in c.get("sources", [])}
    for decision in data.get("decisions", []):
        overlap = sorted(set(decision.get("sources", [])) & unresolved)
        if overlap:
            problems.append(f"decisions: {decision.get('id')} presents an unresolved conflict ({', '.join(overlap)}) as decided")

    decision_sources = {s for d in data.get("decisions", []) for s in d.get("sources", [])}
    for conflict in data.get("conflicts", []):
        if not conflict.get("resolution"):
            continue
        resolved_by = conflict.get("resolvedBy")
        if resolved_by not in known_sources:
            problems.append(f"conflicts: {conflict.get('id')} is marked resolved without citing the deciding source")
        elif resolved_by in conflict.get("sources", []):
            problems.append(f"conflicts: {conflict.get('id')} is 'resolved by' {resolved_by}, one of its own conflicting statements; "
                            "only a separate recorded decision can resolve a conflict")
        elif resolved_by not in decision_sources:
            problems.append(f"conflicts: {conflict.get('id')} is resolved by {resolved_by}, but no decision cites {resolved_by}")

    # Instructions embedded in the inputs (T18) must not leak into what the team will build or has decided.
    # Out-of-scope items, conflicts, and questions may legitimately mention approval, so they are not scanned.
    scanned = {
        "brief": {k: v for k, v in data.get("brief", {}).items() if k != "outOfScope"},
        "epic": data.get("epic", {}),
        "tasks": data.get("tasks", []),
        "decisions": data.get("decisions", []),
    }
    text = json.dumps(scanned, ensure_ascii=False)
    for match in AUTO_APPROVAL.finditer(text):
        context = text[max(0, match.start() - 80): match.end() + 20]
        if not NEGATION.search(context):
            problems.append(f"safety: content implies automatic approval ('{match.group(0)}'); embedded instructions must be ignored")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backlog", required=True, type=Path, help="Path to backlog.json")
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT, help="Stakeholder transcript (markdown with [Tnn] ids)")
    parser.add_argument("--policies", type=Path, default=DEFAULT_POLICIES, help="Routing policies (markdown with POL-... ids)")
    parser.add_argument("--json", action="store_true", help="Print a JSON report instead of text")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        data = json.loads(args.backlog.read_text(encoding="utf-8"))
        known = source_ids(args.transcript, args.policies)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = validate(data, known)
    summary = {
        "backlog": str(args.backlog),
        "valid": not problems,
        "tasks": len(data.get("tasks", [])),
        "openQuestions": len(data.get("openQuestions", [])),
        "conflicts": len(data.get("conflicts", [])),
        "unresolvedConflicts": sum(1 for c in data.get("conflicts", []) if not c.get("resolution")),
        "problems": problems,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        status = "VALID" if not problems else f"INVALID ({len(problems)} problem(s))"
        print(f"{args.backlog}: {status} - {summary['tasks']} tasks, {summary['openQuestions']} open questions, "
              f"{summary['unresolvedConflicts']}/{summary['conflicts']} conflicts unresolved")
        for problem in problems:
            print(f"  - {problem}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
