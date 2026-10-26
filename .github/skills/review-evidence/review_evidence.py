#!/usr/bin/env python3
"""Collect the evidence a reviewer needs for a pull request, kept in two separate sections (review-evidence skill).

1. Deterministic acceptance: CI check results, and (with --run) the regression tests executed at two known commits: the commit
   that only added tests (they must FAIL, proving the defect) and the PR head (they must PASS, proving the fix).
2. Review comments: Copilot code review and human reviews. They inform the reviewer; they do not decide. An empty list of
   comments is not evidence that the change is correct.

Usage
  python .github/skills/review-evidence/review_evidence.py --pr 5
  python .github/skills/review-evidence/review_evidence.py --pr 5 --run --filter "*Decision*"     # needs PostgreSQL on 5432
  python .github/skills/review-evidence/review_evidence.py --pr 5 --run --filter "*Decision*" --comment   # post to the PR

Exit codes: 0 report produced, 2 GitHub CLI or git error.
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
TEST_PATH = re.compile(r"^(app/tests/|app/web/e2e/)|\.(test|spec)\.tsx?$")
COPILOT_REVIEWER = "copilot-pull-request-reviewer"


def sh(*args: str, cwd: Path = REPO, check: bool = True) -> str:
    proc = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {proc.stderr.strip()[:300]}")
    return proc.stdout + (proc.stderr if not check else "")


def run_tests_at(sha: str, test_filter: str) -> str:
    """Run the filtered .NET tests in a temporary worktree at `sha`; returns a short result."""
    with tempfile.TemporaryDirectory(prefix="evidence-") as tmp:
        tree = Path(tmp) / "tree"
        sh("git", "worktree", "add", "--detach", str(tree), sha)
        try:
            out = sh("dotnet", "test", "--solution", "app/RequestHub.slnx", "--filter-method", test_filter, cwd=tree, check=False)
        finally:
            sh("git", "worktree", "remove", "--force", str(tree), check=False)
    total = re.search(r"total:\s*(\d+)", out)
    failed = re.search(r"failed:\s*(\d+)", out)
    if not total:
        return "⚠️ did not run (build error?)"
    t, f = int(total.group(1)), int(failed.group(1)) if failed else 0
    return f"❌ {f} of {t} failed" if f else f"✅ {t} of {t} passed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    parser.add_argument("--run", action="store_true", help="Run the regression tests at the test-only commit and at the head")
    parser.add_argument("--filter", default="*", help="Test method filter for --run, for example \"*Decision*\"")
    parser.add_argument("--comment", action="store_true", help="Post the report as a PR comment")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        repo = json.loads(sh("gh", "repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        pr = json.loads(sh("gh", "pr", "view", str(args.pr), "--json", "number,title,url,headRefOid,baseRefName,commits"))
        checks = json.loads(sh("gh", "pr", "checks", str(args.pr), "--json", "name,state,workflow", check=False) or "[]")
        reviews = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{args.pr}/reviews"))
        comments = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{args.pr}/comments"))
        commits = []
        for c in pr["commits"]:
            files = json.loads(sh("gh", "api", f"repos/{repo}/commits/{c['oid']}", "--jq", "[.files[].filename]"))
            commits.append({"sha": c["oid"], "title": c["messageHeadline"], "testsOnly": bool(files) and all(TEST_PATH.search(f) for f in files)})
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    lines = [f"## Review evidence for #{pr['number']}: {pr['title']}", "",
             "### Deterministic acceptance (decides whether this can merge)", ""]
    if checks:
        lines += ["| Check | Result |", "|---|---|"]
        icon = {"SUCCESS": "✅ pass", "FAILURE": "❌ fail", "PENDING": "⏳ pending", "SKIPPED": "➖ skipped"}
        lines += [f"| {c.get('workflow', '')} · {c['name']} | {icon.get(c['state'], c['state'].lower())} |" for c in checks]
    else:
        lines.append("No CI checks reported yet. Workflows on agent PRs may need a maintainer to approve the run.")

    test_commit = next((c for c in commits if c["testsOnly"]), None)
    lines += ["", f"Regression tests at known commits (filter `{args.filter}`):", "", "| Commit | Content | Result |", "|---|---|---|"]
    if args.run:
        sh("git", "fetch", "-q", "origin", f"pull/{args.pr}/head")
        if test_commit:
            lines.append(f"| `{test_commit['sha'][:9]}` | tests only: {test_commit['title']} | {run_tests_at(test_commit['sha'], args.filter)} (must fail: proves the defect) |")
        else:
            lines.append("| – | no tests-only commit | ⚠️ the failing test was not committed before the fix |")
        lines.append(f"| `{pr['headRefOid'][:9]}` | PR head | {run_tests_at(pr['headRefOid'], args.filter)} (must pass) |")
    else:
        lines.append(f"| `{(test_commit or {}).get('sha', '–')[:9]}` | tests-only commit | not run (use --run) |")

    copilot = [c for c in comments if c["user"]["login"].startswith(COPILOT_REVIEWER) or c["user"]["login"] == "Copilot"]
    copilot_reviews = [r for r in reviews if r["user"]["login"].startswith(COPILOT_REVIEWER) or r["user"]["login"] == "Copilot"]
    humans = [r for r in reviews if r not in copilot_reviews and r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    lines += ["", "### Review comments (inform the reviewer; they do not decide)", ""]
    if copilot_reviews or copilot:
        lines.append(f"- Copilot code review: {len(copilot)} inline comment(s).")
        lines += [f"  - `{c['path']}`: {c['body'].splitlines()[0][:160]}" for c in copilot[:8]]
    else:
        lines.append("- Copilot code review: not requested or no review yet.")
    lines.append("- No comments does not mean correct. The checks above and a person decide.")
    lines += ["", "### Reviewer decision", ""]
    lines += [f"- **{r['state'].replace('_', ' ').lower()}** by @{r['user']['login']} ({r['submitted_at'][:10]})" for r in humans] or ["- Pending a human review."]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.comment:
        subprocess.run(["gh", "pr", "comment", str(args.pr), "--body-file", "-"], input=report, text=True, encoding="utf-8", cwd=REPO, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
