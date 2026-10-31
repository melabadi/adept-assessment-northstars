"""One review of one pull request, in the order the review's trust depends on.

  1. Read the pull request from GitHub's API (the queue message carries only its number) and stop unless it can be
     reviewed: this repository's branch, and for a real review open, not a draft, into the default branch, labelled.
  2. The judge: the rule checker and the review formatter come from main, never from the pull request. The checker
     reads the merge base and the head as data, in a session with no network, before any of the pull request's code
     runs anywhere. Without its verdicts, nothing else happens.
  3. Only now does the pull request's code run, built and tested in its own session (the run pool).
  4. The agent explains what it sees, with a read-only tool on the run session.
  5. Back in the judge's session, the formatter writes the review: the checker's verdicts word for word, the build
     results, then the agent's commentary.
  6. A real review is posted as one COMMENT review, only if the commit it reviewed is still the pull request's head.
     A dry run posts nothing; it returns its result.
Both sessions are deleted at the end, whatever happened. Results travel as files, because a session cuts a command's
output after 4 KB. The GitHub token never reaches a session, the agent, or a log line.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from .agent import AgentError
from .github import GitHubError
from .sessions import SessionError
from .webhook import eligibility

LOG = logging.getLogger("reviewer")

CHECK_COMMAND = ("cd /mnt/data && python3 review_rules.py --base base.tgz --head head.tgz > judge.json; status=$?; "
                 "echo \"review_rules.py exit code $status; judge.json is $(wc -c < judge.json) bytes\"; exit $status")
FORMAT_COMMAND = ("cd /mnt/data && python3 format_review.py --judge judge.json --input review-input.json --agent agent.json "
                  "> review.json; status=$?; echo \"format_review.py exit code $status; review.json is $(wc -c < review.json) "
                  "bytes\"; exit $status")
BUILD_START = "bash /mnt/data/run_change.sh start"
BUILD_STATUS = "bash /mnt/data/run_change.sh status"
SCRIPTS = ("review_rules.py", "format_review.py", "run_change.sh")
SANDBOX_LIMIT = 20000  # the pull request's own code writes the build summary, so only this much of it is kept
DESCRIPTION_LIMIT = 4000


class ReviewError(RuntimeError):
    """A step produced nothing the next step can use."""


@dataclass(frozen=True)
class Settings:
    repository: str
    label: str = "review:azure"
    checker_ref: str = "main"
    scripts_path: str = "solutions/03-develop-microsoft/sandbox"
    agent_name: str = "requesthub-pr-reviewer"
    build_poll_seconds: float = 20
    build_timeout_seconds: float = 1200
    agent_wait_seconds: float = 600
    agent_poll_seconds: float = 5


@dataclass
class Tools:
    github: object  # reviewer.github.GitHub
    session: Callable[[str, str], object]  # (pool "judge" or "run", identifier) -> reviewer.sessions.Session
    agent: object  # reviewer.agent.Agent
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    log: logging.Logger = field(default=LOG)


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def safe(exc: BaseException) -> str:
    """An error for the log and the dry-run result: our own messages name the step and the status; anything else
    only its type, since an unknown message could echo data."""
    return str(exc) if isinstance(exc, (GitHubError, SessionError, AgentError, ReviewError)) else type(exc).__name__


def failure_note(review_id: str, label: str) -> str:
    return ("### Azure pull request review · advisory\n\n"
            f"The reviewer couldn't finish this review (review `{review_id}`). Nothing was decided; review this pull "
            f"request as usual. To try again, remove and add the `{label}` label.\n\n"
            f"<!-- azure-pr-reviewer review={review_id} failed -->")


def describe_build(summary: str) -> str:
    """One line about the build's results, for the log."""
    try:
        data = json.loads(summary)
    except ValueError:
        return "no readable summary"
    if not isinstance(data, dict) or "api" not in data:
        return "the build didn't finish in time" if isinstance(data, dict) and data.get("state") == "not-finished" else "no results"

    def part(name: str, tests: object, status: object) -> str:
        if isinstance(tests, dict) and isinstance(tests.get("total"), int):
            failed = tests.get("failed") or 0
            return f"{name} {failed} of {tests['total']} failed" if failed else f"{name} {tests.get('passed')} of {tests['total']} passed"
        return f"{name} {status or 'not run'}"

    api, web = data.get("api") or {}, data.get("web") or {}
    took = f" in {duration(data['seconds'])}" if isinstance(data.get("seconds"), (int, float)) else ""
    return f"{part('API', api, api.get('status'))}, {part('web', web.get('tests'), web.get('status'))}{took}"


def build_and_test(run, runner: bytes, head_archive: bytes, settings: Settings, tools: Tools, say, warn) -> str:
    """Builds and tests the pull request's code in the run session. Returns the summary (at most SANDBOX_LIMIT
    characters), or "" when the build couldn't run: the review then posts the rule results without test results."""
    started = tools.clock()
    try:
        run.upload("run_change.sh", runner)
        run.upload("head.tgz", head_archive)
        run.execute(BUILD_START, 30)
        say("the pull request's code runs only now, in its own session: build and tests started")
        deadline = started + settings.build_timeout_seconds
        while tools.clock() < deadline:
            tools.sleep(settings.build_poll_seconds)
            if '"state":"done"' in run.execute(BUILD_STATUS, 30)["stdout"]:  # the only output read from a command
                break
        else:
            say("the build didn't finish within %s; the review says so", duration(settings.build_timeout_seconds))
        summary = run.download("summary.json", path="run").decode("utf-8", errors="replace")[:SANDBOX_LIMIT]
    except Exception as exc:
        warn("the build couldn't run: %s", safe(exc))
        return ""
    say("build and tests: %s", describe_build(summary))
    return summary


def review(pr: int, *, review_id: str, dry_run: bool, settings: Settings, tools: Tools) -> dict:
    """Runs one review. Never raises: the result says what happened ("done", "skipped", or "failed")."""
    started = tools.clock()

    def say(message: str, *args) -> None:
        tools.log.info(f"review {review_id}: {message}", *args)

    def warn(message: str, *args) -> None:
        tools.log.warning(f"review {review_id}: {message}", *args)

    result: dict = {"id": review_id, "pr": pr, "dry_run": dry_run, "state": "failed", "posted": False}
    github = tools.github
    try:
        pull = github.pull(pr)
    except Exception as exc:
        warn("couldn't read pull request #%s: %s", pr, safe(exc))
        result.update(step="read the pull request", error=safe(exc))
        return result
    refusal = eligibility(pull, settings.repository, settings.label, dry_run)
    if refusal:
        say("#%s is not reviewed: %s", pr, refusal)
        result.update(state="skipped", reason=refusal)
        return result

    head = str(pull["head"]["sha"])
    result["head"] = head
    say("#%s at %s%s", pr, head[:7], ", dry run: nothing is posted" if dry_run else "")
    judge = tools.session("judge", f"judge-{review_id}")
    run = tools.session("run", f"run-{review_id}")
    step = "find the merge base"
    try:
        base = github.merge_base(str(pull["base"]["sha"]), head)
        step = "read the scripts from " + settings.checker_ref
        scripts = {name: github.file(f"{settings.scripts_path}/{name}", settings.checker_ref) for name in SCRIPTS}
        step = "download the code"
        base_archive, head_archive = github.archive(base), github.archive(head)

        # 1. The judge, before any of the pull request's code runs anywhere.
        step = "check the team rules"
        checked = tools.clock()
        for name, data in (("review_rules.py", scripts["review_rules.py"]), ("format_review.py", scripts["format_review.py"]),
                           ("base.tgz", base_archive), ("head.tgz", head_archive)):
            judge.upload(name, data)
        exit_code = judge.execute(CHECK_COMMAND, 120)["status"]
        verdicts = json.loads(judge.download("judge.json"))
        rules = verdicts.get("rules") if isinstance(verdicts, dict) else None
        if not isinstance(rules, list) or not rules:
            raise ReviewError(f"the rule checker wrote no verdicts (exit code {exit_code})")
        failed = sum(1 for rule in rules if isinstance(rule, dict) and rule.get("result") == "FAIL")
        say("the rule checker from %s read both trees in the judge's session in %s: %s", settings.checker_ref,
            duration(tools.clock() - checked), f"{failed} of {len(rules)} rules failed" if failed else f"all {len(rules)} rules passed")

        # 2. Only now does the pull request's code run, in its own session.
        step = "build and test"
        sandbox = build_and_test(run, scripts["run_change.sh"], head_archive, settings, tools, say, warn)

        # 3. The agent's commentary.
        step = "ask the agent"
        asked = tools.clock()
        request = {
            "pr": {"number": pr, "title": str(pull.get("title") or ""), "author": str((pull.get("user") or {}).get("login") or ""),
                   "description": str(pull.get("body") or "")[:DESCRIPTION_LIMIT], "base": base, "head": head},
            "rules": rules, "sandbox": sandbox, "run_session": run.identifier,
            "diff_truncated": verdicts.get("diff_truncated"), "diff": verdicts.get("diff"),
        }
        answer, agent_status = tools.agent.ask(request, settings.agent_wait_seconds, settings.agent_poll_seconds)
        version = (answer.get("agent_reference") or {}).get("version") if isinstance(answer, dict) else None
        calls = sum(1 for item in (answer.get("output") or []) if isinstance(item, dict) and str(item.get("type", "")).endswith("_call")) \
            if isinstance(answer, dict) else 0
        say("agent %s%s answered in %s (%s, %s sandbox command%s)", settings.agent_name, f" v{version}" if version else "",
            duration(tools.clock() - asked), agent_status, calls, "" if calls == 1 else "s")

        # 4. The review, written in the judge's session from the checker's own judge.json.
        step = "write the review"
        review_input = {"pr": {"number": pr, "title": str(pull.get("title") or ""), "head": head, "base": base},
                        "run": review_id, "dry_run": dry_run, "checker_ref": settings.checker_ref,
                        "agent_name": settings.agent_name, "sandbox": sandbox, "agent_status": agent_status}
        judge.upload("review-input.json", json.dumps(review_input, ensure_ascii=False).encode("utf-8"))
        judge.upload("agent.json", json.dumps(answer, ensure_ascii=False).encode("utf-8"))
        judge.execute(FORMAT_COMMAND, 60)
        written = json.loads(judge.download("review.json"))
        if not isinstance(written, dict) or not isinstance(written.get("markdown"), str) or not written["markdown"]:
            raise ReviewError("the review formatter wrote no review")
        result.update(rules=rules, sandbox=sandbox, agent=written.get("agent"), agent_error=written.get("agent_error"),
                      review=written["markdown"])

        # 5. Post it, as a comment, only on the commit it reviewed.
        if dry_run:
            say("dry run: the review is returned, not posted")
        else:
            step = "post the review"
            now = str((github.pull(pr).get("head") or {}).get("sha") or "")
            if now != head:
                result["superseded"] = True
                say("not posted: %s was pushed while this review ran, and its own review is on its way", now[:7])
            else:
                result["review_url"] = github.comment_review(pr, written["markdown"], head)
                result["posted"] = True
                say("posted a COMMENT review on %s", head[:7])
        result["state"] = "done"
    except Exception as exc:
        warn("failed at '%s': %s", step, safe(exc))
        result.update(state="failed", step=step, error=safe(exc))
        if not dry_run:
            try:
                github.comment_review(pr, failure_note(review_id, settings.label))
                say("posted a note that the review couldn't finish")
            except Exception as note:
                warn("the note couldn't be posted either: %s", safe(note))
    finally:
        for session in (judge, run):
            if not getattr(session, "used", True):
                continue  # never created: nothing to delete
            try:
                session.delete()
            except Exception as exc:
                warn("couldn't delete %s: %s", session.identifier, safe(exc))
        result["seconds"] = round(tools.clock() - started)
        say("%s in %s; sessions deleted", result["state"], duration(result["seconds"]))
    return result
