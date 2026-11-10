"""Tests for eval_prs.py: the evaluation's pull requests are created once per repository, reused, and only ever adopted
from this repository's own branches and trusted authors. No GitHub or network: git and gh are fakes.

Run from the repository root:  python -m unittest discover -s solutions/03-develop-microsoft -p "test_eval_prs.py" -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_prs  # noqa: E402

REPO = "octo/requesthub"
CASES = [json.loads(line) for line in (HERE / "eval_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
CASE = {"id": "admins-decide", "example": 36, "root": "a" * 40, "kind": "known-bad", "why": "Lets admins decide."}


def pull(number: int, case_id: str, *, repo: str = REPO, author: str = "OWNER", state: str = "closed", body: str | None = None):
    head, base = eval_prs.branches(case_id)
    return {"number": number, "state": state, "author_association": author, "body": eval_prs.marker(case_id) if body is None else body,
            "head": {"ref": head, "repo": {"full_name": repo}}, "base": {"ref": base}}


class FakeGitHub(eval_prs.GitHub):
    def __init__(self, pulls=()):
        super().__init__(REPO, run=None)
        self.pulls = {p["number"]: p for p in pulls}
        self.calls = []

    def api(self, path, method="GET", fields=None):
        self.calls.append((method, path, fields))
        if method == "POST":
            number = max(self.pulls, default=200) + 1
            self.pulls[number] = pull(number, fields["head"].removeprefix(eval_prs.PREFIX), state="open", body=fields["body"])
            return self.pulls[number]
        if method == "PATCH":
            self.pulls[int(path.split("/")[1])].update(fields)
            return self.pulls[int(path.split("/")[1])]
        if path.startswith("pulls?"):
            head = re.search(r"head=[^:]+:([^&]+)", path).group(1)
            return [p for p in sorted(self.pulls.values(), key=lambda p: -p["number"]) if p["head"]["ref"] == head]
        number = int(path.split("/")[1])
        if number not in self.pulls:
            raise RuntimeError("not found")
        return self.pulls[number]


class FakeGit(eval_prs.Git):
    def __init__(self, remote=(), commits=("a" * 40,)):
        super().__init__(REPO, run=None)
        self.remote, self.commits, self.calls = set(remote), set(commits), []

    def __call__(self, *args, cwd=None):
        self.calls.append(args)
        if args[0] == "push" and "--delete" not in args:
            self.remote.add(args[-1].removeprefix("HEAD:refs/heads/"))
        if args[0] == "push" and "--delete" in args:
            self.remote -= set(args[args.index("--delete") + 1:])
        return ""

    def has(self, sha):
        return sha in self.commits

    def remote_branches(self, *names):
        return {name for name in names if name in self.remote}


class AdoptionTests(unittest.TestCase):
    def test_only_this_repositorys_branches_by_a_trusted_author_stand_in_for_a_case(self):
        self.assertTrue(eval_prs.ours(pull(5, "admins-decide"), REPO, "admins-decide"))
        self.assertTrue(eval_prs.ours(pull(5, "admins-decide", repo="Octo/RequestHub"), REPO, "admins-decide"))
        for wrong in (pull(5, "admins-decide", repo="mallory/requesthub"),  # a fork's pull request
                      pull(5, "admins-decide", author="NONE"),  # someone without write access
                      pull(5, "admins-decide", body="no marker"),
                      pull(5, "literal-wildcards")):  # another case's branches
            self.assertFalse(eval_prs.ours(wrong, REPO, "admins-decide"))

    def test_kept_numbers_count_only_for_their_repository(self):
        kept = json.dumps({"repository": REPO, "pulls": {"admins-decide": 7}})
        self.assertEqual(eval_prs.stored(kept, REPO), {"admins-decide": 7})
        self.assertEqual(eval_prs.stored(kept, "octo/other"), {})
        self.assertEqual(eval_prs.stored("not json", REPO), {})
        self.assertEqual(eval_prs.stored(None, REPO), {})

    def test_a_kept_number_is_checked_and_replaced_when_it_no_longer_matches(self):
        github = FakeGitHub([pull(7, "literal-wildcards"), pull(9, "admins-decide")])
        found, missing = eval_prs.resolve([CASE], github, {"admins-decide": 7})  # #7 is another case's
        self.assertEqual((found, missing), ({"admins-decide": 9}, []))
        found, missing = eval_prs.resolve([CASE], FakeGitHub(), {})
        self.assertEqual((found, missing), ({}, ["admins-decide"]))

    def test_an_unconfigured_evaluation_says_what_to_run(self):
        with self.assertRaises(eval_prs.SetupMissing) as caught:
            eval_prs.require([CASE], FakeGitHub(), {})
        self.assertIn("python eval_reviewer.py --setup", str(caught.exception))
        self.assertIn("admins-decide", str(caught.exception))
        self.assertIn(REPO, str(caught.exception))


class SetupTests(unittest.TestCase):
    def run_setup(self, github, git, kept=None):
        saved, said = [], []
        found = eval_prs.setup([CASE], github, git, kept or {}, saved.append, said.append)
        return found, saved, said

    def test_the_first_setup_builds_both_branches_and_a_closed_pull_request(self):
        github, git = FakeGitHub(), FakeGit()
        found, saved, said = self.run_setup(github, git)
        number = found["admins-decide"]
        self.assertEqual(github.pulls[number]["state"], "closed")
        self.assertEqual(git.remote, set(eval_prs.branches("admins-decide")))
        commits = [args for args in git.calls if args[0] == "commit"]
        self.assertTrue(commits and all("[skip ci]" in args[-1] for args in commits), "no workflow may run on a fixture")
        self.assertEqual(json.loads(saved[-1]), {"repository": REPO, "pulls": {"admins-decide": number}})
        self.assertIn("(created)", said[0])

    def test_a_second_setup_reuses_the_pull_request_without_touching_git(self):
        github, git = FakeGitHub([pull(42, "admins-decide")]), FakeGit()
        found, saved, said = self.run_setup(github, git, {"admins-decide": 42})
        self.assertEqual(found, {"admins-decide": 42})
        self.assertEqual(git.calls, [])
        self.assertFalse(any(method == "POST" for method, _, _ in github.calls))
        self.assertIn("#42 (reused)", said[0])

    def test_branches_left_by_an_earlier_setup_are_reused(self):
        github, git = FakeGitHub(), FakeGit(remote=eval_prs.branches("admins-decide"))
        found, _, _ = self.run_setup(github, git)
        self.assertIn("admins-decide", found)
        self.assertFalse(any(args[0] == "push" for args in git.calls))

    def test_half_a_case_or_a_missing_root_stops_with_what_to_do(self):
        with self.assertRaisesRegex(RuntimeError, "--cleanup"):
            self.run_setup(FakeGitHub(), FakeGit(remote={eval_prs.branches("admins-decide")[1]}))
        with self.assertRaisesRegex(RuntimeError, "history of main"):
            self.run_setup(FakeGitHub(), FakeGit(commits=()))

    def test_cleanup_deletes_only_the_cases_branches_and_forgets_the_numbers(self):
        github = FakeGitHub([pull(42, "admins-decide", state="open")])
        git = FakeGit(remote={*eval_prs.branches("admins-decide"), "main", "eval/pr-review/someone-else"})
        saved, said = [], []
        eval_prs.cleanup([CASE], github, git, {"admins-decide": 42}, saved.append, said.append)
        self.assertEqual(github.pulls[42]["state"], "closed")
        self.assertEqual(git.remote, {"main", "eval/pr-review/someone-else"})
        self.assertEqual(saved, [""])


class FixtureTests(unittest.TestCase):
    """The cases carry their changes as data, and nothing in them can run a workflow or touch another solution."""

    def test_every_case_has_a_root_and_an_app_only_patch(self):
        ids = [case["id"] for case in CASES]
        self.assertEqual(len(ids), len(set(ids)))
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertRegex(case["id"], r"^[a-z0-9-]+$")
                self.assertRegex(case["root"], r"^[0-9a-f]{40}$")
                self.assertIsInstance(case["example"], int)
                patches = [eval_prs.CHANGES / f"{case['id']}.patch"] + list(eval_prs.CHANGES.glob(f"{case['id']}.base.patch"))
                self.assertTrue(patches[0].is_file())
                for patch in patches:
                    paths = re.findall(r"^diff --git a/(\S+) b/(\S+)$", patch.read_text(encoding="utf-8"), re.M)
                    self.assertTrue(paths)
                    self.assertTrue(all(a.startswith("app/") and b.startswith("app/") for a, b in paths), patch.name)
        self.assertEqual({p.name.split(".")[0] for p in eval_prs.CHANGES.iterdir()}, set(ids))

    def test_every_patch_applies_to_its_root(self):
        """Needs the history of main, as a copy of the repository has; a shallow clone skips it."""
        root_dir = HERE.parents[1]
        for case in CASES:
            with self.subTest(case=case["id"]):
                if subprocess.run(["git", "cat-file", "-e", f"{case['root']}^{{commit}}"], cwd=root_dir,
                                  capture_output=True).returncode:
                    self.skipTest("this clone doesn't have the history of main")
                index = HERE / "out" / f"index-{case['id']}"
                index.parent.mkdir(exist_ok=True)
                env = {**os.environ, "GIT_INDEX_FILE": str(index)}
                try:
                    subprocess.run(["git", "read-tree", case["root"]], cwd=root_dir, env=env, check=True, capture_output=True)
                    for patch in (eval_prs.CHANGES / f"{case['id']}.base.patch", eval_prs.CHANGES / f"{case['id']}.patch"):
                        if patch.is_file():
                            done = subprocess.run(["git", "apply", "--cached", str(patch)], cwd=root_dir, env=env,
                                                  capture_output=True, text=True)
                            self.assertEqual(done.returncode, 0, done.stderr)
                finally:
                    index.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
