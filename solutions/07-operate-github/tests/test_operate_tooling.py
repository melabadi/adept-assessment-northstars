"""Tests for the trust boundaries of 07-operate-github's workflows, agent, and Copilot CLI command.

They check what keeps outsiders and fork pull requests away from Copilot, from the repository's tokens, and from this
repository's Actions cache:

- the regression proof, when someone dispatches it, refuses a pull request whose branch is not in this repository
  (the scope step's own script runs here against a fake `gh`);
- the agentic triage starts only for an incident whose author is the owner, a member, or a collaborator, keeps gh-aw's
  role check on whoever applied the label, and applies nothing when its threat detection flags the run;
- Copilot CLI (option B) runs with file tools only and writes two drafts that a person files;
- the cloud agent works from the follow-up and the triage comment, not from the incident or outsiders' comments.

They run offline in a few seconds. The live demo evidence comes from real runs, never from these tests.

Run from the repository root (the scope tests need bash and jq, as on GitHub's Ubuntu runners):
  python -m unittest discover -s solutions/07-operate-github/tests -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOLUTION = Path(__file__).resolve().parents[1]
GITHUB = SOLUTION / ".github"
PROOF = GITHUB / "workflows" / "operate-github-regression-proof.yml"
TRIAGE_SOURCE = GITHUB / "workflows" / "operate-github-incident-triage.md"
TRIAGE_LOCK = GITHUB / "workflows" / "operate-github-incident-triage.lock.yml"
AGENT = GITHUB / "agents" / "operate-github.agent.md"
EVIDENCE_SKILL = GITHUB / "skills" / "incident-evidence" / "SKILL.md"
FOLLOWUP_SKILL = GITHUB / "skills" / "regression-followup" / "SKILL.md"
FORM = GITHUB / "ISSUE_TEMPLATE" / "07-operate-github-incident.yml"
README = SOLUTION / "README.md"

TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
BASH = shutil.which("bash")
JQ = shutil.which("jq")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def step_block(workflow: str, step_id: str) -> list[str]:
    """The lines of the workflow step whose `id:` is step_id."""
    lines = workflow.split("\n")
    at = next(i for i, line in enumerate(lines) if line.strip() == f"id: {step_id}")
    start = next(i for i in range(at, -1, -1) if lines[i].lstrip().startswith("- "))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if line.strip() and indent(line) <= indent(lines[start]):
            break
        block.append(line)
    return block


def run_script(workflow: str, step_id: str) -> str:
    """The `run: |` script of a step, as GitHub Actions passes it to the shell."""
    block = step_block(workflow, step_id)
    at = next(i for i, line in enumerate(block) if line.strip() == "run: |")
    body: list[str] = []
    for line in block[at + 1:]:
        if line.strip() and indent(line) <= indent(block[at]):
            break
        body.append(line)
    margin = min(indent(line) for line in body if line.strip())
    return "\n".join(line[margin:] for line in body).rstrip() + "\n"


def job_condition(lock: str, job: str) -> str:
    """A compiled job's `if:` condition, on one line."""
    start = lock.index(f"\n  {job}:\n")
    block = lock[start:lock.index("\n    runs-on:", start)]
    if "\n    if:" not in block:
        return ""
    lines = block.split("\n    if:", 1)[1].split("\n")
    condition = [lines[0]] + [line for line in lines[1:] if line.startswith("      ")]
    return " ".join(" ".join(condition).split())


def code_blocks(markdown: str) -> list[str]:
    """The fenced code blocks of a Markdown file, without their fences and list indentation."""
    blocks: list[str] = []
    current: list[str] | None = None
    margin = 0
    for line in markdown.split("\n"):
        if current is None and line.lstrip().startswith("```"):
            current, margin = [], indent(line)
        elif current is not None and line.strip() == "```":
            blocks.append("\n".join(current) + "\n")
            current = None
        elif current is not None:
            current.append(line[margin:] if line[:margin].strip() == "" else line)
    return blocks


def frontmatter(markdown: str) -> str:
    return markdown.split("---\n", 2)[1]


@unittest.skipUnless(BASH and JQ, "needs bash and jq, as on GitHub's Ubuntu runners")
class ProofScopeTests(unittest.TestCase):
    """The scope job decides which commit the proof job checks out and builds. A dispatched run belongs to main: its
    build shares main's Actions cache scope, so it must never build a fork's code."""

    REPO = "octo/requesthub"

    @classmethod
    def setUpClass(cls):
        cls.workflow = read(PROOF)
        cls.script = run_script(cls.workflow, "find")

    def run_scope(self, *, event: str, pr: str, head_repo: str | None = REPO, linked: bool = True):
        closing = [{"number": 41, "labels": {"nodes": [{"name": "incident-followup"}]}}] if linked else []
        response = {"data": {"repository": {"pullRequest": {
            "headRefOid": "a" * 40,
            "baseRefOid": "b" * 40,
            "headRepository": None if head_repo is None else {"nameWithOwner": head_repo},
            "labels": {"nodes": []},
            "closingIssuesReferences": {"nodes": closing},
        }}}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "response.json").write_text(json.dumps(response), encoding="utf-8")
            script = folder / "scope.sh"
            fake_gh = 'gh() { printf "%s\\n" "$*" >> "$GH_CALLS"; cat "$GH_RESPONSE"; }\n'
            script.write_text(fake_gh + self.script, encoding="utf-8", newline="\n")
            env = dict(os.environ, GH_TOKEN="test", REPO=self.REPO, PR=pr, EVENT=event,
                       GH_CALLS=(folder / "calls.txt").as_posix(), GH_RESPONSE=(folder / "response.json").as_posix(),
                       GITHUB_OUTPUT=(folder / "output.txt").as_posix(),
                       GITHUB_STEP_SUMMARY=(folder / "summary.md").as_posix())
            # GitHub Actions runs `shell: bash` steps as `bash --noprofile --norc -eo pipefail {0}`.
            proc = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", script.as_posix()], cwd=folder,
                                  env=env, capture_output=True, text=True, encoding="utf-8")
            output = (folder / "output.txt").read_text(encoding="utf-8") if (folder / "output.txt").exists() else ""
            calls = (folder / "calls.txt").read_text(encoding="utf-8") if (folder / "calls.txt").exists() else ""
        outputs = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        return proc, outputs, calls

    def test_the_step_knows_which_event_started_the_run(self):
        self.assertIn("EVENT: ${{ github.event_name }}", "\n".join(step_block(self.workflow, "find")))

    def test_dispatch_proves_a_pull_request_from_this_repository(self):
        proc, outputs, _ = self.run_scope(event="workflow_dispatch", pr="12")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((outputs.get("followups"), outputs.get("head"), outputs.get("base")), ("#41", "a" * 40, "b" * 40))

    def test_dispatch_refuses_a_fork_pull_request(self):
        proc, outputs, _ = self.run_scope(event="workflow_dispatch", pr="12", head_repo="stranger/requesthub")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("head", outputs)
        self.assertIn("pull_request", proc.stdout, "the error says how to prove a fork's pull request instead")

    def test_dispatch_refuses_a_pull_request_whose_fork_was_deleted(self):
        proc, outputs, _ = self.run_scope(event="workflow_dispatch", pr="12", head_repo=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("head", outputs)

    def test_dispatch_refuses_input_that_is_not_a_pull_request_number(self):
        for value in ("12 13", "-1", "0", "12\nhead=x", ""):
            with self.subTest(pr=value):
                proc, outputs, calls = self.run_scope(event="workflow_dispatch", pr=value)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(calls, "", "nothing is looked up for an invalid number")
                self.assertNotIn("head", outputs)

    def test_the_lookup_asks_for_the_head_repository(self):
        _, _, calls = self.run_scope(event="workflow_dispatch", pr="12")
        self.assertIn("headRepository", calls)

    def test_a_fork_pull_request_run_still_proves_in_its_own_scope(self):
        # A pull_request run of a fork's pull request gets a read-only token, no secrets, and its own cache scope, and
        # waits for approval. That is the run that proves a fork's change.
        proc, outputs, _ = self.run_scope(event="pull_request", pr="12", head_repo="stranger/requesthub")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(outputs.get("head"), "a" * 40)

    def test_a_pull_request_that_is_not_a_follow_up_proves_nothing(self):
        proc, outputs, _ = self.run_scope(event="workflow_dispatch", pr="12", linked=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(outputs.get("followups"), "")


class ProofWorkflowTests(unittest.TestCase):
    def test_the_proof_job_waits_for_the_scope_job(self):
        workflow = read(PROOF)
        self.assertIn("needs: scope", workflow)
        self.assertIn("if: needs.scope.outputs.followups != ''", workflow)

    def test_the_proof_never_gets_write_access_or_secrets(self):
        workflow = read(PROOF)
        permissions = re.search(r"^permissions:\n((?:  .*\n)+)", workflow, re.MULTILINE).group(1)
        self.assertEqual(["contents: read", "issues: read", "pull-requests: read"],
                         [line.strip() for line in permissions.strip("\n").splitlines()])
        self.assertNotRegex(workflow, r"pull_request_target|secrets\.")
        self.assertEqual(workflow.count("persist-credentials: false"), workflow.count("uses: actions/checkout@"))


class TriageGateTests(unittest.TestCase):
    """The incident's text goes into the triage's prompt, and the follow-up that Copilot later works from is written
    from it. gh-aw's role check covers whoever applied the label, so the incident's author is checked separately."""

    @classmethod
    def setUpClass(cls):
        cls.lock = read(TRIAGE_LOCK)
        cls.source = read(TRIAGE_SOURCE)

    def assert_author_gate(self, condition: str):
        self.assertIn("github.event.issue.author_association", condition)
        for association in TRUSTED:
            self.assertIn(f"'{association}'", condition)

    def test_the_source_starts_only_for_a_trusted_author(self):
        gate = re.search(r"^if: (.+)$", frontmatter(self.source), re.MULTILINE)
        self.assertIsNotNone(gate, "the frontmatter has an if: condition")
        self.assert_author_gate(gate.group(1))

    def test_the_compiled_workflow_starts_no_job_for_another_author(self):
        # pre_activation is the first job; every other job needs it, directly or through activation.
        self.assert_author_gate(job_condition(self.lock, "pre_activation"))
        self.assertIn("needs.pre_activation.outputs.activated == 'true'", job_condition(self.lock, "activation"))

    def test_whoever_applies_the_label_still_needs_write_access(self):
        self.assertIn('GH_AW_REQUIRED_ROLES: "admin,maintainer,write"', self.lock)
        self.assertNotRegex(frontmatter(self.source), r"(?m)^\s*roles:")

    def test_a_flagged_run_applies_no_output(self):
        self.assertRegex(frontmatter(self.source), r"threat-detection:\n\s+continue-on-error: false")
        self.assertIn('GH_AW_DETECTION_CONTINUE_ON_ERROR: "false"', self.lock)
        self.assertNotIn('GH_AW_DETECTION_CONTINUE_ON_ERROR: "true"', self.lock)
        self.assertIn("needs.detection.result == 'success'", job_condition(self.lock, "safe_outputs"))

    def test_the_agent_can_only_read(self):
        permissions = re.search(r"^permissions:\n((?:  .*\n)+)", frontmatter(self.source), re.MULTILINE).group(1)
        self.assertEqual(["contents: read", "issues: read"], [line.strip() for line in permissions.strip("\n").splitlines()])


class CopilotCliTests(unittest.TestCase):
    """Option B runs Copilot CLI unattended, signed in as the person who runs it. It gets file tools only and writes two
    drafts; the person reads them and files them."""

    FILE_TOOLS = {"view", "glob", "grep", "skill", "create", "edit", "apply_patch"}
    DRAFTS = {"followup-issue.md", "triage-comment.md"}

    @classmethod
    def setUpClass(cls):
        blocks = [block for block in code_blocks(read(README)) if "copilot --agent operate-github" in block]
        cls.blocks = blocks
        cls.command = " ".join(blocks[0].replace("`\n", " ").split()) if blocks else ""

    def test_the_readme_has_one_copilot_cli_command(self):
        self.assertEqual(len(self.blocks), 1)

    def test_the_model_sees_file_tools_only(self):
        listed = re.search(r"--available-tools '([^']+)'", self.command)
        self.assertIsNotNone(listed, "the command lists the tools the model can see")
        self.assertLessEqual(set(listed.group(1).split(",")), self.FILE_TOOLS)
        self.assertIn("--disable-builtin-mcps", self.command)
        self.assertIn("--disallow-temp-dir", self.command)

    def test_local_env_files_stay_unread(self):
        # A checkout can hold azd environment files, some with a GitHub token. A draft could carry one into a comment.
        self.assertIn("--deny-tool 'read(.env)'", self.command)

    def test_nothing_else_is_approved(self):
        self.assertNotRegex(self.command, r"shell\(|--allow-all|--yolo|--allow-url|url\(")
        allowed = set(re.findall(r"--allow-tool '([^']+)'", self.command))
        self.assertEqual(allowed, {f"write({draft})" for draft in self.DRAFTS})

    def test_only_a_trusted_authors_incident_reaches_copilot(self):
        block = self.blocks[0]
        check = block.index("author_association")
        export = block.index("gh issue view")
        self.assertLess(check, export, "the author is checked before the incident is exported")
        for association in TRUSTED:
            self.assertIn(f"'{association}'", block[check:export])
        self.assertNotIn("comments", block[export:block.index("\n", export)], "comments never reach Copilot")

    def test_the_agent_and_skill_never_file_anything(self):
        for path in (AGENT, EVIDENCE_SKILL):
            with self.subTest(file=path.name):
                self.assertNotRegex(read(path), r"gh issue (create|edit|comment)")


class CloudAgentInputTests(unittest.TestCase):
    """The incident's author can rewrite it after the triage, and anyone can comment on a public repository."""

    def test_the_agent_works_from_the_follow_up_and_the_triage_comment(self):
        agent = read(AGENT)
        self.assertNotIn("then the incident it links to", agent)
        self.assertIn("triage comment", agent)
        self.assertIn("author_association", agent)

    def test_the_skill_does_not_take_the_incident_as_input(self):
        skill = read(FOLLOWUP_SKILL)
        self.assertNotIn("The incident Issue and its triage comment", skill)
        self.assertIn("author_association", skill)


class OutsideReportTests(unittest.TestCase):
    """An outsider's report is not relabeled into the triage: a maintainer refiles it in their own words."""

    def test_the_form_asks_maintainers_to_refile_instead_of_relabeling(self):
        form = read(FORM)
        self.assertNotRegex(form, r"(?i)appl(y|ying) it again|re-?apply")
        self.assertIn("own words", form)

    def test_the_readme_says_the_same(self):
        readme = read(README)
        self.assertNotRegex(readme, r"removes the `incident` label and applies it again")
        self.assertIn("own words", readme)


if __name__ == "__main__":
    unittest.main()
