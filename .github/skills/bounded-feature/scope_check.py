#!/usr/bin/env python3
"""Check that a feature change stays inside its bounds (bounded-feature skill).

Run it before opening a PR, and in review. It compares the working tree (committed and uncommitted changes) with the merge
base of --base and fails when a change crosses a boundary that a feature must not cross without an explicit decision:

  1. Out-of-scope paths: CI/CD workflows, infrastructure, and existing database migrations (new migrations are allowed).
  2. Approval authority: the body of RequestWorkflow.DecideAsync and the approval rules in PermissionsFor are unchanged.
  3. Tests: no test was deleted (count of [Fact]/[Theory] in C# tests and test()/it() in web tests must not drop).
  4. Contract: app/contracts/openapi.json changes are additive only (uses the contract-impact skill).

Usage
  python .github/skills/bounded-feature/scope_check.py                 # against origin/main
  python .github/skills/bounded-feature/scope_check.py --base main
  python .github/skills/bounded-feature/scope_check.py --allow infra/   # accept a boundary on purpose (state why in the PR)

Exit codes: 0 within bounds, 1 a boundary was crossed, 2 git or configuration error.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"
OUT_OF_SCOPE = (".github/workflows/", "infra/", "azure.yaml")
MIGRATIONS = "app/src/RequestHub.Core/Data/Migrations/"
CS_TEST = re.compile(r"\[(Fact|Theory)\b")
TS_TEST = re.compile(r"^\s*(test|it)(\.\w+)?\(", re.M)


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def at_base(base: str, path: str) -> str:
    try:
        return git("show", f"{base}:{path}")
    except RuntimeError:
        return ""


def member(source: str, signature: str) -> str:
    """Text of the C# member whose declaration contains `signature`, found by brace matching ('' when absent)."""
    start = source.find(signature)
    if start < 0:
        return ""
    depth, i = 0, source.find("{", start)
    if i < 0:
        return ""
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return re.sub(r"\s+", " ", source[start:j + 1])
    return ""


def approval_rules(source: str) -> str:
    """The lines of PermissionsFor that compute who may decide (the `blocked` reason chain)."""
    body = member(source, "public static PermissionsDto PermissionsFor(")
    return " ".join(re.findall(r"(?:if|else if) \([^;]*blocked = \"[a-z_]+\";", body))


def count_tests(paths: list[str], base: str | None) -> int:
    total = 0
    for path in paths:
        text = at_base(base, path) if base else ((REPO / path).read_text(encoding="utf-8") if (REPO / path).exists() else "")
        total += len(CS_TEST.findall(text)) if path.endswith(".cs") else len(TS_TEST.findall(text))
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="Base branch or ref (default origin/main)")
    parser.add_argument("--allow", action="append", default=[], help="Path prefix to accept on purpose (repeatable)")
    args = parser.parse_args(argv)

    try:
        merge_base = git("merge-base", args.base, "HEAD").strip()
        status = git("diff", "--name-status", "--no-renames", merge_base)
        untracked = git("ls-files", "--others", "--exclude-standard").split()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    changes = [line.split("\t", 1) for line in status.splitlines() if "\t" in line] + [["A", p] for p in untracked]
    changes = [(kind[0], path.replace("\\", "/")) for kind, path in changes]
    problems: list[str] = []

    for kind, path in changes:
        if any(path.startswith(prefix) for prefix in args.allow):
            continue
        if path.startswith(OUT_OF_SCOPE):
            problems.append(f"out of scope for a feature: {path}")
        if path.startswith(MIGRATIONS) and kind != "A":
            problems.append(f"existing migration changed or deleted (add a new migration instead): {path}")

    head_source = (REPO / WORKFLOW).read_text(encoding="utf-8")
    base_source = at_base(merge_base, WORKFLOW)
    decide = "public async Task<Result<DecisionDto>> DecideAsync("
    if member(base_source, decide) != member(head_source, decide):
        problems.append("approval authority changed: RequestWorkflow.DecideAsync differs from the base")
    if approval_rules(base_source) != approval_rules(head_source):
        problems.append("approval authority changed: the CanDecide rules in RequestWorkflow.PermissionsFor differ from the base")

    test_files = sorted({p for _, p in changes if re.search(r"(^app/tests/.*\.cs$)|(\.(test|spec)\.tsx?$)", p)})
    before, after = count_tests(test_files, merge_base), count_tests(test_files, None)
    if after < before:
        problems.append(f"tests removed: {before} test cases in the changed test files at the base, {after} now")

    contract = "app/contracts/openapi.json"
    if any(p == contract for _, p in changes):
        proc = subprocess.run([sys.executable, str(REPO / ".github/skills/contract-impact/contract_diff.py"), "--base-ref", merge_base,
                               "--fail-on-breaking"], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            problems.append("contract change is not additive:\n" + proc.stdout.strip())

    print(f"compared with {args.base} (merge base {merge_base[:9]}): {len(changes)} changed file(s)")
    for kind, path in changes:
        print(f"  {kind} {path}")
    for problem in problems:
        print(f"FAIL {problem}")
    print("PASS change stays within feature bounds" if not problems else f"{len(problems)} boundary problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
