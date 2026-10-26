"""Mirror each solution's .github files into the repository's root .github folder.

GitHub only reads workflows, custom agents, skills, and issue templates from the root `.github/` folder. Each solution
keeps its own copy under `solutions/<id>/.github/` so the folder is self-contained and easy to adopt elsewhere. This
script copies those files to the root and checks that both copies match.

Usage:
  python tools/sync_solutions.py                   # copy solution files into .github/ (create or update)
  python tools/sync_solutions.py --check           # CI: exit 1 if a root copy is missing or different
  python tools/sync_solutions.py --check --strict  # also fail on root files that no solution owns (orphans)
  python tools/sync_solutions.py --pull .github/workflows/x.lock.yml
      # copy a root file back into the solution that owns it, for files generated at the root
      # (for example `gh aw compile` output)

Rules:
  - solutions/<id>/.github/<path> is mirrored to .github/<path>.
  - Two solutions may ship the same file (for example the same skill) only if the contents are identical.
  - Repository-wide files listed in SHARED are never mirrored; a solution must not ship a file with the same path.
  - Line endings are normalized to LF, matching .gitattributes.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOLUTIONS = REPO / "solutions"
ROOT_GITHUB = REPO / ".github"

# Repository-wide files that belong to no single solution.
SHARED = {
    ".github/copilot-instructions.md",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/copilot-setup-steps.yml",
    ".github/workflows/repo-checks.yml",
}


def normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def owner(source: Path) -> str:
    return source.relative_to(SOLUTIONS).parts[0]


def solution_files() -> dict[str, list[Path]]:
    """Map each root target (".github/...") to the solution files that provide it."""
    targets: dict[str, list[Path]] = defaultdict(list)
    for source in sorted(SOLUTIONS.glob("*/.github/**/*")):
        if source.is_file():
            targets["/".join(source.relative_to(SOLUTIONS).parts[1:])].append(source)
    return targets


def plan(targets: dict[str, list[Path]]) -> tuple[list[str], dict[str, bytes]]:
    """Validate the ownership rules and return (errors, expected root contents)."""
    errors: list[str] = []
    expected: dict[str, bytes] = {}
    for target, sources in sorted(targets.items()):
        owners = ", ".join(owner(s) for s in sources)
        if target in SHARED:
            errors.append(f"{target}: repository-wide file; remove it from {owners}")
            continue
        contents = {normalized(s) for s in sources}
        if len(contents) > 1:
            errors.append(f"{target}: {owners} ship different versions; make them identical")
            continue
        expected[target] = contents.pop()
    return errors, expected


def orphans(expected: dict[str, bytes]) -> list[str]:
    return [
        relative
        for path in sorted(ROOT_GITHUB.rglob("*"))
        if path.is_file()
        and (relative := path.relative_to(REPO).as_posix()) not in expected
        and relative not in SHARED
    ]


def sibling_owner(target: str, targets: dict[str, list[Path]]) -> str | None:
    """Owner of a file with the same name stem in the same folder (foo.lock.yml belongs with foo.md)."""
    folder, _, name = target.rpartition("/")
    stem = name.split(".")[0]
    for other, sources in targets.items():
        other_folder, _, other_name = other.rpartition("/")
        if other_folder == folder and other_name.split(".")[0] == stem:
            return owner(sources[0])
    return None


def pull(paths: list[str], targets: dict[str, list[Path]]) -> int:
    status = 0
    for raw in paths:
        target = Path(raw).resolve().relative_to(REPO).as_posix()
        sources = targets.get(target)
        if not sources:
            solution = sibling_owner(target, targets)
            if solution is None:
                print(f"error: no solution owns {target}; copy it to solutions/<id>/{target} first", file=sys.stderr)
                status = 1
                continue
            sources = [SOLUTIONS / solution / target]
        data = normalized(REPO / target)
        for source in sources:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
            print(f"pulled  {target} -> {source.relative_to(REPO).as_posix()}")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report differences instead of writing; exit 1 if any")
    parser.add_argument("--strict", action="store_true", help="with --check, also fail on root files no solution owns")
    parser.add_argument("--pull", nargs="+", metavar="PATH", help="copy root .github files back into their solution")
    args = parser.parse_args()

    targets = solution_files()
    if args.pull:
        return pull(args.pull, targets)

    errors, expected = plan(targets)
    drift = []
    for target, data in expected.items():
        destination = REPO / target
        current = normalized(destination) if destination.exists() else None
        if current == data:
            continue
        if args.check:
            drift.append(f"{target}: {'missing' if current is None else 'differs from the solution copy'}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            print(f"{'created' if current is None else 'updated'} {target}")

    stray = orphans(expected)
    for message in errors + drift:
        print(f"error: {message}", file=sys.stderr)
    for path in stray:
        print(f"{'error' if args.strict else 'warning'}: {path} is not owned by any solution", file=sys.stderr)
    if drift:
        print("Run `python tools/sync_solutions.py` and commit the result.", file=sys.stderr)

    failed = bool(errors or drift or (args.strict and stray))
    if not failed:
        print(f"OK: {len(expected)} solution files mirrored in .github/ ({len(stray)} root files not owned by a solution).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
