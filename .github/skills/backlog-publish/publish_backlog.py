#!/usr/bin/env python3
"""Publish a validated Plan-phase backlog to GitHub Issues, idempotently.

What it does
  1. Validates backlog.json with ../requirements-traceability/validate_backlog.py (refuses to publish if invalid).
  2. Ensures labels exist: ai-sdlc, phase:plan, type:epic, type:task, track:<track>.
  3. Creates or updates one epic issue and one issue per task. Each issue body carries a hidden marker
     <!-- ai-sdlc-backlog: <scenario>/<track>/<item id> -->, so re-running updates instead of duplicating.
  4. Links every task as a sub-issue of the epic and records "blocked by" dependencies between tasks
     (falls back to a text link when the dependencies API is unavailable).
  5. Optionally adds the issues to a GitHub Project (--project-title). Projects need a token with the
     `project` scope (your `gh auth login`); the Actions GITHUB_TOKEN cannot access projects.

It calls the GitHub CLI (`gh api`), so it uses your gh login locally and GH_TOKEN in GitHub Actions.

Usage
  python .github/skills/backlog-publish/publish_backlog.py --backlog solutions/01-plan-github/brief/backlog.json --track github
  python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track microsoft --dry-run
  python .github/skills/backlog-publish/publish_backlog.py --backlog <path> --track github --project-title "AI-SDLC Plan demo"
  python .github/skills/backlog-publish/publish_backlog.py --track github --close    # demo reset: close this track's issues

The transcript and policies the backlog cites are read from the nearest `inputs/` folder above the backlog.

Exit codes: 0 success, 1 validation failed, 2 GitHub/API or usage error.
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


def epic_body(data: dict, track: str, backlog_path: str, excerpts: dict[str, str], policies_path: str) -> str:
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


def existing_issues(repo: str, scenario: str, track: str) -> dict[str, dict]:
    found = {}
    pattern = re.compile(re.escape(f"<!-- ai-sdlc-backlog: {scenario}/{track}/") + r"([A-Z0-9-]+) -->")
    for issue in gh(f"repos/{repo}/issues?state=all&labels=phase:plan&per_page=100", paginate=True):
        match = pattern.search(issue.get("body") or "")
        if match and "pull_request" not in issue:
            found[match.group(1)] = issue
    return found


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


def link_dependencies(repo: str, data: dict, issues: dict[str, dict], dry_run: bool) -> str:
    """Record 'blocked by' relationships. Returns 'api', 'text-only', or 'skipped'."""
    if dry_run:
        return "skipped"
    mode = "api"
    for task in data["tasks"]:
        issue = issues[task["id"]]
        try:
            current = gh(f"repos/{repo}/issues/{issue['number']}/dependencies/blocked_by", ok404=True)
        except GitHubError:
            current = None
        if current is None:
            mode = "text-only"
            continue
        current_ids = {i["id"] for i in current}
        for dep in task["dependsOn"]:
            blocker = issues[dep]
            if blocker["id"] not in current_ids:
                gh(f"repos/{repo}/issues/{issue['number']}/dependencies/blocked_by", "POST", {"issue_id": blocker["id"]})
    return mode


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
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

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
            print("Refusing to publish: the backlog is not valid.", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1

        backlog_rel = repo_relative(args.backlog)
        policies_rel = repo_relative(policies)
        excerpts = paragraph_excerpts(transcript)
        ensure_labels(repo, args.track, args.dry_run)
        found = existing_issues(repo, data["scenario"], args.track)
        prefix = f"[Plan/{TRACK_NAMES[args.track]}]"
        base_labels = ["ai-sdlc", "phase:plan", f"track:{args.track}"]
        results: list[dict] = []

        epic, action = upsert(repo, found.get(data["epic"]["id"]), f"{prefix} {data['epic']['title']}",
                              epic_body(data, args.track, backlog_rel, excerpts, policies_rel), base_labels + ["type:epic"], args.dry_run)
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
        dependency_mode = link_dependencies(repo, data, issues, args.dry_run)
        project_url = add_to_project(repo, args.project_title, [epic, *task_issues]) if args.project_title and not args.dry_run else None
    except (GitHubError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    counts = {a: sum(1 for r in results if r["action"] == a) for a in {r["action"] for r in results}}
    if args.json:
        print(json.dumps({"repo": repo, "track": args.track, "results": results, "counts": counts,
                          "subIssuesLinked": linked, "dependencies": dependency_mode, "project": project_url}, indent=2))
    else:
        print(f"{repo} · {data['scenario']} · track {args.track}: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
        for r in results:
            print(f"  {r['action']:>12}  {r['id']:<14} #{r['number']}  {r['url']}")
        print(f"  sub-issues newly linked: {linked} · dependencies: {dependency_mode}" + (f" · project: {project_url}" if project_url else ""))
    write_summary([f"### Plan backlog published ({TRACK_NAMES[args.track]} track)", "",
                   "| Item | Issue | Result |", "| --- | --- | --- |",
                   *[f"| {r['id']} | [#{r['number']}]({r['url']}) | {r['action']} |" for r in results]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
