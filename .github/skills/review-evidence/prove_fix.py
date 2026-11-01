#!/usr/bin/env python3
"""Prove a test-first fix: its regression tests fail before the fix and pass after it (review-evidence skill).

A test-first fix starts with a commit that only adds or changes tests, followed by the fix. This script finds that
tests-only commit between the base and the head of a pull request, works out which xUnit test methods it added or
changed, and runs exactly those tests twice, each time in a clean temporary git worktree:

  1. at the tests-only commit  at least one must FAIL: the tests detect the defect
  2. at the head               every one of them must still exist and PASS: the fix works (skipping or deleting a
                               failing test does not count)

Both test outputs (console log and CTRF JSON report) are kept in --out, named after their commit, next to proof.json and
proof.md. The workflow "Test · GitHub · prove the fix test-first" runs this script on fix pull requests, and a reviewer
can run it locally. It proves the order of the evidence, not the quality of the tests: a person still reads them.
proof.md quotes the pull request (commit titles, test and file names, assertion messages) as inert text: no @mention, no
reference to an Issue or a pull request, and no link, image, or HTML, because review_evidence.py posts it with a
person's token.

Usage
  python .github/skills/review-evidence/prove_fix.py --pr 42
      a pull request (needs the GitHub CLI); fetches its base branch and head
  python .github/skills/review-evidence/prove_fix.py --base origin/lab/test-duplicate-decision --head HEAD
      local commits, for example after fixing a defect with Copilot CLI
  python .github/skills/review-evidence/prove_fix.py --pr 42 --filter "*Decision*"
      choose the test methods yourself instead of taking the ones the tests-only commit changed

Needs git, the .NET SDK, and PostgreSQL on localhost:5432 (or the server connection string in REQUESTHUB_TEST_PG).
Only .NET tests under app/tests/ are selected; browser tests in the tests-only commit are reported, not run.

Exit codes: 0 proven, 1 not proven, 2 configuration, git, or GitHub CLI error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOLUTION = "app/RequestHub.slnx"
DOTNET_TESTS = "app/tests/"
TEST_FILE = re.compile(r"^(app/tests/|app/web/e2e/)|\.(test|spec)\.tsx?$")
TEST_ATTRIBUTE = re.compile(r"^\s*\[(?:Fact|Theory)\b")
METHOD = re.compile(r"\b(?:Task|ValueTask|void)\s+(\w+)\s*\(")
CLASS = re.compile(r"\bclass\s+(\w+)")
LITERAL = re.compile(r'@"(?:[^"]|"")*"|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)\'')
ASCII_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
WWW = re.compile(r"(?i)www\.")
MENTION = re.compile(r"@(?!\u200b)")
REFERENCE = re.compile(r"(?i)(#|GH-)(?=\d)")  # #123, GH-123, owner/repo#123: links to an Issue, and a note on its timeline
MAX_BACKTICKS = 80  # GitHub's Markdown parser (cmark-gfm) never opens a code span with a longer run of backticks


class ProofError(Exception):
    """A configuration, git, or GitHub CLI problem (exit code 2)."""


# Text from a pull request or from GitHub (titles, test and file names, messages, review notes) is made inert before it
# goes into Markdown, because review_evidence.py posts that Markdown with a person's token: an @mention in it would
# notify, or start Copilot, in that person's name, and #123 would add "mentioned this" to Issue 123 in that person's
# name. The approach of solutions/03-develop-microsoft's format_review.py, checked against GitHub's own renderer.

def unmention(text: str) -> str:
    """A zero-width space after every @, so nothing GitHub renders from this text notifies anyone, Copilot included."""
    return MENTION.sub("@\u200b", text)


def inert_text(text: str) -> str:
    """Text outside code spans: no HTML or entities, no links or images, no autolinked URLs, no references to Issues or
    pull requests, no math (GitHub reads $...$ and $`...`$ as MathJax, whatever the escaping), no mentions. Zero-width
    spaces do the breaking, so the text reads the same."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("[", "\\[").replace("]", "\\]")
    text = WWW.sub("www\u200b.", text.replace("://", ":/\u200b/"))
    text = REFERENCE.sub("\\g<1>\u200b", text).replace("$", "\u200b$\u200b")
    return unmention(text)


def inert(value: object, limit: int = 500) -> str:
    """Untrusted text as inert Markdown on one line. Code spans are found the way GitHub (cmark-gfm) finds them: a run of
    at most 80 backticks opens a span only if a run of the same length closes it, and a backslash-escaped backtick is a
    literal one. Inside a span nothing is interpreted, so only mentions are neutralized there; everything outside is
    escaped, and so is every backtick that opens no span."""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    out: list[str] = []
    outside: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCTUATION:
            # A backslash escape shows the next character literally: keep it escaped so it stays literal.
            outside.append(c + text[i + 1] if text[i + 1] in "`\\" else text[i + 1])
            i += 2
            continue
        if c == "`":
            n = len(text) - i - len(text[i:].lstrip("`"))
            close = None if n > MAX_BACKTICKS else next(
                (m.start() for m in re.finditer(r"`+", text[i + n:]) if len(m.group(0)) == n), None)
            out.append(inert_text("".join(outside)))
            outside = []
            if close is None:
                out.append("\\`" * n)  # literal backticks: escape them so they can't pair up later
                i += n
                continue
            out.append("`" * n + unmention(text[i + n:i + n + close]) + "`" * n)
            i += n + close + n
            continue
        outside.append(c)
        i += 1
    out.append(inert_text("".join(outside)))
    result = "".join(out)
    return "\\" + result if result.startswith("#") else result  # a line that starts with # would be a heading


def cell(value: object, limit: int = 200) -> str:
    """inert(), for a Markdown table cell, where a | would end the cell."""
    return inert(value, limit).replace("|", "\\|")


def code(value: object, limit: int = 160) -> str:
    """A test name or a file name from the pull request, as a code span it can't break out of."""
    text = " ".join(str(value or "").split()).replace("`", "'")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"`{unmention(text)}`" if text else ""


def short_sha(sha: object) -> str:
    """The first nine characters of a commit id. A proof.json from elsewhere could hold anything, so only hex is kept."""
    return re.sub(r"[^0-9a-f]", "", str(sha or "").lower())[:9] or "?"


def count(value: object) -> int:
    """A test count from a proof; anything that isn't a whole number reads as 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def run(*args: str, cwd: Path = REPO) -> str:
    proc = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ProofError(f"{' '.join(args[:3])}: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def show(rev: str, path: str) -> str:
    """A file's contents at a revision, or an empty string when the file does not exist there."""
    proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.stdout if proc.returncode == 0 else ""


def fetch_pr(number: int) -> tuple[str, str]:
    """Fetch a pull request's base branch and head; return (base ref, head SHA)."""
    pr = json.loads(run("gh", "pr", "view", str(number), "--json", "baseRefName,headRefOid"))
    run("git", "fetch", "--quiet", "--no-tags", "origin", pr["baseRefName"], f"+refs/pull/{number}/head:refs/remotes/origin/pr/{number}")
    return f"origin/{pr['baseRefName']}", pr["headRefOid"]


def history(base: str, head: str) -> list[dict]:
    """Commits from base (exclusive) to head, oldest first, with the files each one changes."""
    commits = []
    for sha in run("git", "rev-list", "--reverse", "--no-merges", f"{base}..{head}").split():
        files = [f for f in run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha).split("\0") if f]
        commits.append({"sha": sha, "title": run("git", "log", "-1", "--format=%s", sha).strip(), "files": files})
    return commits


def tests_only_commit(commits: list[dict]) -> dict | None:
    """The last commit of the leading run of tests-only commits. Empty commits (such as "Initial plan") are skipped."""
    found = None
    for commit in commits:
        if not commit["files"]:
            continue
        if not all(TEST_FILE.search(path) for path in commit["files"]):
            break
        found = commit
    return found


def method_end(lines: list[str], start: int, stop: int) -> int:
    """Index just past the method that starts at `start`: the brace closing its body, or the `;` ending `=> ...`.

    Without this, the last test of a file would run to the end of the file, so adding a helper or a test after it
    would make it look changed.
    """
    depth, opened, arrow = 0, False, False
    for i in range(start, stop):
        code = LITERAL.sub('""', lines[i]).split("//", 1)[0]
        arrow = arrow or (not opened and "=>" in code)
        for char in code:
            if char == "{":
                depth, opened = depth + 1, True
            elif char == "}":
                depth -= 1
        if (opened and depth <= 0) or (arrow and not opened and code.rstrip().endswith(";")):
            return i + 1
    return stop


def test_methods(source: str) -> dict[str, str]:
    """Map each xUnit test method to its text, from its [Fact] or [Theory] attribute to the end of its body."""
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if TEST_ATTRIBUTE.match(line)]
    methods: dict[str, str] = {}
    for n, start in enumerate(starts):
        block = lines[start:method_end(lines, start, starts[n + 1] if n + 1 < len(starts) else len(lines))]
        name = next((m.group(1) for line in block if not line.lstrip().startswith("[") and (m := METHOD.search(line))), None)
        if name:
            methods[name] = "\n".join(line.rstrip() for line in block).strip()
    return methods


def changed_tests(base: str, commit: str) -> tuple[list[str], list[str], list[str]]:
    """Test methods added or changed between base and commit, the classes in those files, and other test files."""
    paths = [p for p in run("git", "diff", "--name-only", "-z", base, commit, "--").split("\0") if TEST_FILE.search(p)]
    names: set[str] = set()
    classes: set[str] = set()
    for path in (p for p in paths if p.startswith(DOTNET_TESTS) and p.endswith(".cs")):
        source = show(commit, path)
        before = test_methods(show(base, path))
        names |= {name for name, text in test_methods(source).items() if before.get(name) != text}
        classes |= set(CLASS.findall(source))
    others = [p for p in paths if not p.startswith(DOTNET_TESTS)]
    return sorted(names), sorted(classes), others


def run_tests(sha: str, filters: list[str], out: Path, label: str) -> dict:
    """Run the selected tests in a temporary worktree at `sha`; keep the console log and the CTRF report in `out`."""
    log, report = out / f"{label}-{sha[:9]}.log", out / f"{label}-{sha[:9]}.ctrf.json"
    report.unlink(missing_ok=True)
    print(f"Running {len(filters) // 2} test filter(s) at {sha[:9]} ({label}) ...", flush=True)
    with tempfile.TemporaryDirectory(prefix="proof-", ignore_cleanup_errors=True) as tmp:
        tree = Path(tmp) / "tree"
        run("git", "worktree", "add", "--quiet", "--detach", str(tree), sha)
        try:
            proc = subprocess.run(
                ["dotnet", "test", "--solution", SOLUTION, *filters, "--results-directory", str(out.resolve()),
                 "--report-xunit-ctrf", "--report-xunit-ctrf-filename", report.name],
                cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise ProofError("dotnet is not installed or not on PATH") from exc
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, capture_output=True)
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    result = {"sha": sha, "log": log.name, "report": None, "exitCode": proc.returncode,
              "total": 0, "passed": 0, "failed": 0, "tests": [], "failedTests": []}
    if report.exists():
        tests = json.loads(report.read_text(encoding="utf-8"))["results"]["tests"]
        failed = [t for t in tests if t.get("status") == "failed"]
        result.update(report=report.name, total=len(tests), failed=len(failed),
                      passed=sum(1 for t in tests if t.get("status") == "passed"),
                      tests=[{"name": t.get("name", "?"), "status": t.get("status", "other")} for t in tests],
                      failedTests=[{"name": t.get("name", "?"), "message": summary_of(t.get("message"))} for t in failed])
    return result


def summary_of(message: str | None) -> str:
    """The first lines of an assertion message on one line, for example "Expected: Conflict · Actual: Created"."""
    lines = [" ".join(line.split())[:90] for line in (message or "").strip().splitlines()
             if line.strip() and not line.strip().startswith(("↓", "↑"))]
    return " · ".join(lines[:3])


def short_name(test: str) -> str:
    """RequestHub.Tests.SomeTests.Method(arg: 1) -> Method(arg: 1)"""
    method, paren, arguments = test.partition("(")
    return method.rsplit(".", 1)[-1] + paren + arguments


def outcome(result: dict, missing: int = 0) -> str:
    total, passed, failed = count(result.get("total")), count(result.get("passed")), count(result.get("failed"))
    if not total:
        return "⚠️ did not run (build error? see the log)"
    if failed:
        return f"❌ {failed} of {total} failed" + (f", {missing} missing" if missing else "")
    if passed < total or missing:
        gaps = [f"{total - passed} skipped"] * (passed < total) + [f"{missing} missing"] * bool(missing)
        return f"⚠️ {passed} of {total + missing} passed, " + ", ".join(gaps)
    return f"✅ {total} of {total} passed"


def render(proof: dict, heading: str = "### Regression tests at known commits") -> str:
    """The proof as Markdown. Commit titles, test and file names, and assertion messages come from the pull request, so
    they are made inert: review_evidence.py posts this Markdown with a person's token."""
    lines = [heading, ""]
    runs = proof["runs"]
    if runs:
        tests_only, head = proof["testsOnly"], runs["head"]
        missing = proof.get("missingAtHead")
        lines += ["| Commit | What it contains | Selected tests | Expected |", "|---|---|---|---|",
                  f"| `{short_sha(tests_only['sha'])}` | tests only: {cell(tests_only['title'])} | {outcome(runs['testsOnly'])} | must fail: proves the defect |",
                  f"| `{short_sha(head['sha'])}` | head: {cell(proof['headTitle'])} | {outcome(head, len(missing) if isinstance(missing, list) else 0)} | must pass: proves the fix |", ""]
    icon = "✅ Proven" if proof["verdict"] == "proven" else "❌ Not proven"
    lines += [f"**{icon}:** {inert(proof['reason'])}", ""]
    if proof["tests"]:
        lines += [f"Selected tests ({inert(proof['selection'])}): " + ", ".join(code(t) for t in proof["tests"]), ""]
    if runs and runs["testsOnly"]["failedTests"]:
        failures = sorted(runs["testsOnly"]["failedTests"], key=lambda t: str(t["name"]))
        lines += ["Failures at the tests-only commit (the reported defect, in the tests' words):", ""]
        lines += [f"- {code(short_name(str(t['name'])))}: {inert(t['message']) or 'failed'}" for t in failures[:12]]
        lines.append("")
    if proof["otherTests"]:
        lines += ["Not run by this check (run them by hand): " + ", ".join(code(p) for p in proof["otherTests"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def prove(base: str, head: str, out: Path, test_filter: str | None = None) -> dict:
    """Build the proof for base..head and write proof.json, proof.md, and both test outputs to `out`."""
    out.mkdir(parents=True, exist_ok=True)
    head_sha = run("git", "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    merge_base = run("git", "merge-base", base, head_sha).strip()
    commits = history(merge_base, head_sha)
    tests_commit = tests_only_commit(commits)
    proof = {"verdict": "not proven", "reason": "", "base": merge_base, "head": head_sha,
             "headTitle": run("git", "log", "-1", "--format=%s", head_sha).strip(),
             "testsOnly": {k: tests_commit[k] for k in ("sha", "title")} if tests_commit else None,
             "commits": [{k: c[k] for k in ("sha", "title")} for c in commits],
             "tests": [], "selection": "", "otherTests": [], "runs": {}, "missingAtHead": []}

    if tests_commit is None:
        proof["reason"] = "no tests-only commit before the fix. Commit the failing tests on their own first, then the fix."
    else:
        names, classes, proof["otherTests"] = changed_tests(merge_base, tests_commit["sha"])
        if test_filter:
            proof["tests"], proof["selection"], filters = [test_filter], "--filter", ["--filter-method", test_filter]
        elif names:
            proof["tests"], proof["selection"] = names, "added or changed by the tests-only commit"
            filters = [arg for name in names for arg in ("--filter-method", f"*.{name}")]
        else:
            proof["tests"], proof["selection"] = classes, "classes the tests-only commit changed"
            filters = [arg for name in classes for arg in ("--filter-class", f"*.{name}")]
        if not filters:
            proof["reason"] = f"the tests-only commit changes no .NET test under {DOTNET_TESTS}, so this check has nothing to run."
        else:
            before = run_tests(tests_commit["sha"], filters, out, "tests-only")
            after = before if tests_commit["sha"] == head_sha else run_tests(head_sha, filters, out, "head")
            proof["runs"] = {"testsOnly": before, "head": after}
            proven, proof["reason"], proof["missingAtHead"] = judge(before, after)
            proof["verdict"] = "proven" if proven else "not proven"

    (out / "proof.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "proof.md").write_text(render(proof), encoding="utf-8")
    return proof


def judge(before: dict, after: dict) -> tuple[bool, str, list[str]]:
    """Whether two runs prove a test-first fix, why, and which tests that ran before no longer exist at the head.

    Every test that ran before the fix must still exist and pass after it, so skipping or deleting a failing test
    cannot turn the proof green.
    """
    status_after = {t["name"]: t["status"] for t in after["tests"]}
    not_passing = sorted(t["name"] for t in before["tests"] if status_after.get(t["name"]) != "passed")
    missing = [name for name in not_passing if name not in status_after]
    skipped = after["total"] - after["passed"] - after["failed"]
    if not before["total"]:
        return False, "the selected tests did not run at the tests-only commit (build error? see the log).", missing
    if not before["failed"]:
        return False, "the new tests pass without the fix, so they do not detect the defect.", missing
    if not after["total"]:
        return False, "the selected tests did not run at the head (build error? see the log).", missing
    if not_passing or skipped or after["failed"]:
        problems = [f"{after['failed']} failed"] * bool(after["failed"]) + [f"{skipped} skipped"] * bool(skipped)
        if missing:
            gone = "test no longer exists" if len(missing) == 1 else "tests no longer exist"
            problems.append(f"{len(missing)} {gone}: " + ", ".join(code(short_name(name)) for name in missing[:8]))
        return False, f"not every selected test passes at the head ({'; '.join(problems)}).", missing
    if after.get("exitCode", 0):
        return False, f"the test command failed at the head (exit code {after['exitCode']}); see the log.", missing
    return True, (f"{before['failed']} of {before['total']} selected tests fail at the tests-only commit "
                  f"`{before['sha'][:9]}`, and {after['total']} of {after['total']} pass at the head `{after['sha'][:9]}`."), missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="Pull request number; fetches its base branch and head with the GitHub CLI")
    target.add_argument("--base", help="Base branch or commit the fix starts from, for example origin/lab/test-duplicate-decision")
    parser.add_argument("--head", default="HEAD", help="Last commit of the fix when using --base (default HEAD)")
    parser.add_argument("--filter", help='Test method filter to run instead of the detected tests, for example "*Decision*"')
    parser.add_argument("--out", type=Path, default=Path("out/regression-proof"),
                        help="Folder for proof.json, proof.md, and both test outputs (default out/regression-proof)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        base, head = fetch_pr(args.pr) if args.pr else (args.base, args.head)
        proof = prove(base, head, args.out, args.filter)
    except ProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print()
    print(render(proof))
    print(f"Proof and both test outputs: {args.out}")
    return 0 if proof["verdict"] == "proven" else 1


if __name__ == "__main__":
    sys.exit(main())
