#!/usr/bin/env python3
"""Check architecture decision records (ADRs) for completeness and honesty (architecture-decision skill).

Every check is deterministic, so a model cannot argue its way past one. The workflow
"Design · GitHub · check the ADR and API impact" runs this script, taken from the base branch, on every pull request
that adds or changes an ADR.

Checks
  1. Sections: every `## ` section of the template is present: Context, Decision drivers, Options considered,
     Decision, Architecture, API impact, Threat model checklist, Consequences, Implementation tasks, Open questions.
  2. Options: at least two `### Option ...` headings.
  3. Diagrams: a mermaid architecture diagram (`flowchart` or `graph`) and a mermaid `sequenceDiagram`.
  4. Decisions belong to people: Status is Proposed, Accepted, Rejected, or Superseded, and any status other than
     Proposed must name the people who decided in **Deciders:**, never Copilot, an agent, a bot, or a placeholder.
  5. Standards: the ADR cites at least one standard, every cited id (STD-XXX-NNN) exists, and a cited version
     (`STD-OBS-001 v1.2`) matches the standard's current version.
  6. Paths: every repository path written in backticks (for example `app/src/...`) exists and uses forward slashes.
     A line or anchor suffix (`:42`, `#L42`) is allowed. Describe files that do not exist yet in plain words, without
     backticks.
  7. No template text left: placeholders from adr-template.md (such as `<option name>` or `YYYY-MM-DD`) are replaced.

Usage
  python .github/skills/architecture-decision/check_adr.py solutions/02-design-github/adr/0001-live-triage-provider.md
  python .github/skills/architecture-decision/check_adr.py solutions/02-design-github/adr/*.md --json

The standards are found automatically: the nearest `standards/` folder above the ADR that contains STD-*.md files
(for example solutions/02-design-github/standards/). Backticked paths are resolved against the git repository that
contains the ADR. Use --standards and --repo to choose other folders.

Exit codes: 0 every ADR passes, 1 problems found, 2 usage or file error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "adr-template.md"
REQUIRED_SECTIONS = ["Context", "Decision drivers", "Options considered", "Decision", "Architecture", "API impact",
                     "Threat model checklist", "Consequences", "Implementation tasks", "Open questions"]
STATUSES = {"Proposed", "Accepted", "Rejected", "Superseded"}
NOT_A_PERSON = re.compile(r"copilot|agent|\bbot\b|\[bot\]|\bTBD\b|to be (decided|named|confirmed)", re.IGNORECASE)
STANDARD_ID = re.compile(r"\bSTD-[A-Z]+-\d{3}\b")
STANDARD_VERSION = re.compile(r"\b(STD-[A-Z]+-\d{3})\s*\(?\s*v(\d+(?:\.\d+)*)\b")
BACKTICKED = re.compile(r"`([^`\s]+)`")
LOCATION_SUFFIX = re.compile(r"(#.*|:\d+(-\d+)?)$")


def find_repo(adr: Path) -> Path:
    """The git repository that contains the ADR (a folder with .git), or the current folder."""
    for folder in adr.resolve().parents:
        if (folder / ".git").exists():
            return folder
    return Path.cwd()


def find_standards(adr: Path) -> Path:
    """The nearest standards/ folder above the ADR that holds STD-*.md files."""
    for folder in adr.resolve().parents:
        candidate = folder / "standards"
        if candidate.is_dir() and any(candidate.glob("STD-*.md")):
            return candidate
    raise FileNotFoundError(f"no standards/ folder with STD-*.md files above {adr}; pass --standards")


def load_standards(folder: Path) -> dict[str, str]:
    """Map each standard id to its version, read from the front matter (`id:` and `version:`)."""
    standards = {}
    for path in sorted(folder.glob("STD-*.md")):
        text = path.read_text(encoding="utf-8")
        front = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        fields = dict(re.findall(r"^(\w+):\s*\"?([^\"\n]*?)\"?\s*$", front.group(1), re.MULTILINE)) if front else {}
        standards[fields.get("id") or path.stem] = fields.get("version", "")
    return standards


def template_placeholders() -> set[str]:
    """Placeholder text in adr-template.md (`<...>`, `ADR NNNN`, `YYYY-MM-DD`) that a finished ADR must replace."""
    if not TEMPLATE.is_file():
        return set()
    text = TEMPLATE.read_text(encoding="utf-8")
    return set(re.findall(r"<[^<>\n]+>", text)) | {token for token in ("ADR NNNN", "YYYY-MM-DD") if token in text}


def same_version(cited: str, current: str) -> bool:
    def parts(version: str) -> list[int]:
        numbers = [int(n) for n in re.findall(r"\d+", version)]
        while len(numbers) > 1 and numbers[-1] == 0:
            numbers.pop()
        return numbers
    return parts(cited) == parts(current)


def repository_paths(text: str, repo: Path) -> dict[str, str]:
    """Backticked tokens that start with a top-level folder of the repository, such as `app/...` or `.github/...`.

    Returns {token as written: path with forward slashes}, so Windows-style paths are checked too."""
    top = {p.name for p in repo.iterdir() if p.is_dir() and p.name != ".git"}
    paths = {}
    for token in BACKTICKED.findall(text):
        path = LOCATION_SUFFIX.sub("", token.rstrip(".,;)")).replace("\\", "/")
        first, slash, _ = path.partition("/")
        if slash and first in top and not re.search(r"[*?<>{}$]", path):
            paths[token] = path
    return paths


def check(adr: Path, standards: dict[str, str], repo: Path, placeholders: set[str]) -> list[str]:
    text = adr.read_text(encoding="utf-8")
    problems = []

    headings = {h.strip().lower() for h in re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)}
    for section in REQUIRED_SECTIONS:
        if section.lower() not in headings:
            problems.append(f"missing section '## {section}'")

    options = re.findall(r"^###\s+Option\b", text, re.MULTILINE)
    if len(options) < 2:
        problems.append(f"compare at least two options with '### Option ...' headings (found {len(options)})")

    diagrams = re.findall(r"```mermaid[^\n]*\n(.*?)```", text, re.DOTALL)
    if not any(re.search(r"^\s*(flowchart|graph)\b", d, re.MULTILINE) for d in diagrams):
        problems.append("add a mermaid architecture diagram (flowchart)")
    if not any(re.search(r"^\s*sequenceDiagram\b", d, re.MULTILINE) for d in diagrams):
        problems.append("add a mermaid sequence diagram of one request (sequenceDiagram)")

    status = re.search(r"\*\*Status:\*\*\s*([A-Za-z]+)", text)
    if not status or status.group(1) not in STATUSES:
        problems.append("status must be one of Proposed, Accepted, Rejected, Superseded")
    elif status.group(1) != "Proposed":
        deciders = re.search(r"\*\*Deciders:\*\*[ \t]*(.*)", text)
        named = re.sub(r"<[^<>]*>", "", deciders.group(1)).strip(" -—") if deciders else ""
        if not named or NOT_A_PERSON.search(named):
            problems.append(f"status {status.group(1)} must name the people who decided in **Deciders:**; "
                            "an agent can only propose")

    cited = set(STANDARD_ID.findall(text))
    if not cited:
        problems.append("cite at least one approved standard by id (STD-XXX-NNN)")
    for standard in sorted(cited - standards.keys()):
        problems.append(f"cites unknown standard {standard}")
    for standard, version in sorted(set(STANDARD_VERSION.findall(text))):
        current = standards.get(standard)
        if current and not same_version(version, current):
            problems.append(f"cites {standard} v{version}, but the approved version is v{current}")

    paths = repository_paths(text, repo)
    for path in sorted(set(paths.values())):
        if not (repo / path).exists():
            problems.append(f"references missing path `{path}`")
    for token in sorted(t for t in paths if "\\" in t):
        problems.append(f"write repository paths with forward slashes: `{token}`")

    for placeholder in sorted(p for p in placeholders if p in text):
        problems.append(f"still contains template text {placeholder}")
    return problems


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("adrs", nargs="+", type=Path, metavar="ADR", help="ADR markdown files to check")
    parser.add_argument("--standards", type=Path,
                        help="folder with the approved STD-*.md files (default: nearest standards/ folder above each ADR)")
    parser.add_argument("--repo", type=Path,
                        help="root that backticked paths are resolved against (default: the git repository of each ADR)")
    parser.add_argument("--json", action="store_true", help="print a machine-readable report: {adr: [problems]}")
    args = parser.parse_args(argv)

    placeholders = template_placeholders()
    results: dict[str, list[str]] = {}
    for adr in args.adrs:
        if adr.name.endswith("template.md"):
            continue
        try:
            standards = load_standards(args.standards or find_standards(adr))
            results[adr.as_posix()] = check(adr, standards, (args.repo or find_repo(adr)).resolve(), placeholders)
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
