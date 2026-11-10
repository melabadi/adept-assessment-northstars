#!/usr/bin/env python3
"""Publish a validated Plan-phase backlog to GitHub Issues, idempotently.

What it does
  1. Validates backlog.json with ../requirements-traceability/validate_backlog.py (refuses to publish if invalid).
  2. With --pull-request, checks whether Microsoft Foundry evaluated the pull request's brief (01-plan-microsoft's
     `runs.py start --evaluate-pull-request N`, the Plan solution combo), whose Function app records each evaluation in a
     GitHub Issue. When it did, the publisher publishes only a revision Foundry evaluated, whose gates passed, and whose
     open items a person has all ticked in that Issue; otherwise it refuses and publishes nothing. Only an evaluation
     Issue that the repository's owner, a member, or a collaborator opened counts. A pull request that Foundry never
     evaluated is published as before.
  3. Ensures labels exist: ai-sdlc, phase:plan, type:epic, type:task, track:<track>.
  4. Creates or updates one epic issue and one issue per task. Each issue body carries a hidden marker
     <!-- ai-sdlc-backlog: <scenario>/<track>/<item id> -->, so re-running updates instead of duplicating. Only an issue
     that the publisher could have opened counts as one it published: GitHub Actions' bot (the workflow) or the
     repository's owner, a member, or a collaborator (a local run). Any other issue that carries the marker is left
     alone, and a note on stderr gives its number. With --revision, the epic's Review section names the commit the
     backlog was published from, and the Foundry evaluation of it, if any.
  5. Links every task as a sub-issue of the epic and records "blocked by" dependencies between tasks
     (falls back to a text link when the dependencies API is unavailable). Links between this backlog's own issues
     that its dependsOn no longer lists are removed, so a new brief never inherits an old one's dependencies;
     links to any other issue are left alone.
  6. When Foundry evaluated the revision, comments the published issues on the evaluation Issue, once, and closes it.
  7. Optionally adds the issues to a GitHub Project (--project-title). Projects need a token with the
     `project` scope (your `gh auth login`); the Actions GITHUB_TOKEN cannot access projects.

It calls the GitHub CLI (`gh api`), so it uses your gh login locally and GH_TOKEN in GitHub Actions.

Usage
  python .github/skills/backlog-publish/publish_backlog.py --backlog solutions/01-plan-github/brief/backlog.json --track github
  python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track github --revision <commit> --pull-request <n>
  python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track microsoft --dry-run
  python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track github --project-title "AI-SDLC Plan demo"
  python .github/skills/backlog-publish/publish_backlog.py --track github --close    # demo reset: close this track's issues

The transcript and policies the backlog cites are read from the nearest `inputs/` folder above the backlog.

Exit codes: 0 success, 1 refused (the backlog is not valid, or Foundry's evaluation doesn't vouch for the revision),
2 GitHub/API or usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "requirements-traceability"))
import validate_backlog  # noqa: E402

TRACK_NAMES = {"github": "Copilot", "microsoft": "Foundry"}
LABELS = {
    "ai-sdlc": ("5319e7", "AI-SDLC demo content"),
    "phase:plan": ("0e8a16", "Plan & specify phase"),
    "type:epic": ("3e4b9e", "Epic"),
    "type:task": ("c5def5", "Bounded engineering task"),
    "track:github": ("24292f", "Produced with GitHub Copilot"),
    "track:microsoft": ("0078d4", "Produced with Microsoft Foundry"),
}
# Who may have opened an Issue that the publisher treats as its own. Anyone can open an Issue with the phase:plan label
# (the issue form applies it) and copy the hidden marker into it, so the marker alone proves nothing.
# - The workflow publishes with its GITHUB_TOKEN, as GitHub Actions' bot. Only this repository's workflows open Issues
#   here as that bot, and GitHub reports its author_association as NONE. If your workflow publishes with another
#   identity, such as a GitHub App, add that app's bot login here, or each run creates the Issues again.
# - A local run publishes with a person's sign-in: the repository's owner, a member, or a collaborator. GitHub reports
#   an organization member whose membership is private as NONE, so such a member's local runs aren't recognized later
#   and a re-run creates the Issues again (SKILL.md says whom to publish as).
PUBLISHER_BOTS = ("github-actions[bot]",)
TRUSTED_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")
# The evaluation Issue that 01-plan-microsoft's Function app opens when Microsoft Foundry evaluated a pull request's
# brief: its marker names the run, the pull request, the exact revision, and whether the gates passed, and the task list
# under OPEN_ITEMS_HEADING holds the open items a person ticks once decided. Keep both in step with that solution
# (function/planner/brief.py: evaluation_marker() and OPEN_ITEMS_HEADING).
EVALUATION_MARKER = re.compile(r"<!-- plan-microsoft evaluation: run (\d{8}-\d{6}-[0-9a-f]{4}), pull request #(\d+), "
                               r"revision ([0-9a-f]{40}(?:[0-9a-f]{24})?), gates (passed|failed) -->")
OPEN_ITEMS_HEADING = "## Open items for the product owner"
TASK_ITEM = re.compile(r"^\s*[-*] \[([ xX])\]\s+(?:\*\*([^*\n]{1,40})\*\*)?")
REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ZERO_WIDTH_SPACE = "\u200b"


class GitHubError(RuntimeError):
    pass


def gh(path: str, method: str = "GET", body: dict | None = None, paginate: bool = False, ok404: bool = False):
    """Call `gh api` and return parsed JSON."""
    cmd = ["gh", "api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    if body is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        if ok404 and ("404" in proc.stderr or "Not Found" in proc.stderr):
            return None
        raise GitHubError(f"gh api {method} {path} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if not proc.stdout.strip():
        return None
    data = json.loads(proc.stdout)
    if paginate:
        return [item for page in data for item in page]
    return data


def graphql(query: str, **variables) -> dict:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise GitHubError(f"GraphQL failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)["data"]


def detect_repo() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    proc = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                          capture_output=True, text=True, cwd=HERE)
    if proc.returncode != 0:
        raise GitHubError("Cannot detect the repository; pass --repo owner/name.")
    return proc.stdout.strip()


def marker(scenario: str, track: str, item_id: str) -> str:
    return f"<!-- ai-sdlc-backlog: {scenario}/{track}/{item_id} -->"


def repo_relative(path: Path) -> str:
    """Path as shown in issue bodies: relative to the repository root when possible."""
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=path.resolve().parent)
    root = Path(proc.stdout.strip()) if proc.returncode == 0 else None
    resolved = path.resolve()
    return resolved.relative_to(root).as_posix() if root and resolved.is_relative_to(root) else path.as_posix()


def paragraph_excerpts(transcript: Path) -> dict[str, str]:
    """Map T01.. to a one-line excerpt so each issue shows the words it came from."""
    excerpts = {}
    for match in re.finditer(r"\*\*\[(T\d{2})\]\*\*\s*(.+)", transcript.read_text(encoding="utf-8")):
        text = match.group(2).strip()
        excerpts[match.group(1)] = text if len(text) <= 220 else text[:217] + "..."
    return excerpts


def sources_section(sources: list[str], excerpts: dict[str, str], policies_path: str) -> str:
    lines = ["## Sources", ""]
    for source in sources:
        quote = excerpts.get(source)
        lines.append(f"- **{source}**" + (f": {quote}" if quote else f" (routing policy, see `{policies_path}`)"))
    return "\n".join(lines)


def review_section(review: dict | None) -> list[str]:
    """The epic's Review section: the commit the backlog was published from and, when Microsoft Foundry evaluated it,
    the evaluation Issue, where the product owner decided its open items."""
    if not review or not review.get("revision"):
        return []
    revision = review["revision"]
    line = (f"- **Revision:** [`{revision[:7]}`]({review['server']}/{review['repo']}/commit/{revision}) of "
            f"`{review['backlog']}`")
    if review.get("pullRequest"):
        line += f", approved in pull request #{review['pullRequest']}"
    lines = ["", "## Review", "", line + "."]
    evaluation = review.get("evaluation")
    if evaluation:
        count = len(evaluation["openItems"])
        lines.append(f"- **Evaluation:** Microsoft Foundry evaluated this revision in #{evaluation['number']} (run "
                     f"`{evaluation['run']}` of 01-plan-microsoft), and its gates passed. The product owner decided its "
                     f"{count} open item{'' if count == 1 else 's'} there before approving.")
    return lines


def epic_body(data: dict, track: str, backlog_path: str, excerpts: dict[str, str], policies_path: str,
              review: dict | None = None) -> str:
    epic = data["epic"]
    unresolved = [c for c in data["conflicts"] if not c.get("resolution")]
    parts = [
        marker(data["scenario"], track, epic["id"]),
        f"> Published from `{backlog_path}` by the Plan phase ({TRACK_NAMES[track]} track). Tasks are linked as sub-issues.",
        "",
        "## Summary", "", epic["summary"], "",
        "## Acceptance criteria", "", *[f"- [ ] {c}" for c in epic["acceptanceCriteria"]], "",
        "## Open questions", "",
        *([f"- [ ] **{q['id']}**{' (blocking)' if q['blocking'] else ''}: {q['question']} ({', '.join(q['sources'])})" for q in data["openQuestions"]] or ["- None."]),
        "",
        "## Unresolved conflicts", "",
        *([f"- **{c['id']}**: {c['summary']} ({', '.join(c['sources'])})" for c in unresolved] or ["- None."]),
        "",
        sources_section(epic["sources"], excerpts, policies_path),
        *review_section(review),
    ]
    return "\n".join(parts)


def task_body(data: dict, task: dict, track: str, epic_number: int | None, numbers: dict[str, int], excerpts: dict[str, str], policies_path: str) -> str:
    deps = ", ".join(f"#{numbers[d]}" if d in numbers else d for d in task["dependsOn"]) or "none"
    parts = [
        marker(data["scenario"], track, task["id"]),
        f"**Epic:** {f'#{epic_number}' if epic_number else 'pending'} · **Owner role:** {task['ownerRole']} · **Depends on:** {deps} · **Backlog id:** `{task['id']}`",
        "",
        "## Description", "", task["description"], "",
        "## Acceptance criteria", "", *[f"- [ ] {c}" for c in task["acceptanceCriteria"]], "",
        sources_section(task["sources"], excerpts, policies_path),
    ]
    return "\n".join(parts)


def ensure_labels(repo: str, track: str, dry_run: bool) -> None:
    existing = {label["name"] for label in gh(f"repos/{repo}/labels?per_page=100", paginate=True)}
    for name, (color, description) in LABELS.items():
        if name.startswith("track:") and name != f"track:{track}":
            continue
        if name not in existing and not dry_run:
            gh(f"repos/{repo}/labels", "POST", {"name": name, "color": color, "description": description})


def could_have_published(issue: dict) -> bool:
    """Whether the publisher could have opened this Issue: GitHub Actions' bot, as the workflow does, or the repository's
    owner, a member, or a collaborator, as a local run does. Nobody can register a [bot] login, and a person's account
    is never of type Bot."""
    user = issue.get("user") or {}
    if user.get("login") in PUBLISHER_BOTS and user.get("type") == "Bot":
        return True
    return issue.get("author_association") in TRUSTED_AUTHORS


def existing_issues(repo: str, scenario: str, track: str) -> dict[str, dict]:
    """This track's Issues from earlier runs, by backlog id, found by their hidden marker. Only an Issue the publisher
    could have opened counts. Any other Issue with the marker is never updated, reopened, closed, or linked; a note on
    stderr gives its number, never who opened it."""
    found = {}
    pattern = re.compile(re.escape(f"<!-- ai-sdlc-backlog: {scenario}/{track}/") + r"([A-Z0-9-]+) -->")
    for issue in gh(f"repos/{repo}/issues?state=all&labels=phase:plan&per_page=100", paginate=True):
        match = pattern.search(issue.get("body") or "")
        if not match or "pull_request" in issue:
            continue
        if not could_have_published(issue):
            print(f"note: ignored #{issue['number']}: it carries this backlog's marker, but neither this repository's "
                  "workflows nor its owner, a member, or a collaborator opened it", file=sys.stderr)
            continue
        found[match.group(1)] = issue
    return found


def neutralize(text: str) -> str:
    """Breaks every @ mention: text the publisher quotes on GitHub can't mention anyone."""
    return text.replace("@", "@" + ZERO_WIDTH_SPACE)


def evaluation_record(issue: dict) -> dict | None:
    """What a Foundry evaluation Issue says: its run, pull request, revision, verdict, and open items (ticked or not).
    None when its body doesn't carry exactly one evaluation marker."""
    body = (issue.get("body") or "").replace("\r\n", "\n")
    found = EVALUATION_MARKER.findall(body)
    if len(found) != 1:
        return None
    run_id, pull_request, revision, gates = found[0]
    section = body.split(OPEN_ITEMS_HEADING, 1)[1] if OPEN_ITEMS_HEADING in body else ""
    section = re.split(r"^#{1,6} ", section, maxsplit=1, flags=re.MULTILINE)[0]
    items = []
    for line in section.split("\n"):
        item = TASK_ITEM.match(line)
        if item:
            items.append({"id": item.group(2) or "an unnamed item", "resolved": item.group(1) != " "})
    return {"number": issue["number"], "state": issue.get("state"), "run": run_id, "pullRequest": int(pull_request),
            "revision": revision, "passed": gates == "passed", "openItems": items}


def foundry_evaluations(repo: str, pull_request: int) -> list[dict]:
    """Microsoft Foundry's evaluations of this pull request's brief, newest first. Only an Issue that the repository's
    owner, a member, or a collaborator opened counts (01-plan-microsoft's Function app opens it with a token of one of
    them): anyone can open an Issue with the phase:plan label and copy the marker, and such an Issue can neither block
    nor vouch for a publish."""
    records = []
    for issue in gh(f"repos/{repo}/issues?state=all&labels=phase:plan&per_page=100", paginate=True):
        if "pull_request" in issue or issue.get("author_association") not in TRUSTED_AUTHORS:
            continue
        record = evaluation_record(issue)
        if record and record["pullRequest"] == pull_request:
            records.append(record)
    return sorted(records, key=lambda record: record["number"], reverse=True)


def check_evaluation(records: list[dict], pull_request: int, revision: str) -> tuple[dict | None, str | None]:
    """The evaluation that vouches for this revision, or why publishing it is refused. Without any evaluation, the pull
    request is on the GitHub track alone, and nothing is refused."""
    if not records:
        return None, None
    again = (f"evaluate it again (in solutions/01-plan-microsoft: `python runs.py start --evaluate-pull-request "
             f"{pull_request}`), then apply brief-approved again")
    matching = [record for record in records if record["revision"] == revision]
    if not matching:
        newest = records[0]
        return None, (f"Microsoft Foundry evaluated pull request #{pull_request} at revision {newest['revision'][:7]} "
                      f"(#{newest['number']}), not at revision {revision[:7]}, the one approved. The brief changed "
                      f"after its evaluation: {again}.")
    record = matching[0]
    if not record["passed"]:
        return None, (f"Microsoft Foundry's evaluation of revision {revision[:7]} (#{record['number']}) didn't pass its "
                      f"gates. Fix the brief, then {again}.")
    unresolved = [item["id"] for item in record["openItems"] if not item["resolved"]]
    if unresolved:
        return None, (f"{len(unresolved)} open item{'' if len(unresolved) == 1 else 's'} in Microsoft Foundry's "
                      f"evaluation #{record['number']} {'is' if len(unresolved) == 1 else 'are'} not decided yet: "
                      f"{', '.join(unresolved)}. Decide each one and tick it there, then apply brief-approved again.")
    return record, None


def published_marker(pull_request: int, revision: str) -> str:
    return f"<!-- ai-sdlc-backlog published: pull request #{pull_request}, revision {revision} -->"


def report_on_evaluation(repo: str, record: dict, pull_request: int, revision: str, epic: dict, tasks: list[dict],
                         dry_run: bool) -> str:
    """Comments the published issues on Foundry's evaluation Issue, once, and closes it as completed: the evaluation
    then links the backlog it vouched for. Returns what it did, for the output."""
    number = record["number"]
    if dry_run:
        return f"would comment the published issues on #{number} and close it"
    mark = published_marker(pull_request, revision)
    comments = gh(f"repos/{repo}/issues/{number}/comments?per_page=100", paginate=True)
    done = []
    if not any(mark in (comment.get("body") or "") and could_have_published(comment) for comment in comments):
        task_list = ", ".join(f"#{task['number']}" for task in tasks)
        body = "\n".join([
            "### Backlog published from this revision", "",
            f"After a person approved pull request #{pull_request}, GitHub published revision `{revision[:7]}`, "
            f"the revision this evaluation scored:", "",
            f"- Epic: #{epic['number']}",
            f"- Tasks, linked to the epic as sub-issues: {task_list}", "",
            mark,
        ])
        gh(f"repos/{repo}/issues/{number}/comments", "POST", {"body": body})
        done.append(f"commented the published issues on #{number}")
    if record.get("state") != "closed":
        gh(f"repos/{repo}/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
        done.append(f"closed #{number}")
    return " and ".join(done) or f"#{number} already lists them"


def refuse(lines: list[str], refusal_file: Path | None) -> int:
    """Publishes nothing, and says why: on stderr, in the job summary, and in the refusal file the workflow comments on
    the pull request. The reasons can quote the brief or the evaluation Issue, so their @ mentions are broken."""
    lines = [neutralize(line) for line in lines]
    print("\n".join(lines), file=sys.stderr)
    write_summary(["### Nothing was published", "", *lines])
    if refusal_file:
        refusal_file.write_text("### Nothing was published\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return 1


def revision_arg(value: str) -> str:
    if not REVISION.match(value):
        raise argparse.ArgumentTypeError("a revision is a full commit SHA (40 hexadecimal characters)")
    return value


def upsert(repo: str, existing: dict | None, title: str, body: str, labels: list[str], dry_run: bool) -> tuple[dict, str]:
    if existing is None or not existing.get("number"):  # a dry-run placeholder is not an existing issue
        if dry_run:
            return {"number": 0, "id": 0, "html_url": "(dry run)", "node_id": ""}, "would create"
        return gh(f"repos/{repo}/issues", "POST", {"title": title, "body": body, "labels": labels}), "created"
    current_labels = sorted(label["name"] for label in existing.get("labels", []))
    if existing["title"] == title and (existing.get("body") or "").strip() == body.strip() \
            and existing["state"] == "open" and set(labels) <= set(current_labels):
        return existing, "unchanged"
    if dry_run:
        return existing, "would update"
    updated = gh(f"repos/{repo}/issues/{existing['number']}", "PATCH",
                 {"title": title, "body": body, "state": "open", "labels": sorted(set(current_labels) | set(labels))})
    return updated, "updated"


def link_sub_issues(repo: str, epic: dict, tasks: list[dict], dry_run: bool) -> int:
    if dry_run or not epic.get("number"):
        return 0
    current = {i["id"] for i in gh(f"repos/{repo}/issues/{epic['number']}/sub_issues?per_page=100", paginate=True)}
    linked = 0
    for task in tasks:
        if task["id"] not in current:
            gh(f"repos/{repo}/issues/{epic['number']}/sub_issues", "POST", {"sub_issue_id": task["id"], "replace_parent": True})
            linked += 1
    return linked


def link_dependencies(repo: str, data: dict, issues: dict[str, dict], dry_run: bool) -> tuple[str, int]:
    """Make each task's 'blocked by' links match its dependsOn.

    Adds missing links, and removes links to this backlog's own Issues that dependsOn no longer lists (for example
    after a reset and a new brief). Links to any other Issue are left alone. Returns the mode ('api', 'text-only', or
    'skipped') and the number of links removed.
    """
    if dry_run:
        return "skipped", 0
    mode, removed = "api", 0
    own = {issue["id"] for issue in issues.values() if issue.get("id")}
    for task in data["tasks"]:
        issue = issues[task["id"]]
        path = f"repos/{repo}/issues/{issue['number']}/dependencies/blocked_by"
        try:
            current = gh(f"{path}?per_page=100", ok404=True)
        except GitHubError:
            current = None
        if current is None:
            mode = "text-only"
            continue
        current_ids = {i["id"] for i in current}
        wanted = [issues[dep]["id"] for dep in task["dependsOn"]]
        for blocker_id in wanted:
            if blocker_id not in current_ids:
                gh(path, "POST", {"issue_id": blocker_id})
        for blocker in current:
            if blocker["id"] in own and blocker["id"] not in wanted:
                gh(f"{path}/{blocker['id']}", "DELETE")
                removed += 1
    return mode, removed


def add_to_project(repo: str, title: str, issues: list[dict]) -> str:
    owner = repo.split("/")[0]
    data = graphql(
        "query($login:String!){repositoryOwner(login:$login){id ... on User{projectsV2(first:50){nodes{id title url}}}"
        " ... on Organization{projectsV2(first:50){nodes{id title url}}}}}", login=owner)
    owner_node = data["repositoryOwner"]
    project = next((p for p in owner_node["projectsV2"]["nodes"] if p["title"] == title), None)
    if project is None:
        project = graphql("mutation($owner:ID!,$title:String!){createProjectV2(input:{ownerId:$owner,title:$title}){projectV2{id title url}}}",
                          owner=owner_node["id"], title=title)["createProjectV2"]["projectV2"]
    for issue in issues:
        graphql("mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}",
                p=project["id"], c=issue["node_id"])
    return project["url"]


def close_track(repo: str, scenario: str, track: str) -> int:
    closed = 0
    for issue in existing_issues(repo, scenario, track).values():
        if issue["state"] == "open":
            gh(f"repos/{repo}/issues/{issue['number']}", "PATCH", {"state": "closed", "state_reason": "not_planned"})
            closed += 1
    return closed


def write_summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backlog", type=Path, help="Validated backlog.json to publish")
    parser.add_argument("--track", required=True, choices=sorted(TRACK_NAMES), help="Which demo track produced the backlog")
    parser.add_argument("--repo", help="owner/name (default: current repository)")
    parser.add_argument("--scenario", default="assisted-triage-brief")
    parser.add_argument("--project-title", help="Also add the issues to this GitHub Project (needs the 'project' token scope)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--close", action="store_true", help="Reset: close every issue this track published for the scenario")
    parser.add_argument("--json", action="store_true", help="Print a JSON result")
    parser.add_argument("--revision", type=revision_arg,
                        help="The commit the backlog was read from (full SHA): the epic's Review section names it")
    parser.add_argument("--pull-request", type=int, metavar="N",
                        help="The pull request a person approved (needs --revision). If Microsoft Foundry evaluated its "
                             "brief (the Plan solution combo), publish only a revision it evaluated, whose gates passed "
                             "and whose open items are all ticked; otherwise refuse")
    parser.add_argument("--refusal-file", type=Path,
                        help="When the publisher refuses, also write why to this Markdown file (the workflow comments it)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.pull_request is not None and (args.pull_request < 1 or not args.revision):
        parser.error("--pull-request needs a pull request number and --revision")

    try:
        repo = args.repo or detect_repo()
        if args.close:
            print(f"closed {close_track(repo, args.scenario, args.track)} issue(s) for {args.scenario}/{args.track}")
            return 0
        if not args.backlog:
            parser.error("--backlog is required unless --close is used")

        data = json.loads(args.backlog.read_text(encoding="utf-8"))
        transcript, policies = validate_backlog.find_inputs(args.backlog)
        problems = validate_backlog.validate(data, validate_backlog.source_ids(transcript, policies))
        if problems:
            return refuse(["Refusing to publish: the backlog is not valid.", *[f"  - {problem}" for problem in problems]],
                          args.refusal_file)
        evaluation = None
        if args.pull_request:
            evaluation, refusal = check_evaluation(foundry_evaluations(repo, args.pull_request), args.pull_request,
                                                   args.revision)
            if refusal:
                return refuse([f"Refusing to publish: {refusal}"], args.refusal_file)

        backlog_rel = repo_relative(args.backlog)
        policies_rel = repo_relative(policies)
        excerpts = paragraph_excerpts(transcript)
        review = {"revision": args.revision, "pullRequest": args.pull_request, "repo": repo, "backlog": backlog_rel,
                  "server": os.environ.get("GITHUB_SERVER_URL") or "https://github.com", "evaluation": evaluation}
        ensure_labels(repo, args.track, args.dry_run)
        found = existing_issues(repo, data["scenario"], args.track)
        prefix = f"[Plan/{TRACK_NAMES[args.track]}]"
        base_labels = ["ai-sdlc", "phase:plan", f"track:{args.track}"]
        results: list[dict] = []

        epic, action = upsert(repo, found.get(data["epic"]["id"]), f"{prefix} {data['epic']['title']}",
                              epic_body(data, args.track, backlog_rel, excerpts, policies_rel, review),
                              base_labels + ["type:epic"], args.dry_run)
        results.append({"id": data["epic"]["id"], "number": epic["number"], "url": epic["html_url"], "action": action})

        issues: dict[str, dict] = {data["epic"]["id"]: epic}
        numbers = {t["id"]: found[t["id"]]["number"] for t in data["tasks"] if t["id"] in found}
        for _ in range(2):  # second pass fills in issue numbers for "Depends on" once every task exists
            for task in data["tasks"]:
                body = task_body(data, task, args.track, epic["number"] or None, numbers, excerpts, policies_rel)
                issue, action = upsert(repo, issues.get(task["id"]) or found.get(task["id"]),
                                       f"{prefix} {task['title']}", body, base_labels + ["type:task"], args.dry_run)
                issues[task["id"]] = issue
                if issue["number"]:
                    numbers[task["id"]] = issue["number"]
                previous = next((r for r in results if r["id"] == task["id"]), None)
                if previous is None:
                    results.append({"id": task["id"], "number": issue["number"], "url": issue["html_url"], "action": action})
                elif action == "updated" and previous["action"] == "created":
                    pass  # same run: created, then updated with dependency numbers
                elif action != "unchanged":
                    previous["action"] = action

        task_issues = [issues[t["id"]] for t in data["tasks"]]
        linked = link_sub_issues(repo, epic, task_issues, args.dry_run)
        dependency_mode, dependencies_removed = link_dependencies(repo, data, issues, args.dry_run)
        project_url = add_to_project(repo, args.project_title, [epic, *task_issues]) if args.project_title and not args.dry_run else None
        reported = (report_on_evaluation(repo, evaluation, args.pull_request, args.revision, epic, task_issues, args.dry_run)
                    if evaluation else None)
    except (GitHubError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    counts = {a: sum(1 for r in results if r["action"] == a) for a in {r["action"] for r in results}}
    revision_line = (f"revision {args.revision[:7]}" + (f" of pull request #{args.pull_request}" if args.pull_request else "")
                     if args.revision else None)
    evaluation_line = (f"Foundry evaluation #{evaluation['number']} (run {evaluation['run']}): gates passed, "
                       f"{len(evaluation['openItems'])} open item(s) decided · {reported}" if evaluation else None)
    if args.json:
        print(json.dumps({"repo": repo, "track": args.track, "results": results, "counts": counts,
                          "subIssuesLinked": linked, "dependencies": dependency_mode,
                          "dependenciesRemoved": dependencies_removed, "project": project_url,
                          "revision": args.revision, "pullRequest": args.pull_request,
                          "evaluation": {"issue": evaluation["number"], "run": evaluation["run"],
                                         "openItems": len(evaluation["openItems"]), "reported": reported}
                          if evaluation else None}, indent=2))
    else:
        print(f"{repo} · {data['scenario']} · track {args.track}: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
        for r in results:
            print(f"  {r['action']:>12}  {r['id']:<14} #{r['number']}  {r['url']}")
        print(f"  sub-issues newly linked: {linked} · dependencies: {dependency_mode}"
              + (f" · stale dependencies removed: {dependencies_removed}" if dependencies_removed else "")
              + (f" · project: {project_url}" if project_url else ""))
        for line in (revision_line, evaluation_line):
            if line:
                print(f"  {line}")
    write_summary([f"### Plan backlog published ({TRACK_NAMES[args.track]} track)", "",
                   "| Item | Issue | Result |", "| --- | --- | --- |",
                   *[f"| {r['id']} | [#{r['number']}]({r['url']}) | {r['action']} |" for r in results],
                   *(["", f"Published from {revision_line}."] if revision_line else []),
                   *([f"{evaluation_line}."] if evaluation_line else [])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
