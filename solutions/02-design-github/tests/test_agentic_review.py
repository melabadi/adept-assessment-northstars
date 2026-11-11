"""Tests for the trust boundaries of 02-design-github's agentic design review (`/design-review`).

They check what keeps outsiders, forks' pull requests, and the model's opinion out of the review:

- the command runs only for people with write access (gh-aw's role check), on an Issue whose author is the owner, a
  member, or a collaborator, or on a pull request from a branch of this repository: the pre-activation step's own
  script runs here against a fake `gh`;
- the agent can only read, sees only trusted GitHub content, and writes nothing but one comment and the two
  allow-listed labels;
- a run that threat detection flags applies nothing;
- the API contract verdict comes from the default branch's contract_diff.py, run before gh-aw checks out the pull
  request's branch: the step's own script runs here against a fake `gh` and the real tool;
- the lock file comes from the gh-aw version that the checks workflow pins and the README names.

They run offline in a few seconds. The live evidence comes from real runs, never from these tests.

Run from the repository root (the script tests need bash, as on GitHub's Ubuntu runners):
  python -m unittest discover -s solutions/02-design-github/tests -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOLUTION = Path(__file__).resolve().parents[1]
REPO = SOLUTION.parents[1]
GITHUB = SOLUTION / ".github"
SOURCE = GITHUB / "workflows" / "design-github-agentic-review.md"
LOCK = GITHUB / "workflows" / "design-github-agentic-review.lock.yml"
CHECKS = GITHUB / "workflows" / "design-github-checks.yml"
README = SOLUTION / "README.md"
CONTRACT = REPO / "app" / "contracts" / "openapi.json"

TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
LABELS = ["adr-needed", "standards-conflict"]
REPOSITORY = "octo/requesthub"
CONTRACT_STEP = "name: Keep the approved inputs and compare the pull request's API contract"
BASH = shutil.which("bash")

FAKE_GH = """
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
with open(os.environ["FAKE_GH_FIXTURES"], encoding="utf-8") as handle:
    fixtures = json.load(handle)
path, jq, accept, rest = None, None, None, list(args[1:])
while rest:
    arg = rest.pop(0)
    if arg == "--jq":
        jq = rest.pop(0)
    elif arg == "-H":
        accept = rest.pop(0)
    elif not arg.startswith("-"):
        path = arg
kind = "jq" if jq else "diff" if accept and "diff" in accept else "raw" if accept and "raw" in accept else "json"
key = f"{path}#{kind}"
if args[:1] != ["api"] or key not in fixtures:
    sys.stderr.write(f"gh: HTTP 404: Not Found ({key})\\n")
    sys.exit(1)
sys.stdout.write(fixtures[key])
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def frontmatter(markdown: str) -> str:
    return markdown.split("---\n", 2)[1]


def prompt(markdown: str) -> str:
    return markdown.split("---\n", 2)[2]


def step_block(text: str, marker: str) -> list[str]:
    """The lines of the YAML step that contains the line `marker` (for example `id: same_repository`)."""
    lines = text.split("\n")
    at = next(i for i, line in enumerate(lines) if line.strip() in (marker, f"- {marker}"))
    start = next(i for i in range(at, -1, -1) if lines[i].lstrip().startswith("- "))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if line.strip() and indent(line) <= indent(lines[start]):
            break
        block.append(line)
    return block


def run_script(text: str, marker: str) -> str:
    """The `run: |` script of a step, as GitHub Actions passes it to the shell."""
    block = step_block(text, marker)
    at = next(i for i, line in enumerate(block) if line.strip() == "run: |")
    body: list[str] = []
    for line in block[at + 1:]:
        if line.strip() and indent(line) <= indent(block[at]):
            break
        body.append(line)
    margin = min(indent(line) for line in body if line.strip())
    return "\n".join(line[margin:] for line in body).rstrip() + "\n"


def job(lock: str, name: str) -> str:
    """A compiled job, from its `  name:` line to the next job."""
    start = lock.index(f"\n  {name}:\n")
    following = re.search(r"\n  [a-z_]+:\n", lock[start + 1:])
    return lock[start:start + 1 + following.start()] if following else lock[start:]


def job_condition(lock: str, name: str) -> str:
    """A compiled job's `if:` condition, on one line."""
    block = job(lock, name)
    head = block[:block.index("\n    runs-on:")]
    if "\n    if:" not in head:
        return ""
    lines = head.split("\n    if:", 1)[1].split("\n")
    condition = [lines[0]] + [line for line in lines[1:] if line.startswith("      ")]
    return " ".join(" ".join(condition).split())


def posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


@unittest.skipUnless(BASH, "needs bash, as on GitHub's Ubuntu runners")
class ScriptTestCase(unittest.TestCase):
    """Runs a step's own script under bash, with a fake `gh` that answers from fixtures and logs every call."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.bin_dir = self.temp / "bin"
        self.bin_dir.mkdir()
        (self.temp / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
        for name, target in (("gh", f'"{posix(sys.executable)}" "{posix(self.temp / "fake_gh.py")}"'),
                             ("python3", f'"{posix(sys.executable)}"')):
            shim = self.bin_dir / name
            shim.write_text(f'#!/usr/bin/env bash\nexec {target} "$@"\n', encoding="utf-8", newline="\n")
            shim.chmod(0o755)
        self.log = self.temp / "gh.log"
        self.summary = self.temp / "summary.md"

    def run_step(self, marker: str, fixtures: dict[str, str], env: dict[str, str],
                 replace: tuple[str, str] | None = None) -> subprocess.CompletedProcess:
        script = run_script(read(SOURCE), marker)
        if replace:
            script = script.replace(*replace)
        (self.temp / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN")}
        environment.update(env, PATH=f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                           FAKE_GH_LOG=str(self.log), FAKE_GH_FIXTURES=str(self.temp / "fixtures.json"),
                           GITHUB_REPOSITORY=REPOSITORY, GITHUB_STEP_SUMMARY=posix(self.summary))
        return subprocess.run([BASH, "-c", script], cwd=REPO, env=environment, capture_output=True, text=True,
                              encoding="utf-8")

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class SameRepositoryGateTests(ScriptTestCase):
    """The pre-activation step that keeps forks' pull requests out: an issue_comment event doesn't say where a pull
    request's head lives, so the step asks the API. Its outcome gates the activation job."""

    PULL = f"repos/{REPOSITORY}/pulls/7#jq"

    def gate(self, fixtures: dict[str, str], is_pull_request: bool = True) -> subprocess.CompletedProcess:
        return self.run_step("id: same_repository", fixtures,
                             {"IS_PULL_REQUEST": str(is_pull_request).lower(), "NUMBER": "7"})

    def test_an_issue_has_no_head_to_check(self):
        result = self.gate({}, is_pull_request=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], self.calls())

    def test_a_branch_of_this_repository_passes(self):
        result = self.gate({self.PULL: f"{REPOSITORY}\n"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["api", f"repos/{REPOSITORY}/pulls/7", "--jq", '.head.repo.full_name // ""']], self.calls())

    def test_a_fork_is_refused(self):
        result = self.gate({self.PULL: "someone/requesthub\n"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("comes from someone/requesthub", result.stdout)

    def test_a_deleted_fork_is_refused(self):
        result = self.gate({self.PULL: "\n"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("a deleted repository", result.stdout)

    def test_an_api_failure_refuses(self):
        self.assertNotEqual(0, self.gate({}).returncode)


class ContractStepTests(ScriptTestCase):
    """The deterministic step that keeps the approved inputs and computes the API contract verdict with the default
    branch's contract_diff.py, before gh-aw checks out the pull request's branch."""

    BASE, HEAD, MERGE_BASE = "b" * 40, "c" * 40, "d" * 40

    def setUp(self):
        super().setUp()
        self.dest = self.temp / "design-review"
        self.contract = read(CONTRACT)

    def step(self, fixtures: dict[str, str], is_pull_request: bool = True) -> subprocess.CompletedProcess:
        return self.run_step(CONTRACT_STEP, fixtures,
                             {"IS_PULL_REQUEST": str(is_pull_request).lower(), "NUMBER": "7",
                              "STANDARDS": "solutions/02-design-github/standards",
                              "BRIEF": "solutions/02-design-github/inputs/reviewed-brief.md",
                              "CONTRACT": "app/contracts/openapi.json",
                              "CONTRACT_TOOL": ".github/skills/contract-impact/contract_diff.py"},
                             replace=("/tmp/gh-aw/agent/design-review", posix(self.dest)))

    def pull_request(self, files: str, head_contract: str | None = None) -> dict[str, str]:
        api = f"repos/{REPOSITORY}"
        fixtures = {f"{api}/pulls/7#jq": f"{self.BASE} {self.HEAD}\n",
                    f"{api}/pulls/7/files#jq": files,
                    f"{api}/pulls/7#diff": "diff --git a/x b/x\n",
                    f"{api}/compare/{self.BASE}...{self.HEAD}#jq": f"{self.MERGE_BASE}\n",
                    f"{api}/contents/app/contracts/openapi.json?ref={self.MERGE_BASE}#raw": self.contract}
        if head_contract is not None:
            fixtures[f"{api}/contents/app/contracts/openapi.json?ref={self.HEAD}#raw"] = head_contract
        return fixtures

    def edited_contract(self, edit) -> str:
        contract = json.loads(self.contract)
        edit(contract["components"]["schemas"]["RecommendationDto"]["properties"])
        return json.dumps(contract)

    def report(self) -> str:
        return (self.dest / "contract-impact.md").read_text(encoding="utf-8")

    def test_an_issue_keeps_the_approved_inputs_and_has_nothing_to_compare(self):
        result = self.step({}, is_pull_request=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], self.calls())
        self.assertIn("is an Issue, not a pull request", self.report())
        approved = self.dest / "approved"
        self.assertEqual(sorted(p.name for p in (SOLUTION / "standards").glob("*.md")),
                         sorted(p.name for p in (approved / "standards").glob("*.md")))
        self.assertTrue((approved / "reviewed-brief.md").is_file())
        self.assertEqual(self.contract, read(approved / "openapi.json"))
        self.assertTrue((self.dest / "tool" / "contract_diff.py").is_file())

    def test_a_pull_request_that_leaves_the_contract_alone_has_its_files_and_diff(self):
        result = self.step(self.pull_request("modified\tsolutions/02-design-github/adr/0001-x.md\n"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("doesn't change `app/contracts/openapi.json`", self.report())
        self.assertIn("solutions/02-design-github/adr/0001-x.md", (self.dest / "changed-files.txt").read_text())
        self.assertIn("diff --git", (self.dest / "pull-request.diff").read_text())

    def test_a_removed_property_is_breaking_against_the_merge_base(self):
        head = self.edited_contract(lambda properties: properties.pop("providerTraceId"))
        result = self.step(self.pull_request("modified\tapp/contracts/openapi.json\n", head))
        self.assertEqual(0, result.returncode, result.stderr)
        report = self.report()
        self.assertIn("**Breaking change**", report)
        self.assertIn("providerTraceId", report)
        self.assertIn(f"vs merge base {self.MERGE_BASE[:12]})", report.splitlines()[0])
        self.assertNotIn("base.json", report)
        self.assertEqual(report, self.summary.read_text(encoding="utf-8"))

    def test_an_added_property_is_compatible(self):
        head = self.edited_contract(lambda properties: properties.update(note={"type": "string"}))
        result = self.step(self.pull_request("modified\tapp/contracts/openapi.json\n", head))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("**Compatible**", self.report())
        self.assertIn("Additive changes: 1", self.report())

    def test_a_diff_too_large_to_download_does_not_stop_the_review(self):
        fixtures = self.pull_request("modified\tapp/web/src/App.tsx\n")
        del fixtures[f"repos/{REPOSITORY}/pulls/7#diff"]
        result = self.step(fixtures)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("too large to download", (self.dest / "pull-request.diff").read_text())

    def test_a_contract_it_cannot_read_stops_the_review(self):
        result = self.step(self.pull_request("modified\tapp/contracts/openapi.json\n", head_contract=None))
        self.assertNotEqual(0, result.returncode)


class GateTests(unittest.TestCase):
    """Who can start a review, and whose text reaches the prompt."""

    @classmethod
    def setUpClass(cls):
        cls.source = read(SOURCE)
        cls.lock = read(LOCK)

    def test_the_command_is_design_review_in_comments_only(self):
        self.assertRegex(frontmatter(self.source),
                         r"slash_command:\n\s+name: design-review\n\s+events: \[issue_comment, pull_request_comment\]")
        triggers = re.search(r"^on:\n((?:  .*\n)+)", self.lock, re.MULTILINE).group(1)
        self.assertEqual(["issue_comment"], re.findall(r"^  ([a-z_]+):", triggers, re.MULTILINE))

    def test_whoever_comments_needs_write_access(self):
        self.assertIn('GH_AW_REQUIRED_ROLES: "admin,maintainer,write"', self.lock)
        self.assertNotRegex(frontmatter(self.source), r"(?m)^\s*roles:")
        self.assertNotRegex(frontmatter(self.source), r"(?m)^\s*bots:")

    def test_only_trusted_authors_and_this_repositorys_branches_reach_the_prompt(self):
        gate = job_condition(self.lock, "activation")
        self.assertIn("needs.pre_activation.outputs.activated == 'true'", gate)
        for association in TRUSTED:
            self.assertIn(f"github.event.issue.author_association == '{association}'", gate)
        self.assertIn("(github.event.issue.pull_request != null && github.event.issue.user.login == 'Copilot' && "
                      "github.event.issue.user.type == 'Bot')", gate)
        self.assertIn("needs.pre_activation.outputs.same_repository_result == 'success'", gate)
        self.assertIn("needs: activation", job(self.lock, "agent"))

    def test_the_branch_check_runs_for_the_command_and_cannot_be_skipped_into_a_review(self):
        pre_activation = job(self.lock, "pre_activation")
        self.assertIn("same_repository_result: ${{ steps.same_repository.outcome }}", pre_activation)
        block = "\n".join(step_block(pre_activation, "id: same_repository"))
        self.assertIn("if: startsWith(github.event.comment.body, '/design-review')", block)
        self.assertIn("continue-on-error: true", block)
        permissions = re.search(r"\n    permissions:\n((?:      .*\n)+)", pre_activation).group(1)
        self.assertEqual(["pull-requests: read"], [line.split("#")[0].strip() for line in permissions.splitlines()])


class OutputTests(unittest.TestCase):
    """What the agent can read and write."""

    @classmethod
    def setUpClass(cls):
        cls.source = read(SOURCE)
        cls.lock = read(LOCK)
        config = re.search(r"GH_AW_SAFE_OUTPUTS_CONFIG: \"(.+)\"\n", cls.lock).group(1)
        cls.config = json.loads(json.loads(f'"{config}"'))

    def test_the_agent_can_only_read(self):
        permissions = re.search(r"^permissions:\n((?:  .*\n)+)", frontmatter(self.source), re.MULTILINE).group(1)
        self.assertEqual(["contents: read", "issues: read", "pull-requests: read"],
                         [line.strip() for line in permissions.strip("\n").splitlines()])
        agent = job(self.lock, "agent")
        self.assertNotRegex(agent[:agent.index("\n    steps:")], r": write")
        self.assertIn("edit: false", frontmatter(self.source))
        self.assertNotIn("--allow-tool write", self.lock)
        commands = re.search(r"^  bash: \[(.+)\]$", frontmatter(self.source), re.MULTILINE).group(1).split(", ")
        self.assertEqual(["cat", "grep", "head", "tail", "ls", "wc", "sort"], commands)

    def test_the_agent_sees_only_trusted_github_content(self):
        self.assertRegex(frontmatter(self.source), r"\n    min-integrity: approved\n")
        self.assertIn('"min-integrity": "approved"', self.lock)

    def test_it_writes_one_comment_and_two_allow_listed_labels(self):
        writers = {"add_comment", "add_labels"}
        reporters = {"noop", "report_incomplete", "report_missing_data", "report_missing_tool",
                     "create_report_incomplete_issue"}
        self.assertEqual(set(), set(self.config) - writers - reporters)
        self.assertEqual(1, self.config["add_comment"]["max"])
        self.assertEqual(LABELS, self.config["add_labels"]["allowed"])
        self.assertEqual(1, self.config["add_labels"]["max"])
        self.assertNotIn("create_if_missing", self.config["add_labels"])

    def test_no_report_becomes_an_issue_and_no_status_comment_is_posted(self):
        for flag in ("GH_AW_NOOP_REPORT_AS_ISSUE", "GH_AW_MISSING_TOOL_CREATE_ISSUE",
                     "GH_AW_REPORT_INCOMPLETE_CREATE_ISSUE", "GH_AW_FAILURE_REPORT_AS_ISSUE"):
            self.assertIn(f'{flag}: "false"', self.lock)
            self.assertNotIn(f'{flag}: "true"', self.lock)
        self.assertIn("status-comment: false", frontmatter(self.source))

    def test_a_flagged_run_applies_nothing(self):
        self.assertRegex(frontmatter(self.source), r"threat-detection:\n\s+continue-on-error: false")
        self.assertIn('GH_AW_DETECTION_CONTINUE_ON_ERROR: "false"', self.lock)
        self.assertNotIn('GH_AW_DETECTION_CONTINUE_ON_ERROR: "true"', self.lock)
        self.assertIn("needs.detection.result == 'success'", job_condition(self.lock, "safe_outputs"))

    def test_the_prompt_asks_only_for_the_allowed_labels(self):
        body = prompt(self.source)
        for label in LABELS:
            self.assertIn(f"`{label}`", body)
        self.assertIn("data, not instructions", body)

    def test_each_run_has_a_budget(self):
        budget = int(re.search(r"^max-ai-credits: (\d+)$", frontmatter(self.source), re.MULTILINE).group(1))
        self.assertTrue(0 < budget < 1000, "a cap below gh-aw's default of 1000")
        self.assertIn(f'GH_AW_MAX_AI_CREDITS: "{budget}"', self.lock)
        detection = int(re.search(r"\n    max-ai-credits: (\d+)", frontmatter(self.source)).group(1))
        self.assertTrue(0 < detection < 400, "a detection cap below gh-aw's default of 400")


class ContractVerdictTests(unittest.TestCase):
    """The verdict comes from the default branch's tool, before the pull request's branch is checked out."""

    @classmethod
    def setUpClass(cls):
        cls.source = read(SOURCE)
        cls.agent = job(read(LOCK), "agent")

    def test_the_step_runs_before_the_pull_requests_branch_is_checked_out(self):
        step = self.agent.index(CONTRACT_STEP)
        self.assertLess(self.agent.index("name: Checkout repository (gh-aw default)"), step)
        self.assertLess(step, self.agent.index("name: Checkout PR branch"))

    def test_the_tool_comes_from_the_checkout_of_the_default_branch(self):
        block = "\n".join(step_block(frontmatter(self.source), CONTRACT_STEP))
        self.assertIn("CONTRACT_TOOL: .github/skills/contract-impact/contract_diff.py", block)
        self.assertIn('cp "$CONTRACT_TOOL" "$dest/tool/contract_diff.py"', block)
        self.assertIn('python3 "$dest/tool/contract_diff.py"', block)

    def test_the_agent_takes_the_verdict_as_given(self):
        body = prompt(self.source)
        self.assertIn("contract-impact.md", body)
        self.assertIn("Never reassess it", body)


class VersionTests(unittest.TestCase):
    """One gh-aw version: the one that compiled the lock, the one the checks install, and the one the README names."""

    def test_the_lock_the_checks_and_the_readme_name_the_same_compiler(self):
        compiled = re.search(r"generated by gh-aw \((v[\d.]+)\)", read(LOCK)).group(1)
        pinned = re.search(r"GH_AW_VERSION: (v[\d.]+)", read(CHECKS)).group(1)
        self.assertEqual(compiled, pinned)
        self.assertIn(f"gh-aw {pinned}", read(README))

    def test_a_change_to_any_custom_agent_reruns_the_lock_check(self):
        # gh-aw records every custom agent's frontmatter in each lock file's manifest.
        self.assertIn("agent_metadata", read(LOCK).split("\n", 2)[1])
        self.assertIn("      - '.github/agents/**'\n", read(CHECKS))

    def test_the_readme_documents_the_command_the_labels_and_the_secret(self):
        readme = read(README)
        for text in ("/design-review", *LABELS, "COPILOT_GITHUB_TOKEN", "gh aw compile design-github-agentic-review"):
            self.assertIn(text, readme)


if __name__ == "__main__":
    unittest.main()
