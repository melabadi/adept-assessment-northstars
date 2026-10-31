"""Offline tests for the Test · Microsoft solution's reporting function. No Azure or GitHub access is needed.

They port the checks that proved the Logic App this function replaces, and add the function's own:
  - the report: the same Markdown the Logic App's KQL wrote for Issue #180 (plus the sampling note), and the six
    verdicts (accepted, warning, expected-failure, regression, no-telemetry, no-verdict);
  - replay protection: a notification without a run id, an unknown run, another test's run, and a run that ended more
    than an hour ago never reach the queue;
  - the waits: a run without a verdict and incomplete telemetry come back later through the queue, with a delay, and
    stop after a bounded number of checks;
  - GitHub: only this test's open Issue counts (full title prefix, pull requests skipped); a failing run opens or
    comments; only an accepted run that started after the Issue opened closes it; a repeated delivery changes nothing;
    one report posts at a time; and the token never appears in a log or an error;
  - the Function's bindings: a function key on the HTTP route, written with the action group's copy in one deployment,
    the queue name Bicep creates, and a GitHub token that only Key Vault holds (read with the function's identity, and
    never by the HTTP route).
The runs and Issues below are fixtures (numbers from the live run of 2026-10-30); the live demo never uses them.

Run from this folder (azd runs them before every deploy):
  python -m unittest -v test_reporter
"""
from __future__ import annotations

import ast
import json
import logging
import re
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "function"))
from reporter import flow, issues, report, services  # noqa: E402

TEST_ID = "requesthub-journey"
GROUP = "rg-ai-sdlc-test"
TOKEN = "github_pat_fixture_never_logged_0123456789"
SETTINGS = flow.Settings(test_id=TEST_ID, resource_group=GROUP)
NOW = datetime(2026, 10, 30, 18, 44, 12, tzinfo=timezone.utc)


def criterion(request, aggregate, metric, value, actual, result):
    return {"clientMetric": metric, "aggregate": aggregate, "condition": ">", "requestName": request, "value": value,
            "action": "continue", "actualValue": actual, "result": result}


def stats(count, p50, p95, p99):
    return {"sampleCount": float(count), "errorCount": 0.0, "errorPct": 0.0, "medianResTime": float(p50),
            "pct1ResTime": float(p95), "pct2ResTime": float(p95), "pct3ResTime": float(p99)}


def slowdown_run(**overrides) -> dict:
    """The "After the slowdown" run of 2026-10-30, as Azure Load Testing returns it (trimmed)."""
    run = {
        "testRunId": "slowdown-20261030-183250", "testId": TEST_ID, "displayName": "After the slowdown",
        "status": "DONE", "testResult": "FAILED", "startDateTime": "2026-10-30T18:36:00Z",
        "endDateTime": "2026-10-30T18:37:59Z", "virtualUsers": 10, "duration": 119000,
        "passFailCriteria": {"passFailMetrics": {
            "c1": criterion("decide", "p95", "response_time_ms", 1500.0, 107.0, "passed"),
            "c2": criterion(None, "percentage", "error", 1.0, 0.0, "passed"),
            "c3": criterion("team-queue", "p95", "response_time_ms", 1000.0, 1580.0, "failed"),
            "c4": criterion("my-requests", "p95", "response_time_ms", 1000.0, 1570.0, "failed"),
            "c5": criterion("submit", "p95", "response_time_ms", 1500.0, 106.0, "passed"),
        }},
        "testRunStatistics": {
            "my-requests": stats(99, 1510, 1570, 1730), "submit": stats(100, 35, 106, 187),
            "open-request": stats(197, 18, 94, 107), "denied-other-department": stats(20, 19, 91, 94),
            "denied-invalid-token": stats(20, 5, 95, 272), "team-queue": stats(99, 1510, 1580, 1810),
            "Total": stats(579, 34, 1520, 1580), "decide": stats(44, 25, 107, 300),
        },
    }
    run.update(overrides)
    return run


def fix_run(**overrides) -> dict:
    """The "After the fix" run that closed Issue #180."""
    run = slowdown_run(
        testRunId="fix-20261030-185145", displayName="After the fix", testResult="PASSED",
        startDateTime="2026-10-30T18:54:30Z", endDateTime="2026-10-30T18:56:30Z", duration=120000)
    run["passFailCriteria"] = {"passFailMetrics": {
        "c1": criterion("decide", "p95", "response_time_ms", 1500.0, 111.0, "passed"),
        "c2": criterion(None, "percentage", "error", 1.0, 0.0, "passed"),
        "c3": criterion("team-queue", "p95", "response_time_ms", 1000.0, 81.0, "passed"),
        "c4": criterion("my-requests", "p95", "response_time_ms", 1000.0, 84.0, "passed"),
        "c5": criterion("submit", "p95", "response_time_ms", 1500.0, 172.0, "passed"),
    }}
    run["testRunStatistics"] = {
        "decide": stats(41, 24, 111, 284), "denied-invalid-token": stats(20, 5, 289, 290),
        "denied-other-department": stats(20, 17, 108, 182), "my-requests": stats(100, 11, 84, 96),
        "open-request": stats(198, 16, 93, 105), "submit": stats(100, 31, 172, 380), "team-queue": stats(100, 14, 81, 87),
        "Total": stats(579, 16, 97, 276),
    }
    run.update(overrides)
    return run


def row(name, requests, errors, denied, p95, delayed, newest="2026-10-30T18:37:58.9Z"):
    return {"Name": name, "requests": requests, "server_errors": errors, "denied": denied, "p95": p95,
            "delayed": delayed, "newest": newest}


SLOWDOWN_ROWS = [
    row("POST /api/requests/{id}/decisions", 39, 0, 0, 105.2, 0),
    row("GET /api/requests", 151, 0, 0, 1537.3, 151),
    row("POST /api/requests", 93, 0, 0, 79.4, 0),
    row("GET /api/requests/{id}", 172, 0, 9, 32.1, 0),
]
FIX_ROWS = [
    row("GET /api/requests", 161, 0, 0, 39.0, 0, "2026-10-30T18:56:29Z"),
    row("GET /api/requests/{id}", 152, 0, 12, 58.0, 0, "2026-10-30T18:56:29Z"),
    row("POST /api/admin/load-test/cleanup", 1, 0, 0, 556.0, 0, "2026-10-30T18:56:29Z"),
    row("POST /api/requests", 94, 0, 0, 104.0, 0, "2026-10-30T18:56:29Z"),
    row("POST /api/requests/{id}/decisions", 26, 0, 0, 75.0, 0, "2026-10-30T18:56:29Z"),
]

# Issue #180's report, written by the Logic App's KQL on 2026-10-30, with the sampling note this function adds.
SLOWDOWN_REPORT = """## Load test: After the slowdown

**FAILED** · test `requesthub-journey` · 10 virtual users · 119 s

**Expected failure:** the API ran with the rehearsal slowdown (151 server requests carried `requesthub.fault.queue_delay_ms`), and the criteria caught it. This run proves the gate works; it is not an acceptance run.

### Pass/fail criteria

| Criterion | Fails when | Actual | Result |
|---|---|---|---|
| all requests percentage(error) | > 1% | 0% | passed |
| decide p95(response_time_ms) | > 1,500 ms | 107 ms | passed |
| my-requests p95(response_time_ms) | > 1,000 ms | 1,570 ms | failed |
| submit p95(response_time_ms) | > 1,500 ms | 106 ms | passed |
| team-queue p95(response_time_ms) | > 1,000 ms | 1,580 ms | failed |

### Client side (Azure Load Testing)

| Request | Requests | Errors | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| decide | 44 | 0.0% | 25 | 107 | 300 |
| denied-invalid-token | 20 | 0.0% | 5 | 95 | 272 |
| denied-other-department | 20 | 0.0% | 19 | 91 | 94 |
| my-requests | 99 | 0.0% | 1,510 | 1,570 | 1,730 |
| open-request | 197 | 0.0% | 18 | 94 | 107 |
| submit | 100 | 0.0% | 35 | 106 | 187 |
| team-queue | 99 | 0.0% | 1,510 | 1,580 | 1,810 |
| Total | 579 | 0.0% | 34 | 1,520 | 1,580 |

### Server side (Application Insights, same window)

| Operation | Requests | Server errors | Denied (401/403) | p95 ms | With injected delay |
|---|---|---|---|---|---|
| GET /api/requests | 151 | 0 | 0 | 1,537 | 151 |
| GET /api/requests/{id} | 172 | 0 | 9 | 32 | 0 |
| POST /api/requests | 93 | 0 | 0 | 79 | 0 |
| POST /api/requests/{id}/decisions | 39 | 0 | 0 | 105 | 0 |

Application Insights keeps only a sample of the API's requests under load, so these counts can be lower than the client's.

Open the run in the Azure portal for client and server metrics side by side, and its AI insights: resource group `rg-ai-sdlc-test` › the Load Testing resource › Tests › `requesthub-journey` › `After the slowdown`."""


# ---------- fakes ----------

class FakeRuns:
    def __init__(self, *runs):
        self.runs = {run["testRunId"]: run for run in runs}
        self.reads = []

    def get(self, test_run_id):
        self.reads.append(test_run_id)
        run = self.runs.get(test_run_id)
        return None if run is None else {key: value for key, value in run.items() if key != "testRunId"} | {"testRunId": test_run_id}


class FakeTelemetry:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def server_rows(self, started, ended):
        self.queries.append((started, ended))
        return [dict(r) for r in self.rows]


class FakeQueue:
    def __init__(self):
        self.sent = []

    def send(self, message, delay):
        self.sent.append((json.loads(json.dumps(message)), delay))


class FakeLease:
    def __init__(self, lock):
        self.lock = lock

    def release(self):
        self.lock.held = False
        self.lock.released += 1


class FakeLock:
    def __init__(self, busy=False):
        self.held, self.released, self.busy = False, 0, busy

    def acquire(self):
        if self.busy or self.held:
            return None
        self.held = True
        return FakeLease(self)


class FakeGitHub:
    def __init__(self, open_issues=None, comments=None):
        self.issues = list(open_issues or [])
        self.comments_by_issue = {key: list(value) for key, value in (comments or {}).items()}
        self.calls = []
        self.next_number = 200

    def open_issues(self, label):
        self.calls.append(("list", label))
        return [dict(issue) for issue in self.issues if issue.get("state", "open") == "open"]

    def comments(self, number, since=None):
        self.calls.append(("comments", number, since))
        return list(self.comments_by_issue.get(number, []))

    def create_issue(self, title, body, labels):
        self.calls.append(("create", title, body, labels))
        issue = {"number": self.next_number, "title": title, "body": body, "created_at": "2026-10-30T18:44:19Z",
                 "labels": labels, "state": "open"}
        self.issues.append(issue)
        self.next_number += 1
        return issue

    def comment(self, number, body):
        self.calls.append(("comment", number, body))
        self.comments_by_issue.setdefault(number, []).append({"body": body})
        return {"body": body}

    def close(self, number):
        self.calls.append(("close", number))
        for issue in self.issues:
            if issue["number"] == number:
                issue["state"] = "closed"
        return {"number": number, "state": "closed"}

    def writes(self):
        return [call for call in self.calls if call[0] in ("create", "comment", "close")]


def wire(runs=(), rows=SLOWDOWN_ROWS, github=None, lock=None):
    return SimpleNamespace(runs=FakeRuns(*runs), telemetry=FakeTelemetry(rows), queue=FakeQueue(),
                           lock=lock or FakeLock(), github=github)


def message(test_run_id, phase="verdict", checks=0) -> bytes:
    return json.dumps({"testRunId": test_run_id, "phase": phase, "checks": checks}).encode()


def notification(test_run_id, nested=True) -> bytes:
    context = {"testRunId": test_run_id, "testRunStatus": "DONE"}
    body = {"data": {"data": {"alertContext": context}}} if nested else {"data": {"alertContext": context}}
    return json.dumps(body).encode()


# ---------- the report ----------

class ReportTests(unittest.TestCase):
    def test_the_report_is_the_logic_apps_report_with_the_sampling_note(self):
        verdict = report.outcome("FAILED", SLOWDOWN_ROWS)
        self.assertEqual(verdict, "expected-failure")
        self.assertEqual(report.render(slowdown_run(), SLOWDOWN_ROWS, verdict, GROUP), SLOWDOWN_REPORT)

    def test_the_passing_report_matches_the_comment_that_closed_issue_180(self):
        text = report.render(fix_run(), FIX_ROWS, report.outcome("PASSED", FIX_ROWS), GROUP)
        self.assertIn("**Accepted:** the journey met every criterion, and no server request carried the rehearsal "
                      "slowdown.", text)
        self.assertIn("| POST /api/admin/load-test/cleanup | 1 | 0 | 0 | 556 | 0 |", text)
        self.assertIn("| Total | 579 | 0.0% | 16 | 97 | 276 |", text)
        self.assertTrue(text.startswith("## Load test: After the fix\n\n**PASSED** · test `requesthub-journey` · "
                                        "10 virtual users · 120 s\n\n"))

    def test_six_verdicts(self):
        delayed = [row("GET /api/requests", 10, 0, 0, 1500, 10)]
        clean = [row("GET /api/requests", 10, 0, 0, 20, 0)]
        self.assertEqual(report.outcome("PASSED", clean), "accepted")
        self.assertEqual(report.outcome("PASSED", delayed), "warning")
        self.assertEqual(report.outcome("FAILED", delayed), "expected-failure")
        self.assertEqual(report.outcome("FAILED", clean), "regression")
        self.assertEqual(report.outcome("FAILED", []), "no-telemetry")
        self.assertEqual(report.outcome("PASSED", []), "no-telemetry")
        self.assertEqual(report.outcome("NOT_APPLICABLE", delayed), "no-verdict")
        self.assertEqual(report.outcome(None, clean), "no-verdict")

    def test_each_verdict_has_its_text(self):
        for verdict in ("accepted", "warning", "expected-failure", "regression", "no-telemetry", "no-verdict"):
            rows = [] if verdict == "no-telemetry" else SLOWDOWN_ROWS
            result = "NOT_APPLICABLE" if verdict == "no-verdict" else "FAILED"
            text = report.render(slowdown_run(testResult=result), rows, verdict, GROUP)
            self.assertIn(report.VERDICTS[verdict].format(delayed=0 if not rows else 151, result=result), text)
        empty = report.render(slowdown_run(), [], "no-telemetry", GROUP)
        self.assertIn("No server-side telemetry for this window yet.", empty)
        self.assertNotIn(report.SAMPLING_NOTE, empty)
        self.assertIn("**NOT_APPLICABLE:** the run did not produce a verdict.",
                      report.render(slowdown_run(testResult="NOT_APPLICABLE"), [], "no-verdict", GROUP))

    def test_no_report_text_names_the_logic_app(self):
        self.assertNotIn("Logic App", " ".join(report.VERDICTS.values()))

    def test_numbers_round_like_the_kql_did(self):
        self.assertEqual(report.whole_ms(1560.4), "1,560")
        self.assertEqual(report.whole_ms(1559.5), "1,560")
        self.assertEqual(report.whole_ms(999.5), "1,000")
        self.assertEqual(report.whole_ms(0), "0")
        self.assertEqual(report.whole_ms(None), "")
        self.assertEqual(report.one_decimal(0), "0.0")
        self.assertEqual(report.one_decimal(1.25), "1.3")

    def test_the_query_gets_checked_times_only(self):
        query = report.server_query(datetime(2026, 10, 30, 18, 36, tzinfo=timezone.utc),
                                    report.parse_time("2026-10-30T20:37:59+02:00"))
        self.assertIn("let started = datetime(2026-10-30T18:36:00.000000Z);", query)
        self.assertIn("let ended = datetime(2026-10-30T18:37:59.000000Z);", query)
        self.assertNotIn("__", query)
        self.assertIn("sum(ItemCount)", query)
        self.assertIn("percentilew(DurationMs, ItemCount, 95)", query)

    def test_times_from_azure_and_github_parse(self):
        self.assertEqual(report.parse_time("2026-10-30T18:37:58.1234567Z"),
                         datetime(2026, 10, 30, 18, 37, 58, 123456, tzinfo=timezone.utc))
        self.assertEqual(report.parse_time("2026-10-30T18:44:19Z"), datetime(2026, 10, 30, 18, 44, 19, tzinfo=timezone.utc))
        self.assertIsNone(report.parse_time("not a time"))
        self.assertIsNone(report.parse_time(None))

    def test_the_telemetry_is_ready_once_it_reaches_the_runs_last_90_seconds(self):
        ended = report.parse_time("2026-10-30T18:37:59Z")
        self.assertTrue(report.telemetry_ready(SLOWDOWN_ROWS, ended))
        self.assertTrue(report.telemetry_ready([row("x", 1, 0, 0, 1, 0, "2026-10-30T18:36:30Z")], ended))
        self.assertFalse(report.telemetry_ready([row("x", 1, 0, 0, 1, 0, "2026-10-30T18:36:28Z")], ended))
        self.assertFalse(report.telemetry_ready([], ended))


# ---------- replay protection (the HTTP route) ----------

class AcceptTests(unittest.TestCase):
    def accept(self, body, *runs, now=NOW):
        services = wire(runs)
        with self.assertLogs("reporter", level="INFO"):
            answer = flow.accept(body, services, SETTINGS, now)
        return answer, services

    def test_a_run_that_just_ended_is_queued_at_once(self):
        for nested in (True, False):
            answer, services = self.accept(notification("slowdown-20261030-183250", nested), slowdown_run())
            self.assertEqual(answer.status, 202)
            self.assertEqual(services.queue.sent,
                             [({"testRunId": "slowdown-20261030-183250", "phase": "verdict", "checks": 0}, 0)])

    def test_a_notification_without_a_run_id_stops_at_once(self):
        for body in (b"{}", b'{"data": {}}', b"[]", b'{"data": {"alertContext": {"testRunId": 7}}}'):
            answer, services = self.accept(body)
            self.assertEqual(answer.status, 400)
            self.assertEqual(services.runs.reads, [])
            self.assertEqual(services.queue.sent, [])

    def test_a_body_that_is_not_json_or_an_invalid_id_is_refused(self):
        self.assertEqual(self.accept(b"not json")[0].status, 400)
        answer, services = self.accept(notification("../test-runs/x?y=1"))
        self.assertEqual(answer.status, 400)
        self.assertEqual(services.runs.reads, [])

    def test_an_unknown_run_is_refused(self):
        answer, services = self.accept(notification("no-such-run"))
        self.assertEqual(answer.status, 404)
        self.assertEqual(services.queue.sent, [])

    def test_another_tests_run_is_refused(self):
        answer, services = self.accept(notification("other-run"), slowdown_run(testRunId="other-run", testId="another-test"))
        self.assertEqual(answer.status, 403)
        self.assertEqual(services.queue.sent, [])

    def test_a_replay_of_an_old_run_is_refused(self):
        # The Baseline of 2026-10-29, replayed a day later: what the Logic App answered with NotARecentRun.
        baseline = fix_run(testRunId="baseline-20261029-154215", endDateTime="2026-10-29T15:47:00Z")
        answer, services = self.accept(notification("baseline-20261029-154215"), baseline)
        self.assertEqual(answer.status, 410)
        self.assertEqual(services.queue.sent, [])
        ended = datetime(2026, 10, 30, 18, 37, 59, tzinfo=timezone.utc)  # slowdown_run()'s endDateTime
        self.assertEqual(self.accept(notification("slowdown-20261030-183250"), slowdown_run(),
                                     now=ended + timedelta(minutes=61))[0].status, 410)
        self.assertEqual(self.accept(notification("slowdown-20261030-183250"), slowdown_run(),
                                     now=ended + timedelta(minutes=59))[0].status, 202)

    def test_a_run_that_has_not_ended_is_refused(self):
        answer, services = self.accept(notification("slowdown-20261030-183250"), slowdown_run(endDateTime=None))
        self.assertEqual(answer.status, 410)
        self.assertEqual(services.queue.sent, [])


# ---------- the queued steps ----------

class StepTests(unittest.TestCase):
    def step(self, raw, services, settings=SETTINGS):
        with self.assertLogs("reporter", level="INFO") as logs:
            result = flow.step(raw, services, settings, NOW)
        return result, "\n".join(logs.output)

    def test_a_run_without_its_verdict_is_checked_again_a_minute_later(self):
        services = wire([slowdown_run(testResult="NOT_APPLICABLE")])
        result, _ = self.step(message("slowdown-20261030-183250"), services)
        self.assertEqual(result, "waiting-for-verdict")
        self.assertEqual(services.queue.sent, [({"testRunId": "slowdown-20261030-183250", "phase": "verdict", "checks": 1}, 60)])
        self.assertEqual(services.telemetry.queries, [])

    def test_the_verdict_wait_stops_after_ten_checks_or_a_cancelled_run(self):
        services = wire([slowdown_run(testResult="NOT_APPLICABLE")])
        self.assertEqual(self.step(message("slowdown-20261030-183250", checks=9), services)[0], "no-verdict")
        self.assertEqual(services.queue.sent, [])
        services = wire([slowdown_run(testResult="NOT_APPLICABLE", status="CANCELLED")])
        self.assertEqual(self.step(message("slowdown-20261030-183250"), services)[0], "no-verdict")
        self.assertEqual(services.queue.sent, [])

    def test_incomplete_telemetry_is_checked_again_then_reported_as_it_is(self):
        early = [dict(r, newest="2026-10-30T18:36:10Z") for r in SLOWDOWN_ROWS]
        github = FakeGitHub()
        services = wire([slowdown_run()], rows=early, github=github)
        self.assertEqual(self.step(message("slowdown-20261030-183250"), services)[0], "waiting-for-telemetry")
        self.assertEqual(services.queue.sent, [({"testRunId": "slowdown-20261030-183250", "phase": "telemetry", "checks": 1}, 60)])
        self.assertEqual(github.writes(), [])
        services = wire([slowdown_run()], rows=early, github=github)
        result, logs = self.step(message("slowdown-20261030-183250", "telemetry", 7), services)
        self.assertEqual(result, "opened #200")
        self.assertIn("still incomplete after 8 checks", logs)

    def test_without_a_token_the_report_is_built_but_not_posted(self):
        services = wire([slowdown_run()])
        result, logs = self.step(message("slowdown-20261030-183250"), services)
        self.assertEqual(result, "no-token")
        self.assertIn("No GitHub token configured", logs)
        self.assertIn("verdict expected-failure (455 server requests, 151 with the injected delay)", logs)

    def test_one_report_posts_at_a_time(self):
        github = FakeGitHub()
        services = wire([slowdown_run()], github=github, lock=FakeLock(busy=True))
        self.assertEqual(self.step(message("slowdown-20261030-183250"), services)[0], "busy")
        self.assertEqual(services.queue.sent, [({"testRunId": "slowdown-20261030-183250", "phase": "report", "checks": 1}, 15)])
        self.assertEqual(github.calls, [])
        services = wire([slowdown_run()], github=github, lock=FakeLock(busy=True))
        self.assertEqual(self.step(message("slowdown-20261030-183250", "report", 19), services)[0], "lock-timeout")
        self.assertEqual(services.queue.sent, [])

    def test_the_lock_is_released_even_when_github_fails(self):
        class Broken(FakeGitHub):
            def open_issues(self, label):
                raise services.GitHubError("GitHub answered 502 to GET issues: Bad Gateway", 502)
        lock = FakeLock()
        with self.assertRaises(services.GitHubError), self.assertLogs("reporter", level="INFO"):
            flow.step(message("slowdown-20261030-183250"), wire([slowdown_run()], github=Broken(), lock=lock), SETTINGS, NOW)
        self.assertEqual((lock.held, lock.released), (False, 1))

    def test_a_message_that_is_not_a_step_is_dropped(self):
        for raw in (b"not json", b"[]", message("../x"), json.dumps({"testRunId": "a-run", "phase": "x", "checks": 0}),
                    json.dumps({"testRunId": "a-run", "phase": "verdict", "checks": -1})):
            services = wire([slowdown_run()])
            with self.assertLogs("reporter", level="ERROR"):
                self.assertEqual(flow.step(raw, services, SETTINGS, NOW), "bad-message")
            self.assertEqual(services.runs.reads, [])

    def test_a_step_for_another_tests_run_or_a_deleted_run_stops(self):
        services = wire([slowdown_run(testRunId="other-run", testId="another-test")], github=FakeGitHub())
        self.assertEqual(self.step(message("other-run"), services)[0], "not-this-test")
        self.assertEqual(self.step(message("gone-run"), wire(github=FakeGitHub()))[0], "no-run")


# ---------- GitHub ----------

def issue(number=180, title="[load-test requesthub-journey] RequestHub journey missed its performance criteria",
          created_at="2026-10-30T18:44:19Z", body="", **extra):
    return {"number": number, "title": title, "created_at": created_at, "body": body, "state": "open", **extra}


class GitHubTests(unittest.TestCase):
    def post(self, run, github, rows=None, phase="telemetry"):
        rows = rows if rows is not None else (FIX_ROWS if run["testResult"] == "PASSED" else SLOWDOWN_ROWS)
        services = wire([run], rows=rows, github=github)
        with self.assertLogs("reporter", level="INFO") as logs:
            result = flow.step(message(run["testRunId"], phase), services, SETTINGS, NOW)
        return result, "\n".join(logs.output)

    def test_a_failing_run_with_no_open_issue_opens_one(self):
        github = FakeGitHub()
        result, _ = self.post(slowdown_run(), github)
        self.assertEqual(result, "opened #200")
        (_, title, body, labels), = github.writes()
        self.assertEqual(title, "[load-test requesthub-journey] RequestHub journey missed its performance criteria")
        self.assertEqual(labels, ["load-test"])
        self.assertTrue(body.startswith("`After the slowdown` missed its performance criteria. Azure Load Testing sent "
                                        "the finished run to an Azure Function in resource group `rg-ai-sdlc-test`, "
                                        "which wrote this report. The function closes this Issue when a run passes "
                                        "again.\n\n" + SLOWDOWN_REPORT))
        self.assertTrue(body.endswith(issues.marker("slowdown-20261030-183250", "expected-failure")))
        self.assertNotIn("slowdown-20261030-183250", body)

    def test_pull_requests_and_other_tests_issues_do_not_count(self):
        others = [issue(number=7, pull_request={"url": "x"}),
                  issue(number=8, title="[load-test another-test] Something else"),
                  issue(number=9, title="[load-test requesthub-journey-2] RequestHub journey missed its performance criteria"),
                  issue(number=10, title="load-test requesthub-journey: no brackets")]
        github = FakeGitHub(others)
        self.assertEqual(self.post(slowdown_run(), github)[0], "opened #200")
        github = FakeGitHub(others)
        self.assertEqual(self.post(fix_run(), github)[0], "no-change")
        self.assertEqual(github.writes(), [])

    def test_a_failing_run_comments_on_the_open_issue(self):
        github = FakeGitHub([issue(created_at="2026-10-30T10:00:00Z")])
        self.assertEqual(self.post(slowdown_run(), github)[0], "commented #180")
        (kind, number, body), = github.writes()
        self.assertEqual((kind, number), ("comment", 180))
        self.assertTrue(body.startswith("`After the slowdown` also missed its performance criteria.\n\n## Load test:"))

    def test_an_accepted_run_that_started_after_the_issue_closes_it(self):
        github = FakeGitHub([issue()])
        self.assertEqual(self.post(fix_run(), github)[0], "closed #180")
        self.assertEqual([call[0] for call in github.writes()], ["comment", "close"])
        self.assertTrue(github.writes()[0][2].startswith("`After the fix` passed every criterion. Closing.\n\n"))

    def test_an_older_run_never_closes_the_issue(self):
        github = FakeGitHub([issue(created_at="2026-10-30T19:00:00Z")])
        result, logs = self.post(fix_run(), github)
        self.assertEqual(result, "no-change")
        self.assertIn("started before the open Issue was created", logs)
        self.assertEqual(github.writes(), [])

    def test_a_pass_with_the_slowdown_on_or_without_telemetry_keeps_the_issue_open(self):
        for rows in ([row("GET /api/requests", 10, 0, 0, 1500, 10, "2026-10-30T18:56:29Z")], []):
            github = FakeGitHub([issue()])
            run = fix_run()
            services = wire([run], rows=rows, github=github)
            with self.assertLogs("reporter", level="INFO"):
                result = flow.step(message(run["testRunId"], "report"), services, SETTINGS, NOW)
            self.assertEqual(result, "kept-open #180")
            (kind, number, body), = github.writes()
            self.assertEqual(kind, "comment")
            self.assertIn("passed its criteria, but the report does not accept it, so this Issue stays open.", body)

    def test_a_repeated_delivery_changes_nothing(self):
        github = FakeGitHub()
        self.assertEqual(self.post(slowdown_run(), github)[0], "opened #200")
        self.assertEqual(self.post(slowdown_run(), github)[0], "no-change")
        self.assertEqual(self.post(fix_run(), github)[0], "closed #200")
        self.assertEqual(self.post(fix_run(), github)[0], "no-change")
        self.assertEqual([call[0] for call in github.writes()], ["create", "comment", "close"])

    def test_a_run_reported_again_with_new_telemetry_gets_one_new_comment(self):
        github = FakeGitHub()
        self.assertEqual(self.post(slowdown_run(), github, rows=[], phase="report")[0], "opened #200")
        self.assertIn("Telemetry not available", github.writes()[0][2])
        self.assertEqual(self.post(slowdown_run(), github)[0], "commented #200")
        self.assertTrue(github.writes()[1][2].startswith("`After the slowdown`: the report again, with the telemetry "
                                                         "that has arrived since.\n\n"))
        self.assertEqual(self.post(slowdown_run(), github)[0], "no-change")

    def test_a_close_that_failed_after_its_comment_is_retried_without_a_second_comment(self):
        closing = {"body": "earlier\n\n" + issues.marker("fix-20261030-185145", "accepted")}
        github = FakeGitHub([issue()], comments={180: [closing]})
        self.assertEqual(self.post(fix_run(), github)[0], "closed #180")
        self.assertEqual(github.writes(), [("close", 180)])

    def test_the_comments_checked_are_the_ones_since_the_run_started(self):
        github = FakeGitHub([issue(created_at="2026-10-30T10:00:00Z")])
        self.post(slowdown_run(), github)
        self.assertIn(("comments", 180, "2026-10-30T18:36:00Z"), github.calls)


# ---------- the real clients, with a fake HTTP session ----------

class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self.payload = status, payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


class FakeCredential:
    def get_token(self, scope):
        return SimpleNamespace(token=f"azure-token-for-{scope}")


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(services._shared)
        services._shared["credential"] = FakeCredential()

    def tearDown(self):
        services._shared.clear()
        services._shared.update(self.saved)

    def use(self, *responses):
        session = FakeSession(*responses)
        services._shared["session"] = session
        return session

    def test_github_errors_name_the_status_and_message_but_never_the_token(self):
        session = self.use(FakeResponse(401, {"message": "Bad credentials"}))
        with self.assertRaises(services.GitHubError) as caught:
            services.GitHub("melabadi/adept-assessment-northstars", TOKEN).open_issues("load-test")
        self.assertEqual(caught.exception.status, 401)
        self.assertIn("401", str(caught.exception))
        self.assertIn("Bad credentials", str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        method, url, kwargs = session.requests[0]
        self.assertEqual((method, url), ("GET", "https://api.github.com/repos/melabadi/adept-assessment-northstars/issues"))
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(kwargs["params"], {"state": "open", "labels": "load-test", "per_page": 100})

    def test_the_token_never_appears_in_a_log_or_an_error(self):
        self.use(FakeResponse(200, []), FakeResponse(201, {"number": 201}))
        github = services.GitHub("owner/repo", TOKEN)
        with self.assertLogs(level="DEBUG") as logs:
            result = flow.step(message("slowdown-20261030-183250", "telemetry"), wire([slowdown_run()], github=github),
                               SETTINGS, NOW)
        self.assertEqual(result, "opened #201")
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.use(FakeResponse(401, {"message": "Bad credentials"}))
        with self.assertLogs(level="DEBUG") as logs, self.assertRaises(services.GitHubError) as caught:
            flow.step(message("fix-20261030-185145", "telemetry"), wire([fix_run()], rows=FIX_ROWS, github=github),
                      SETTINGS, NOW)
        self.assertNotIn(TOKEN, "\n".join(logs.output) + str(caught.exception))

    def test_github_calls(self):
        session = self.use(FakeResponse(201, {"number": 5}), FakeResponse(201, {}), FakeResponse(200, {}), FakeResponse(200, []))
        github = services.GitHub("owner/repo", TOKEN)
        github.create_issue("t", "b", ["load-test"])
        github.comment(5, "c")
        github.close(5)
        github.comments(5, since="2026-10-30T18:36:00Z")
        calls = [(method, url.rsplit("/repos/owner/repo", 1)[1], kwargs.get("json"), kwargs.get("params"))
                 for method, url, kwargs in session.requests]
        self.assertEqual(calls, [
            ("POST", "/issues", {"title": "t", "body": "b", "labels": ["load-test"]}, None),
            ("POST", "/issues/5/comments", {"body": "c"}, None),
            ("PATCH", "/issues/5", {"state": "closed", "state_reason": "completed"}, None),
            ("GET", "/issues/5/comments", None, {"per_page": 100, "since": "2026-10-30T18:36:00Z"}),
        ])

    def test_the_repository_must_be_owner_slash_name(self):
        for bad in ("owner", "owner/repo/issues", "../x/y", "owner/repo?x=1"):
            with self.assertRaises(ValueError):
                services.GitHub(bad, TOKEN)

    def test_runs_are_read_with_the_load_testing_audience_and_an_encoded_id(self):
        session = self.use(FakeResponse(200, {"testId": TEST_ID}), FakeResponse(404, {}))
        runs = services.Runs("https://example.loadtesting.azure.com/")
        self.assertEqual(runs.get("fix-1"), {"testId": TEST_ID})
        self.assertIsNone(runs.get("a b"))
        (_, first, kwargs), (_, second, _) = session.requests
        self.assertEqual(first, "https://example.loadtesting.azure.com/test-runs/fix-1")
        self.assertEqual(second, "https://example.loadtesting.azure.com/test-runs/a%20b")
        self.assertEqual(kwargs["params"], {"api-version": "2024-12-01-preview"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer azure-token-for-https://cnt-prod.loadtesting.azure.com/.default")

    def test_telemetry_rows_come_back_as_dicts(self):
        table = {"tables": [{"columns": [{"name": "Name"}, {"name": "requests"}], "rows": [["GET /api/requests", 3]]}]}
        session = self.use(FakeResponse(200, table))
        rows = services.Telemetry("workspace-id").server_rows(report.parse_time("2026-10-30T18:36:00Z"),
                                                             report.parse_time("2026-10-30T18:37:59Z"))
        self.assertEqual(rows, [{"Name": "GET /api/requests", "requests": 3}])
        _, url, kwargs = session.requests[0]
        self.assertEqual(url, "https://api.loganalytics.azure.com/v1/workspaces/workspace-id/query")
        self.assertIn("datetime(2026-10-30T18:36:00.000000Z)", kwargs["json"]["query"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer azure-token-for-https://api.loganalytics.io/.default")

    def test_the_token_comes_from_key_vault_and_only_for_steps_that_post(self):
        class FakeVault:
            def __init__(self, value=None, status=None):
                self.value, self.status, self.reads = value, status, []

            def get_secret(self, name):
                self.reads.append(name)
                if self.status:
                    raise type("ResourceNotFoundError", (Exception,), {"status_code": self.status})("no secret")
                return SimpleNamespace(value=self.value)

        env = {"LOAD_TESTING_ENDPOINT": "https://x", "WORKSPACE_ID": "w", "STORAGE_QUEUE_ENDPOINT": "https://q",
               "QUEUE_NAME": "test-runs", "STORAGE_BLOB_ENDPOINT": "https://b", "GITHUB_REPOSITORY": "owner/repo",
               "KEY_VAULT_URI": "https://kv.vault.azure.net/"}
        vault = services._shared[("vault", env["KEY_VAULT_URI"])] = FakeVault(TOKEN)
        self.assertIsNone(services.connect(env, github=False).github)  # the HTTP route never reads the vault
        self.assertEqual(vault.reads, [])
        self.assertIsInstance(services.connect(env).github, services.GitHub)
        self.assertEqual(vault.reads, ["github-token"])
        # No secret yet: no GitHub client, even if an old GITHUB_TOKEN app setting is still around.
        services._shared[("vault", env["KEY_VAULT_URI"])] = FakeVault(status=404)
        self.assertIsNone(services.connect({**env, "GITHUB_TOKEN": TOKEN}).github)
        services._shared[("vault", env["KEY_VAULT_URI"])] = FakeVault(status=403)
        with self.assertRaises(Exception):
            services.connect(env)  # a vault the function can't read fails the step, and the queue retries it

    def test_the_vault_client_is_built_once_without_a_deadlock(self):
        # Live, building the client inside _once took the credential's lock twice, and the step hung until its timeout.
        built = []

        class SecretClient:
            def __init__(self, vault_uri, identity):
                built.append((vault_uri, identity))

            def get_secret(self, name):
                return SimpleNamespace(value=TOKEN)

        sdk = types.ModuleType("azure.keyvault.secrets")
        sdk.SecretClient = SecretClient
        modules = {"azure": types.ModuleType("azure"), "azure.keyvault": types.ModuleType("azure.keyvault"),
                   "azure.keyvault.secrets": sdk}
        with mock.patch.dict(sys.modules, modules):
            read = []
            worker = threading.Thread(target=lambda: read.append(services.vault_secret("https://kv/", "github-token")),
                                      daemon=True)
            worker.start()
            worker.join(5)
            self.assertFalse(worker.is_alive(), "vault_secret deadlocked")
            self.assertEqual(read, [TOKEN])
            self.assertEqual(services.vault_secret("https://kv/", "github-token"), TOKEN)
        self.assertEqual(len(built), 1)
        self.assertIsInstance(built[0][1], FakeCredential)


# ---------- the Function's bindings and the Bicep that hosts it ----------

class BindingTests(unittest.TestCase):
    source = (HERE / "function" / "function_app.py").read_text(encoding="utf-8")
    bicep = (HERE / "infra" / "reporting.bicep").read_text(encoding="utf-8")

    def decorators(self):
        tree = ast.parse(self.source)
        found = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        found[node.name] = (ast.unparse(decorator.func),
                                            {k.arg: ast.unparse(k.value) for k in decorator.keywords})
        return found

    def test_the_http_route_needs_a_function_key_and_only_accepts_post(self):
        kind, args = self.decorators()["test_run_ended"]
        self.assertEqual(kind, "app.route")
        self.assertEqual(args["auth_level"], "func.AuthLevel.FUNCTION")
        self.assertEqual(args["methods"], "['POST']")
        self.assertEqual(args["route"], "'test-run-ended'")
        self.assertIn("http_auth_level=func.AuthLevel.FUNCTION", self.source)

    def test_the_queue_trigger_uses_the_queue_bicep_creates(self):
        kind, args = self.decorators()["report_run"]
        self.assertEqual(kind, "app.queue_trigger")
        self.assertEqual(args["queue_name"], "QUEUE")
        self.assertEqual(args["connection"], "'AzureWebJobsStorage'")
        queue = re.search(r'^QUEUE = "([^"]+)"', self.source, re.M).group(1)
        self.assertIn(f"var queueName = '{queue}'", self.bicep)

    def test_the_action_group_calls_the_route_with_a_function_key(self):
        self.assertIn("azureFunctionReceivers", self.bicep)
        self.assertIn("functionName: 'test_run_ended'", self.bicep)
        self.assertIn("/api/test-run-ended?code=", self.bicep)
        self.assertNotIn("Microsoft.Logic/workflows", self.bicep)

    def test_the_function_and_the_action_group_get_the_same_key_in_one_deployment(self):
        # Live, listKeys right after writing the key returned the previous value: a second `azd provision` left the
        # action group with a key the function rejected (401), and Azure's notifications never reached the function.
        self.assertNotIn("listKeys(", self.bicep)
        self.assertRegex(self.bicep, r"@secure\(\)\s*@description\([^\n]*\)\s*param routeKey string = '[^\n]*newGuid\(\)")
        self.assertRegex(self.bicep, r"functionKeys@[\d-]+' = \{[\s\S]*?properties: \{\s*name: 'actiongroup'\s*value: routeKey\s*\}")
        self.assertIn("/api/test-run-ended?code=${routeKey}'", self.bicep)
        self.assertEqual(len(re.findall(r"\brouteKey\b", self.bicep)), 3)  # the parameter, the key, the URL

    def test_the_github_token_is_secure_and_never_an_output(self):
        self.assertRegex(self.bicep, r"@secure\(\)\s*(@description\([^)]*\)\s*)?param githubToken string")
        for line in self.bicep.splitlines():
            if line.startswith("output "):
                self.assertNotIn("githubToken", line)
                self.assertNotIn("listKeys", line)

    def test_the_github_token_lives_only_in_key_vault(self):
        # The parameter, the condition, and the secret's value: no app setting, tag, or output carries the token.
        self.assertEqual(len(re.findall(r"\bgithubToken\b", self.bicep)), 3)
        self.assertRegex(self.bicep, r"vaults/secrets@[\d-]+' = if \(!empty\(githubToken\)\) \{\s*parent: vault\s*"
                                     r"name: 'github-token'\s*properties: \{\s*value: githubToken")
        self.assertNotIn("'GITHUB_TOKEN'", self.bicep)
        self.assertIn("{ name: 'KEY_VAULT_URI', value: vault.properties.vaultUri }", self.bicep)
        self.assertIn("roles.keyVaultSecretsUser", self.bicep)
        self.assertIn("services.connect(github=False)", self.source)  # the HTTP route never reads the vault

    def test_the_azure_sdks_do_not_log_requests_or_tokens(self):
        # Live, their INFO lines listed every storage request's headers and every token they got.
        self.assertRegex(self.source, r'(?m)^logging\.getLogger\("azure"\)\.setLevel\(logging\.WARNING\)$')


if __name__ == "__main__":
    unittest.main()
