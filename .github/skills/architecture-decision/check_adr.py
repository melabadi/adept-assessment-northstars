#!/usr/bin/env python3
"""Check Architecture Decision Records for completeness and honesty (architecture-decision skill).

Deterministic checks, run locally and by the `Design · checks` workflow on every PR that touches docs/adr/:
  1. Required sections: Context, Decision drivers, Options considered, Decision, Architecture, API impact,
     Threat model checklist, Consequences, Implementation tasks.
  2. At least two options are compared (### Option ... headings).
  3. Status is Proposed, Accepted, Rejected, or Superseded. A PR authored by an agent may only propose: an ADR
     with Status Accepted must name human deciders (not Copilot or an agent).
  4. Every cited standard id (STD-XXX-NNN) exists in phases/02-design/standards/.
  5. Every repository path written in backticks (for example `app/src/...`) exists.
  6. At least one mermaid diagram.

Usage
  python check_adr.py docs/adr/0001-live-triage-provider.md
  python check_adr.py docs/adr/*.md --json

Exit codes: 0 all ADRs pass, 1 problems found, 2 file error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STANDARDS = REPO / "phases/02-design/standards"
REQUIRED_SECTIONS = ["Context", "Decision drivers", "Options considered", "Decision", "Architecture", "API impact",
                     "Threat model checklist", "Consequences", "Implementation tasks"]
STATUSES = {"Proposed", "Accepted", "Rejected", "Superseded"}
PATH_PATTERN = re.compile(r"`((?:app|infra|phases|docs|\.github)/[^`\s*?<>]+)`")


def check(path: Path, known_standards: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = []
    headings = {h.strip().lower() for h in re.findall(r"^##\s+(.+)$", text, re.MULTILINE)}
    for section in REQUIRED_SECTIONS:
        if section.lower() not in headings:
            problems.append(f"missing section '## {section}'")
    options = re.findall(r"^###\s+Option\b", text, re.MULTILINE)
    if len(options) < 2:
        problems.append(f"compare at least two options (found {len(options)})")
    status = re.search(r"\*\*Status:\*\*\s*([A-Za-z]+)", text)
    if not status or status.group(1) not in STATUSES:
        problems.append("status must be one of Proposed, Accepted, Rejected, Superseded")
    elif status.group(1) == "Accepted":
        deciders = re.search(r"\*\*Deciders:\*\*\s*(.+)", text)
        if not deciders or re.search(r"copilot|agent|<", deciders.group(1), re.IGNORECASE):
            problems.append("an Accepted ADR must name human deciders; an agent can only propose")
    for standard in sorted(set(re.findall(r"STD-[A-Z]+-\d{3}", text)) - known_standards):
        problems.append(f"cites unknown standard {standard}")
    for ref in sorted(set(PATH_PATTERN.findall(text))):
        if not (REPO / ref.rstrip("/.,:;")).exists():
            problems.append(f"references missing path `{ref}`")
    if "```mermaid" not in text:
        problems.append("add at least one mermaid diagram (architecture or sequence)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("adrs", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    known = {p.stem for p in STANDARDS.glob("STD-*.md")}
    results = {}
    for adr in args.adrs:
        if adr.name.endswith("template.md"):
            continue
        try:
            results[str(adr)] = check(adr, known)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for adr, problems in results.items():
            print(f"{adr}: {'PASS' if not problems else f'FAIL ({len(problems)})'}")
            for problem in problems:
                print(f"  - {problem}")
    return 0 if all(not p for p in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
