"""Tests for the reviewer's Azure Function (function/): the properties the review's trust depends on.

The tests run the real pipeline, the real GitHub, sessions, and agent clients, the real rule checker, and the real review
formatter against a fake network: GitHub's API and archive host, the two session pools (with the platform's 4 KB cap on
command output), and Foundry. No Azure, no GitHub, no token. Run from the repository root:
  python -m unittest discover -s solutions/03-develop-microsoft -p "test_reviewer*.py" -v
"""
from __future__ import annotations

import email.message
import hashlib
import hmac
import io
import json
import logging
import re
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "function"))
sys.path.insert(0, str(HERE / "sandbox"))
from reviewer import pipeline, webhook  # noqa: E402
from reviewer.agent import Agent  # noqa: E402
from reviewer.github import GitHub, GitHubError  # noqa: E402
from reviewer.sessions import Session  # noqa: E402
import format_review  # noqa: E402
import review_rules  # noqa: E402
from test_sandbox_scripts import BASE, WORKFLOW, WORKFLOW_SOURCE  # noqa: E402

TOKEN = "github_pat_TESTTOKEN_0123456789abcdef"
ARCHIVE_TOKEN = "CODELOADTOKEN42"
SECRET = "webhook-secret-for-tests"
REPO = "octo/requesthub"
JUDGE = "https://judgepool.example.net"
RUN = "https://runpool.example.net"
FOUNDRY = "https://foundry.example.net/api/projects/develop"
MERGE_BASE, BASE_SHA, HEAD, NEWER = "e" * 40, "b" * 40, "c" * 40, "d" * 40
REVIEW_ID = "a1b2c3d4e5f6"
SCRIPTS = {name: (HERE / "sandbox" / name).read_bytes() for name in pipeline.SCRIPTS}
NOTES = "".join(f"Line {i} of the release notes: nothing in this file changes how requests are decided.\n" for i in range(120))


def tree_bytes(changes: dict[str, str | None]) -> dict[str, bytes]:
    files = {path: text.encode() for path, text in BASE.items()}
    for path, text in changes.items():
        if text is None:
            files.pop(path, None)
        else:
            files[path] = text.encode()
    return files


BASE_TREE = tree_bytes({"docs/notes.md": "# Notes\n"})
# The head lets an approver decide their own low-priority request (the demo's change) and rewrites a long file, so the
# rule checker's judge.json (verdicts plus the diff) is several times longer than a session's 4 KB output cap.
HEAD_TREE = tree_bytes({
    WORKFLOW: WORKFLOW_SOURCE.replace('else if (r.RequesterId == user.Id) blocked = "self_approval";',
                                      'else if (r.RequesterId == user.Id && r.Priority != Priority.Low) blocked = "self_approval";'),
    "docs/notes.md": "# Notes\n" + NOTES,
})


def archive(files: dict[str, bytes], sha: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(f"octo-requesthub-{sha[:7]}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


ARCHIVES = {MERGE_BASE: archive(BASE_TREE, MERGE_BASE), HEAD: archive(HEAD_TREE, HEAD), NEWER: archive(HEAD_TREE, NEWER)}
ANSWER = {"summary": "This change lets approvers decide their own low-priority requests, while keeping the self-approval "
                     "block for every other priority. The main risk is that it weakens the approval-authority rule.",
          "observations": [{"severity": severity, "file": WORKFLOW, "line": 12 + i,
                            "text": f"Observation {i}: self-approval is now allowed for low-priority requests in both the "
                                    "decision and the permission check, which changes who can authorize a request; the "
                                    "person should confirm that this exception is intended and covered by a test."}
                           for i, severity in enumerate(("concern", "warning", "warning", "info", "info", "info"))],
          "rule_notes": [{"rule_id": "approval-authority",
                          "note": "DecideAsync and PermissionsFor now skip the self-approval guard when the priority is Low."}],
          "tests_note": "All tests passed: API 67 of 67 and web 14 of 14, with no reruns.",
          "for_the_person": "Decide whether letting approvers approve their own low-priority requests is an intended policy."}
SUMMARY = {"setup_seconds": 35, "seconds": 116,
           "api": {"status": "passed", "exit_code": 0, "seconds": 47, "total": 67, "passed": 67, "failed": 0, "skipped": 0,
                   "failed_tests": []},
           "web": {"status": "passed", "install_exit_code": 0, "typecheck": "passed",
                   "tests": {"total": 14, "passed": 14, "failed": 0, "skipped": 0, "failed_tests": []}, "rerun": None,
                   "seconds": 30}}


def pull(head: str = HEAD, *, repo: str = REPO, state: str = "open", draft: bool = False, ref: str = "main",
         labels: tuple[str, ...] = ("review:azure",)) -> dict:
    return {"number": 7, "title": "Let approvers fast-track their own low-priority requests", "user": {"login": "demo-author"},
            "body": "Approvers wait for a colleague even for a replacement keyboard.", "state": state, "draft": draft,
            "head": {"sha": head, "repo": {"full_name": repo}},
            "base": {"sha": BASE_SHA, "ref": ref, "repo": {"full_name": REPO, "default_branch": "main"}},
            "labels": [{"name": name} for name in labels]}


class Response:
    def __init__(self, status: int = 200, body: bytes | dict = b"", headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        self._body = json.dumps(body).encode() if isinstance(body, dict) else body

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit is None or limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url: str, code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(url, code, "error", message, None)


def cap(text: str) -> str:
    """What a session's execution API returns for a long output: the first 4,093 bytes, then '...'."""
    raw = text.encode()
    return raw[:4093].decode(errors="ignore") + "..." if len(raw) > 4096 else text


class FakeNetwork:
    """GitHub, its archive host, two session pools, and Foundry, for one review. Records every request."""

    def __init__(self, pulls: list[dict] | None = None, *, judge_writes: bool = True, build_polls: int = 2,
                 summary: str | None = None, agent_statuses: tuple[str, ...] = ("completed",), run_pool_down: bool = False,
                 redirect: str | None = None, github_status: int = 200):
        self.pulls = pulls or [pull()]
        self.reads = 0
        self.judge_writes, self.build_polls, self.summary = judge_writes, build_polls, summary
        self.agent_statuses, self.agent_calls = agent_statuses, 0
        self.run_pool_down, self.redirect, self.github_status = run_pool_down, redirect, github_status
        self.requests: list[tuple[str, str, dict, bytes]] = []
        self.sessions: dict[str, dict] = {}
        self.posts: list[dict] = []
        self.agent_inputs: list[dict] = []

    # ------------------------------------------------------------------ dispatch
    def open(self, request, timeout):
        url, method = request.full_url, request.get_method()
        headers = {k.lower(): v for k, v in request.header_items()}
        body = request.data or b""
        self.requests.append((method, url, headers, body))
        parts = urlsplit(url)
        if parts.hostname == "api.github.com":
            return self.github(method, url, parts, body)
        if parts.hostname == "codeload.github.com":
            return self.codeload(parts)
        if url.startswith(JUDGE) or url.startswith(RUN):
            return self.session("judge" if url.startswith(JUDGE) else "run", method, parts, headers, body)
        if url.startswith(FOUNDRY):
            return self.foundry(method, parts, body)
        raise AssertionError(f"unexpected request to {parts.hostname}")

    def github(self, method: str, url: str, parts, body: bytes):
        path = parts.path.removeprefix(f"/repos/{REPO}/")
        if self.github_status != 200:
            raise http_error(url, self.github_status)
        if method == "GET" and path == "pulls/7":
            value = self.pulls[min(self.reads, len(self.pulls) - 1)]
            self.reads += 1
            return Response(200, value)
        if method == "GET" and path.startswith("compare/"):
            return Response(200, {"merge_base_commit": {"sha": MERGE_BASE}})
        if method == "GET" and path.startswith("contents/"):
            name = path.rsplit("/", 1)[-1]
            assert parse_qs(parts.query).get("ref") == ["main"], "scripts must come from main"
            return Response(200, SCRIPTS[name])
        if method == "GET" and path.startswith("tarball/"):
            sha = path.rsplit("/", 1)[-1]
            location = self.redirect or f"https://codeload.github.com/{REPO}/legacy.tar.gz/{sha}?token={ARCHIVE_TOKEN}"
            raise http_error(url, 302, {"Location": location})
        if method == "POST" and path == "pulls/7/reviews":
            self.posts.append(json.loads(body))
            return Response(200, {"html_url": f"https://github.com/{REPO}/pull/7#pullrequestreview-{len(self.posts)}"})
        raise AssertionError(f"unexpected GitHub call {method} {path}")

    def codeload(self, parts):
        sha = parts.path.rsplit("/", 1)[-1]
        if sha not in ARCHIVES:
            raise http_error("https://codeload.github.com/", 404)
        return Response(200, ARCHIVES[sha])

    # ------------------------------------------------------------------ sessions
    def session(self, pool: str, method: str, parts, headers: dict, body: bytes):
        query = parse_qs(parts.query)
        identifier = query["identifier"][0]
        state = self.sessions.setdefault(identifier, {"pool": pool, "files": {}, "commands": [], "deleted": False})
        assert state["pool"] == pool, "one identifier, one pool"
        if pool == "run" and self.run_pool_down:
            raise http_error(parts.geturl(), 503)
        if method == "POST" and parts.path == "/files":
            boundary = re.search(r"boundary=(\S+)", headers["content-type"]).group(1).encode()
            split = body.index(b"\r\n\r\n")
            name = re.search(rb'filename="([^"]+)"', body[:split]).group(1).decode()
            state["files"][name] = body[split + 4:body.rindex(b"\r\n--" + boundary + b"--")]
            return Response(200, {"value": [{"name": name}]})
        if method == "POST" and parts.path == "/executions":
            command = json.loads(body)["shellCommand"]
            state["commands"].append(command)
            status, stdout = (self.judge_command if pool == "judge" else self.run_command)(state, command)
            return Response(200, {"identifier": identifier, "status": status,
                                  "result": {"stdout": cap(stdout), "stderr": "", "executionTimeInMilliseconds": 5}})
        match = re.fullmatch(r"/files/([^/]+)/content", parts.path)
        if method == "GET" and match:
            name = (query["path"][0] + "/" if "path" in query else "") + match.group(1)
            if name not in state["files"]:
                raise http_error(parts.geturl(), 404)
            return Response(200, state["files"][name], {"Content-Type": "application/octet-stream"})
        if method == "DELETE" and parts.path == "/session":
            state["deleted"] = True
            return Response(204)
        raise AssertionError(f"unexpected session call {method} {parts.path}")

    def judge_command(self, state: dict, command: str) -> tuple[str, str]:
        files = state["files"]
        if command == pipeline.CHECK_COMMAND:
            if not self.judge_writes:
                return "2", "review_rules.py exit code 2; judge.json is 0 bytes"
            with tempfile.TemporaryDirectory() as folder:
                for name in ("base.tgz", "head.tgz"):
                    Path(folder, name).write_bytes(files[name])
                result = review_rules.judge(review_rules.load_tree(Path(folder, "base.tgz")), review_rules.load_tree(Path(folder, "head.tgz")))
            result["markdown"] = review_rules.markdown(result)
            files["judge.json"] = json.dumps(result, ensure_ascii=False).encode()
            exit_code = "1" if result["summary"]["rules_failed"] else "0"
            # The old workflow printed judge.json too; a session would have cut it after 4 KB.
            return exit_code, f"review_rules.py exit code {exit_code}; judge.json is {len(files['judge.json'])} bytes\n" + files["judge.json"].decode()
        if command == pipeline.FORMAT_COMMAND:
            request = json.loads(files["review-input.json"])
            request["agent"] = json.loads(files["agent.json"])
            files["review.json"] = json.dumps(format_review.compose(json.loads(files["judge.json"]), request), ensure_ascii=False).encode()
            return "0", f"format_review.py exit code 0; review.json is {len(files['review.json'])} bytes\n" + files["review.json"].decode()
        return "127", "the judge runs only the checker and the formatter"

    def run_command(self, state: dict, command: str) -> tuple[str, str]:
        files = state["files"]
        if command == pipeline.BUILD_START:
            files["run/summary.json"] = b'{"state":"not-finished"}\n'
            state["polls"] = 0
            return "0", '{"state":"running","step":"queued"}'
        if command == pipeline.BUILD_STATUS:
            state["polls"] += 1
            if state["polls"] >= self.build_polls:
                files["run/summary.json"] = (self.summary or json.dumps(SUMMARY)).encode()
                return "0", '{"state":"done","step":"done"}'
            return "0", '{"state":"running","step":"api-tests"}'
        return "127", "the run pool runs only the runner"

    # ------------------------------------------------------------------ Foundry
    def foundry(self, method: str, parts, body: bytes):
        if method == "POST" and parts.path.endswith("/openai/v1/responses"):
            request = json.loads(body)
            self.agent_inputs.append(json.loads(request["input"]))
            self.agent_calls += 1
            return Response(200, {"id": f"resp_{self.agent_calls}", "status": "queued"})
        if method == "GET" and "/openai/v1/responses/" in parts.path:
            status = self.agent_statuses[min(self.agent_calls, len(self.agent_statuses)) - 1]
            answer = {"id": f"resp_{self.agent_calls}", "status": status, "model": "gpt-5.4-mini",
                      "agent_reference": {"type": "agent_reference", "name": "requesthub-pr-reviewer", "version": "4"}}
            if status == "completed":
                answer["output"] = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(ANSWER)}]}]
            else:
                answer["error"] = {"code": "content_filter", "message": "not shown"}
            return Response(200, answer)
        raise AssertionError(f"unexpected Foundry call {method} {parts.path}")

    # ------------------------------------------------------------------ what happened
    def calls_to(self, prefix: str) -> list[int]:
        return [i for i, (_, url, _, _) in enumerate(self.requests) if url.startswith(prefix)]

    def session_named(self, prefix: str) -> dict:
        return next(state for identifier, state in self.sessions.items() if identifier.startswith(prefix))


class FakeTime:
    def __init__(self):
        self.now = 1000.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        self.now += 0.1
        return self.now


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def review(net: FakeNetwork, *, dry_run: bool = False, **overrides) -> tuple[dict, list[str]]:
    clock = FakeTime()
    records = Records()
    root = logging.getLogger()
    root.addHandler(records)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    log = logging.getLogger(f"reviewer.test.{id(net)}")
    try:
        tools = pipeline.Tools(
            github=GitHub(REPO, TOKEN, open_url=net.open, sleep=clock.sleep),
            session=lambda pool, identifier: Session(JUDGE if pool == "judge" else RUN, identifier, lambda: "sessions-entra-token",
                                                     open_url=net.open, sleep=clock.sleep),
            agent=Agent(FOUNDRY, "requesthub-pr-reviewer", lambda: "foundry-entra-token", open_url=net.open, sleep=clock.sleep,
                        clock=clock.clock),
            sleep=clock.sleep, clock=clock.clock, log=log)
        result = pipeline.review(7, review_id=REVIEW_ID, dry_run=dry_run, settings=pipeline.Settings(repository=REPO, **overrides),
                                 tools=tools)
    finally:
        root.removeHandler(records)
        root.setLevel(old_level)
    return result, records.lines


class TheJudgeRunsFirst(unittest.TestCase):
    def test_the_verdicts_exist_before_any_of_the_pull_requests_code_reaches_a_session(self):
        net = FakeNetwork()
        result, _ = review(net)
        self.assertEqual(result["state"], "done", result)
        verdicts_read = next(i for i, (method, url, _, _) in enumerate(net.requests)
                             if method == "GET" and url.startswith(f"{JUDGE}/files/judge.json/content"))
        self.assertGreater(min(net.calls_to(RUN)), verdicts_read)

    def test_without_verdicts_no_code_runs_and_only_a_note_is_posted(self):
        net = FakeNetwork(judge_writes=False)
        result, _ = review(net)
        self.assertEqual((result["state"], result["step"]), ("failed", "check the team rules"))
        self.assertEqual(net.calls_to(RUN), [])
        self.assertEqual(net.agent_calls, 0)
        self.assertEqual(len(net.posts), 1)
        self.assertIn("couldn't finish this review", net.posts[0]["body"])

    def test_the_judge_runs_only_the_checker_and_the_formatter(self):
        net = FakeNetwork()
        review(net)
        judge = net.session_named("judge-")
        self.assertEqual(judge["commands"], [pipeline.CHECK_COMMAND, pipeline.FORMAT_COMMAND])
        for command in judge["commands"]:
            self.assertRegex(command, r"^cd /mnt/data && python3 (review_rules|format_review)\.py ")

    def test_the_pull_requests_code_goes_only_to_the_run_pool_and_only_the_runner_runs_there(self):
        net = FakeNetwork()
        review(net)
        run = net.session_named("run-")
        self.assertEqual(set(run["files"]) - {"run/summary.json"}, {"run_change.sh", "head.tgz"})
        self.assertEqual(set(run["commands"]), {pipeline.BUILD_START, pipeline.BUILD_STATUS})
        self.assertEqual(run["files"]["run_change.sh"], SCRIPTS["run_change.sh"])

    def test_the_scripts_come_from_main(self):
        net = FakeNetwork()
        review(net)  # the fake asserts ref=main on every contents call
        judge = net.session_named("judge-")
        self.assertEqual(judge["files"]["review_rules.py"], SCRIPTS["review_rules.py"])
        self.assertEqual(judge["files"]["format_review.py"], SCRIPTS["format_review.py"])


class ResultsTravelAsFiles(unittest.TestCase):
    def test_results_longer_than_the_4_kb_output_cap_are_read_whole(self):
        net = FakeNetwork()
        result, _ = review(net, dry_run=True)
        judge = net.session_named("judge-")
        self.assertGreater(len(judge["files"]["judge.json"]), 4096)
        self.assertGreater(len(judge["files"]["review.json"]), 4096)
        self.assertEqual(len(result["rules"]), 5)
        self.assertEqual(result["review"], json.loads(judge["files"]["review.json"])["markdown"])
        self.assertIn("Approval authority is untouched", result["review"])
        self.assertEqual(net.agent_inputs[0]["diff"], json.loads(judge["files"]["judge.json"])["diff"])

    def test_the_build_summary_is_bounded(self):
        net = FakeNetwork(summary=json.dumps({"state": "done", "padding": "x" * 50000}))
        result, _ = review(net, dry_run=True)
        self.assertEqual(len(result["sandbox"]), pipeline.SANDBOX_LIMIT)
        self.assertEqual(len(net.agent_inputs[0]["sandbox"]), pipeline.SANDBOX_LIMIT)

    def test_a_build_that_runs_out_of_time_says_so(self):
        net = FakeNetwork(build_polls=10**9)
        result, _ = review(net, dry_run=True)
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["sandbox"].strip(), '{"state":"not-finished"}')
        self.assertIn("The build didn't finish in time", result["review"])
        self.assertEqual(net.session_named("run-")["commands"].count(pipeline.BUILD_STATUS), 60)

    def test_a_build_that_cant_run_still_posts_the_rule_results(self):
        net = FakeNetwork(run_pool_down=True)
        result, _ = review(net)
        self.assertEqual((result["state"], result["posted"]), ("done", True))
        self.assertIn("No test results came back from the sandbox", net.posts[0]["body"])
        self.assertIn("Approval authority is untouched", net.posts[0]["body"])


class GitHubAccess(unittest.TestCase):
    def test_reviews_are_comments_only(self):
        for net in (FakeNetwork(), FakeNetwork(judge_writes=False)):
            review(net)
            self.assertEqual(len(net.posts), 1)
            self.assertEqual(net.posts[0]["event"], "COMMENT")

    def test_no_code_can_approve_or_request_changes(self):
        for path in (HERE / "function").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for word in ("APPROVE", "REQUEST_CHANGES"):
                self.assertNotIn(word, source, path.name)

    def test_a_review_is_posted_on_the_commit_it_reviewed(self):
        net = FakeNetwork()
        result, _ = review(net)
        self.assertEqual(net.posts[0]["commit_id"], HEAD)
        self.assertTrue(result["posted"])

    def test_a_stale_review_is_not_posted(self):
        net = FakeNetwork([pull(HEAD), pull(NEWER)])
        result, lines = review(net)
        self.assertEqual(net.posts, [])
        self.assertTrue(result["superseded"])
        self.assertTrue(any("not posted" in line for line in lines))

    def test_the_token_goes_to_api_github_com_and_nowhere_else(self):
        for net in (FakeNetwork(), FakeNetwork(judge_writes=False), FakeNetwork(agent_statuses=("failed", "failed"))):
            review(net)
            for method, url, headers, body in net.requests:
                host = urlsplit(url).hostname
                if host == "api.github.com":
                    self.assertEqual(headers.get("authorization"), f"Bearer {TOKEN}")
                    continue
                self.assertNotIn(TOKEN, url)
                self.assertNotIn(TOKEN, json.dumps(headers))
                self.assertNotIn(TOKEN.encode(), body, f"{method} {host}")
                if host == "codeload.github.com":
                    self.assertNotIn("authorization", headers)
            for state in net.sessions.values():
                for name, data in state["files"].items():
                    self.assertNotIn(TOKEN.encode(), data, name)
            self.assertNotIn(TOKEN, json.dumps(net.agent_inputs))

    def test_neither_the_token_nor_an_archive_link_reaches_a_log(self):
        cases = (FakeNetwork(), FakeNetwork(judge_writes=False), FakeNetwork(github_status=401), FakeNetwork(run_pool_down=True),
                 FakeNetwork(redirect="https://evil.example.net/x?token=" + ARCHIVE_TOKEN))
        for net in cases:
            for dry_run in (False, True):
                result, lines = review(net, dry_run=dry_run)
                text = "\n".join(lines) + json.dumps(result)
                self.assertNotIn(TOKEN, text)
                self.assertNotIn(ARCHIVE_TOKEN, text)
                self.assertNotIn("codeload", text)
                self.assertTrue(lines)

    def test_an_archive_is_downloaded_only_from_githubs_archive_host(self):
        net = FakeNetwork(redirect="https://evil.example.net/archive.tgz")
        result, _ = review(net, dry_run=True)
        self.assertEqual((result["state"], result["step"]), ("failed", "download the code"))
        self.assertFalse(any(urlsplit(url).hostname == "evil.example.net" for _, url, _, _ in net.requests))
        self.assertEqual(net.sessions, {})


class OnlyThisRepositorysBranches(unittest.TestCase):
    """On a public repository anyone can open a pull request from a fork. Its code must never reach a session or the
    agent, not even in a dry run. A real review also needs the label, which only people with triage access can apply."""

    def test_a_fork_is_never_built_or_reviewed_even_in_a_dry_run(self):
        for dry_run in (False, True):
            net = FakeNetwork([pull(repo="someone/requesthub")])
            result, _ = review(net, dry_run=dry_run)
            self.assertEqual(result["state"], "skipped")
            self.assertIn("fork", result["reason"])
            self.assertEqual([url for _, url, _, _ in net.requests if "api.github.com" not in url], [])
            self.assertEqual(net.posts, [])

    def test_a_real_review_needs_an_open_labelled_non_draft_pull_request_into_the_default_branch(self):
        for variant in (pull(state="closed"), pull(draft=True), pull(ref="release"), pull(labels=())):
            net = FakeNetwork([variant])
            result, _ = review(net)
            self.assertEqual(result["state"], "skipped", variant)
            self.assertEqual(net.sessions, {})
            dry, _ = review(FakeNetwork([variant]), dry_run=True)  # a dry run checks only the branch's repository
            self.assertEqual(dry["state"], "done", variant)

    def test_the_label_and_the_branch_are_read_from_githubs_api_not_the_delivery(self):
        payload = {"action": "labeled", "label": {"name": "review:azure"}, "repository": {"full_name": REPO},
                   "pull_request": {"number": 7, "labels": [{"name": "review:azure"}], "head": {"repo": {"full_name": REPO}}}}
        for api_view, expected in ((pull(labels=()), 200), (pull(repo="someone/requesthub"), 200), (pull(), 202)):
            reads = []
            status, answer, message = intake(payload, read_pull=lambda n, view=api_view: reads.append(n) or view)
            self.assertEqual((status, reads), (expected, [7]), answer)
            self.assertEqual(message is not None, expected == 202)


class DryRuns(unittest.TestCase):
    def test_a_dry_run_posts_nothing_even_when_it_fails(self):
        for net in (FakeNetwork(), FakeNetwork(judge_writes=False)):
            review(net, dry_run=True)
            self.assertEqual(net.posts, [])
            self.assertEqual(net.reads, 1)  # no second read: nothing is posted, so nothing can be stale

    def test_a_dry_run_returns_what_the_evaluation_reads(self):
        result, _ = review(FakeNetwork(), dry_run=True)
        for key in ("rules", "review", "agent", "sandbox", "agent_error"):
            self.assertIn(key, result)
        self.assertEqual(result["agent"]["summary"], ANSWER["summary"])
        self.assertIn(f"review `{REVIEW_ID}`", result["review"])


class Sessions(unittest.TestCase):
    def test_both_sessions_are_deleted_after_a_review(self):
        net = FakeNetwork()
        review(net)
        self.assertEqual({k: v["deleted"] for k, v in net.sessions.items()}, {f"judge-{REVIEW_ID}": True, f"run-{REVIEW_ID}": True})

    def test_the_judges_session_is_deleted_after_a_failure_and_the_unused_run_session_isnt_called(self):
        net = FakeNetwork(judge_writes=False)
        review(net)
        self.assertEqual({k: v["deleted"] for k, v in net.sessions.items()}, {f"judge-{REVIEW_ID}": True})

    def test_the_agent_gets_the_run_session_never_the_judges(self):
        net = FakeNetwork()
        review(net)
        self.assertEqual(net.agent_inputs[0]["run_session"], f"run-{REVIEW_ID}")
        self.assertNotIn(f"judge-{REVIEW_ID}", json.dumps(net.agent_inputs))


class TheAgent(unittest.TestCase):
    def test_the_agent_is_asked_once_more_when_its_answer_doesnt_complete(self):
        net = FakeNetwork(agent_statuses=("failed", "completed"))
        result, _ = review(net)
        self.assertEqual(net.agent_calls, 2)
        self.assertIn(ANSWER["summary"], net.posts[0]["body"])
        self.assertIsNone(result["agent_error"])

    def test_without_an_answer_the_review_still_posts_the_rule_results(self):
        net = FakeNetwork(agent_statuses=("failed", "failed"))
        result, _ = review(net)
        self.assertEqual(net.agent_calls, 2)
        self.assertTrue(result["posted"])
        self.assertIn("not available", net.posts[0]["body"])
        self.assertIn("Approval authority is untouched", net.posts[0]["body"])


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def intake(payload: dict, *, event: str = "pull_request", signature: str | None = None, read_pull=None, secret: str = SECRET):
    body = json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": "0" * 8 + "-1111-2222-3333-" + "4" * 12,
               "X-Hub-Signature-256": sign(body) if signature is None else signature}
    return webhook.intake(headers, body, secret=secret, repository=REPO, label="review:azure",
                          read_pull=read_pull or (lambda n: pull()), new_id=lambda: REVIEW_ID)


class Webhook(unittest.TestCase):
    LABELED = {"action": "labeled", "label": {"name": "review:azure"}, "repository": {"full_name": REPO},
               "pull_request": {"number": 7, "labels": [{"name": "review:azure"}]}}

    def test_only_a_correctly_signed_delivery_is_read(self):
        for signature in ("", "sha256=" + "0" * 64, sign(b"other body"), sign(json.dumps(self.LABELED).encode(), "wrong secret"),
                          "sha1=abc"):
            reads = []
            status, _, message = intake(self.LABELED, signature=signature, read_pull=lambda n: reads.append(n) or pull())
            self.assertEqual((status, reads, message), (401, [], None), signature)

    def test_without_a_secret_nothing_is_accepted(self):
        status, _, message = intake(self.LABELED, secret="")
        self.assertEqual((status, message), (503, None))

    def test_the_review_label_queues_a_review_with_only_the_number(self):
        status, answer, message = intake(self.LABELED)
        self.assertEqual(status, 202, answer)
        self.assertEqual(set(message), {"id", "pr", "dryRun", "event", "delivery"})
        self.assertEqual((message["pr"], message["dryRun"], message["event"]), (7, False, "pull_request.labeled"))

    def test_pushes_reopening_and_ready_for_review_queue_a_review_when_labelled(self):
        for action in webhook.LABEL_ACTIONS:
            status, _, message = intake(dict(self.LABELED, action=action))
            self.assertEqual(status, 202, action)
            unlabelled = dict(self.LABELED, action=action, pull_request={"number": 7, "labels": [{"name": "other"}]})
            reads = []
            status, answer, message = intake(unlabelled, read_pull=lambda n: reads.append(n) or pull())
            self.assertEqual((status, message, reads), (200, None, []), answer)

    def test_everything_else_is_acknowledged_and_ignored(self):
        cases = [("ping", {"zen": "Keep it simple."}), ("issues", self.LABELED),
                 ("pull_request", dict(self.LABELED, label={"name": "bug"})),
                 ("pull_request", dict(self.LABELED, action="opened")), ("pull_request", dict(self.LABELED, action="closed")),
                 ("pull_request", dict(self.LABELED, repository={"full_name": "someone/requesthub"}))]
        for event, payload in cases:
            reads = []
            status, answer, message = intake(payload, event=event, read_pull=lambda n: reads.append(n) or pull())
            self.assertEqual((status, message, reads), (200, None, []), (event, payload.get("action")))
            self.assertEqual(answer["result"], "ignored")

    def test_github_refusing_the_token_is_reported_without_the_token(self):
        def refuse(number):
            raise GitHubError(f"read pull request #{number}: GitHub answered HTTP 401", 401)
        status, answer, message = intake(self.LABELED, read_pull=refuse)
        self.assertEqual((status, message), (502, None))
        self.assertIn("HTTP 401", answer["error"])


class Clients(unittest.TestCase):
    def test_a_github_error_names_the_call_never_the_url_or_the_token(self):
        net = FakeNetwork(github_status=404)
        client = GitHub(REPO, TOKEN, open_url=net.open, sleep=lambda s: None)
        with self.assertRaises(GitHubError) as raised:
            client.pull(7)
        self.assertEqual(str(raised.exception), "read pull request #7: GitHub answered HTTP 404")

    def test_the_github_client_never_shows_the_token(self):
        self.assertNotIn(TOKEN, repr(GitHub(REPO, TOKEN)))
        with self.assertRaises(GitHubError):
            GitHub(REPO, "")


class FunctionSettings(unittest.TestCase):
    host = json.loads((HERE / "function" / "host.json").read_text(encoding="utf-8"))
    app = (HERE / "function" / "function_app.py").read_text(encoding="utf-8")

    def test_a_failed_review_message_is_not_retried(self):
        self.assertEqual(self.host["extensions"]["queues"]["maxDequeueCount"], 1)

    def test_a_queued_review_starts_as_soon_as_an_instance_has_room(self):
        queues = self.host["extensions"]["queues"]
        # At most four reviews at a time on one instance: each holds two archives in memory. With newBatchThreshold 0,
        # an instance would take no new review until every review it runs has finished, so a review queued behind a
        # running one would wait minutes; with batchSize 1, the platform also scales out one instance per waiting review.
        self.assertLessEqual(queues["batchSize"] + queues["newBatchThreshold"], 4)
        self.assertGreaterEqual(queues["newBatchThreshold"], 1)
        self.assertEqual(queues["batchSize"], 1)

    def test_a_review_has_time_for_the_build_and_two_agent_attempts(self):
        hours, minutes, _ = (int(part) for part in self.host["functionTimeout"].split(":"))
        settings = pipeline.Settings(repository=REPO)
        self.assertGreater(hours * 60 + minutes, (settings.build_timeout_seconds + 2 * settings.agent_wait_seconds) / 60 + 5)

    def test_only_the_webhook_is_anonymous_and_the_dry_run_routes_need_the_function_key(self):
        routes = re.findall(r"@app\.route\(([^)]*)\)", self.app)
        self.assertEqual(len(routes), 3)
        for route in routes:
            anonymous = "auth_level" not in route
            self.assertEqual(anonymous, 'route="github/webhook"' in route, route)
        self.assertIn("http_auth_level=func.AuthLevel.ANONYMOUS", self.app)
        self.assertIn("webhook.intake(", self.app)  # the webhook's only path in: the signature check comes first

    def test_nothing_logs_a_secret_setting(self):
        for name in ("GITHUB_REVIEW_TOKEN", "GITHUB_WEBHOOK_SECRET"):
            for line in self.app.splitlines():
                if name in line:
                    self.assertNotIn("log.", line)


if __name__ == "__main__":
    unittest.main()
