#!/usr/bin/env python3
"""Assemble the review evidence for a fix pull request, keeping what decides apart from what informs (review-evidence skill).

The report has three sections:

  1. Deterministic acceptance decides whether the change can merge: the pull request's checks, and the regression tests
     run at two known commits (they must fail at the tests-only commit and pass at the head). The proof comes from the
     latest "Test · GitHub · prove the fix test-first" workflow run for the head (its regression-proof artifact), or
     from a local prove_fix.py run with --run.
  2. Review comments inform the reviewer: Copilot code review and comments from people. They do not decide, and an
     empty review is not evidence that the change is correct.
  3. Reviewer decision: the GitHub reviews that approved the change or requested changes.

Usage
  python .github/skills/review-evidence/review_evidence.py --pr 42             print the report
  python .github/skills/review-evidence/review_evidence.py --pr 42 --comment   post it on the pull request, or update
                                                                              the report this account posted before
  python .github/skills/review-evidence/review_evidence.py --pr 42 --run       prove it locally instead of reading the
                                                                              workflow's proof (.NET SDK, PostgreSQL)

Needs the GitHub CLI, signed in with read access to the repository (and write access for --comment).

Exit codes: 0 report produced, 2 GitHub CLI or git error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prove_fix  # noqa: E402  (the sibling script in this skill)

REPO = prove_fix.REPO
MARKER = "<!-- review-evidence -->"
ARTIFACT = "regression-proof"
COPILOT = ("copilot-pull-request-reviewer", "Copilot")


def gh(*args: str, check: bool = True, stdin: str | None = None) -> str:
    try:
        proc = subprocess.run(["gh", *args], cwd=REPO, input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
    except FileNotFoundError as exc:
        raise prove_fix.ProofError("the GitHub CLI (gh) is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise prove_fix.ProofError(f"gh {' '.join(args[:2])} did not answer within 5 minutes") from exc
    if check and proc.returncode != 0:
        raise prove_fix.ProofError(f"gh {' '.join(args[:2])}: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def gh_list(endpoint: str) -> list[dict]:
    """Every item of a paginated REST list (one compact JSON object per line, so it works on older GitHub CLIs too)."""
    out = gh("api", "--paginate", f"{endpoint}?per_page=100", "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def first_line(text: str | None, width: int = 160) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip() and not line.lstrip().startswith(("<", "#"))]
    return lines[0][:width] if lines else ""


def check_result(check: dict) -> str:
    """One check run or commit status from statusCheckRollup, as a short result."""
    if check.get("__typename") == "StatusContext":
        state = check.get("state", "")
        return {"SUCCESS": "✅ pass", "FAILURE": "❌ fail", "ERROR": "❌ error"}.get(state, "⏳ pending")
    if check.get("status") != "COMPLETED":
        return "⏳ pending"
    conclusion = check.get("conclusion") or ""
    return {"SUCCESS": "✅ pass", "FAILURE": "❌ fail", "TIMED_OUT": "❌ timed out", "STARTUP_FAILURE": "❌ failed to start",
            "CANCELLED": "⛔ cancelled", "SKIPPED": "➖ skipped", "NEUTRAL": "➖ neutral",
            "ACTION_REQUIRED": "⏳ waiting for a person to approve the run"}.get(conclusion, conclusion.lower())


def checks(number: int) -> list[str]:
    rollup = json.loads(gh("pr", "view", str(number), "--json", "statusCheckRollup"))["statusCheckRollup"] or []
    latest: dict[tuple[str, str], dict] = {}
    for check in sorted(rollup, key=lambda c: c.get("startedAt") or ""):
        latest[(check.get("workflowName") or "", check.get("name") or check.get("context") or "?")] = check
    if not latest:
        return ["No checks yet. Workflows on Copilot's pull requests wait until a person selects **Approve and run workflows**.", ""]
    rows = [f"| {workflow or '–'} · {name} | {check_result(check)} |" for (workflow, name), check in latest.items()]
    return ["| Check | Result |", "|---|---|", *rows, ""]


def workflow_proof(head: str, workflow: str) -> tuple[dict | None, str]:
    """The proof from the latest completed run of `workflow` for `head`, and where it came from."""
    runs = json.loads(gh("run", "list", "--workflow", workflow, "--commit", head, "--limit", "10",
                         "--json", "databaseId,status,conclusion,url", check=False) or "[]")
    done = [r for r in runs if r["status"] == "completed" and r["conclusion"] in ("success", "failure")]
    if not done:
        state = runs[0]["status"].replace("_", " ") if runs else "not started"
        return None, (f"no completed `{workflow}` run for `{head[:9]}` yet ({state}). Approve the workflow runs on the "
                      "pull request, or prove it locally with `--run`.")
    latest = done[0]
    with tempfile.TemporaryDirectory(prefix="evidence-") as tmp:
        try:
            gh("run", "download", str(latest["databaseId"]), "--name", ARTIFACT, "--dir", tmp)
            proof = json.loads((Path(tmp) / "proof.json").read_text(encoding="utf-8"))
        except (prove_fix.ProofError, OSError, json.JSONDecodeError):
            return None, f"[the latest workflow run]({latest['url']}) ended before it produced a proof; open it to see why."
    return proof, f"Source: [workflow run]({latest['url']}). Both test outputs are kept in its `{ARTIFACT}` artifact."


def is_copilot(login: str) -> bool:
    return login.startswith(COPILOT)


def headline(body: str | None) -> str:
    """A review's verdict and first sentence, for example "🔵 Needs a closer look: Approval correctness depends on ..."."""
    title = next((line.strip().lstrip("#").strip() for line in (body or "").splitlines() if line.strip().startswith("#")), "")
    summary = first_line(body, 240)
    return ": ".join(part for part in (title, summary) if part)


def reviews(repo: str, number: int) -> list[str]:
    submitted = gh_list(f"repos/{repo}/pulls/{number}/reviews")
    inline = gh_list(f"repos/{repo}/pulls/{number}/comments")
    # Copilot code review submits reviews as copilot-pull-request-reviewer; the cloud agent replies in threads as Copilot.
    copilot_reviews = [r for r in submitted if r["user"]["login"].startswith(COPILOT[0])]
    review_ids = {r["id"] for r in copilot_reviews}
    copilot_inline = [c for c in inline if c.get("pull_request_review_id") in review_ids and not c.get("in_reply_to_id")]
    replies = [c for c in inline if c.get("in_reply_to_id") and c["user"]["login"] == COPILOT[1]]
    people_inline = [c for c in inline if not is_copilot(c["user"]["login"])]

    lines = ["### 2. Review comments (inform the reviewer; they do not decide)", ""]
    if copilot_reviews:
        verdict = headline(copilot_reviews[-1].get("body"))
        lines.append(f"- **Copilot code review:** {verdict + ' ' if verdict else ''}({len(copilot_inline)} inline comment(s))")
        lines += [f"  - `{c['path']}`: {first_line(c['body'])}" for c in copilot_inline[:8]]
    else:
        lines.append("- **Copilot code review:** not requested or not finished yet.")
    if replies:
        lines.append(f"- **Copilot (author) replied** in {len(replies)} thread(s): {first_line(replies[-1]['body'])}")
    if people_inline:
        people = ", ".join(sorted({f"@{c['user']['login']}" for c in people_inline}))
        lines.append(f"- **People:** {len(people_inline)} inline comment(s) from {people}.")
    lines += ["- No comments does not mean correct: the checks above and a person decide.", ""]

    decisions = [r for r in submitted if not is_copilot(r["user"]["login"]) and r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    lines += ["### 3. Reviewer decision", ""]
    if decisions:
        for r in decisions:
            note = first_line(r.get("body"))
            lines.append(f"- **{r['state'].replace('_', ' ').lower()}** by @{r['user']['login']} on {r['submitted_at'][:10]}"
                         + (f": {note}" if note else ""))
    else:
        lines.append("- Pending. A person approves or requests changes on the pull request, then runs this again to record it.")
    return lines


def post(repo: str, number: int, report: str) -> str:
    """Update the report this account posted earlier, or post a new comment."""
    me = gh("api", "user", "--jq", ".login", check=False).strip()
    earlier = [c for c in gh_list(f"repos/{repo}/issues/{number}/comments")
               if me and c["user"]["login"] == me and c["body"].startswith(MARKER)]
    if earlier:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{earlier[-1]['id']}", "--input", "-", stdin=json.dumps({"body": report}))
        return f"Updated {earlier[-1]['html_url']}"
    return f"Posted {gh('pr', 'comment', str(number), '--body-file', '-', stdin=report).strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr", type=int, required=True, help="Pull request number")
    parser.add_argument("--run", action="store_true",
                        help="Run the regression tests locally with prove_fix.py instead of reading the workflow's proof")
    parser.add_argument("--filter", help='With --run: test method filter to use instead of the tests the tests-only commit changed')
    parser.add_argument("--workflow", default="test-github-proof.yml",
                        help="Workflow file that publishes the regression-proof artifact (default test-github-proof.yml)")
    parser.add_argument("--comment", action="store_true",
                        help="Post the report on the pull request, or update the report this account posted before")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        repo = json.loads(gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        pr = json.loads(gh("pr", "view", str(args.pr), "--json", "number,title,headRefOid"))
        lines = [MARKER, f"## Review evidence for #{pr['number']}: {pr['title']}", "",
                 "### 1. Deterministic acceptance (decides whether this can merge)", "", *checks(args.pr)]
        if args.run:
            base, head = prove_fix.fetch_pr(args.pr)
            out = Path("out/regression-proof") / f"pr-{args.pr}"
            proof, source = prove_fix.prove(base, head, out, args.filter), f"Source: `prove_fix.py` run locally; test outputs in `{out.as_posix()}`."
        else:
            proof, source = workflow_proof(pr["headRefOid"], args.workflow)
        if proof:
            lines += [prove_fix.render(proof, heading="**Regression tests at known commits**").rstrip(), "", source, ""]
        else:
            lines += [f"**Regression tests at known commits:** {source}", ""]
        lines += reviews(repo, args.pr)
        report = "\n".join(lines).rstrip() + "\n"
        print(report)
        if args.comment:
            print(post(repo, args.pr, report))
    except prove_fix.ProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
