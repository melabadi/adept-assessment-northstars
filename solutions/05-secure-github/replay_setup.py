#!/usr/bin/env python3
"""Set up the nightly remediation replay in this repository (Secure phase, GitHub track).

The replay workflow (.github/workflows/secure-github-verify.yml) proves every night that the Secure lab's regression test
fails on the unsafe search and passes after the repair. It replays a repair pull request of this repository: a branch of
this repository into a lab/secure-* branch, whose head adds the regression test in a commit of its own before the fix.
A copy of this repository has no such pull request, so this script makes one, once, from files in this folder:

  lab/secure-replay-base     main, as it is when you run the script
  lab/secure-replay          plus lab/code-finding.patch: the unsafe search, never merged or deployed
  lab/secure-replay-repair   plus regression/SearchSecurityTests.cs in its own commit, then the search as it is on main

It opens the pull request lab/secure-replay-repair -> lab/secure-replay, closes it at once (the replay reads a closed
pull request; nothing else acts on it), and stores its number in the repository variable SECURE_REPLAY_PR, which the
nightly run reads. Every commit is marked [skip ci], so no workflow runs on these branches. Run it again and it finds the
same pull request and reuses it. To replay a repair Copilot made in a live run instead, --adopt that pull request.

A pull request counts only when its branches are the ones above, in this repository, and a person with write access
(owner, member, or collaborator) opened it. --adopt accepts what the workflow itself accepts: a pull request from a
branch of this repository into a lab/secure-* branch.

Usage, from the repository root:
  python solutions/05-secure-github/replay_setup.py             # create or find the reference repair; store its number
  python solutions/05-secure-github/replay_setup.py --adopt 105 # replay this repair pull request instead
  python solutions/05-secure-github/replay_setup.py --status    # what the nightly replay will use
  python solutions/05-secure-github/replay_setup.py --cleanup   # close it, delete its branches, remove the variable

Needs git and the GitHub CLI (`gh auth login`), signed in as someone who can push branches, open pull requests, and set
repository variables. The repository is the one `gh repo view` resolves from this clone; --repo <owner/name> overrides.
Exit codes: 0 done (with --status: the replay is set up), 1 --status found no usable pull request, 2 git or GitHub refused.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VARIABLE = "SECURE_REPLAY_PR"
BASE, LAB, REPAIR = "lab/secure-replay-base", "lab/secure-replay", "lab/secure-replay-repair"
MARKER = "<!-- ai-sdlc-secure-replay -->"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
TEST = "app/tests/RequestHub.Tests/SearchSecurityTests.cs"
WORKFLOW = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"


def same_repository(pull: dict, repository: str) -> bool:
    return str(((pull.get("head") or {}).get("repo") or {}).get("full_name") or "").lower() == repository.lower()


def replayable(pull: dict, repository: str) -> str | None:
    """Why the workflow would refuse this pull request, as its own check does; None when it would replay it."""
    if not same_repository(pull, repository):
        return "its branch isn't in this repository"
    if not str((pull.get("base") or {}).get("ref") or "").startswith("lab/secure-"):
        return "it doesn't target a lab/secure-* branch"
    return None


def ours(pull: dict, repository: str) -> bool:
    """The reference repair this script made: its branches, this repository, a trusted author, its marker."""
    return (replayable(pull, repository) is None and (pull.get("head") or {}).get("ref") == REPAIR
            and (pull.get("base") or {}).get("ref") == LAB and pull.get("author_association") in TRUSTED
            and MARKER in str(pull.get("body") or ""))


class Tools:
    """git and the GitHub CLI, as the person who runs the script."""

    def __init__(self, repository: str, run=subprocess.run):
        self.repository, self._run = repository, run
        self.url = f"https://github.com/{repository}.git"

    def git(self, *args: str, cwd: Path = ROOT) -> str:
        done = self._run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {(done.stderr or '').strip()[:300]}")
        return done.stdout.strip()

    def gh(self, *args: str, ok_codes: tuple = (0,)) -> str:
        done = self._run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
        if done.returncode not in ok_codes:
            raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {(done.stderr or '').strip()[:300]}")
        return done.stdout.strip() if done.returncode == 0 else ""

    def api(self, path: str, method: str = "GET", fields: dict | None = None):
        args = ["api", "-X", method, f"repos/{self.repository}/{path}"]
        for key, value in (fields or {}).items():
            args += ["-f", f"{key}={value}"]
        out = self.gh(*args)
        return json.loads(out) if out else None

    def pull(self, number: int) -> dict | None:
        try:
            return self.api(f"pulls/{int(number)}")
        except (RuntimeError, ValueError):
            return None

    def variable(self) -> str:
        return self.gh("variable", "get", VARIABLE, "--repo", self.repository, ok_codes=(0, 1)).strip()

    def set_variable(self, value: str) -> None:
        self.gh("variable", "set", VARIABLE, "--repo", self.repository, "--body", value)

    def delete_variable(self) -> None:
        self.gh("variable", "delete", VARIABLE, "--repo", self.repository, ok_codes=(0, 1))

    def remote_branches(self) -> set[str]:
        listed = self.git("ls-remote", "--heads", self.url, BASE, LAB, REPAIR)
        return {line.split("refs/heads/", 1)[1] for line in listed.splitlines() if "refs/heads/" in line}


def find(tools: Tools) -> dict | None:
    """The reference repair pull request, by its branch, if this script made one before."""
    owner = tools.repository.split("/")[0]
    pulls = tools.api(f"pulls?state=all&per_page=100&head={owner}:{REPAIR}") or []
    return next((p for p in pulls if ours(p, tools.repository)), None)


def current(tools: Tools) -> tuple[dict | None, str]:
    """(the pull request the nightly replay will use, or None; why)."""
    value = tools.variable()
    if not value:
        return None, f"the repository variable {VARIABLE} isn't set"
    pull = tools.pull(int(value)) if value.isdigit() else None
    if not pull:
        return None, f"{VARIABLE} is {value!r}, which isn't a pull request of {tools.repository}"
    refusal = replayable(pull, tools.repository)
    return (None, f"#{value} can't be replayed: {refusal}") if refusal else (pull, f"#{value}")


def build(tools: Tools, say) -> None:
    """Push the three lab branches from main, the lab patch, the regression, and the search as it is on main."""
    present = tools.remote_branches()
    if present == {BASE, LAB, REPAIR}:
        say("  the lab branches exist already; reusing them")
        return
    if present:
        raise RuntimeError(f"{', '.join(sorted(present))} exist without the rest; run --cleanup, then setup again")
    tools.git("fetch", "--quiet", tools.url, "main")
    root = tools.git("rev-parse", "FETCH_HEAD")
    regression = tools.git("show", f"{root}:solutions/05-secure-github/regression/SearchSecurityTests.cs")
    with tempfile.TemporaryDirectory(prefix="secure-replay-") as folder:
        tree = Path(folder) / "tree"
        tools.git("worktree", "add", "--quiet", "--detach", str(tree), root)
        try:
            tools.git("push", "--quiet", tools.url, f"HEAD:refs/heads/{BASE}", cwd=tree)
            tools.git("apply", "--ignore-space-change", "solutions/05-secure-github/lab/code-finding.patch", cwd=tree)
            tools.git("add", WORKFLOW, cwd=tree)
            tools.git("commit", "--quiet", "--no-verify", "-m",
                      "Secure lab: intentionally unsafe search, never deploy or merge [skip ci]", cwd=tree)
            tools.git("push", "--quiet", tools.url, f"HEAD:refs/heads/{LAB}", cwd=tree)
            (tree / TEST).write_text(regression + "\n", encoding="utf-8", newline="\n")
            tools.git("add", TEST, cwd=tree)
            tools.git("commit", "--quiet", "--no-verify", "-m",
                      "Add the search security regression; it fails before the repair [skip ci]", cwd=tree)
            tools.git("checkout", root, "--", WORKFLOW, cwd=tree)
            tools.git("commit", "--quiet", "--no-verify", "-am",
                      "Repair the search: parameters again, as on main (reference repair) [skip ci]", cwd=tree)
            tools.git("push", "--quiet", tools.url, f"HEAD:refs/heads/{REPAIR}", cwd=tree)
        finally:
            tools.git("worktree", "remove", "--force", str(tree))


def setup(tools: Tools, say=print) -> int:
    pull, _ = current(tools)
    if pull and ours(pull, tools.repository):
        say(f"The nightly replay uses #{pull['number']} (reused): {VARIABLE} is set.")
        return int(pull["number"])
    pull = find(tools)
    if pull is None:
        build(tools, say)
        pull = tools.api("pulls", "POST", {
            "title": "Secure replay: reference repair of the unsafe search (never merge)", "head": REPAIR, "base": LAB,
            "body": f"{MARKER}\nThe pull request the nightly remediation replay (secure-github-verify.yml) replays: "
                    "the regression in its own commit, then the repair. Training fixture on lab branches: never reopen, "
                    "merge, or deploy it. Made by solutions/05-secure-github/replay_setup.py."})
        tools.api(f"pulls/{pull['number']}", "PATCH", {"state": "closed"})
        say(f"Created #{pull['number']}: {REPAIR} -> {LAB}, closed.")
    else:
        say(f"Found #{pull['number']}, made by an earlier setup.")
    tools.set_variable(str(pull["number"]))
    say(f"{VARIABLE} = {pull['number']}: the nightly replay uses it.")
    return int(pull["number"])


def adopt(tools: Tools, number: int, say=print) -> int:
    pull = tools.pull(number)
    if not pull:
        raise RuntimeError(f"#{number} isn't a pull request of {tools.repository}")
    refusal = replayable(pull, tools.repository)
    if refusal:
        raise RuntimeError(f"#{number} can't be replayed: {refusal}")
    tools.set_variable(str(number))
    say(f"{VARIABLE} = {number}: the nightly replay uses it.")
    return number


def cleanup(tools: Tools, say=print) -> None:
    pull = find(tools)
    if pull and pull.get("state") == "open":
        tools.api(f"pulls/{pull['number']}", "PATCH", {"state": "closed"})
    present = sorted(tools.remote_branches())
    if present:
        tools.git("push", "--quiet", tools.url, "--delete", *present)
    value = tools.variable()
    if value and (not pull or value == str(pull["number"])):
        tools.delete_variable()
    say(f"{'#' + str(pull['number']) + ' closed; ' if pull else ''}{len(present)} lab branches deleted; "
        f"{VARIABLE} {'removed' if value and (not pull or value == str(pull['number'])) else 'left as it was'}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--adopt", type=int, metavar="PR", help="Replay this repair pull request instead of the reference one")
    group.add_argument("--status", action="store_true", help="Say which pull request the nightly replay will use")
    group.add_argument("--cleanup", action="store_true", help="Close the reference repair, delete its branches, remove the variable")
    parser.add_argument("--repo", help="owner/name (default: the repository of this clone, from `gh repo view`)")
    args = parser.parse_args(argv)
    try:
        repository = args.repo or Tools("").gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
        tools = Tools(repository)
        if args.status:
            pull, why = current(tools)
            print(f"The nightly replay in {repository} uses {why}." if pull else
                  f"The nightly replay in {repository} isn't set up: {why}. Run "
                  "`python solutions/05-secure-github/replay_setup.py` once, or --adopt a repair pull request.")
            return 0 if pull else 1
        if args.cleanup:
            cleanup(tools)
        elif args.adopt:
            adopt(tools, args.adopt)
        else:
            setup(tools)
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
