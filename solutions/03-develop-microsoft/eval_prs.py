"""The pull requests the Azure reviewer's evaluation dry-runs, created in this repository (Develop phase, Microsoft track).

The evaluation dry-runs the deployed reviewer on labelled pull requests, so they must exist in the repository the
reviewer reviews. A copy of this repository has the commits of main but none of the original pull requests, so each
labelled case in eval_cases.jsonl carries its change as data: `root`, the commit of main the original pull request
started from; eval_changes/<id>.patch, the app/ part of that pull request; and, when it targeted a lab branch rather
than main, eval_changes/<id>.base.patch, that branch's change. `setup` builds two branches per case with your git:

  eval/pr-review/<id>-base   the root commit, plus the base patch if there is one
  eval/pr-review/<id>        one more commit with the change, marked [skip ci] so no workflow runs on it

then opens the pull request between them with your GitHub CLI and closes it at once: a dry run reviews a closed pull
request; nobody merges it, and nothing else acts on it. The pull requests' numbers are kept in the azd environment
(REVIEWER_EVAL_PRS), and a second `setup` reuses them. A stored or discovered pull request is used only when its branches
are the ones above, in this repository, and a person with write access (owner, member, or collaborator) opened it, so
nobody else's pull request can stand in for a labelled case. `cleanup` closes them, deletes their branches, and forgets
their numbers.

Run it through eval_reviewer.py:
  python eval_reviewer.py --setup      # create the missing pull requests, reuse the rest (a minute or two the first time)
  python eval_reviewer.py --cleanup    # remove them

Settings: GITHUB_REPOSITORY (owner/name) from the environment or this solution's azd environment. Needs git and the
GitHub CLI signed in as someone who can push branches and open pull requests in that repository.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANGES = HERE / "eval_changes"
PREFIX = "eval/pr-review/"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
SETTING = "REVIEWER_EVAL_PRS"


class SetupMissing(Exception):
    """The evaluation's pull requests aren't set up in this repository; the message says what to run."""


def branches(case_id: str) -> tuple[str, str]:
    """(head, base) branch names of a case's pull request."""
    return f"{PREFIX}{case_id}", f"{PREFIX}{case_id}-base"


def marker(case_id: str) -> str:
    return f"<!-- ai-sdlc-reviewer-eval: {case_id} -->"


def ours(pull: dict, repository: str, case_id: str) -> bool:
    """Whether this pull request is the case's evaluation pull request: its branches, in this repository, opened by
    someone with write access. Anything else, a fork's pull request included, never stands in for a labelled case."""
    head, base = branches(case_id)
    return (str(((pull.get("head") or {}).get("repo") or {}).get("full_name") or "").lower() == repository.lower()
            and (pull.get("head") or {}).get("ref") == head and (pull.get("base") or {}).get("ref") == base
            and pull.get("author_association") in TRUSTED and marker(case_id) in str(pull.get("body") or ""))


class GitHub:
    """GitHub's REST API through the person's GitHub CLI (`gh api`)."""

    def __init__(self, repository: str, run=subprocess.run):
        self.repository, self._run = repository, run

    def api(self, path: str, method: str = "GET", fields: dict | None = None):
        command = ["gh", "api", "-X", method, f"repos/{self.repository}/{path}"]
        for key, value in (fields or {}).items():
            command += ["-f", f"{key}={value}"]
        done = self._run(command, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise RuntimeError(f"GitHub refused {method} {path.split('?')[0]}: {(done.stderr or '').strip()[:200]}")
        return json.loads(done.stdout) if done.stdout.strip() else None

    def pull(self, number: int) -> dict | None:
        try:
            return self.api(f"pulls/{int(number)}")
        except RuntimeError:
            return None

    def find(self, case_id: str) -> dict | None:
        """The newest evaluation pull request of this case, open or closed."""
        head, _ = branches(case_id)
        owner = self.repository.split("/")[0]
        pulls = self.api(f"pulls?state=all&per_page=100&head={owner}:{head}") or []
        return next((p for p in pulls if ours(p, self.repository, case_id)), None)


def stored(value: str | None, repository: str) -> dict[str, int]:
    """The pull request numbers kept in the azd environment, if they were kept for this repository."""
    try:
        data = json.loads(value or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict) or str(data.get("repository", "")).lower() != repository.lower():
        return {}
    return {str(k): int(v) for k, v in (data.get("pulls") or {}).items() if str(v).isdigit()}


def resolve(cases: list[dict], github: GitHub, kept: dict[str, int]) -> tuple[dict[str, int], list[str]]:
    """({case id: pull request number} for every case set up in this repository, [case ids that aren't]). A kept
    number is checked against GitHub; when it no longer matches, the case's pull request is looked up by its branch."""
    found, missing = {}, []
    for case in cases:
        number = kept.get(case["id"])
        pull = github.pull(number) if number else None
        if not (pull and ours(pull, github.repository, case["id"])):
            pull = github.find(case["id"])
        if pull:
            found[case["id"]] = int(pull["number"])
        else:
            missing.append(case["id"])
    return found, missing


def require(cases: list[dict], github: GitHub, kept: dict[str, int]) -> dict[str, int]:
    """Every case's pull request number, or SetupMissing naming what to run."""
    found, missing = resolve(cases, github, kept)
    if missing:
        raise SetupMissing(f"the evaluation's pull requests aren't set up in {github.repository}: {', '.join(missing)} "
                           f"{'has' if len(missing) == 1 else 'have'} none. Run `python eval_reviewer.py --setup` once in "
                           "solutions/03-develop-microsoft: it creates them from eval_changes/, or finds the ones it "
                           "created before")
    return found


class Git:
    """The person's git, in their clone of the repository."""

    def __init__(self, repository: str, run=subprocess.run, cwd: Path = HERE):
        self.url, self._run, self.cwd = f"https://github.com/{repository}.git", run, cwd

    def __call__(self, *args: str, cwd: Path | None = None) -> str:
        done = self._run(["git", *args], cwd=cwd or self.cwd, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {(done.stderr or '').strip()[:300]}")
        return done.stdout.strip()

    def has(self, sha: str) -> bool:
        return self._run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=self.cwd, capture_output=True).returncode == 0

    def remote_branches(self, *names: str) -> set[str]:
        listed = self(*["ls-remote", "--heads", self.url, *names])
        return {line.split("refs/heads/", 1)[1] for line in listed.splitlines() if "refs/heads/" in line}


def build(case: dict, git: Git) -> None:
    """Push the case's two branches: the root commit plus its base patch, then one commit with the change."""
    head, base = branches(case["id"])
    present = git.remote_branches(head, base)
    if present == {head, base}:
        return  # an earlier setup pushed them; only the pull request is missing
    if present:
        raise RuntimeError(f"{', '.join(sorted(present))} exists without the rest of {case['id']}'s branches; run "
                           "`python eval_reviewer.py --cleanup`, then --setup again")
    if not git.has(case["root"]):
        git("fetch", "--quiet", git.url, "main")
        if not git.has(case["root"]):
            raise RuntimeError(f"commit {case['root'][:12]}, where {case['id']} starts, isn't in {git.url}'s history: "
                               "make the copy with the history of main (a fork or a mirror push), not from a template")
    with tempfile.TemporaryDirectory(prefix="eval-pr-") as folder:
        tree = Path(folder) / "tree"
        git("worktree", "add", "--quiet", "--detach", str(tree), case["root"])
        try:
            base_patch = CHANGES / f"{case['id']}.base.patch"
            if base_patch.is_file():
                git("apply", "--whitespace=nowarn", str(base_patch), cwd=tree)
                git("add", "--all", "app", cwd=tree)
                git("commit", "--quiet", "--no-verify", "-m",
                    f"Evaluation fixture {case['id']}: the lab branch its change targeted [skip ci]", cwd=tree)
            git("push", "--quiet", git.url, f"HEAD:refs/heads/{base}", cwd=tree)
            git("apply", "--whitespace=nowarn", str(CHANGES / f"{case['id']}.patch"), cwd=tree)
            git("add", "--all", "app", cwd=tree)
            git("commit", "--quiet", "--no-verify", "-m", f"{case['why']} (evaluation fixture {case['id']}) [skip ci]",
                cwd=tree)
            git("push", "--quiet", git.url, f"HEAD:refs/heads/{head}", cwd=tree)
        finally:
            git("worktree", "remove", "--force", str(tree))


def open_closed(case: dict, github: GitHub) -> int:
    """Open the case's pull request and close it at once; returns its number."""
    head, base = branches(case["id"])
    example = case.get("example")
    body = (f"{marker(case['id'])}\nEvaluation fixture for the Azure pull request reviewer (solutions/03-develop-microsoft): "
            f"{case['kind']}, {case['why']} It is a dry-run target only: never reopen or merge it."
            + (f"\n\nThe change comes from pull request #{example} of the original repository." if example else ""))
    pull = github.api("pulls", "POST", {"title": f"[eval] {case['id']}: {case['why']}"[:250], "head": head,
                                        "base": base, "body": body})
    github.api(f"pulls/{pull['number']}", "PATCH", {"state": "closed"})
    return int(pull["number"])


def setup(cases: list[dict], github: GitHub, git: Git, kept: dict[str, int], save, say=print) -> dict[str, int]:
    """Reuse the cases' pull requests that exist, create the others, and keep every number with save(json)."""
    found, missing = resolve(cases, github, kept)
    for case in cases:
        if case["id"] in found:
            say(f"  {case['id']:<22} #{found[case['id']]} (reused)")
            continue
        build(case, git)
        found[case["id"]] = open_closed(case, github)
        say(f"  {case['id']:<22} #{found[case['id']]} (created)")
    save(json.dumps({"repository": github.repository, "pulls": found}, sort_keys=True))
    return found


def cleanup(cases: list[dict], github: GitHub, git: Git, kept: dict[str, int], save, say=print) -> None:
    """Close the cases' pull requests (they are closed already, unless someone reopened one), delete their branches,
    and forget their numbers. Only pull requests and branches setup made are touched."""
    found, _ = resolve(cases, github, kept)
    for case in cases:
        number = found.get(case["id"])
        if number and (github.pull(number) or {}).get("state") == "open":
            github.api(f"pulls/{number}", "PATCH", {"state": "closed"})
        present = sorted(git.remote_branches(*branches(case["id"])))
        if present:
            git("push", "--quiet", git.url, "--delete", *present)
        say(f"  {case['id']:<22} {'#' + str(number) + ' closed, ' if number else ''}"
            f"{len(present)} branch{'es' if len(present) != 1 else ''} deleted")
    save("")
