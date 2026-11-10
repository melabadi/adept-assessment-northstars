"""Offline tests for candidate.py, the script that deploys one commit as an API revision and load-tests it.

They check the names that link a commit to its revision and its load test run (revision suffixes without hyphens, run
ids the report names, a description the reporting function reads back), which image `restore` goes back to, the
Azure CLI calls each command makes, and that `deploy` builds only a commit on a branch of this repository, never a
fork's pull request commit. No Azure access is needed: a fake `az` answers, and the branch check runs against small
git repositories in a temporary folder.

Run from this folder:
  python -m unittest -v test_candidate
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "function"))
import candidate  # noqa: E402
from reporter import flow, report  # noqa: E402

SHA = "9f1c2ab3d4e5f60718293a4b5c6d7e8f90a1b2c3"
NOW = datetime(2026, 11, 10, 5, 15, 0, tzinfo=timezone.utc)
REGISTRY = "registry.example.test"
NORMAL = f"{REGISTRY}/ai-sdlc-test-microsoft/api-ai-sdlc-test:azd-deploy-1793430330"
CANDIDATE = f"{REGISTRY}/requesthub-api:{SHA}"


class NamesTests(unittest.TestCase):
    def test_only_a_full_commit_sha_is_accepted(self):
        self.assertEqual(candidate.commit(f" {SHA.upper()} "), SHA)
        for bad in (SHA[:7], SHA + "0", "g" * 40, "", "main"):
            with self.assertRaises(argparse.ArgumentTypeError):
                candidate.commit(bad)

    def test_an_issue_is_a_positive_number(self):
        self.assertEqual(candidate.issue_number("284"), 284)
        for bad in ("0", "-1", "#284", "abc", "10000000"):
            with self.assertRaises(argparse.ArgumentTypeError):
                candidate.issue_number(bad)

    def test_the_revision_suffix_names_the_commit_without_hyphens(self):
        self.assertEqual(candidate.suffix_for(SHA, set(), NOW), "c9f1c2ab")
        # A revision can't be deleted: a second deployment of the same commit adds the time.
        self.assertEqual(candidate.suffix_for(SHA, {"0000025", "c9f1c2ab"}, NOW), "c9f1c2abt11100515")
        for suffix in (candidate.suffix_for(SHA, set(), NOW), candidate.suffix_for(SHA, {"c9f1c2ab"}, NOW)):
            self.assertNotIn("-", suffix)
            self.assertRegex(suffix, r"^[a-z][a-z0-9]+$")

    def test_a_candidate_image_names_its_commit(self):
        self.assertEqual(candidate.candidate_sha(CANDIDATE), SHA)
        for other in (NORMAL, f"{REGISTRY}/requesthub-api:latest", f"{REGISTRY}/requesthub-api@sha256:{'a' * 64}",
                      f"{REGISTRY}/other/requesthub-api:{SHA}", "", None):
            self.assertEqual(candidate.candidate_sha(other), "")

    def test_restore_goes_back_to_the_newest_normal_image(self):
        revisions = [
            {"name": "app--0000024", "created": "2026-10-31T07:07:51+00:00", "image": NORMAL},
            {"name": "app--0000023", "created": "2026-10-31T04:48:57+00:00", "image": NORMAL + "-old"},
            {"name": "app--c9f1c2ab", "created": "2026-11-10T05:00:00+00:00", "image": CANDIDATE},
            {"name": "app--0000026", "created": "2026-11-10T05:05:00+00:00", "image": CANDIDATE},  # the slowdown, on top
        ]
        self.assertEqual(candidate.normal_revision(revisions)["name"], "app--0000024")
        self.assertIsNone(candidate.normal_revision(revisions[2:]))

    def test_the_run_names_the_commit_and_the_revision_the_way_the_function_reads_them(self):
        run_id = candidate.run_id(SHA, NOW)
        self.assertEqual(run_id, "candidate-9f1c2ab-20261110-051500")
        self.assertRegex(run_id, flow.RUN_ID)
        self.assertEqual(report.run_name({"testRunId": run_id}), run_id)
        description = candidate.run_description(SHA, "c9f1c2ab", 284)
        self.assertEqual(description, f"Commit {SHA} on API revision c9f1c2ab for Issue #284")
        self.assertEqual(report.candidate({"description": description}),
                         {"commit": SHA, "revision": "c9f1c2ab", "issue": 284})
        self.assertEqual(report.candidate({"description": candidate.run_description(SHA, "c9f1c2abt11100515")}),
                         {"commit": SHA, "revision": "c9f1c2abt11100515"})
        # Azure Load Testing takes descriptions of up to 100 characters; the longest one candidate.py writes fits.
        self.assertEqual(len(candidate.run_description(SHA, "c9f1c2abt11100515", 9_999_999)), 100)


class FakeAz:
    """Answers the Azure CLI calls candidate.py makes, from a small model of the API container app."""

    def __init__(self, image, env, revisions, revision="app--current"):
        self.image, self.env, self.revisions, self.revision, self.calls = image, env, revisions, revision, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("containerapp", "show"):
            query = args[args.index("--query") + 1]
            if query.startswith("properties.template.containers[0].env"):
                return [e["name"] for e in self.env]
            return {"revision": self.revision, "image": self.image, "env": [e["name"] for e in self.env]}
        if args[:3] == ("containerapp", "revision", "list"):
            query = args[args.index("--query") + 1]
            return [r["name"] for r in self.revisions] if query == "[].name" else self.revisions
        if args[:2] == ("containerapp", "update"):
            suffix = args[args.index("--revision-suffix") + 1] if "--revision-suffix" in args else "0000027"
            return f"app--{suffix}"
        if args[:3] == ("load", "test-run", "create"):
            return None
        raise AssertionError(f"unexpected az call: {args}")


def settings(name, default=None):
    return {"AZURE_RESOURCE_GROUP": "rg-ai-sdlc-test", "API_APP_NAME": "app", "LOAD_TEST_NAME": "lt",
            "AZURE_CONTAINER_REGISTRY_NAME": "registry", "AZURE_CONTAINER_REGISTRY_ENDPOINT": REGISTRY}[name]


class CommandTests(unittest.TestCase):
    def run_command(self, fake, *argv, build_sha=SHA, branches=("copilot/fix-duplicate-decisions",)):
        out = io.StringIO()
        with mock.patch.object(candidate, "az", fake), mock.patch("slowdown.az", fake), \
                mock.patch.object(candidate, "setting", settings), mock.patch("slowdown.setting", settings), \
                mock.patch.object(candidate, "wait_for") as wait, \
                mock.patch.object(candidate, "served_build", return_value=build_sha), \
                mock.patch.object(candidate, "branches_with", return_value=list(branches)), \
                mock.patch.object(candidate, "build", return_value=CANDIDATE) as build, \
                mock.patch.object(candidate, "datetime", wraps=datetime) as clock, redirect_stdout(out):
            clock.now.return_value = NOW
            code = candidate.main(list(argv))
        self.build = build
        return code, out.getvalue(), wait

    def updates(self, fake):
        return [call for call in fake.calls if call[:2] == ("containerapp", "update")]

    def test_deploy_names_the_revision_after_the_commit_and_lets_the_image_report_its_build(self):
        env = [{"name": "BUILD_SHA", "value": "local"}, {"name": "Faults__QueueDelayMs", "value": "1500"},
               {"name": "OTEL_SERVICE_NAME", "value": "requesthub-api"}]
        fake = FakeAz(NORMAL, env, [{"name": "app--0000025"}])
        code, out, wait = self.run_command(fake, "deploy", SHA)
        self.assertEqual(code, 0)
        (update,) = self.updates(fake)
        self.assertEqual(update[update.index("--image") + 1], CANDIDATE)
        self.assertEqual(update[update.index("--revision-suffix") + 1], "c9f1c2ab")
        removed = update[update.index("--remove-env-vars") + 1:update.index("--query")]
        self.assertEqual(removed, ("BUILD_SHA", "Faults__QueueDelayMs"))
        wait.assert_called_once_with("app--c9f1c2ab")
        self.assertIn("API revision c9f1c2ab serves all traffic, and /api/meta reports build 9f1c2ab3d4e5", out)

    def test_deploy_stops_when_the_api_reports_another_build(self):
        fake = FakeAz(NORMAL, [], [])
        with mock.patch("sys.stderr", io.StringIO()) as err:
            code, _, _ = self.run_command(fake, "deploy", SHA, build_sha="local")
        self.assertEqual(code, 2)
        self.assertIn("/api/meta reports build local, not 9f1c2ab3d4e5", err.getvalue())

    def test_deploy_refuses_a_commit_on_no_branch_of_this_repository(self):
        # A fork's pull request commit is served through refs/pull/<n>/head, never a branch here: nothing reaches Azure.
        fake = FakeAz(NORMAL, [], [])
        with mock.patch("sys.stderr", io.StringIO()) as err:
            code, _, wait = self.run_command(fake, "deploy", SHA, branches=())
        self.assertEqual(code, 2)
        self.assertIn("is on no branch of origin, this repository", err.getvalue())
        self.assertEqual(fake.calls, [])
        self.build.assert_not_called()
        wait.assert_not_called()

    def test_run_starts_a_load_test_that_names_the_commit_the_revision_and_the_issue(self):
        fake = FakeAz(CANDIDATE, [], [], revision="app--c9f1c2ab")
        code, out, _ = self.run_command(fake, "run", "--issue", "284")
        self.assertEqual(code, 0)
        (create,) = [call for call in fake.calls if call[:3] == ("load", "test-run", "create")]
        value = {flag: create[create.index(flag) + 1] for flag in
                 ("--test-id", "--test-run-id", "--display-name", "--description", "--load-test-resource")}
        self.assertEqual(value, {"--test-id": "requesthub-journey", "--test-run-id": "candidate-9f1c2ab-20261110-051500",
                                 "--display-name": "Candidate 9f1c2ab", "--load-test-resource": "lt",
                                 "--description": f"Commit {SHA} on API revision c9f1c2ab for Issue #284"})
        self.assertIn("--no-wait", create)
        self.assertIn("on Issue #284 too.", out)

    def test_run_refuses_an_api_without_a_candidate(self):
        fake = FakeAz(NORMAL, [], [])
        with mock.patch("sys.stderr", io.StringIO()) as err:
            code, _, _ = self.run_command(fake, "run")
        self.assertEqual(code, 2)
        self.assertIn("runs no candidate build", err.getvalue())
        self.assertFalse([call for call in fake.calls if call[:2] == ("load", "test-run")])

    def test_restore_puts_back_the_normal_image_and_its_build_setting(self):
        revisions = [{"name": "app--0000025", "created": "2026-11-10T04:00:00+00:00", "image": NORMAL,
                      "env": [{"name": "BUILD_SHA", "value": "local"}]},
                     {"name": "app--c9f1c2ab", "created": "2026-11-10T05:00:00+00:00", "image": CANDIDATE, "env": []}]
        fake = FakeAz(CANDIDATE, [{"name": "Faults__ExpiresAtUtc"}], revisions)
        code, out, wait = self.run_command(fake, "restore")
        self.assertEqual(code, 0)
        (update,) = self.updates(fake)
        self.assertEqual(update[update.index("--image") + 1], NORMAL)
        self.assertEqual(update[update.index("--set-env-vars") + 1], "BUILD_SHA=local")
        self.assertEqual(update[update.index("--remove-env-vars") + 1], "Faults__ExpiresAtUtc")
        self.assertNotIn("--revision-suffix", update)  # Container Apps names the restored revision
        wait.assert_called_once_with("app--0000027")
        self.assertIn("runs the normal image again", out)

    def test_restore_changes_nothing_when_the_normal_image_runs(self):
        fake = FakeAz(NORMAL, [], [])
        code, out, _ = self.run_command(fake, "restore")
        self.assertEqual(code, 0)
        self.assertEqual(self.updates(fake), [])
        self.assertIn("Nothing to restore", out)


@unittest.skipUnless(shutil.which("git"), "needs git")
class BranchCheckTests(unittest.TestCase):
    """The branch check against real git repositories: an origin with a branch, and a fork's pull request commit that
    GitHub would serve through refs/pull/1/head."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        origin, work, self.clone = self.tmp / "origin.git", self.tmp / "work", self.tmp / "clone"
        self.run_git(None, "init", "--quiet", "--bare", "-b", "main", str(origin))
        self.run_git(None, "init", "--quiet", "-b", "main", str(work))
        self.main = self.commit(work, "main.txt")
        self.run_git(work, "push", "--quiet", "--no-verify", str(origin), "main")
        self.run_git(work, "switch", "--quiet", "-c", "copilot/fix")
        self.fix = self.commit(work, "fix.txt")
        self.run_git(work, "push", "--quiet", "--no-verify", str(origin), "copilot/fix")
        self.run_git(work, "switch", "--quiet", "-c", "fork", "main")
        self.fork = self.commit(work, "fork.txt")
        self.run_git(work, "push", "--quiet", "--no-verify", str(origin), "fork:refs/pull/1/head")
        self.run_git(None, "clone", "--quiet", str(origin), str(self.clone))
        self.run_git(self.clone, "fetch", "--quiet", "origin", "refs/pull/1/head")  # the fork's commit is in the clone

    def run_git(self, cwd, *args):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, work, name):
        (work / name).write_text(name, encoding="utf-8")
        self.run_git(work, "add", name)
        self.run_git(work, "-c", "user.name=Test", "-c", "user.email=candidate-test", "-c", "commit.gpgsign=false",
                     "commit", "--quiet", "--no-verify", "-m", name)
        return self.run_git(work, "rev-parse", "HEAD")

    def branches(self, sha):
        with mock.patch.object(candidate, "REPO", self.clone):
            return candidate.branches_with(sha)

    def test_a_commit_on_a_branch_of_this_repository_counts(self):
        self.assertEqual(self.branches(self.fix), ["copilot/fix"])
        self.assertEqual(self.branches(self.main), ["copilot/fix", "main"])

    def test_a_forks_pull_request_commit_does_not_count_even_when_the_clone_has_it(self):
        self.assertEqual(self.run_git(self.clone, "cat-file", "-t", self.fork), "commit")
        self.assertEqual(self.branches(self.fork), [])
        self.assertEqual(self.branches("0" * 40), [])

    def test_the_check_leaves_no_refs_behind(self):
        self.branches(self.fix)
        self.assertEqual(self.run_git(self.clone, "for-each-ref", candidate.CHECK_REFS), "")


if __name__ == "__main__":
    unittest.main()
