"""Tests for the Function app's run (../function/planner): every behavior the demo depends on, with fake Foundry and
GitHub clients and a fake clock, so they run anywhere in about a second. setup_foundry.py publish runs them (with the
evaluator tests) before it publishes anything, and azd runs them again before it deploys the Function app.

    python -m unittest discover -s solutions/01-plan-microsoft/tests -v

The fixture sample-brief.json is a brief the Foundry agent wrote. The live demo evidence comes from real runs, never
from these fakes.
"""
import copy
import http.client
import json
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SOLUTION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOLUTION))
sys.path.insert(0, str(SOLUTION / "function"))
import setup_foundry  # noqa: E402
from planner import brief, checks, clients, steps  # noqa: E402
from planner.clients import ServiceError  # noqa: E402
from planner.store import MemoryStore  # noqa: E402

SAMPLE = (Path(__file__).parent / "sample-brief.json").read_text(encoding="utf-8")
ALL_CHECKS = list(setup_foundry.THRESHOLDS)


def function_timeout() -> timedelta:
    """host.json's functionTimeout: Azure Functions stops any invocation that runs longer."""
    host = json.loads((SOLUTION / "function/host.json").read_text(encoding="utf-8"))
    hours, minutes, seconds = (int(part) for part in host["functionTimeout"].split(":"))
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def result(name, passed=True, score=1.0, errored=False):
    return {"name": name, "passed": passed, "score": score,
            "sample": {"error": {"message": "An error occurred during grading"} if errored else None}}


def passing(**overrides):
    """Seven results that pass, with some replaced: passing(citations=result("citations", False, 0.5))."""
    return [overrides.get(name, result(name)) for name in ALL_CHECKS]


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)

    def now(self):
        return self.moment

    def sleep(self, seconds):
        self.moment += timedelta(seconds=seconds)


class FakeFoundry:
    """Scripted Foundry: responses end as the given statuses; each evaluation attempt returns the given outcome."""

    def __init__(self, responses=("completed",), answer=SAMPLE, attempts=None, evaluation_id="eval_1"):
        self.response_statuses = list(responses)
        self.answer = answer
        # Each attempt: (status, errored gates, Foundry results, Copilot results or None)
        self.attempts = list(attempts or [("completed", [], passing(), None)])
        self.eval_id = evaluation_id
        self.started_responses, self.started_runs = [], []
        self.polls = {}

    def start_response(self, agent, prompt):
        self.started_responses.append((agent, prompt))
        return {"id": f"resp_{len(self.started_responses)}", "status": "queued"}

    def response(self, response_id):
        n = int(response_id.split("_")[1])
        self.polls[response_id] = self.polls.get(response_id, 0) + 1
        if self.polls[response_id] < 2:
            return {"id": response_id, "status": "in_progress"}
        status = self.response_statuses[min(n, len(self.response_statuses)) - 1]
        if status != "completed":
            return {"id": response_id, "status": status, "error": {"message": "The server is overloaded or not ready yet."}}
        return {"id": response_id, "status": "completed", "output": [
            {"type": "file_search_call"},
            {"type": "message", "content": [{"type": "output_text", "text": self.answer}]}]}

    def evaluation_id(self, name):
        return self.eval_id

    def start_evaluation_run(self, evaluation_id, name, items):
        self.started_runs.append({"name": name, "items": items})
        return {"id": f"evalrun_{len(self.started_runs)}", "status": "queued"}

    def attempt(self, run_id):
        n = int(run_id.split("_")[1])
        return self.attempts[min(n, len(self.attempts)) - 1]

    def evaluation_run(self, evaluation_id, run_id):
        status, errored, _, _ = self.attempt(run_id)
        return {"id": run_id, "status": status, "per_testing_criteria_results": [
            {"testing_criteria": name, "passed": 0, "failed": 0, "errored": 1 if name in errored else 0} for name in ALL_CHECKS]}

    def output_items(self, evaluation_id, run_id):
        _, _, foundry, copilot = self.attempt(run_id)
        items = [{"datasource_item": {"brief": checks.FOUNDRY_LABEL}, "results": foundry}]
        if copilot is not None:
            items.append({"datasource_item": {"brief": checks.copilot_label(129)}, "results": copilot})
        return items


class FakeGitHub:
    def __init__(self, fail_on=None):
        self.issues = {}
        self.calls = []
        self.fail_on = fail_on or {}  # call name -> (call number, exception)
        self.counts = {}
        self.files = {}

    def hit(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1
        self.calls.append(name)
        failure = self.fail_on.get(name)
        if failure and failure[0] == self.counts[name]:
            raise failure[1]

    def create_issue(self, title, body, labels, author_association="OWNER"):
        self.hit("create_issue")
        number = 200 + len(self.issues)
        self.issues[number] = {"number": number, "id": 90000 + number, "title": title, "body": body,
                               "labels": [{"name": label} for label in labels], "state": "open", "state_reason": None,
                               "author_association": author_association,
                               "comments": [], "sub_issues": [], "blocked_by": []}
        return self.issues[number]

    def outsider_issue(self, body, labels):
        """An Issue someone outside the repository filed, for example through a form that applies labels."""
        issue = self.create_issue("copied marker", body, labels, author_association="NONE")
        self.counts["create_issue"] -= 1
        return issue

    def issue(self, number):
        self.hit("issue")
        if number not in self.issues:
            raise ServiceError("GitHub", 404, "Not Found")
        return self.issues[number]

    def comment(self, number, body):
        self.hit("comment")
        self.issues[number]["comments"].append(body)

    def close(self, number, reason):
        self.hit("close")
        self.issues[number].update(state="closed", state_reason=reason)

    def add_sub_issue(self, parent, child_id):
        self.hit("add_sub_issue")
        self.issues[parent]["sub_issues"].append(child_id)

    def add_blocked_by(self, number, blocker_id):
        self.hit("add_blocked_by")
        self.issues[number]["blocked_by"].append(blocker_id)

    def read_file(self, path, ref):
        self.hit("read_file")
        if (path, ref) not in self.files:
            raise ServiceError("GitHub", 404, "Not Found")
        return self.files[(path, ref)]

    def list_issues(self, labels):
        self.hit("list_issues")
        return [issue for issue in sorted(self.issues.values(), key=lambda i: -i["number"])
                if set(labels) <= {label["name"] for label in issue["labels"]}]

    def check(self):
        return {"status": 200, "expires": "2027-02-28 05:00:00 UTC", "error": None}

    def label(self, number, name):
        self.issues[number]["labels"].append({"name": name})

    repository = "owner/repo"

    def add_pull_request(self, number, author_association="OWNER", brief_text='{"copilot": true}', head_repo=None):
        self.pulls = getattr(self, "pulls", {})
        sha = f"{number:040x}"
        self.pulls[number] = {"number": number, "author_association": author_association,
                              "head": {"sha": sha, "repo": {"full_name": head_repo or self.repository}}}
        self.files[(steps.COPILOT_BRIEF, sha)] = brief_text

    def pull_request(self, number):
        self.hit("pull_request")
        if number not in getattr(self, "pulls", {}):
            raise ServiceError("GitHub", 404, "Not Found")
        return self.pulls[number]


class RunTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = MemoryStore()
        self.github = FakeGitHub()
        self.foundry = FakeFoundry()
        self.logs = []
        self.token_missing = False
        self.excerpts = brief.source_excerpts(
            (SOLUTION / "inputs/stakeholder-transcript.md").read_text(encoding="utf-8"),
            (SOLUTION / "inputs/routing-policies.md").read_text(encoding="utf-8"))

    def services(self):
        def github():
            if self.token_missing:
                raise steps.TokenMissing("Key Vault has no GitHub token yet")
            return self.github

        return steps.Services(store=self.store, foundry=self.foundry, github=github,
                              settings=steps.Settings(agent="requirements-analyst", prompt="Analyze the transcript.",
                                                      excerpts=self.excerpts),
                              now=self.clock.now, sleep=self.clock.sleep, log=self.logs.append)

    def record(self, run_id):
        return self.store.peek(run_id)

    def to_review(self, compare=None):
        """start → draft → evaluate: returns the run id, waiting for a person (or failed)."""
        svc = self.services()
        run_id = steps.start(svc, compare)["id"]
        if steps.draft(svc, run_id) == "evaluate":
            try:
                steps.evaluate(svc, run_id)
            except steps.Stop:
                pass
        return run_id

    def draft_only(self):
        svc = self.services()
        run_id = steps.start(svc)["id"]
        try:
            steps.draft(svc, run_id)
        except steps.Stop:
            pass
        return run_id

    def review_issue(self, run_id):
        return self.github.issues[self.record(run_id)["review"]["issue"]]

    def approve_and_publish(self, run_id):
        svc = self.services()
        self.github.label(self.record(run_id)["review"]["issue"], "brief-approved")
        to_publish = steps.check_reviews(svc)
        self.assertEqual(to_publish, [run_id])
        try:
            steps.publish(svc, run_id)
        except steps.Stop:  # run_step catches it in Azure: the record says why the run ended
            pass

    # ---------- the definitions agree with setup_foundry.py ----------
    def test_gates_and_names_match_what_setup_foundry_publishes(self):
        self.assertEqual(checks.GATES, tuple(ALL_CHECKS[:4]))
        self.assertEqual(checks.GATES + checks.REPORTED, tuple(ALL_CHECKS))
        self.assertEqual(set(checks.CHECK_NAMES), set(ALL_CHECKS))
        self.assertEqual(steps.EVALUATION, setup_foundry.EVALUATION_NAME)

    def test_the_queue_retry_count_matches_host_json(self):
        host = json.loads((SOLUTION / "function/host.json").read_text(encoding="utf-8"))
        app = (SOLUTION / "function/function_app.py").read_text(encoding="utf-8")
        self.assertIn(f"MAX_DEQUEUE_COUNT = {host['extensions']['queues']['maxDequeueCount']}", app)

    # ---------- the whole path ----------
    def test_an_approved_brief_is_published_as_an_epic_with_four_linked_tasks(self):
        run_id = self.to_review()
        record = self.record(run_id)
        self.assertEqual(record["state"], "awaiting_review")
        review = self.review_issue(run_id)
        self.assertEqual({l["name"] for l in review["labels"]}, {"ai-sdlc", "phase:plan", "track:microsoft", "type:brief"})
        self.assertIn("| Every citation exists in the inputs | gate | ✅ 1 |", review["body"])
        self.assertIn(f"run `{run_id}`", review["body"])
        self.assertIn("(response `resp_1`)", review["body"])
        self.assertTrue(review["body"].rstrip().endswith(brief.review_marker(run_id)))

        self.assertEqual(steps.check_reviews(self.services()), [], "no decision yet")
        self.approve_and_publish(run_id)

        record = self.record(run_id)
        self.assertEqual(record["state"], "published")
        sample = json.loads(SAMPLE)
        epic = self.github.issues[record["published"]["epic"]["number"]]
        tasks = [self.github.issues[t["number"]] for t in record["published"]["tasks"]]
        self.assertEqual(len(tasks), 4)
        self.assertEqual(epic["title"], f"[Plan/Foundry] {sample['epic']['title']}")
        self.assertEqual(epic["sub_issues"], [t["id"] for t in tasks])
        self.assertIn(f"after a person approved review Issue #{review['number']}", epic["body"])
        for task, issue in zip(sample["tasks"], tasks):
            self.assertIn(f"**Epic:** #{epic['number']}", issue["body"])
            self.assertEqual(len(issue["blocked_by"]), len(task.get("dependsOn") or []))
        self.assertEqual(review["state"], "closed")
        self.assertEqual(review["state_reason"], "completed")
        self.assertIn(f"- Epic: #{epic['number']}", review["comments"][-1])

    def test_a_dependency_points_at_the_blocking_tasks_issue(self):
        run_id = self.to_review()
        self.approve_and_publish(run_id)
        by_task = {t["taskId"]: t for t in self.record(run_id)["published"]["tasks"]}
        for task in json.loads(SAMPLE)["tasks"]:
            blocked = self.github.issues[by_task[task["id"]]["number"]]["blocked_by"]
            self.assertEqual(blocked, [by_task[b]["id"] for b in task.get("dependsOn") or []])

    # ---------- the agent ----------
    def test_the_agent_runs_in_background_mode_and_is_polled(self):
        run_id = self.draft_only()
        record = self.record(run_id)
        self.assertEqual(record["state"], "evaluating")
        self.assertEqual(self.foundry.started_responses, [("requirements-analyst", "Analyze the transcript.")])
        self.assertEqual(record["briefText"], SAMPLE)
        self.assertEqual(record["draft"]["seconds"], steps.RESPONSE_POLL_SECONDS * 2)

    def test_a_failed_response_is_asked_for_once_more(self):
        self.foundry = FakeFoundry(responses=("failed", "completed"))
        run_id = self.draft_only()
        self.assertEqual(self.record(run_id)["state"], "evaluating")
        self.assertEqual(len(self.foundry.started_responses), 2)

    def test_two_failed_responses_fail_the_run_before_github(self):
        self.foundry = FakeFoundry(responses=("failed", "failed"))
        run_id = self.draft_only()
        record = self.record(run_id)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["error"]["code"], "AgentDidNotFinish")
        self.assertEqual(self.github.calls, [])

    def test_an_answer_that_is_not_json_fails_the_run(self):
        self.foundry = FakeFoundry(answer="Here is your brief: ...")
        run_id = self.draft_only()
        self.assertEqual(self.record(run_id)["error"]["code"], "AgentDidNotFinish")

    def test_a_response_still_running_after_ten_minutes_fails_the_run(self):
        self.foundry = FakeFoundry()
        self.foundry.response = lambda response_id: {"id": response_id, "status": "in_progress"}
        run_id = self.draft_only()
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "AgentDidNotFinish")
        self.assertIn("'in_progress'", record["error"]["message"])

    def test_a_redelivered_draft_polls_the_response_it_started(self):
        svc = self.services()
        run_id = steps.start(svc)["id"]
        original, polls = self.foundry.response, []

        def stop_at_the_first_poll(response_id):
            polls.append(response_id)
            if len(polls) == 1:
                raise clients.ServiceUnreachable("Foundry", "TimeoutError")
            return original(response_id)

        self.foundry.response = stop_at_the_first_poll
        with self.assertRaises(OSError):
            steps.draft(svc, run_id)
        self.assertEqual(steps.draft(self.services(), run_id), "evaluate")  # the queue delivers the step again
        self.assertEqual(len(self.foundry.started_responses), 1, "the agent was asked once")
        self.assertEqual(self.record(run_id)["state"], "evaluating")

    # ---------- the evaluation ----------
    def test_an_errored_gate_runs_the_evaluation_again(self):
        self.foundry = FakeFoundry(attempts=[("completed", ["citations"], passing(citations=result("citations", False, 0, True)), None),
                                             ("completed", [], passing(), None)])
        run_id = self.to_review()
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")
        self.assertEqual(len(self.foundry.started_runs), 2)
        self.assertIn("attempt 2", self.foundry.started_runs[1]["name"])

    def test_a_gate_that_errors_three_times_fails_the_run(self):
        errored = ("completed", ["structure"], passing(structure=result("structure", False, 0, True)), None)
        self.foundry = FakeFoundry(attempts=[errored] * 3)
        run_id = self.to_review()
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "BriefFailedEvaluation")
        self.assertIn("structure", record["error"]["message"])
        self.assertEqual(len(self.foundry.started_runs), 3)
        self.assertNotIn("create_issue", self.github.calls)

    def test_scores_from_different_attempts_are_combined(self):
        # Seen live: the sandbox errored on one gate in the first attempt and on another in the second. Each gate was
        # scored once, and the checks are code, so the brief passes without a third attempt.
        self.foundry = FakeFoundry(attempts=[
            ("completed", ["injection_ignored"], passing(injection_ignored=result("injection_ignored", False, 0, True)), None),
            ("completed", ["citations"], passing(citations=result("citations", False, 0, True)), None)])
        run_id = self.to_review()
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")
        self.assertEqual(len(self.foundry.started_runs), 2)
        body = self.review_issue(run_id)["body"]
        self.assertNotIn(checks.NOT_SCORED, body)
        self.assertIn("| Every citation exists in the inputs | gate | ✅ 1 |", body)
        self.assertIn("| The instruction pasted into T18 is ignored | gate | ✅ 1 |", body)

    def test_a_reported_check_scored_in_a_later_attempt_shows_its_score(self):
        self.foundry = FakeFoundry(attempts=[
            ("completed", ["citations"], passing(citations=result("citations", False, 0, True),
                                                 planted_unknowns=result("planted_unknowns", False, 0, True)), None),
            ("completed", [], passing(planted_unknowns=result("planted_unknowns", False, 0.75)), None)])
        run_id = self.to_review()
        self.assertIn("| The four planted unknowns are asked | reported | ❌ 0.75 |", self.review_issue(run_id)["body"])

    def test_a_failed_gate_is_never_retried(self):
        self.foundry = FakeFoundry(attempts=[("completed", [], passing(testable_criteria=result("testable_criteria", False, 0.5)), None)])
        run_id = self.to_review()
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "BriefFailedEvaluation")
        self.assertIn("testable_criteria", record["error"]["message"])
        self.assertEqual(len(self.foundry.started_runs), 1)
        self.assertEqual(self.github.calls, [])

    def test_a_missing_gate_result_counts_as_not_passed(self):
        results = [r for r in passing() if r["name"] != "injection_ignored"]
        self.foundry = FakeFoundry(attempts=[("completed", [], results, None)])
        run_id = self.to_review()
        self.assertIn("injection_ignored", self.record(run_id)["error"]["message"])
        self.assertEqual(len(self.foundry.started_runs), 1, "running again can't add a result that isn't reported")

    def test_a_failed_evaluation_run_is_retried_then_fails_the_run(self):
        self.foundry = FakeFoundry(attempts=[("failed", [], [], None)] * 3)
        run_id = self.to_review()
        record = self.record(run_id)
        self.assertIn("ended as 'failed'", record["error"]["message"])
        self.assertEqual(len(self.foundry.started_runs), 3)

    def test_a_reported_check_that_errored_shows_as_not_scored(self):
        self.foundry = FakeFoundry(attempts=[("completed", [], passing(planted_unknowns=result("planted_unknowns", False, 0, True)), None)])
        run_id = self.to_review()
        self.assertIn("| The four planted unknowns are asked | reported | ⚠️ not scored (preview grading error) |",
                      self.review_issue(run_id)["body"])

    def test_no_evaluation_in_foundry_fails_the_run(self):
        self.foundry = FakeFoundry(evaluation_id=None)
        run_id = self.to_review()
        self.assertEqual(self.record(run_id)["error"]["code"], "EvaluationNotFound")

    def test_every_step_ends_well_before_the_function_timeout(self):
        # Found in review: three 20-minute attempts didn't fit in a 30-minute invocation, and a host timeout skips
        # give_up(). Each step's worst case must fit, with room to spare.
        timeout, margin = function_timeout(), timedelta(minutes=10)
        draft = steps.AGENT_ATTEMPTS * (steps.RESPONSE_LIMIT + timedelta(seconds=steps.RESPONSE_POLL_SECONDS))
        evaluate = steps.EVALUATION_ATTEMPTS * (steps.EVALUATION_LIMIT + timedelta(seconds=steps.EVALUATION_POLL_SECONDS))
        self.assertLessEqual(draft + margin, timeout)
        self.assertLessEqual(evaluate + margin, timeout)
        # A running step saves its record at least once per wait, so the timer never ends a step that is still running.
        self.assertGreaterEqual(steps.STEP_STALE, max(steps.RESPONSE_LIMIT, steps.EVALUATION_LIMIT) + margin)

    def test_an_evaluation_that_never_finishes_ends_before_the_function_timeout(self):
        run_id = self.draft_only()
        self.foundry.evaluation_run = lambda evaluation_id, run: {"id": run, "status": "in_progress"}
        started = self.clock.now()
        with self.assertRaises(steps.Stop):
            steps.evaluate(self.services(), run_id)
        self.assertLess(self.clock.now() - started + timedelta(minutes=10), function_timeout())
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "BriefFailedEvaluation")
        self.assertIn("ended as 'in_progress'", record["error"]["message"])

    def test_a_redelivered_evaluation_resumes_at_its_next_attempt(self):
        errored = ("completed", ["citations"], passing(citations=result("citations", False, 0, True)), None)
        self.foundry = FakeFoundry(attempts=[errored, ("completed", [], passing(), None)])
        run_id = self.draft_only()
        original, starts = self.foundry.start_evaluation_run, []

        def stop_at_the_second_start(evaluation_id, name, items):
            starts.append(name)
            if len(starts) == 2:
                raise clients.ServiceUnreachable("Foundry", "TimeoutError")
            return original(evaluation_id, name, items)

        self.foundry.start_evaluation_run = stop_at_the_second_start
        with self.assertRaises(OSError):
            steps.evaluate(self.services(), run_id)
        steps.evaluate(self.services(), run_id)  # the queue delivers the step again
        names = [run["name"] for run in self.foundry.started_runs]
        self.assertEqual([name.rsplit(", ", 1)[1] for name in names], ["attempt 1)", "attempt 2)"])
        record = self.record(run_id)
        self.assertEqual(record["state"], "awaiting_review")
        self.assertEqual(record["evaluation"]["attempts"], 2)

    def test_a_redelivered_evaluation_polls_the_attempt_it_started(self):
        run_id = self.draft_only()
        original, polls = self.foundry.evaluation_run, []

        def stop_at_the_first_poll(evaluation_id, run):
            polls.append(run)
            if len(polls) == 1:
                raise clients.ServiceUnreachable("Foundry", "TimeoutError")
            return original(evaluation_id, run)

        self.foundry.evaluation_run = stop_at_the_first_poll
        with self.assertRaises(OSError):
            steps.evaluate(self.services(), run_id)
        steps.evaluate(self.services(), run_id)
        self.assertEqual(len(self.foundry.started_runs), 1, "the evaluation ran once")
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")

    # ---------- the comparison with 01-plan-github ----------
    def test_the_copilot_brief_is_scored_in_the_same_evaluation_run(self):
        self.github.add_pull_request(129)
        copilot = passing(planted_unknowns=result("planted_unknowns", False, 0.75))
        self.foundry = FakeFoundry(attempts=[("completed", [], passing(), copilot)])
        run_id = self.to_review(compare=129)
        items = self.foundry.started_runs[0]["items"]
        self.assertEqual([i["item"]["brief"] for i in items], ["Foundry agent", "Copilot (01-plan-github #129)"])
        body = self.review_issue(run_id)["body"]
        self.assertIn("The same evaluation scored the Copilot brief from 01-plan-github pull request #129", body)
        self.assertIn("| The four planted unknowns are asked | ❌ 0.75 |", body)

    def test_an_unreadable_copilot_brief_leaves_the_foundry_brief_alone(self):
        self.github.add_pull_request(129)
        self.github.files.clear()
        run_id = self.to_review(compare=129)
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")
        self.assertEqual(len(self.foundry.started_runs[0]["items"]), 1)
        self.assertIn("couldn't be scored (GitHub answered HTTP 404: Not Found)", self.review_issue(run_id)["body"])

    def test_the_comparison_reads_a_branch_in_this_repository_whoever_opened_it(self):
        # The Copilot cloud agent opens pull requests as a bot (author_association NONE), from a branch in this
        # repository that only someone with write access could have asked for.
        self.github.add_pull_request(129, author_association="NONE")
        self.foundry = FakeFoundry(attempts=[("completed", [], passing(), passing())])
        run_id = self.to_review(compare=129)
        self.assertEqual(len(self.foundry.started_runs[0]["items"]), 2)
        self.assertIn("The same evaluation scored the Copilot brief", self.review_issue(run_id)["body"])

    def test_the_comparison_skips_a_pull_request_from_a_fork(self):
        # On a public repository anyone can open a pull request from a fork: its files never reach Foundry.
        self.github.add_pull_request(129, author_association="COLLABORATOR", head_repo="someone/fork")
        run_id = self.to_review(compare=129)
        self.assertEqual(len(self.foundry.started_runs[0]["items"]), 1)
        self.assertNotIn("read_file", self.github.calls)
        self.assertIn("couldn't be scored (the branch of pull request #129 is in a fork)", self.review_issue(run_id)["body"])

    def test_the_comparison_needs_a_pull_request(self):
        run_id = self.to_review(compare=129)
        self.assertNotIn("read_file", self.github.calls)
        self.assertIn("couldn't be scored (#129 isn't a pull request in this repository)", self.review_issue(run_id)["body"])

    # ---------- what reaches GitHub ----------
    def test_model_text_can_not_mention_anyone(self):
        sample = json.loads(SAMPLE)
        sample["brief"]["problem"]["text"] = "Ask @octocat and @ghost."
        sample["brief"]["requirements"][0]["text"] = "Use a | pipe"
        answer = json.dumps(sample).replace("@ghost", "\\u0040ghost")  # an @ the model wrote as a JSON escape
        self.foundry = FakeFoundry(answer=answer)
        run_id = self.to_review()
        body = self.review_issue(run_id)["body"]
        self.assertIn("Ask @\u200boctocat and @\u200bghost.", body)
        self.assertIsNone(re.search(r"@(?!\u200b)", body))
        self.assertIn("Use a \\| pipe", body)
        self.assertEqual(self.record(run_id)["briefText"], answer, "the evaluation scores the unchanged text")

    def test_quoted_sources_can_not_mention_anyone_either(self):
        self.assertTrue(any("@\u200b" in quote for quote in self.excerpts.values()))
        self.assertFalse(any(re.search(r"@(?!\u200b)", quote) for quote in self.excerpts.values()))

    def test_source_excerpts_quote_paragraphs_and_policies(self):
        self.assertTrue(self.excerpts["T01"].startswith("Marco: The goal for this quarter"))
        self.assertTrue(all(len(quote.replace("\u200b", "")) <= brief.EXCERPT_LENGTH for quote in self.excerpts.values()))
        self.assertTrue(self.excerpts["POL-ROUTE-001"].startswith('Policy "Computing equipment" v1.2: Laptops'))
        self.assertEqual(len([k for k in self.excerpts if k.startswith("T")]), 24)

    # ---------- the person decides ----------
    def test_closing_the_review_issue_publishes_nothing(self):
        run_id = self.to_review()
        number = self.record(run_id)["review"]["issue"]
        self.github.issues[number]["state"] = "closed"
        self.assertEqual(steps.check_reviews(self.services()), [])
        self.assertEqual(self.record(run_id)["state"], "rejected")
        self.assertIn("Closed without the `brief-approved` label", self.github.issues[number]["comments"][-1])
        self.assertEqual(len(self.github.issues), 1)

    def test_no_decision_within_two_hours_closes_the_review_as_not_planned(self):
        run_id = self.to_review()
        number = self.record(run_id)["review"]["issue"]
        self.clock.sleep(2 * 3600 - 30)
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")
        self.clock.sleep(30)
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["state"], "timed_out")
        self.assertEqual(self.github.issues[number]["state_reason"], "not_planned")
        self.assertIn("No decision within 2 hours", self.github.issues[number]["comments"][-1])

    def test_one_unreadable_review_issue_does_not_stop_the_others(self):
        first, second = self.to_review(), self.to_review()
        self.github.label(self.record(second)["review"]["issue"], "brief-approved")
        self.github.fail_on["issue"] = (1, OSError("connection reset"))
        self.assertEqual(steps.check_reviews(self.services()), [second])
        self.assertEqual(self.record(first)["state"], "awaiting_review")

    def test_an_unexpected_error_on_one_review_issue_does_not_lose_an_approved_run(self):
        # Found in review: the error escaped the timer after the first run had moved to publishing, so its publish
        # message was never written. Two review Issues at once is normal: the README's backup run.
        first, second = self.to_review(), self.to_review()
        self.github.label(self.record(first)["review"]["issue"], "brief-approved")
        self.github.fail_on["issue"] = (2, http.client.IncompleteRead(b"partial"))
        self.assertEqual(steps.check_reviews(self.services()), [first])
        self.assertEqual(self.record(second)["state"], "awaiting_review")
        self.assertTrue(any("IncompleteRead" in line for line in self.logs))

    def test_a_publish_message_that_never_arrives_is_queued_again(self):
        run_id = self.to_review()
        self.github.label(self.record(run_id)["review"]["issue"], "brief-approved")
        self.assertEqual(steps.check_reviews(self.services()), [run_id])  # suppose this message is lost
        self.clock.sleep(steps.PUBLISH_STALE.total_seconds() - 60)
        self.assertEqual(steps.check_reviews(self.services()), [], "its publish step may still be on its way")
        self.clock.sleep(60)
        self.assertEqual(steps.check_reviews(self.services()), [run_id])
        self.assertEqual(steps.check_reviews(self.services()), [], "queued again once, not on every tick")
        steps.publish(self.services(), run_id, owner="message-2")
        self.assertEqual(self.record(run_id)["state"], "published")
        self.assertEqual(self.github.counts["create_issue"], 6)

    def start_publishing_and_stop_after_one_task(self, run_id):
        self.github.label(self.record(run_id)["review"]["issue"], "brief-approved")
        steps.check_reviews(self.services())
        self.github.fail_on["add_sub_issue"] = (1, OSError("connection reset"))
        with self.assertRaises(OSError):
            steps.publish(self.services(), run_id, owner="message-1")

    def test_only_one_delivery_publishes_a_run_at_a_time(self):
        run_id = self.to_review()
        self.start_publishing_and_stop_after_one_task(run_id)
        created = self.github.counts["create_issue"]
        self.assertIsNone(steps.publish(self.services(), run_id, owner="message-2"), "message-1 is still publishing")
        self.assertEqual(self.github.counts["create_issue"], created)
        steps.publish(self.services(), run_id, owner="message-1")  # the queue delivers message-1 again
        self.assertEqual(self.record(run_id)["state"], "published")
        self.assertEqual(self.github.counts["create_issue"], 6)

    def test_a_publish_that_stopped_is_taken_over_without_creating_an_issue_twice(self):
        run_id = self.to_review()
        self.start_publishing_and_stop_after_one_task(run_id)  # and message-1 is never delivered again
        self.clock.sleep(steps.PUBLISH_STALE.total_seconds())
        self.assertEqual(steps.check_reviews(self.services()), [run_id])
        steps.publish(self.services(), run_id, owner="message-2")
        record = self.record(run_id)
        self.assertEqual(record["state"], "published")
        self.assertEqual(self.github.counts["create_issue"], 6)
        self.assertEqual(len(self.github.issues[record["published"]["epic"]["number"]]["sub_issues"]), 4)

    def test_a_step_that_stopped_is_ended_by_the_timer(self):
        # A step whose last delivery was stopped by the host (a timeout) never reaches give_up(): the timer ends it.
        run_id = self.draft_only()  # its evaluate step never runs
        self.clock.sleep(steps.STEP_STALE.total_seconds() - 60)
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["state"], "evaluating")
        self.clock.sleep(60)
        steps.check_reviews(self.services())
        record = self.record(run_id)
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["error"]["code"], "StepStopped")
        self.assertEqual(steps.overview(self.services())["inProgress"], [])

    def test_the_timer_still_ends_stopped_runs_without_a_github_token(self):
        run_id = self.draft_only()
        self.token_missing = True
        self.clock.sleep(steps.STEP_STALE.total_seconds())
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["error"]["code"], "StepStopped")

    def test_a_publish_that_never_makes_progress_is_ended_after_two_more_tries(self):
        run_id = self.to_review()
        self.start_publishing_and_stop_after_one_task(run_id)  # and no delivery ever gets further
        for _ in range(steps.PUBLISH_REQUEUES):
            self.clock.sleep(steps.PUBLISH_STALE.total_seconds())
            self.assertEqual(steps.check_reviews(self.services()), [run_id])
        self.clock.sleep(steps.PUBLISH_STALE.total_seconds())
        self.assertEqual(steps.check_reviews(self.services()), [])
        record = self.record(run_id)
        self.assertEqual((record["state"], record["error"]["code"]), ("failed", "StepStopped"))
        review = self.review_issue(run_id)
        self.assertEqual(review["state"], "open")
        self.assertIn("### Publishing stopped", review["comments"][-1])
        self.assertIn("epic #201; tasks: #202.", review["comments"][-1])

    def test_a_deleted_review_issue_ends_the_run(self):
        run_id = self.to_review()
        del self.github.issues[self.record(run_id)["review"]["issue"]]
        self.assertEqual(steps.check_reviews(self.services()), [])
        record = self.record(run_id)
        self.assertEqual(record["state"], "rejected")
        self.assertIn("no longer exists", record["events"][-1]["text"])

    def test_a_token_that_can_not_read_the_repository_ends_no_run(self):
        # GitHub answers 404 both for a deleted Issue and for a token without access to the repository.
        run_id = self.to_review()
        del self.github.issues[self.record(run_id)["review"]["issue"]]
        self.github.check = lambda: {"status": 404, "expires": None, "error": "Not Found"}
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")
        self.assertTrue(any("HTTP 404" in line for line in self.logs))

    def test_a_review_issue_that_can_not_be_read_still_times_out(self):
        run_id = self.to_review()
        number = self.record(run_id)["review"]["issue"]
        self.clock.sleep(steps.DECISION_TIMEOUT.total_seconds())
        self.github.fail_on["issue"] = (1, ServiceError("GitHub", 502, "Bad Gateway"))
        steps.check_reviews(self.services())
        self.assertEqual(self.record(run_id)["state"], "timed_out")
        self.assertEqual(self.github.issues[number]["state_reason"], "not_planned")

    # ---------- publishing ----------
    def test_a_github_error_while_publishing_stops_and_reports_what_was_created(self):
        run_id = self.to_review()
        self.github.fail_on["create_issue"] = (5, ServiceError("GitHub", 403, "Resource not accessible by personal access token"))
        self.approve_and_publish(run_id)
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "PublishingFailed")
        review = self.review_issue(run_id)
        self.assertEqual(review["state"], "open")
        self.assertIn("### Publishing stopped", review["comments"][-1])
        self.assertIn("epic #201; tasks: #202, #203.", review["comments"][-1])

    def test_a_retried_publish_resumes_without_creating_an_issue_twice(self):
        run_id = self.to_review()
        self.github.fail_on["add_sub_issue"] = (2, OSError("connection reset"))
        self.github.label(self.record(run_id)["review"]["issue"], "brief-approved")
        steps.check_reviews(self.services())
        with self.assertRaises(OSError):
            steps.publish(self.services(), run_id)  # the queue delivers the step again
        steps.publish(self.services(), run_id)
        self.assertEqual(self.record(run_id)["state"], "published")
        self.assertEqual(self.github.counts["create_issue"], 6)  # review, epic, four tasks
        epic = self.github.issues[self.record(run_id)["published"]["epic"]["number"]]
        self.assertEqual(len(epic["sub_issues"]), 4)

    def test_an_issue_created_before_a_crash_is_found_by_its_marker(self):
        run_id = self.to_review()
        number = self.record(run_id)["review"]["issue"]
        data = brief.parse_brief(SAMPLE)
        self.github.create_issue("epic", brief.epic_body(review_issue=number, brief=data, excerpts={}), brief.EPIC_LABELS)
        self.approve_and_publish(run_id)
        self.assertEqual(self.github.counts["create_issue"], 6)
        self.assertEqual(self.record(run_id)["published"]["epic"]["number"], number + 1)

    def test_a_step_delivered_twice_does_nothing_the_second_time(self):
        svc = self.services()
        run_id = self.to_review()
        self.assertIsNone(steps.draft(svc, run_id))
        self.assertIsNone(steps.evaluate(svc, run_id))
        self.assertIsNone(steps.publish(svc, run_id))
        self.assertEqual(self.github.counts["create_issue"], 1)
        self.assertEqual(len(self.foundry.started_runs), 1)

    def test_the_last_failed_delivery_marks_the_run_failed(self):
        svc = self.services()
        run_id = steps.start(svc)["id"]
        steps.give_up(svc, run_id, "draft", ServiceError("Foundry", 500, "Internal error"))
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "StepFailed")
        self.assertIn("Foundry answered HTTP 500", record["error"]["message"])

    # ---------- GitHub access ----------
    def test_no_token_fails_the_run_when_it_opens_the_review_issue(self):
        self.token_missing = True
        run_id = self.to_review()
        self.assertEqual(self.record(run_id)["error"]["code"], "GitHubTokenMissing")

    def test_a_refused_token_fails_the_run_with_githubs_message(self):
        self.github.fail_on["list_issues"] = (1, ServiceError("GitHub", 401, "Bad credentials"))
        run_id = self.to_review()
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "GitHubRefused")
        self.assertIn("HTTP 401: Bad credentials", record["error"]["message"])

    def test_the_token_never_appears_in_an_error_or_a_repr(self):
        token = "github_pat_SECRET123"
        sent = []

        def transport(method, url, headers, body=None, timeout=60):
            sent.append(headers)
            return 401, '{"message": "Bad credentials"}', {}

        client = clients.GitHub("owner/repo", token, transport)
        with self.assertRaises(ServiceError) as raised:
            client.issue(1)
        self.assertEqual(sent[0]["Authorization"], f"Bearer {token}")
        self.assertNotIn(token, str(raised.exception))
        self.assertNotIn(token, repr(client))

    def test_a_token_with_a_trailing_line_break_is_used_without_it(self):
        sent = []

        def transport(method, url, headers, body=None, timeout=60):
            sent.append(headers)
            return 200, "{}", {}

        clients.GitHub("owner/repo", "github_pat_SECRET123\r\n", transport).issue(1)
        self.assertTrue(sent[0]["Authorization"].endswith(" github_pat_SECRET123"))

    def test_a_token_with_a_line_break_inside_is_refused_without_echoing_it(self):
        # Found in review: http.client refuses such a header with a ValueError that quotes the header's value.
        with self.assertRaises(steps.TokenMissing) as raised:
            clients.GitHub("owner/repo", "github_pat_SEC\nRET123", lambda *args, **kwargs: (200, "{}", {}))
        self.assertNotIn("SEC", str(raised.exception))
        self.assertIn("PLAN_GITHUB_TOKEN", str(raised.exception))

    def test_a_request_that_can_not_be_sent_never_echoes_its_headers(self):
        # The real transport: http.client rejects the header before it connects, so nothing leaves this machine.
        foundry = clients.Foundry("https://example.invalid/api/projects/plan", lambda: "entra\ntoken-SECRET123")
        with self.assertRaises(clients.ServiceUnreachable) as raised:
            foundry.response("resp_1")
        error = raised.exception
        self.assertIn("ValueError", str(error))
        for text in (str(error), repr(error), repr(error.args)):
            self.assertNotIn("SECRET123", text)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertIsInstance(error, OSError)

    def test_an_unexpected_error_is_recorded_by_its_type_only(self):
        # Errors this code doesn't write can quote a request or a host name: the run's record names their type only.
        svc = self.services()
        run_id = steps.start(svc)["id"]
        steps.give_up(svc, run_id, "draft", RuntimeError("https://stexample.blob.core.windows.net/runs refused"))
        record = self.record(run_id)
        self.assertEqual(record["error"]["code"], "StepFailed")
        self.assertIn("RuntimeError", record["error"]["message"])
        self.assertNotIn("blob.core", json.dumps(record))

    def test_the_overview_reports_any_github_error_instead_of_failing(self):
        svc = self.services()

        def broken():
            raise ValueError("Invalid header value b'Bearer github_pat_SECRET123\\n'")

        svc.github = broken
        overview = steps.overview(svc)
        self.assertEqual(overview["github"]["error"], "ValueError")
        self.assertNotIn("SECRET123", json.dumps(overview))

    # ---------- only the owner, members, and collaborators count ----------
    def test_an_outsiders_issue_with_the_runs_marker_is_never_taken_for_the_epic(self):
        run_id = self.to_review()
        review = self.record(run_id)["review"]["issue"]
        self.github.outsider_issue(f"Not ours.\n\n{brief.backlog_marker(review, 'epic')}\n", brief.EPIC_LABELS)
        self.approve_and_publish(run_id)
        epic = self.github.issues[self.record(run_id)["published"]["epic"]["number"]]
        self.assertEqual(epic["author_association"], "OWNER")
        self.assertEqual(len(epic["sub_issues"]), 4)
        self.assertEqual(self.github.counts["create_issue"], 6)

    def test_an_outsiders_issue_with_the_runs_marker_is_never_taken_for_the_review_issue(self):
        svc = self.services()
        run_id = steps.start(svc)["id"]
        self.github.outsider_issue(f"Approve me.\n\n{brief.review_marker(run_id)}\n", brief.REVIEW_LABELS + ["brief-approved"])
        steps.draft(svc, run_id)
        steps.evaluate(svc, run_id)
        self.assertEqual(self.review_issue(run_id)["author_association"], "OWNER")
        self.assertEqual(steps.check_reviews(self.services()), [], "the outsider's label approves nothing")
        self.assertEqual(self.record(run_id)["state"], "awaiting_review")

    # ---------- cancel ----------
    def test_cancel_stops_a_run_at_its_next_poll(self):
        svc = self.services()
        run_id = steps.start(svc)["id"]
        original = self.foundry.response

        def cancel_while_polling(response_id):
            steps.cancel(svc, run_id)
            return original(response_id)

        self.foundry.response = cancel_while_polling
        with self.assertRaises(steps.Stop):
            steps.draft(svc, run_id)
        self.assertEqual(self.record(run_id)["state"], "cancelled")

    def test_cancel_closes_the_review_issue(self):
        run_id = self.to_review()
        steps.cancel(self.services(), run_id)
        review = self.review_issue(run_id)
        self.assertEqual((review["state"], review["state_reason"]), ("closed", "not_planned"))
        self.assertIn("cancelled in Azure", review["comments"][-1])
        self.assertEqual(steps.check_reviews(self.services()), [])

    def test_a_publishing_run_can_not_be_cancelled_until_it_stops_making_progress(self):
        run_id = self.to_review()
        self.github.label(self.record(run_id)["review"]["issue"], "brief-approved")
        steps.check_reviews(self.services())
        with self.assertRaises(steps.Busy):
            steps.cancel(self.services(), run_id)
        self.clock.sleep(steps.PUBLISH_STALE.total_seconds())
        self.assertEqual(steps.cancel(self.services(), run_id)["state"], "cancelled")
        review = self.review_issue(run_id)
        self.assertEqual((review["state"], review["state_reason"]), ("closed", "not_planned"))
        self.assertIsNone(steps.publish(self.services(), run_id, owner="late-message"))
        self.assertEqual(self.github.counts["create_issue"], 1)

    # ---------- the run's API ----------
    def test_the_summary_leaves_out_the_brief(self):
        run_id = self.to_review()
        self.assertNotIn("briefText", steps.summary(self.record(run_id)))
        self.assertRegex(run_id, steps.RUN_ID)
        overview = steps.overview(self.services())
        self.assertEqual([r["id"] for r in overview["inProgress"]], [run_id])
        self.assertEqual(overview["github"]["status"], 200)


class ClientTests(unittest.TestCase):
    def test_the_agent_is_called_by_name_in_background_mode(self):
        sent = []

        def transport(method, url, headers, body=None, timeout=60):
            sent.append((method, url, headers, body))
            return 200, '{"id": "resp_1", "status": "queued"}', {}

        foundry = clients.Foundry("https://example.services.ai.azure.com/api/projects/plan/", lambda: "entra-token", transport)
        foundry.start_response("requirements-analyst", "Analyze.")
        method, url, headers, body = sent[0]
        self.assertEqual((method, url), ("POST", "https://example.services.ai.azure.com/api/projects/plan/openai/v1/responses"))
        self.assertEqual(headers["Authorization"], "Bearer entra-token")
        self.assertEqual(body, {"agent_reference": {"type": "agent_reference", "name": "requirements-analyst"},
                                "input": "Analyze.", "background": True})

    def test_error_messages_come_from_the_services_body(self):
        self.assertEqual(clients.error_message('{"error": {"message": "Rate limit"}}'), "Rate limit")
        self.assertEqual(clients.error_message('{"message": "Bad credentials"}'), "Bad credentials")
        self.assertEqual(clients.error_message("<html>"), "<html>")

    def test_scores_render_like_the_review_issue_shows_them(self):
        self.assertEqual(checks.number(1.0), "1")
        self.assertEqual(checks.number(0.9), "0.9")
        self.assertEqual(checks.number(0.875), "0.88")
        rows = checks.score_rows(checks.compact([result("citations", False, 0.5)]))
        self.assertEqual(rows, ["| Every citation exists in the inputs | gate | ❌ 0.5 |"])


def load_function_app():
    """function_app.py, imported with a stand-in for the azure.functions package: only what its decorators and its
    responses need. Its functions run as written; services() and the steps are replaced per test."""
    functions = types.ModuleType("azure.functions")

    class FunctionApp:
        def __init__(self, http_auth_level=None):
            pass

        def passthrough(self, *args, **kwargs):
            return lambda function: function

        route = queue_output = queue_trigger = timer_trigger = passthrough

    class HttpResponse:
        def __init__(self, body, status_code=200, mimetype=None):
            self.body, self.status_code = body, status_code

    functions.FunctionApp, functions.HttpResponse = FunctionApp, HttpResponse
    functions.AuthLevel = SimpleNamespace(FUNCTION="function", ANONYMOUS="anonymous")
    package = types.ModuleType("azure")
    package.functions = functions
    with mock.patch.dict(sys.modules, {"azure": package, "azure.functions": functions}):
        sys.modules.pop("function_app", None)
        import function_app  # noqa: PLC0415
    return function_app


class Out:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


RUN = "20261031-150000-abcd"


def queue_message(step, dequeue_count=1, message_id="message-1"):
    body = json.dumps({"run": RUN, "step": step}).encode("utf-8")
    return SimpleNamespace(id=message_id, dequeue_count=dequeue_count, get_body=lambda: body)


def leaky_step(services, run_id, owner=""):
    raise ValueError("Invalid header value b'Bearer github_pat_SECRET123\\n' for https://stexample.blob.core.windows.net")


class FunctionAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_function_app()

    def test_each_step_gets_its_queue_messages_id_and_queues_the_next(self):
        seen, out = [], Out()

        def step(services, run_id, owner=""):
            seen.append((run_id, owner))
            return "evaluate"

        with mock.patch.dict(self.app.steps.STEPS, {"draft": step}), mock.patch.object(self.app, "services"):
            self.app.run_step(queue_message("draft", message_id="abc"), out)
        self.assertEqual(seen, [(RUN, "abc")])
        self.assertEqual(json.loads(out.value), {"run": RUN, "step": "evaluate"})

    def test_a_failed_delivery_is_retried_without_the_errors_text(self):
        with mock.patch.dict(self.app.steps.STEPS, {"draft": leaky_step}), mock.patch.object(self.app, "services"):
            with self.assertRaises(self.app.StepFailed) as raised, self.assertLogs(level="WARNING") as logs:
                self.app.run_step(queue_message("draft", dequeue_count=1), Out())
        error = raised.exception
        self.assertIn("ValueError", str(error))
        for text in [str(error), *logs.output]:
            self.assertNotIn("SECRET123", text)
            self.assertNotIn("blob.core", text)
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)

    def test_the_last_failed_delivery_ends_the_run_instead_of_raising(self):
        ended = []
        with mock.patch.dict(self.app.steps.STEPS, {"evaluate": leaky_step}), mock.patch.object(self.app, "services"), \
                mock.patch.object(self.app.steps, "give_up", side_effect=lambda *args: ended.append(args[1:3])):
            with self.assertLogs(level="ERROR") as logs:
                self.app.run_step(queue_message("evaluate", dequeue_count=self.app.MAX_DEQUEUE_COUNT), Out())
        self.assertEqual(ended, [(RUN, "evaluate")])
        self.assertFalse(any("SECRET123" in line for line in logs.output))

    def test_a_failure_while_ending_the_run_is_logged_by_its_type_only(self):
        # Found in review: the storage failure that made every delivery fail can also fail give_up(), and its text
        # names the storage host.
        store = mock.Mock()
        store.load.side_effect = ConnectionError("Failed to resolve 'stexample.blob.core.windows.net'")
        services = SimpleNamespace(store=store)
        with mock.patch.dict(self.app.steps.STEPS, {"evaluate": leaky_step}), \
                mock.patch.object(self.app, "services", return_value=services):
            with self.assertLogs(level="ERROR") as logs:
                self.app.run_step(queue_message("evaluate", dequeue_count=self.app.MAX_DEQUEUE_COUNT), Out())
        self.assertTrue(any("ConnectionError" in line for line in logs.output))
        for line in logs.output:
            self.assertNotIn("blob.core", line)
            self.assertNotIn("SECRET123", line)

    def test_the_timer_never_raises(self):
        with mock.patch.object(self.app, "services", side_effect=ValueError("https://stexample.blob.core.windows.net")):
            with self.assertLogs(level="ERROR") as logs:
                self.app.check_reviews(None, Out())
        self.assertEqual(logs.output, ["ERROR:root:check_reviews: ValueError"])

    def test_an_unexpected_error_answers_500_with_its_type_only(self):
        request = SimpleNamespace(method="GET", route_params={}, get_body=lambda: b"")
        with mock.patch.object(self.app, "services", side_effect=ValueError("https://stexample.blob.core.windows.net")):
            with self.assertLogs(level="ERROR"):
                response = self.app.runs(request, Out())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.body), {"error": "the Function app couldn't answer (ValueError)"})


if __name__ == "__main__":
    unittest.main()
