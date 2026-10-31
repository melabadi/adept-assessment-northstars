"""What the function does with a run that ended: accept the notification, wait for the verdict and the telemetry, and
post the report to GitHub. Plain Python: the Azure and GitHub calls come in as small objects (services.py builds the
real ones; test_reporter.py passes fakes), so every decision here has a unit test.

accept()  The HTTP route calls it for each notification. It takes the run id from the notification, reads the run from
          Azure Load Testing, and accepts it only if the run belongs to this function's test and ended within the last
          60 minutes, so a replayed or forged call can't report an old run. Then it queues the first step and answers
          202 at once: nothing slow happens while the action group waits.
step()    The queue trigger calls it for each step. A step that has to wait queues the next one with a visibility
          delay instead of sleeping:
            verdict    a run reaches DONE a minute or two before PASSED or FAILED: check every minute, up to 10 times;
            telemetry  Application Insights receives the API's requests a few minutes late: check every minute, up to
                       8 times, then report with what has arrived (the verdict says when nothing has);
            report     build the report, then take the GitHub lock (one report at a time, so two runs never both open
                       an Issue), and open, comment on, or close the test's Issue.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import issues, report

log = logging.getLogger("reporter")
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
ENDED_WITHOUT_VERDICT = {"CANCELLED", "FAILED"}
PHASES = ("verdict", "telemetry", "report")


@dataclass(frozen=True)
class Settings:
    test_id: str
    resource_group: str
    recent: timedelta = timedelta(minutes=60)
    verdict_checks: int = 10
    verdict_delay: int = 60
    telemetry_checks: int = 8
    telemetry_delay: int = 60
    lock_checks: int = 20
    lock_delay: int = 15

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        return cls(test_id=env["TEST_ID"], resource_group=env.get("RESOURCE_GROUP_NAME", ""))


@dataclass(frozen=True)
class Answer:
    status: int
    message: str


def run_id_from(notification) -> str:
    """The run id in an Azure Load Testing notification (the action group sends the alert in `data`)."""
    if not isinstance(notification, dict):
        return ""
    data = notification.get("data") if isinstance(notification.get("data"), dict) else {}
    for context in ((data.get("data") or {}).get("alertContext") if isinstance(data.get("data"), dict) else None,
                    data.get("alertContext")):
        if isinstance(context, dict) and isinstance(context.get("testRunId"), str):
            return context["testRunId"].strip()
    return ""


def accept(body, services, settings: Settings, now: datetime) -> Answer:
    """Check a notification and queue its first step (see the module docstring)."""
    try:
        notification = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return _refuse(400, "The request body is not JSON.")
    test_run_id = run_id_from(notification)
    if not test_run_id:
        return _refuse(400, "The notification carried no test run id.")
    if not RUN_ID.fullmatch(test_run_id):
        return _refuse(400, "The test run id is not valid.")
    run = services.runs.get(test_run_id)
    if run is None:
        return _refuse(404, "Azure Load Testing has no run with that id.")
    if run.get("testId") != settings.test_id:
        return _refuse(403, "The run does not belong to the test this function reports.")
    ended = report.parse_time(run.get("endDateTime"))
    if ended is None or ended < now - settings.recent:
        return _refuse(410, f"The run has not ended, or it ended more than {int(settings.recent.total_seconds() // 60)} "
                            "minutes ago. Only runs that just ended are reported.")
    services.queue.send({"testRunId": test_run_id, "phase": "verdict", "checks": 0}, 0)
    log.info("Accepted %s (%s, ended %s): queued for its report.", run.get("displayName") or test_run_id, test_run_id,
             run.get("endDateTime"))
    return Answer(202, "Accepted: the function reports the run as soon as its verdict and telemetry are ready.")


def _refuse(status: int, message: str) -> Answer:
    log.warning("Refused a notification (%s): %s", status, message)
    return Answer(status, message)


def parse_message(raw) -> dict:
    """A queued step, checked: {"testRunId": str, "phase": verdict|telemetry|report, "checks": int}."""
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    message = json.loads(text)
    if not isinstance(message, dict):
        raise ValueError("not an object")
    if not RUN_ID.fullmatch(str(message.get("testRunId") or "")):
        raise ValueError("no valid testRunId")
    if message.get("phase") not in PHASES:
        raise ValueError(f"unknown phase {message.get('phase')!r}")
    if not isinstance(message.get("checks"), int) or message["checks"] < 0:
        raise ValueError("checks must be a whole number")
    return {"testRunId": message["testRunId"], "phase": message["phase"], "checks": message["checks"]}


def step(raw, services, settings: Settings, now: datetime) -> str:
    """Run one queued step and say what happened (the queue trigger logs it; the tests check it)."""
    try:
        message = parse_message(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        log.error("Dropped a queue message that is not a report step: %s", exc)
        return "bad-message"
    test_run_id, phase, checks = message["testRunId"], message["phase"], message["checks"]
    run = services.runs.get(test_run_id)
    if run is None:
        log.warning("Run %s no longer exists in Azure Load Testing: nothing to report.", test_run_id)
        return "no-run"
    if run.get("testId") != settings.test_id:
        log.warning("Run %s belongs to another test: nothing to report.", test_run_id)
        return "not-this-test"
    name = run.get("displayName") or test_run_id
    run = {**run, "testRunId": test_run_id}

    if phase == "verdict":
        if run.get("testResult") not in report.FINAL:
            if run.get("status") in ENDED_WITHOUT_VERDICT or checks + 1 >= settings.verdict_checks:
                log.warning("%s ended without a verdict (status %s, result %s): nothing to report.", name,
                            run.get("status"), run.get("testResult"))
                return "no-verdict"
            _again(services, test_run_id, "verdict", checks + 1, settings.verdict_delay)
            log.info("%s has no verdict yet (status %s): checking again in %s s, check %s of %s.", name,
                     run.get("status"), settings.verdict_delay, checks + 2, settings.verdict_checks)
            return "waiting-for-verdict"
        phase, checks = "telemetry", 0

    started, ended = report.parse_time(run.get("startDateTime")), report.parse_time(run.get("endDateTime"))
    if started is None or ended is None:
        log.error("%s has no start or end time: nothing to report.", name)
        return "no-window"
    rows = services.telemetry.server_rows(started, ended)
    if phase == "telemetry" and not report.telemetry_ready(rows, ended):
        if checks + 1 < settings.telemetry_checks:
            _again(services, test_run_id, "telemetry", checks + 1, settings.telemetry_delay)
            log.info("%s: %s, but Application Insights has not received the end of the run yet: checking again in %s s, "
                     "check %s of %s.", name, run.get("testResult"), settings.telemetry_delay, checks + 2,
                     settings.telemetry_checks)
            return "waiting-for-telemetry"
        log.warning("%s: the telemetry is still incomplete after %s checks; reporting what has arrived.", name,
                    settings.telemetry_checks)

    verdict = report.outcome(run.get("testResult"), rows)
    markdown = report.render(run, rows, verdict, settings.resource_group)
    log.info("%s: %s, verdict %s (%s server requests, %s with the injected delay).", name, run.get("testResult"),
             verdict, sum(int(r.get("requests") or 0) for r in rows), sum(int(r.get("delayed") or 0) for r in rows))
    if services.github is None:
        log.warning("No GitHub token configured, so the report was built but not posted. Set GITHUB_ISSUES_TOKEN in "
                    "the azd environment and run azd provision.")
        return "no-token"

    lease = services.lock.acquire()
    if lease is None:
        tries = checks + 1 if phase == "report" else 1
        if tries >= settings.lock_checks:
            log.error("%s: another report held the GitHub lock for %s tries; giving up.", name, tries)
            return "lock-timeout"
        _again(services, test_run_id, "report", tries, settings.lock_delay)
        log.info("%s: another report is posting to GitHub; trying again in %s s.", name, settings.lock_delay)
        return "busy"
    try:
        return _post(run, verdict, markdown, services.github, settings)
    finally:
        lease.release()


def _again(services, test_run_id: str, phase: str, checks: int, delay: int) -> None:
    services.queue.send({"testRunId": test_run_id, "phase": phase, "checks": checks}, delay)


def _post(run: dict, verdict: str, markdown: str, github, settings: Settings) -> str:
    name = run.get("displayName") or run["testRunId"]
    issue = issues.choose(github.open_issues(issues.LABEL), settings.test_id)
    earlier = []
    if issue is not None:
        comments = github.comments(issue["number"], since=run.get("startDateTime"))
        earlier = [issue.get("body") or ""] + [comment.get("body") or "" for comment in comments]
    action = issues.decide(run, verdict, markdown, issue, earlier, settings.test_id, settings.resource_group)
    if action.kind == "open":
        created = github.create_issue(action.title, action.body, [issues.LABEL])
        log.info("%s: opened Issue #%s (%s).", name, created.get("number"), action.reason)
        return f"opened #{created.get('number')}"
    if action.kind in ("comment", "close", "keep-open"):
        if action.body:
            github.comment(action.number, action.body)
        if action.kind == "close":
            github.close(action.number)
            log.info("%s: closed Issue #%s (%s).", name, action.number, action.reason)
            return f"closed #{action.number}"
        log.info("%s: commented on Issue #%s (%s).", name, action.number, action.reason)
        return f"{'kept-open' if action.kind == 'keep-open' else 'commented'} #{action.number}"
    log.info("%s: no change on GitHub: %s.", name, action.reason)
    return "no-change"
