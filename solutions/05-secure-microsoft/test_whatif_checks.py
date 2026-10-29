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
