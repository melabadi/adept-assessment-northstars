#!/usr/bin/env python3
"""Check that a feature change stays inside its bounds (bounded-feature skill).

A feature may change the app and its tests. It must not change the rules it is judged by, the infrastructure the app
runs on, or who may approve. This script compares a change with the merge base of --base and fails when the change
crosses one of these boundaries:

  1. Scope: every changed file is under app/, outside app/infra/. CI/CD and agent configuration (.github/),
     infrastructure (infra/ folders, azure.yaml, Bicep files), and everything outside the app are out of scope.
  2. Migrations: existing EF Core migrations stay as they are. Adding a migration (which also updates the model
     snapshot) is fine.
  3. Approval authority: RequestWorkflow.DecideAsync and the approval rules in RequestWorkflow.PermissionsFor are
     unchanged, and no other code starts recording decisions, setting a request to Approved or Rejected, or calling
     the decision API from the web UI.
  4. Tests: no test is deleted or skipped, and a change to app code comes with a change to its tests.
  5. Contract: changes to app/contracts/openapi.json are additive only (uses the contract-impact skill).

By default it checks your working tree: commits since the merge base plus uncommitted and untracked files. With
--head it checks the commits of that ref instead and never reads the working tree. CI uses this to run the checker
from the base branch against a pull request's commits, so a pull request cannot change the checker that judges it.

Usage
  python .github/skills/bounded-feature/scope_check.py                       # working tree against origin/main
  python .github/skills/bounded-feature/scope_check.py --base main
  python .github/skills/bounded-feature/scope_check.py --head origin/copilot/my-feature
  python .github/skills/bounded-feature/scope_check.py --allow app/infra/    # accept a path on purpose; say why in the PR

Exit codes: 0 within bounds, 1 a boundary was crossed, 2 git or configuration error.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP = "app/"
WORKFLOW = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"
MIGRATIONS = "app/src/RequestHub.Core/Data/Migrations/"
CONTRACT = "app/contracts/openapi.json"
CONTRACT_DIFF = ".github/skills/contract-impact/contract_diff.py"
DECIDE = "public async Task<Result<DecisionDto>> DecideAsync("
PERMISSIONS = "public static PermissionsDto PermissionsFor("

TEST_FILE = re.compile(r"(^app/tests/.*\.cs$)|(\.(test|spec)\.tsx?$)")
CODE_FILE = re.compile(r"^app/(src|web/src)/.*\.(cs|tsx?)$")
CS_TEST = re.compile(r"\[(Fact|Theory)\b")
TS_TEST = re.compile(r"^\s*(test|it)(\.\w+)?\(", re.M)
SKIPPED = re.compile(r"\bSkip\s*=|\b(test|it|describe)\.(skip|fixme|only)\(")
# Code that records a decision: a new ApprovalDecision, an insert into Decisions, a status set to Approved/Rejected.
DECISION_WRITE = re.compile(
    r"\bnew\s+ApprovalDecision\b|\bDecisions\s*\.\s*Add(Range)?\s*\(|\bStatus\s*=(?!=)[^;,(){}]*\bRequestStatus\s*\.\s*(Approved|Rejected)\b")
DECISION_CALL = re.compile(r"\bapi\s*\.\s*decide\s*\(")


class GitError(RuntimeError):
    pass


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def at_ref(ref: str, path: str) -> str:
    """File content at a git ref ('' when the file does not exist there)."""
    try:
        return git("show", f"{ref}:{path}")
    except GitError:
        return ""


class Change:
    """The files a change touches and their content before (merge base) and after (head ref or working tree)."""

    def __init__(self, base: str, head: str | None):
        self.head = head
        self.merge_base = git("merge-base", base, head or "HEAD").strip()
        if head:
            status = git("diff", "--name-status", "--no-renames", self.merge_base, head)
            untracked: list[str] = []
        else:
            status = git("diff", "--name-status", "--no-renames", self.merge_base)
            untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
        rows = [line.split("\t", 1) for line in status.splitlines() if "\t" in line] + [["A", p] for p in untracked]
        self.files = [(kind[0], path.replace("\\", "/")) for kind, path in rows]

    def before(self, path: str) -> str:
        return at_ref(self.merge_base, path)

    def after(self, path: str) -> str:
        if self.head:
            return at_ref(self.head, path)
        file = REPO / path
        return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else ""


def member(source: str, signature: str) -> str:
    """Whitespace-normalized text of the C# member whose declaration contains `signature` ('' when absent)."""
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


def approval_rules(source: str) -> list[str]:
    """The parts of PermissionsFor that decide who may approve: the `blocked` reason chain and CanDecide."""
    body = member(source, PERMISSIONS)
    return (re.findall(r"(?:if|else if) \([^;]*blocked = \"[a-z_]+\";", body)
            + re.findall(r"\b(?:CanDecide|DecideBlockedReason):[^,)]*", body))


def scope_problem(path: str) -> str | None:
    parts = path.split("/")
    if path.startswith(".github/"):
        return "CI/CD or agent configuration"
    if "infra" in parts[:-1] or parts[-1] == "azure.yaml" or parts[-1].endswith((".bicep", ".bicepparam")):
        return "infrastructure"
    if not path.startswith(APP):
        return "outside the app"
    return None


def count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def test_cases(path: str, text: str) -> int:
    return count(CS_TEST, text) if path.endswith(".cs") else count(TS_TEST, text)


def contract_problems(change: Change) -> list[str]:
    script = REPO / CONTRACT_DIFF
    if not script.is_file():
        raise GitError(f"{CONTRACT} changed but {CONTRACT_DIFF} is missing; copy the contract-impact skill next to this one")
    with tempfile.TemporaryDirectory() as tmp:
        head_contract = Path(tmp) / "openapi.json"
        head_contract.write_text(change.after(CONTRACT), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(script), "--base-ref", change.merge_base, "--head", str(head_contract),
                               "--fail-on-breaking"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        return []
    return ["contract change is not additive:\n" + (proc.stdout.strip() or proc.stderr.strip())]


def check(change: Change, allow: list[str]) -> list[str]:
    problems: list[str] = []
    changed = [path for kind, path in change.files if kind != "D"]

    for kind, path in change.files:
        if any(path.startswith(prefix) for prefix in allow):
            continue
        if reason := scope_problem(path):
            problems.append(f"out of scope ({reason}): {path}")
        if path.startswith(MIGRATIONS) and kind != "A" and not path.endswith("ModelSnapshot.cs"):
            problems.append(f"existing migration changed or deleted (add a new migration instead): {path}")

    base_workflow, head_workflow = change.before(WORKFLOW), change.after(WORKFLOW)
    if member(base_workflow, DECIDE) != member(head_workflow, DECIDE):
        problems.append("approval authority changed: RequestWorkflow.DecideAsync differs from the base")
    if approval_rules(base_workflow) != approval_rules(head_workflow):
        problems.append("approval authority changed: the approval rules in RequestWorkflow.PermissionsFor differ from the base")
    for path in changed:
        if CODE_FILE.match(path) and not TEST_FILE.search(path) and not path.startswith(MIGRATIONS):
            before, after = change.before(path), change.after(path)
            if count(DECISION_WRITE, after) > count(DECISION_WRITE, before):
                problems.append(f"approval authority changed: {path} adds code that records a decision or sets Approved/Rejected")
            if count(DECISION_CALL, after) > count(DECISION_CALL, before):
                problems.append(f"approval authority changed: {path} adds a call to the decision API")

    tests = sorted({path for _, path in change.files if TEST_FILE.search(path)})
    before = sum(test_cases(p, change.before(p)) for p in tests)
    after = sum(test_cases(p, change.after(p)) for p in tests)
    if after < before:
        problems.append(f"tests removed: {before} test cases in the changed test files at the base, {after} now")
    skipped_before = sum(count(SKIPPED, change.before(p)) for p in tests)
    skipped_after = sum(count(SKIPPED, change.after(p)) for p in tests)
    if skipped_after > skipped_before:
        problems.append(f"tests skipped or focused: {skipped_after - skipped_before} new Skip/.skip/.fixme/.only marker(s)")
    code = [p for p in changed if CODE_FILE.match(p) and not TEST_FILE.search(p) and not p.startswith(MIGRATIONS)]
    if code and not any(TEST_FILE.search(p) for p in changed):
        problems.append("no tests changed: app code changed without a test (turn each acceptance criterion into a test)")

    if any(path == CONTRACT for _, path in change.files):
        problems += contract_problems(change)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main",
                        help="Base branch or commit; the change is compared with its merge base (default origin/main)")
    parser.add_argument("--head", help="Check the commits of this ref instead of the working tree (CI passes the pull request's commit)")
    parser.add_argument("--allow", action="append", default=[], metavar="PREFIX",
                        help="Path prefix to accept outside the scope on purpose, for example app/infra/ (repeatable; say why in the PR)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        change = Change(args.base, args.head)
        problems = check(change, args.allow)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("hint: fetch the base first, for example `git fetch origin main` (add --unshallow in a shallow clone)", file=sys.stderr)
        return 2

    target = f"{args.head} ({git('rev-parse', '--short', args.head).strip()})" if args.head else "working tree"
    print(f"compared {target} with {args.base} (merge base {change.merge_base[:9]}): {len(change.files)} changed file(s)")
    for kind, path in change.files:
        print(f"  {kind} {path}")
    for problem in problems:
        print(f"FAIL {problem}")
    print("PASS change stays within feature bounds" if not problems else f"{len(problems)} boundary problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
