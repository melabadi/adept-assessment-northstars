"""Unit tests for the release-evidence and workflow-investigation skill scripts.

They use small JUnit fixtures and a fake GitHub API, so they run offline in a few seconds. They test the scripts'
logic only: the live demo evidence comes from real workflow runs, never from these fixtures.

Run from the repository root:
  python -m unittest discover -s solutions/06-release-github/tests -v
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SOLUTION = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SOLUTION / ".github" / "skills" / "release-evidence"))
sys.path.insert(0, str(SOLUTION / ".github" / "skills" / "workflow-investigation"))

import investigate_run  # noqa: E402
import release_evidence as rel  # noqa: E402
import smoke_test  # noqa: E402
import summarize_tests  # noqa: E402

REPO = "octo/requesthub"
COMMIT = "a" * 40
TAG = "demo-v1.2.0"
DIGESTS = {"api": "sha256:" + "1" * 64, "worker": "sha256:" + "2" * 64}
_environment = unittest.mock.patch.dict(os.environ)


def setUpModule():
    # Never write to a real job summary or outputs, even when the tests run inside GitHub Actions.
    _environment.start()
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SERVER_URL",
                 "GITHUB_ACTOR", "GHCR_TOKEN"):
        os.environ.pop(name, None)


def tearDownModule():
    _environment.stop()


def quietly(func, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = func(*args)
    return code, out.getvalue()


class SummarizeTests(unittest.TestCase):
    def test_counts_come_from_testcases(self):
        result = summarize_tests.parse_junit(FIXTURES / "vitest.junit.xml")
        self.assertEqual((result["tests"], result["passed"], result["skipped"], result["failed"]), (3, 2, 1, 0))

    def test_failures_are_listed(self):
        result = summarize_tests.parse_junit(FIXTURES / "failing.junit.xml")
        self.assertEqual(result["failed"], 1)
        self.assertIn("Concurrent_double_click", result["failing"][0]["test"])
        self.assertIn("Values differ", result["failing"][0]["message"])

    def test_gate_passes_when_every_suite_ran_and_passed(self):
        summary = summarize_tests.summarize([("api", FIXTURES / "xunit.junit.xml"), ("web", FIXTURES / "vitest.junit.xml")])
        self.assertTrue(summary["gate"]["passed"])
        self.assertEqual(summary["totals"]["tests"], 6)

    def test_gate_fails_on_failure_missing_report_or_no_tests(self):
        summary = summarize_tests.summarize([
            ("api", FIXTURES / "failing.junit.xml"),
            ("web", FIXTURES / "missing.junit.xml"),
            ("smoke", FIXTURES / "empty.junit.xml"),
        ])
        self.assertFalse(summary["gate"]["passed"])
        reasons = " ".join(summary["gate"]["reasons"])
        self.assertIn("api: 1 failed", reasons)
        self.assertIn("web: report missing.junit.xml not found", reasons)
        self.assertIn("smoke: no tests ran", reasons)

    def test_cli_exit_code_follows_the_gate(self):
        code, _ = quietly(summarize_tests.main, ["--suite", f"api={FIXTURES / 'xunit.junit.xml'}"])
        self.assertEqual(code, 0)
        code, out = quietly(summarize_tests.main, ["--suite", f"api={FIXTURES / 'failing.junit.xml'}"])
        self.assertEqual(code, 1)
        self.assertIn("Gate: failed", out)


class SmokeJunitTests(unittest.TestCase):
    def test_smoke_report_round_trips_through_the_parser(self):
        results = [
            {"name": "api_ready", "status": "passed", "detail": "ready", "seconds": 1.0},
            {"name": "self_approval_refused", "status": "failed", "detail": "HTTP 201", "seconds": 0.1},
            {"name": "approver_decides", "status": "skipped", "detail": "no request", "seconds": 0.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smoke.junit.xml"
            smoke_test.write_junit(results, path)
            parsed = summarize_tests.parse_junit(path)
        self.assertEqual((parsed["tests"], parsed["passed"], parsed["failed"], parsed["skipped"]), (3, 1, 1, 1))


class FakeGitHub:
    """Answers the GitHub REST paths the scripts read, like `gh api` would."""

    def __init__(self, release_state: str = "draft", role: str = "admin", reviewers: list | None = None):
        self.release_state = release_state
        self.role = role
        self.reviewers = reviewers or []
        self.calls: list[str] = []

    def __call__(self, path: str, ok404: bool = False, paginate: bool = False):
        self.calls.append(path)
        if path.startswith(f"repos/{REPO}/compare/"):
            return {"status": "identical", "ahead_by": 0}
        if path == f"repos/{REPO}/actions/runs/101":
            return {"id": 101, "path": rel.CANDIDATE_WORKFLOW, "head_sha": COMMIT, "head_branch": "main",
                    "status": "completed", "conclusion": "success", "html_url": "https://example.test/runs/101"}
        if path == f"repos/{REPO}/git/ref/tags/{TAG}":
            return {"object": {"type": "commit", "sha": COMMIT}} if self.release_state == "published" else None
        if path == f"repos/{REPO}/environments/{rel.ENVIRONMENT}":
            rules = [{"type": "branch_policy"}]
            if self.reviewers:
                rules.append({"type": "required_reviewers", "prevent_self_review": True,
                              "reviewers": [{"reviewer": {"login": r}} for r in self.reviewers]})
            return {"html_url": "https://example.test/env", "protection_rules": rules,
                    "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
        if path.startswith(f"repos/{REPO}/environments/{rel.ENVIRONMENT}/deployment-branch-policies"):
            return {"branch_policies": [{"name": "main", "type": "branch"}]}
        if path.startswith(f"repos/{REPO}/collaborators/"):
            return {"role_name": self.role}
        if path == f"repos/{REPO}/actions/runs/202/approvals":
            return []
        if ok404:
            return None
        raise AssertionError(f"unexpected API call {path}")


class AssembleVerifyApproveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fake = FakeGitHub()
        original = rel.api
        rel.api = self.fake
        self.addCleanup(setattr, rel, "api", original)
        self.evidence = self.tmp / "evidence"
        self.evidence.mkdir()
        sources = {"api": "xunit.junit.xml", "web": "vitest.junit.xml", "smoke": "xunit.junit.xml",
                   "browser": "playwright.junit.xml"}
        for key, fixture in sources.items():
            shutil.copy(FIXTURES / fixture, self.evidence / rel.SUITES[key][2])
        summary = summarize_tests.summarize([(key, self.evidence / rel.SUITES[key][2]) for key in rel.SUITES])
        (self.evidence / rel.TEST_SUMMARY).write_text(json.dumps(summary), encoding="utf-8")
        for service in rel.SERVICES:
            sbom = f"sbom-requesthub-{service}.spdx.json"
            (self.evidence / sbom).write_text('{"spdxVersion": "SPDX-2.3"}', encoding="utf-8")
            (self.evidence / f"image-{service}.json").write_text(json.dumps({
                "service": service, "name": f"ghcr.io/octo/requesthub-{service}", "tag": TAG,
                "digest": DIGESTS[service], "build_sha": COMMIT, "sbom": sbom}), encoding="utf-8")
        (self.evidence / rel.WHATS_CHANGED).write_text(
            "## What's Changed\n* Add release evidence by @octo in https://example.test/pull/7\n", encoding="utf-8")
        self.release_dir = self.tmp / "release"
        self.notes = self.tmp / "release-notes.md"

    def assemble(self) -> int:
        code, _ = quietly(rel.main, [
            "assemble", "--repo", REPO, "--evidence", str(self.evidence), "--out", str(self.release_dir),
            "--notes", str(self.notes), "--tag", TAG, "--commit", COMMIT, "--run-id", "101",
            "--requested-by", "ava-dev", "--approval-mode", "the person who runs the approval workflow"])
        return code

    def release(self, body: str | None = None) -> dict:
        return {"tag_name": TAG, "draft": self.fake.release_state == "draft", "target_commitish": COMMIT,
                "body": body if body is not None else self.notes.read_text(encoding="utf-8")}

    def verify(self, require_images: bool = False):
        return rel.verify_release(REPO, TAG, self.release_dir, self.release(), "any", require_images, None, None)[0]

    def statuses(self, checks):
        return {c.name: c.status for c in checks}

    def test_assemble_writes_manifest_checksums_and_waiting_notes(self):
        self.assertEqual(self.assemble(), 0)
        manifest = json.loads((self.release_dir / rel.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["commit"], COMMIT)
        self.assertEqual([i["digest"] for i in manifest["images"]], [DIGESTS["api"], DIGESTS["worker"]])
        self.assertEqual([s["name"] for s in manifest["tests"]["suites"]], list(rel.SUITES))
        sums = rel.read_sums(self.release_dir / rel.SUMS)
        self.assertIn(rel.MANIFEST, sums)
        self.assertEqual(set(sums), {p.name for p in self.release_dir.iterdir()} - {rel.SUMS})
        notes = self.notes.read_text(encoding="utf-8")
        self.assertIn("Waiting for approval", notes)
        self.assertIn("Add release evidence", notes)
        self.assertTrue(notes.rstrip().endswith(rel.AI_MARKER))

    def test_assemble_refuses_failed_tests_or_wrong_image_commit(self):
        shutil.copy(FIXTURES / "failing.junit.xml", self.evidence / "api-tests.junit.xml")
        summary = summarize_tests.summarize([(k, self.evidence / rel.SUITES[k][2]) for k in rel.SUITES])
        (self.evidence / rel.TEST_SUMMARY).write_text(json.dumps(summary), encoding="utf-8")
        self.assertEqual(self.assemble(), 1)
        self.assertFalse(self.release_dir.exists())

    def test_verify_passes_on_untouched_evidence(self):
        self.assemble()
        statuses = self.statuses(self.verify())
        self.assertEqual(statuses.pop("images"), "SKIP")
        self.assertEqual(statuses.pop("approval record"), "SKIP")
        self.assertEqual(set(statuses.values()), {"PASS"}, statuses)

    def test_verify_catches_an_edited_report(self):
        self.assemble()
        report = self.release_dir / "web-tests.junit.xml"
        report.write_text(report.read_text(encoding="utf-8").replace("<skipped/>", ""), encoding="utf-8")
        statuses = self.statuses(self.verify())
        self.assertEqual(statuses["checksums"], "FAIL")
        self.assertEqual(statuses["tests"], "FAIL")

    def test_verify_catches_an_unlisted_asset_and_requires_images_when_asked(self):
        self.assemble()
        (self.release_dir / "extra.txt").write_text("not evidence", encoding="utf-8")
        statuses = self.statuses(self.verify(require_images=True))
        self.assertEqual(statuses["checksums"], "FAIL")
        self.assertEqual(statuses["images"], "FAIL")

    def approve(self, approver: str = "chloe-lead", extra: list[str] | None = None, ai_text: str = ""):
        self.assemble()
        release = self.release(self.notes.read_text(encoding="utf-8") + ai_text)
        original = rel.load_release
        rel.load_release = lambda args, repo: (release, self.release_dir)
        self.addCleanup(setattr, rel, "load_release", original)
        final_notes = self.tmp / "final-notes.md"
        with unittest.mock.patch.dict(os.environ, {"GHCR_TOKEN": "token"}):
            code, out = quietly(rel.main, ["approve", "--repo", REPO, "--tag", TAG, "--approver", approver,
                                           "--run-id", "202", "--notes", str(final_notes), *(extra or [])])
        return code, out, final_notes

    def registry_ok(self):
        original = rel.registry_check
        rel.registry_check = lambda image, user, token: (True, f"{image['name']} exists")
        self.addCleanup(setattr, rel, "registry_check", original)
        original_scopes = rel.token_can_read_packages
        rel.token_can_read_packages = lambda token: None
        self.addCleanup(setattr, rel, "token_can_read_packages", original_scopes)

    def test_a_token_without_package_scope_is_reported_not_mistaken_for_missing_images(self):
        self.assemble()
        original = rel.token_can_read_packages
        rel.token_can_read_packages = lambda token: False
        self.addCleanup(setattr, rel, "token_can_read_packages", original)
        checks = rel.verify_release(REPO, TAG, self.release_dir, self.release(), "any", False, None, "gho_token")[0]
        images = next(c for c in checks if c.name == "images")
        self.assertEqual(images.status, "SKIP")
        self.assertIn("cannot read packages", images.detail)
        checks = rel.verify_release(REPO, TAG, self.release_dir, self.release(), "any", True, None, "gho_token")[0]
        self.assertEqual(next(c for c in checks if c.name == "images").status, "FAIL")

    def test_approve_writes_the_record_and_keeps_the_ai_summary(self):
        self.registry_ok()
        code, out, final_notes = self.approve(
            ai_text="\n---\n\n## AI summary\nThe release adds release evidence.\n",
            extra=["--comment", "Evidence reviewed."])
        self.assertEqual(code, 0, out)
        record = json.loads((self.release_dir / rel.APPROVAL).read_text(encoding="utf-8"))
        self.assertEqual(record["approved_by"], "chloe-lead")
        self.assertEqual(record["requested_by"], "ava-dev")
        self.assertFalse(record["self_approval"])
        self.assertEqual(record["manifest_sha256"], summarize_tests.sha256_file(self.release_dir / rel.MANIFEST))
        notes = final_notes.read_text(encoding="utf-8")
        self.assertIn("Approved by @chloe-lead", notes)
        self.assertIn("Evidence reviewed.", notes)
        self.assertIn("The release adds release evidence.", notes)
        self.assertNotIn("Waiting for approval", notes)
        statuses = self.statuses(rel.verify_release(REPO, TAG, self.release_dir, self.release(notes), "any", False, None, None)[0])
        self.assertEqual(statuses["approval record"], "PASS")

    def test_approve_refuses_bots_writers_and_self_approval_when_prevented(self):
        self.registry_ok()
        code, out, _ = self.approve(approver="github-actions[bot]")
        self.assertEqual(code, 1)
        self.assertIn("only a person can approve", out)
        self.fake.role = "write"
        code, out, _ = self.approve(approver="ben-dev")
        self.assertEqual(code, 1)
        self.assertIn("approving needs admin or maintain", out)
        self.fake.role = "admin"
        code, out, _ = self.approve(approver="ava-dev", extra=["--prevent-self-approval"])
        self.assertEqual(code, 1)
        self.assertIn("cannot approve it", out)
        self.assertFalse((self.release_dir / rel.APPROVAL).exists())

    def test_approve_requires_an_environment_review_when_reviewers_are_configured(self):
        self.fake.reviewers = ["chloe-lead"]
        self.registry_ok()
        code, out, _ = self.approve()
        self.assertEqual(code, 1)
        self.assertIn("has no approved review", out)


class PreflightTests(unittest.TestCase):
    def run_preflight(self, releases: list, version: str = "1.2.0", ref: str = "refs/heads/main") -> tuple[int, str]:
        fake = FakeGitHub()

        def api(path, ok404=False, paginate=False):
            if path.startswith(f"repos/{REPO}/releases"):
                return releases
            return fake(path, ok404, paginate)

        original = rel.api
        rel.api = api
        try:
            return quietly(rel.main, ["preflight", "--repo", REPO, "--version", version, "--ref", ref])
        finally:
            rel.api = original

    def test_preflight_accepts_a_new_version_on_main(self):
        code, out = self.run_preflight([{"tag_name": "demo-v1.1.0", "draft": False}])
        self.assertEqual(code, 0, out)
        self.assertIn("previous demo release: `demo-v1.1.0`", out)

    def test_preflight_refuses_other_branches_released_and_lower_versions(self):
        self.assertEqual(self.run_preflight([], ref="refs/heads/feature")[0], 1)
        self.assertEqual(self.run_preflight([{"tag_name": "demo-v1.2.0", "draft": False}])[0], 1)
        code, out = self.run_preflight([{"tag_name": "demo-v2.0.0", "draft": False}])
        self.assertEqual(code, 1)
        self.assertIn("must be higher", out)


class InvestigateTests(unittest.TestCase):
    LOG = "\n".join([
        "Verify the evidence\tVerify\t2026-10-27T12:00:00.0000000Z ##[group]Run python verify",
        "Verify the evidence\tVerify\t2026-10-27T12:00:00.1000000Z \x1b[36;1mpython release_evidence.py verify\x1b[0m",
        "Verify the evidence\tVerify\t2026-10-27T12:00:00.2000000Z   GH_TOKEN: ***",
        "Verify the evidence\tVerify\t2026-10-27T12:00:01.0000000Z   PASS  manifest: commit abc1234",
        "Verify the evidence\tVerify\t2026-10-27T12:00:01.1000000Z   FAIL  checksums: web-tests.junit.xml changed after the candidate run",
        "Verify the evidence\tVerify\t2026-10-27T12:00:01.2000000Z ##[error]Process completed with exit code 1.",
    ])

    def test_excerpts_keep_errors_and_drop_the_step_preamble(self):
        excerpt = investigate_run.error_excerpts(self.LOG, 40)["Verify the evidence"]
        text = "\n".join(excerpt)
        self.assertIn("FAIL  checksums: web-tests.junit.xml changed", text)
        self.assertIn("##[error]Process completed with exit code 1.", text)
        self.assertNotIn("GH_TOKEN", text)
        self.assertNotIn("##[group]", text)

    def test_failing_tests_are_read_from_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(FIXTURES / "failing.junit.xml", Path(tmp) / "api-tests.junit.xml")
            shutil.copy(FIXTURES / "xunit.junit.xml", Path(tmp) / "other.junit.xml")
            failures = investigate_run.failing_tests(Path(tmp))
        self.assertEqual(len(failures), 1)
        self.assertIn("Concurrent_double_click", failures[0]["test"])

    def test_run_urls_and_ids_are_accepted(self):
        self.assertEqual(investigate_run.parse_target("https://github.com/octo/requesthub/actions/runs/42", None),
                         ("octo/requesthub", "42"))
        self.assertEqual(investigate_run.parse_target("42", "octo/requesthub"), ("octo/requesthub", "42"))

    def test_digest_shows_refusals_that_happen_before_any_step(self):
        digest = {
            "run": {"id": 7, "name": "Release · GitHub · approve and publish", "status": "completed",
                    "conclusion": "failure", "run_attempt": 1, "html_url": "https://example.test/runs/7",
                    "event": "workflow_dispatch", "head_branch": "demo/not-main", "head_sha": COMMIT, "actor": "ava-dev"},
            "failed_jobs": [{"name": "Record the approval and publish", "conclusion": "failure", "url": None,
                             "failed_steps": [], "annotations": [
                                 'Branch "demo/not-main" is not allowed to deploy to release-github due to environment protection rules.']}],
            "log_excerpts": {}, "failing_tests": [], "artifacts_read": [],
        }
        text = investigate_run.markdown(digest)
        self.assertIn("Annotation: Branch \"demo/not-main\" is not allowed to deploy", text)
        self.assertIn("on `demo/not-main`", text)


if __name__ == "__main__":
    unittest.main()
