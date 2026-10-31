"""Tests for whatif.py's untrusted-Bicep check and the sanitizing of what it posts, run offline.

A pull request's Bicep is compiled by the posture-whatif job. These cases are templates that must be refused before
compiling, because they could make the compiler read files or the environment, and names that must not break out of the
pull request comment. The environment test runs on Linux only, where the job runs.

  python -m unittest test_whatif_checks.py      (from this folder; no Azure or GitHub access needed)
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import whatif

ENTRY = Path(whatif.ENTRY)
TRUSTED_CONFIG = (Path(__file__).resolve().parents[2] / "app" / "infra" / "bicepconfig.json").read_text(encoding="utf-8")


class Sandbox:
    """A repository-shaped folder holding the entry template, the trusted bicepconfig.json, and any other files."""

    def __init__(self, entry: str, **files: str) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for path, text in {"app/infra/bicepconfig.json": TRUSTED_CONFIG, str(ENTRY): entry, **files}.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))

    def problems(self) -> list[str]:
        try:
            return whatif.check_templates(self.root, self.root / ENTRY)
        finally:
            self.tmp.cleanup()


def refused(entry: str, **files: str) -> list[str]:
    return Sandbox(entry, **files).problems()


OUTSIDE = {"solutions/05-secure-microsoft/outside.bicep": "param p string = 'x'\n"}


class Refused(unittest.TestCase):
    def test_bare_carriage_return_hides_a_module_reference(self):
        found = refused("// harmless comment\rmodule m '../outside.bicep' = {\n  name: 'm'\n}\n", **OUTSIDE)
        self.assertTrue(any("carriage return" in p for p in found), found)

    def test_comment_between_a_load_function_and_its_parenthesis(self):
        found = refused("var s = loadTextContent /* c */ ('../secret.txt')\noutput o string = s\n")
        self.assertTrue(any("loadTextContent" in p for p in found), found)

    def test_bare_carriage_return_before_a_load_call(self):
        found = refused("// note\rvar s = loadTextContent('../secret.txt')\n")
        self.assertTrue(any("carriage return" in p for p in found), found)

    def test_load_function_name_in_a_comment(self):
        found = refused("// loadJsonContent is not used here\nparam p string = 'x'\n")
        self.assertTrue(any("loadJsonContent" in p for p in found), found)

    def test_every_compile_time_reader(self):
        for name in ("loadTextContent", "loadFileAsBase64", "loadJsonContent", "loadYamlContent", "loadDirectoryFileInfo",
                     "readEnvironmentVariable", "externalInput"):
            with self.subTest(name=name):
                self.assertTrue(refused(f"var v = {name}('x')\n"))

    def test_extension_and_provider_statements(self):
        for statement in ("extension 'br:mcr.microsoft.com/bicep/extensions/microsoftgraph/v1.0:1.0.0'",
                          "extension kubernetes", "provider microsoftGraph", "provider 'microsoftGraph@1.0.0'",
                          "  extension microsoftGraphV1 with {\n  x: 1\n}", "Extension microsoftGraphV1"):
            with self.subTest(statement=statement):
                found = refused(f"{statement}\nparam p string = 'x'\n")
                self.assertTrue(any("statement" in p for p in found), found)

    def test_module_outside_the_infra_folders(self):
        found = refused("module m '../outside.bicep' = {\n  name: 'm'\n}\n", **OUTSIDE)
        self.assertTrue(any("outside" in p for p in found), found)

    def test_registry_module(self):
        found = refused("module m 'br/public:avm/res/storage/storage-account:0.9.0' = {\n  name: 'm'\n}\n")
        self.assertTrue(any("registry" in p for p in found), found)


class Accepted(unittest.TestCase):
    def test_the_solutions_own_templates(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(whatif.check_templates(root, root / ENTRY), [])

    def test_load_balancer_type_is_not_a_load_function(self):
        self.assertEqual(refused("resource lb 'Microsoft.Network/loadBalancers@2023-04-01' existing = {\n  name: 'x'\n}\n"), [])

    def test_extension_alias_from_the_trusted_config(self):
        self.assertEqual(refused("extension microsoftGraphV1\nparam p string = 'x'\n"), [])

    def test_crlf_line_endings(self):
        self.assertEqual(refused("// comment\r\nparam p string = 'x'\r\n"), [])

    def test_comment_ends_at_carriage_return(self):
        self.assertEqual(whatif.without_comments("// a\rmodule"), "    \rmodule")


class FetchTemplates(unittest.TestCase):
    def test_pull_request_bicepconfig_is_ignored(self):
        files = {
            "solutions/05-secure-microsoft/infra/resources.bicep": b"param p string\n",
            "solutions/05-secure-microsoft/infra/bicepconfig.json": b'{"experimentalFeaturesEnabled": {}}',
            "app/infra/sub/BicepConfig.json": b"{}",
            "app/infra/requesthub.bicep": b"param q string\n",
            "tools/outside.bicep": b"param r string\n",
        }

        class FakeGitHub:
            def call(self, method, path, body=None):
                if path.startswith("git/trees/"):
                    return {"truncated": False, "tree": [{"path": p, "type": "blob", "mode": "100644", "sha": p} for p in files]}
                if path.startswith("git/blobs/"):
                    return {"content": base64.b64encode(files[path.removeprefix("git/blobs/")]).decode()}
                raise AssertionError(path)

            def file(self, path, ref):
                return b"trusted from " + ref.encode()

        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            whatif.fetch_templates(FakeGitHub(), "0" * 40, sandbox)
            written = {p.relative_to(sandbox).as_posix(): p.read_bytes() for p in sandbox.rglob("*") if p.is_file()}
        self.assertNotIn("solutions/05-secure-microsoft/infra/bicepconfig.json", written)
        self.assertNotIn("app/infra/sub/BicepConfig.json", written)
        self.assertNotIn("tools/outside.bicep", written)
        self.assertEqual(written["app/infra/bicepconfig.json"], b"trusted from main")
        self.assertIn("app/infra/requesthub.bicep", written)


class CodeSpans(unittest.TestCase):
    def test_backticks_cannot_end_the_span(self):
        span = whatif.code("a`b``c")
        self.assertTrue(span.startswith("```") and span.endswith("```"), span)

    def test_leading_backtick_is_padded(self):
        self.assertEqual(whatif.code("`x"), "`` `x ``")

    def test_line_breaks_and_table_pipes(self):
        self.assertEqual(whatif.code("a\nb\rc|d", table=True), "`a b c\\|d`")

    def test_summary_table_keeps_the_verdict_column_narrow(self):
        outcome = {"changes": [{"kind": "Create", "type": "Microsoft.Network/privateEndpoints", "name": "pe-blob-x",
                                "leaves": {}, "expected": True}],
                   "unexpected": [], "remaining": [], "noise": 0, "previewless": [], "baseline": True}
        text = whatif.summary(outcome, whatif.DEFAULT_EXPECT, "rg", "intro", details=False)
        self.assertIn("| Create | `Microsoft.Network/privateEndpoints`<br>`pe-blob-x` | ✅ expected |", text)


class PullRequestStatus(unittest.TestCase):
    """The commit status posture/what-if never stays pending, and says what to do when it can. GitHub and Azure are fakes."""

    class FakeGitHub:
        def __init__(self, fail_on: str | None = None, **pull) -> None:
            self.fail_on, self.statuses, self.comments, self.calls = fail_on, [], [], []
            self.pull = {"state": "open", "head": {"sha": "a" * 40, "repo": {"full_name": "o/r"}},
                         "author_association": "OWNER", **pull}

        def call(self, method, path, body=None):
            self.calls.append((method, path))
            if self.fail_on and self.fail_on in path:
                raise KeyError("unexpected response shape")
            if path.startswith("pulls/") and "/files" not in path:
                return self.pull
            if path.startswith("statuses/"):
                self.statuses.append((body["state"], body["description"]))
                return {}
            if path.startswith("issues/") and method == "POST":
                self.comments.append(body["body"])
                return {}
            return []

    PASS = {"changes": [], "unexpected": [], "remaining": [], "noise": 0, "previewless": [], "baseline": True}

    def run_preview(self, github, preview) -> int:
        def fetch(gh, sha, sandbox):
            target = sandbox / whatif.ENTRY
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("param p string = 'x'\n", encoding="utf-8")

        environment = {"POSTURE_GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "AZURE_RESOURCE_GROUP": "rg"}
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(whatif, "GitHub", lambda repository, token: github), \
                mock.patch.object(whatif, "fetch_templates", fetch), mock.patch.object(whatif, "sign_in", lambda: None), \
                mock.patch.object(whatif, "erase_from_initial_environment", lambda name: True), \
                mock.patch.object(whatif, "preview", preview):
            return whatif.preview_pull_request(7, whatif.DEFAULT_EXPECT, "resources")

    def test_pass_posts_the_summary_and_success(self):
        github = self.FakeGitHub()
        self.assertEqual(self.run_preview(github, lambda *a, **k: self.PASS), 0)
        self.assertEqual(github.statuses[-1][0], "success")
        self.assertIn("**PASS**", github.comments[-1])

    def test_stopped_database_says_what_to_do_without_naming_it(self):
        def preview(*args, **kwargs):
            raise whatif.ConfigError("az deployment group what-if failed: ERROR: DeploymentWhatIfResourceError ... "
                                     "ServerStoppedError - Server 'psql-abcdefghij123' is in 'Stopped' state.")
        github = self.FakeGitHub()
        self.assertEqual(self.run_preview(github, preview), 2)
        state, description = github.statuses[-1]
        self.assertEqual(state, "error")
        self.assertIn("stopped PostgreSQL", description)
        self.assertNotIn("psql", description)
        self.assertLessEqual(len(description), 140)
        self.assertEqual(github.comments, [])

    def test_unexpected_failure_sets_error(self):
        def preview(*args, **kwargs):
            raise KeyError("whatIf output shape")
        github = self.FakeGitHub()
        self.assertEqual(self.run_preview(github, preview), 2)
        self.assertEqual(github.statuses[-1][0], "error")

    def test_failure_to_post_the_comment_sets_error(self):
        github = self.FakeGitHub(fail_on="issues/")
        self.assertEqual(self.run_preview(github, lambda *a, **k: self.PASS), 2)
        self.assertEqual(github.statuses[-1][0], "error")


class PullRequestGate(unittest.TestCase):
    """Only this repository's branches, opened by its owner, members, or collaborators, reach Azure. On a public repository
    anyone can open a pull request, from a fork or from one of this repository's branches."""

    FakeGitHub, PASS, run_preview = PullRequestStatus.FakeGitHub, PullRequestStatus.PASS, PullRequestStatus.run_preview

    def assertRefused(self, github) -> None:
        def reached_azure(*args, **kwargs):
            raise AssertionError("a refused pull request reached Azure")
        self.assertEqual(self.run_preview(github, reached_azure), 1)
        self.assertEqual(github.calls, [("GET", "pulls/7")])  # nothing else read, nothing written
        self.assertEqual((github.statuses, github.comments), ([], []))

    def test_a_fork_is_refused_before_anything_is_read_or_written(self):
        self.assertRefused(self.FakeGitHub(head={"sha": "a" * 40, "repo": {"full_name": "someone/r"}}))

    def test_a_deleted_fork_is_refused(self):
        self.assertRefused(self.FakeGitHub(head={"sha": "a" * 40, "repo": None}))
        self.assertRefused(self.FakeGitHub(head={"sha": "a" * 40}))

    def test_an_outside_author_is_refused_even_on_a_branch_of_this_repository(self):
        for association in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", "", None):
            with self.subTest(association=association):
                self.assertRefused(self.FakeGitHub(author_association=association))

    def test_the_owner_members_and_collaborators_are_previewed(self):
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                github = self.FakeGitHub(author_association=association,
                                         head={"sha": "a" * 40, "repo": {"full_name": "O/R"}})
                self.assertEqual(self.run_preview(github, lambda *a, **k: self.PASS), 0)
                self.assertEqual(github.statuses[-1][0], "success")


@unittest.skipUnless(sys.platform.startswith("linux"), "the job runs on Linux; /proc is Linux-only")
class InitialEnvironment(unittest.TestCase):
    def test_token_is_erased_from_proc_environ(self):
        script = textwrap.dedent("""
            import os, sys
            sys.path.insert(0, sys.argv[1])
            import whatif
            print(whatif.erase_from_initial_environment("POSTURE_GITHUB_TOKEN"))
            print(b"secret-value" in open("/proc/self/environ", "rb").read())
        """)
        env = dict(os.environ, POSTURE_GITHUB_TOKEN="secret-value")
        out = subprocess.run([sys.executable, "-c", script, str(Path(__file__).resolve().parent)], env=env,
                             capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["True", "False"])


if __name__ == "__main__":
    unittest.main()
