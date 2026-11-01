"""The run, one step at a time. function_app.py calls these from Azure Functions; the tests call them with fakes.

  start()          POST /api/runs. Saves a new record (queued); the caller queues the draft step.
  draft()          Queue step. Asks the Foundry agent for the brief in background mode, and polls every 5 seconds
                   until the answer is ready. A response that fails is asked for once more.
  evaluate()       Queue step. Scores the brief with the Foundry evaluation, polling every 15 seconds. When the
                   grading sandbox errored on a gate (not failed it), the evaluation runs again, up to 3 attempts,
                   and each check keeps the first score any attempt gave it: the checks are code, so a brief's score
                   never changes. Every gate must report a pass; otherwise the run fails and nothing reaches GitHub.
                   Then it opens the review Issue: the brief and its scores, for a person.
  check_reviews()  Timer, every 30 seconds. Reads each review Issue that waits for a person:
                   brief-approved applied → publishing (the caller queues the publish step);
                   closed without it → rejected, with a comment; 2 hours without either → timed out, with a comment,
                   and the Issue is closed as not planned. A review Issue that no longer exists ends its run, and one
                   that can't be read still times out. The timer also looks after runs whose step stopped: a publish
                   that made no progress for 5 minutes is queued again, twice at most, and a draft or evaluate step that
                   saved nothing for 45 minutes ends its run as failed.
  publish()        Queue step. Creates the epic and its four tasks, links each task to the epic as a sub-issue, marks
                   the tasks' "blocked by" dependencies, comments the links on the review Issue, and closes it.
  cancel()         DELETE /api/runs/{run}. Ends an unfinished run, and closes its review Issue if it has one.

Each step starts by loading the run's record and checking its state, so a step that runs twice (a queue message
delivered again) does nothing the second time, and a cancelled run stops at its next poll. The steps save their progress
as they go, so a step delivered again resumes where it stopped: draft and evaluate poll the response or the evaluation
run they had started, evaluate keeps its attempts and scores, and publish looks for each Issue's marker before it creates
one, so no Issue is created twice. Only one delivery publishes a run at a time: publish claims the run with the queue
message's id. A GitHub error while publishing stops the run, and the review Issue gets a comment listing what was
already created. Only Issues opened by the repository's owner, members, or collaborators count (clients.trusted()).

Every step's worst case (two agent responses of up to 10 minutes; three evaluation attempts of up to 15) ends well
before host.json's functionTimeout, and a running step saves its record at least once per wait.

Errors this code doesn't raise itself can quote a request or a host name: records and logs name their type only
(describe()).
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import brief, checks
from .clients import ServiceError, ServiceUnreachable, TokenMissing, answer_text, same_repository, trusted
from .store import ACTIVE, FINISHED, Conflict

EVALUATION = "plan-brief-checks"
AGENT_ATTEMPTS = 2
RESPONSE_POLL_SECONDS = 5
RESPONSE_LIMIT = timedelta(minutes=10)
EVALUATION_ATTEMPTS = 3
EVALUATION_POLL_SECONDS = 15
EVALUATION_LIMIT = timedelta(minutes=15)
DECISION_TIMEOUT = timedelta(hours=2)
# A publish saves after every Issue it writes: one that saved nothing for this long has stopped. The timer queues it
# again, twice at most, then ends the run.
PUBLISH_STALE = timedelta(minutes=5)
PUBLISH_REQUEUES = 2
# A draft or evaluate step saves at least once per wait: one that saved nothing for this long has stopped, for example
# because the host ended its last delivery, which never reaches give_up().
STEP_STALE = timedelta(minutes=45)
COPILOT_BRIEF = "solutions/01-plan-github/brief/backlog.json"
RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
STEP_OF = {"queued": "draft", "drafting": "draft", "evaluating": "evaluate"}


class Stop(Exception):
    """The run ended in this step (failed or cancelled): the record says why, and there's nothing to retry."""


class Busy(Exception):
    """The run is publishing its backlog and can't be cancelled now."""


@dataclass
class Settings:
    agent: str                     # agent.yaml: name
    prompt: str                    # agent.yaml: prompt, the request each run sends the agent
    excerpts: dict[str, str]       # source id → the quote the published Issues show
    evaluation: str = EVALUATION


@dataclass
class Services:
    store: object                  # store.BlobStore in Azure, store.MemoryStore in the tests
    foundry: object                # clients.Foundry
    github: Callable[[], object]   # returns clients.GitHub; raises clients.TokenMissing
    settings: Settings
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    sleep: Callable[[float], None] = time.sleep
    log: Callable[[str], None] = print


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def minutes(span: timedelta) -> int:
    return round(span.total_seconds() / 60)


def describe(error: BaseException) -> str:
    """What records and logs say about an error: the message of the errors this code raises, which never quote a request,
    a token, or a host name; for any other error, its type only."""
    if isinstance(error, (ServiceError, ServiceUnreachable, TokenMissing)):
        return str(error)
    return type(error).__name__


class Run:
    """A run's record while a step works on it: its events, and saving with the ETag it was loaded with."""

    def __init__(self, services: Services, run_id: str):
        self.services = services
        self.record, self.etag = services.store.load(run_id)

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def state(self) -> str:
        return self.record["state"]

    def idle(self) -> timedelta:
        """How long since anyone saved the record."""
        return self.services.now() - parse_iso(self.record.get("updated") or self.record["created"])

    def event(self, step: str, text: str) -> None:
        self.record.setdefault("events", []).append({"at": iso(self.services.now()), "step": step, "text": text})
        self.services.log(f"run {self.id} [{step}] {text}")

    def save(self) -> None:
        self.record["updated"] = iso(self.services.now())
        try:
            self.etag = self.services.store.save(self.record, self.etag)
        except Conflict:
            latest, _ = self.services.store.load(self.id)
            if latest["state"] == "cancelled":
                raise Stop("cancelled") from None
            raise

    def stop_if_cancelled(self) -> None:
        latest, _ = self.services.store.load(self.id)
        if latest["state"] == "cancelled":
            raise Stop("cancelled")

    def fail(self, step: str, code: str, message: str) -> None:
        self.record["state"] = "failed"
        self.record["error"] = {"code": code, "message": message}
        self.event(step, f"{code}: {message}")
        self.save()
        raise Stop(code)

    def seconds_since(self, started: datetime) -> int:
        return round((self.services.now() - started).total_seconds())


def best_effort(run: Run, step: str, what: str, action: Callable[[], None]) -> None:
    """A GitHub write whose failure must not change the outcome (a comment, a close): the record notes the failure."""
    try:
        action()
    except Exception as error:  # noqa: BLE001 - the outcome stands either way
        run.event(step, f"couldn't {what}: {describe(error)}")


def summary(record: dict) -> dict:
    """The record without the briefs' text, for GET /api/runs/{run}."""
    return {key: value for key, value in record.items() if key not in ("briefText", "copilotBriefText")}


# ---------- start ----------
def start(services: Services, compare_with_pull_request: int | None = None) -> dict:
    now = services.now()
    run_id = f"{now.astimezone(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    text = "queued"
    if compare_with_pull_request:
        text += f"; the Copilot brief from 01-plan-github pull request #{compare_with_pull_request} is scored alongside"
    record = {"id": run_id, "state": "queued", "created": iso(now), "updated": iso(now),
              "compareWithPullRequest": compare_with_pull_request,
              "events": [{"at": iso(now), "step": "start", "text": text}]}
    services.store.create(record)
    services.log(f"run {run_id} [start] {text}")
    return record


# ---------- draft ----------
def wait_for_response(services: Services, run: Run, response: dict) -> dict:
    deadline = services.now() + RESPONSE_LIMIT
    while response.get("status") in ("queued", "in_progress") and services.now() < deadline:
        services.sleep(RESPONSE_POLL_SECONDS)
        run.stop_if_cancelled()
        response = services.foundry.response(response["id"])
    return response


def draft(services: Services, run_id: str, owner: str = "") -> str | None:
    """Returns the next step to queue ("evaluate"), or None when there's nothing to do."""
    run = Run(services, run_id)
    if run.state not in ("queued", "drafting"):
        return None
    if run.record.get("briefText"):  # delivered again after the brief was saved
        run.record["state"] = "evaluating"
        run.save()
        return "evaluate"
    run.record["state"] = "drafting"
    settings = services.settings
    progress = run.record.setdefault("draft", {})
    progress.setdefault("started", iso(services.now()))
    progress.setdefault("attempts", 0)
    status, response = progress.get("status", "not started"), {}
    while True:
        if progress.get("pending"):  # delivered again: poll the response the earlier delivery started
            response = wait_for_response(services, run, {"id": progress["responseId"], "status": "queued"})
        elif progress["attempts"] < AGENT_ATTEMPTS:
            progress["attempts"] += 1
            started = services.foundry.start_response(settings.agent, settings.prompt)
            progress.update(responseId=started.get("id"), pending=True)
            again = f" (attempt {progress['attempts']})" if progress["attempts"] > 1 else ""
            run.event("draft", f"asked the agent {settings.agent} for the brief in background mode{again}")
            run.save()
            response = wait_for_response(services, run, started)
        else:
            break
        status = response.get("status")
        if status == "completed":
            break
        progress.update(pending=False, status=status)
        reason = (response.get("error") or {}).get("message") or "no error message"
        then = "; asking once more" if progress["attempts"] < AGENT_ATTEMPTS else ""
        run.event("draft", f"the agent's response ended as '{status}': {reason}{then}")
        run.save()
    if status != "completed":
        run.fail("draft", "AgentDidNotFinish", f"The agent's response ended as '{status}'. Nothing was sent to GitHub.")
    text = answer_text(response) or ""
    try:
        brief.parse_brief(text)
    except ValueError:
        run.fail("draft", "AgentDidNotFinish", "The agent's answer isn't the JSON brief. Nothing was sent to GitHub.")
    seconds = run.seconds_since(parse_iso(progress["started"]))
    progress.update(pending=False, status=status, seconds=seconds)
    run.record["briefText"] = text
    run.record["state"] = "evaluating"
    run.event("draft", f"brief ready after {seconds} s")
    run.save()
    return "evaluate"


# ---------- evaluate ----------
def wait_for_evaluation(services: Services, run: Run, evaluation_id: str, evaluation_run: dict) -> dict:
    deadline = services.now() + EVALUATION_LIMIT
    while evaluation_run.get("status") not in ("completed", "failed", "canceled") and services.now() < deadline:
        services.sleep(EVALUATION_POLL_SECONDS)
        run.stop_if_cancelled()
        evaluation_run = services.foundry.evaluation_run(evaluation_id, evaluation_run["id"])
    return evaluation_run


def copilot_brief(services: Services, pull_request: int) -> tuple[str | None, str | None]:
    """The Copilot brief on a 01-plan-github pull request, or why it can't be scored. Only a pull request whose branch is
    in this repository counts: anyone can open one from a fork on a public repository, and its files never reach
    Foundry. A branch here was pushed by someone with write access, or by the Copilot cloud agent that such a person
    assigned, which opens its pull requests as a bot (author_association NONE). The brief is read at the commit checked."""
    try:
        github = services.github()
        try:
            pull = github.pull_request(pull_request)
        except ServiceError as error:
            if error.status == 404:
                return None, f"#{pull_request} isn't a pull request in this repository"
            raise
        if not same_repository(pull, github.repository):
            return None, f"the branch of pull request #{pull_request} is in a fork"
        return github.read_file(COPILOT_BRIEF, pull["head"]["sha"]), None
    except (ServiceError, ServiceUnreachable, TokenMissing) as error:
        return None, str(error)


def first_attempt(services: Services, run: Run) -> dict:
    """The evaluation's progress, saved in the record: the attempts started, the scores kept, the attempt in flight."""
    settings = services.settings
    pull_request = run.record.get("compareWithPullRequest")
    copilot_error = None
    if pull_request:
        text, copilot_error = copilot_brief(services, pull_request)
        if text is not None:
            run.record["copilotBriefText"] = text
            run.event("evaluate", f"read the Copilot brief from 01-plan-github pull request #{pull_request}")
        else:
            run.event("evaluate", f"couldn't score the Copilot brief from pull request #{pull_request} ({copilot_error}); "
                                  f"scoring the Foundry brief alone")
    evaluation_id = services.foundry.evaluation_id(settings.evaluation)
    if not evaluation_id:
        run.fail("evaluate", "EvaluationNotFound", f"Foundry has no evaluation named {settings.evaluation}; run "
                                                   f"`python setup_foundry.py publish`. Nothing was sent to GitHub.")
    progress = {"evaluationId": evaluation_id, "started": iso(services.now()), "attempts": 0, "status": "not started",
                "pending": False, "scored": {}, "latest": [], "copilotScored": {}, "copilotLatest": [],
                "copilotError": copilot_error}
    run.record["evaluation"] = progress
    return progress


def score(services: Services, run: Run) -> None:
    """Runs the evaluation and records the scores; fails the run unless every gate reports a pass.

    The checks are code, so a brief's score never changes: each check keeps the first result the grading sandbox
    scored, from whichever attempt, and the evaluation runs again only while a gate has no scored result yet. Progress is
    saved after each attempt starts and ends, so a step delivered again continues instead of starting over."""
    settings = services.settings
    pull_request = run.record.get("compareWithPullRequest")
    progress = run.record.get("evaluation") or {}
    if not progress.get("evaluationId"):
        progress = first_attempt(services, run)
    items = [{"item": {"brief": checks.FOUNDRY_LABEL, "response": run.record["briefText"]}}]
    if run.record.get("copilotBriefText") is not None:
        items.append({"item": {"brief": checks.copilot_label(pull_request), "response": run.record["copilotBriefText"]}})
    while True:
        if not progress["pending"]:
            if progress["attempts"] >= EVALUATION_ATTEMPTS:
                break
            progress["attempts"] += 1
            name = f"brief {services.now():%Y-%m-%d %H:%M} (run {run.id}, attempt {progress['attempts']})"
            started = services.foundry.start_evaluation_run(progress["evaluationId"], name, items)
            progress.update(runId=started.get("id"), pending=True)
            run.event("evaluate", f"attempt {progress['attempts']} of the evaluation {settings.evaluation} started")
            run.save()
        evaluation_run = wait_for_evaluation(services, run, progress["evaluationId"],
                                             {"id": progress["runId"], "status": "queued"})
        status = evaluation_run.get("status")
        if status == "completed":
            output = services.foundry.output_items(progress["evaluationId"], progress["runId"])
            found = checks.results_for(output, checks.FOUNDRY_LABEL)
            if len(found) == 1:
                progress["latest"] = found[0]
                checks.keep_scored(progress["scored"], found[0])
            copilot = checks.results_for(output, checks.copilot_label(pull_request)) if pull_request else []
            if copilot:
                progress["copilotLatest"] = copilot[0]
                checks.keep_scored(progress["copilotScored"], copilot[0])
        progress.update(pending=False, status=status)
        unscored = [gate for gate in checks.GATES if gate not in progress["scored"]]
        if not unscored:
            break
        if status == "completed":
            errored = [gate for gate in unscored
                       if any(r.get("name") == gate and r.get("errored") for r in progress["latest"])]
            if not errored:  # a gate with no result at all: running again won't add one
                break
            reason = f"the grading sandbox errored on {', '.join(errored)}"
        else:
            reason = f"the evaluation run ended as '{status}'"
        then = "; running it again" if progress["attempts"] < EVALUATION_ATTEMPTS else ""
        run.event("evaluate", f"attempt {progress['attempts']}: {reason}{then}")
        run.save()
        if not then:
            break
    results = checks.combine(progress["latest"], progress["scored"])
    not_passed = checks.gates_not_passed(results)
    if not_passed:
        run.fail("evaluate", "BriefFailedEvaluation", f"The evaluation ended as '{progress['status']}', and these gates "
                                                      f"didn't pass: {', '.join(not_passed)}. Nothing was sent to GitHub.")
    copilot_results = (checks.combine(progress["copilotLatest"], progress["copilotScored"])
                       if progress["copilotLatest"] else None)
    seconds = run.seconds_since(parse_iso(progress["started"]))
    progress.update({
        "seconds": seconds, "passed": True, "foundry": results, "copilot": copilot_results,
        "copilotError": (progress.get("copilotError") or "no result") if pull_request and not copilot_results else None,
    })
    run.event("evaluate", f"the four gates passed after {seconds} s: {checks.passed_count(results)} of {len(results)} "
                          f"checks passed")
    run.save()


def existing_issue(github, marker: str, labels: list[str]) -> dict | None:
    """The newest Issue with these labels whose body ends with the run's marker, opened by the repository's owner, a
    member, or a collaborator. Anyone can open an Issue on a public repository and copy a marker into it: those never
    count, so nobody outside can stand in for the review Issue or make a publish look done."""
    for issue in github.list_issues(labels):
        if issue.get("pull_request") or not trusted(issue):
            continue
        if (issue.get("body") or "").rstrip().endswith(marker):
            return issue
    return None


def open_review(services: Services, run: Run) -> None:
    settings = services.settings
    evaluation = run.record["evaluation"]
    try:
        github = services.github()
        existing = existing_issue(github, brief.review_marker(run.id), ["type:brief", "track:microsoft"])
        if existing:
            number = existing["number"]
        else:
            body = brief.review_issue_body(
                run_id=run.id, agent=settings.agent, response_id=run.record["draft"]["responseId"],
                evaluation=settings.evaluation, brief=brief.parse_brief(run.record["briefText"]),
                foundry=evaluation["foundry"], pull_request=run.record.get("compareWithPullRequest"),
                copilot=evaluation.get("copilot"), copilot_error=evaluation.get("copilotError"))
            number = github.create_issue(brief.REVIEW_TITLE, body, brief.REVIEW_LABELS)["number"]
    except TokenMissing as error:
        run.fail("review", "GitHubTokenMissing", str(error))
    except ServiceError as error:
        run.fail("review", "GitHubRefused", f"{error}, when the run opened the review Issue.")
    run.record["review"] = {"issue": number, "opened": iso(services.now())}
    run.record["state"] = "awaiting_review"
    run.event("review", f"opened review Issue #{number}; waiting up to 2 hours for {brief.APPROVAL_LABEL} or a close")
    run.save()


def evaluate(services: Services, run_id: str, owner: str = "") -> str | None:
    run = Run(services, run_id)
    if run.state != "evaluating":
        return None
    if not (run.record.get("evaluation") or {}).get("passed"):  # delivered again after scoring: don't score twice
        score(services, run)
    open_review(services, run)
    return None


# ---------- wait for a person, and look after runs whose step stopped ----------
def decide(services: Services, github, run_id: str) -> str | None:
    run = Run(services, run_id)
    if run.state != "awaiting_review":
        return None
    number = run.record["review"]["issue"]
    now = services.now()
    overdue = now - parse_iso(run.record["review"]["opened"]) >= DECISION_TIMEOUT
    issue = None
    try:
        issue = github.issue(number)
    except ServiceError as error:
        # GitHub answers 404 both for a deleted Issue and for a token that can't read the repository: only the first
        # ends the run.
        if error.status in (404, 410) and github.check().get("status") == 200:
            run.record["state"] = "rejected"
            run.record["decision"] = {"outcome": "gone", "at": iso(now)}
            run.event("decision", f"review Issue #{number} no longer exists: published nothing")
            run.save()
            return None
        if not overdue:
            raise
    except Exception:
        if not overdue:  # read again in 30 seconds; past 2 hours, an unreadable Issue can't keep the run waiting
            raise
    labels = {label.get("name") for label in (issue or {}).get("labels") or []}
    if brief.APPROVAL_LABEL in labels:
        run.record["state"] = "publishing"
        run.record["decision"] = {"outcome": "approved", "at": iso(now)}
        run.event("decision", f"{brief.APPROVAL_LABEL} is on review Issue #{number}: publishing the backlog")
        run.save()
        return "publish"
    if (issue or {}).get("state") == "closed":
        best_effort(run, "decision", "comment on the review Issue",
                    lambda: github.comment(number, brief.rejected_comment(run.id)))
        run.record["state"] = "rejected"
        run.record["decision"] = {"outcome": "rejected", "at": iso(now)}
        run.event("decision", f"review Issue #{number} was closed without {brief.APPROVAL_LABEL}: published nothing")
        run.save()
        return None
    if overdue:
        best_effort(run, "decision", "comment on the review Issue",
                    lambda: github.comment(number, brief.timed_out_comment(run.id)))
        best_effort(run, "decision", "close the review Issue", lambda: github.close(number, "not_planned"))
        run.record["state"] = "timed_out"
        run.record["decision"] = {"outcome": "timed_out", "at": iso(now)}
        run.event("decision", f"no decision within 2 hours: closed review Issue #{number} as not planned, published nothing")
        run.save()
    return None


def stop_publishing(services: Services, run: Run, step: str, code: str, reason: str) -> None:
    """Ends a run that was publishing: the review Issue stays open, with a comment listing what was already created."""
    progress = run.record.get("published") or {}
    created = [t["number"] for t in progress.get("tasks") or []]
    epic_number = (progress.get("epic") or {}).get("number")
    review = run.record["review"]["issue"]
    best_effort(run, step, "comment what was created",
                lambda: services.github().comment(
                    review, brief.publishing_stopped_comment(run.id, epic_number, created, reason)))
    run.fail(step, code, f"{reason[:1].upper()}{reason[1:]}. The comment on review Issue #{review} lists what was created.")


def publish_again(services: Services, run_id: str) -> bool:
    """A publish that made no progress for 5 minutes: its message was lost, or its last delivery stopped. Queue it again
    (publish is safe to repeat), at most twice; after that, the run ends and the review Issue says what was created."""
    run = Run(services, run_id)
    if run.state != "publishing" or run.idle() < PUBLISH_STALE:
        return False
    progress = run.record.setdefault("published", {"tasks": [], "blocked": []})
    if progress.get("requeued", 0) >= PUBLISH_REQUEUES:
        stop_publishing(services, run, "publish", "StepStopped",
                        f"publishing made no progress for {minutes(PUBLISH_STALE)} minutes, "
                        f"{PUBLISH_REQUEUES + 1} times in a row")
    progress["requeued"] = progress.get("requeued", 0) + 1
    run.event("publish", f"publishing made no progress for {minutes(PUBLISH_STALE)} minutes: queued the publish step again")
    run.save()
    return True


def end_stopped_step(services: Services, run_id: str) -> None:
    run = Run(services, run_id)
    if run.state not in STEP_OF or run.idle() < STEP_STALE:
        return
    step = STEP_OF[run.state]
    run.fail(step, "StepStopped", f"The {step} step stopped without finishing, and the run made no progress for "
                                  f"{minutes(STEP_STALE)} minutes. Start a new run.")


def check_reviews(services: Services) -> list[str]:
    """Returns the runs whose publish step to queue. Each run is checked on its own: an error on one is logged by type,
    the others go on, and it's checked again in 30 seconds."""
    to_publish, waiting = [], []
    for found in services.store.list():
        run_id, state = found["id"], found["state"]
        try:
            idle = services.now() - parse_iso(found.get("updated") or found["created"])
            if state == "awaiting_review":
                waiting.append(run_id)
            elif state == "publishing" and idle >= PUBLISH_STALE:
                if publish_again(services, run_id):
                    to_publish.append(run_id)
            elif state in STEP_OF and idle >= STEP_STALE:
                end_stopped_step(services, run_id)
        except (Stop, Conflict):
            continue
        except Exception as error:  # noqa: BLE001
            services.log(f"run {run_id} [check] couldn't check the run ({describe(error)}); trying again in 30 seconds")
    if not waiting:
        return to_publish
    try:
        github = services.github()
    except Exception as error:  # noqa: BLE001
        services.log(f"can't read the review Issues: {describe(error)}")
        return to_publish
    for run_id in waiting:
        try:
            if decide(services, github, run_id) == "publish":
                to_publish.append(run_id)
        except (Stop, Conflict):
            continue
        except Exception as error:  # noqa: BLE001
            services.log(f"run {run_id} [decision] couldn't read the review Issue ({describe(error)}); "
                         f"trying again in 30 seconds")
    return to_publish


# ---------- publish ----------
def existing_or_new(github, marker: str, labels: list[str], title: str, body: str) -> dict:
    return existing_issue(github, marker, labels) or github.create_issue(title, body, labels)


def publish(services: Services, run_id: str, owner: str = "") -> None:
    """`owner` is the queue message's id: the same message delivered again resumes, and another message leaves the run to
    the delivery that claimed it, unless that one made no progress for 5 minutes."""
    run = Run(services, run_id)
    if run.state != "publishing":
        return None
    progress = run.record.setdefault("published", {"tasks": [], "blocked": []})
    claim = progress.get("claim") or {}
    if claim.get("owner") and claim["owner"] != owner and services.now() - parse_iso(claim["at"]) < PUBLISH_STALE:
        services.log(f"run {run.id} [publish] another delivery is publishing this run")
        return None
    progress["claim"] = {"owner": owner, "at": iso(services.now())}

    def save() -> None:
        progress["claim"]["at"] = iso(services.now())
        run.save()

    # Two deliveries that loaded the same record can't both get past here: the second save fails with a Conflict, and
    # once the queue delivers it again, that delivery finds this claim.
    save()
    excerpts = services.settings.excerpts
    data = brief.parse_brief(run.record["briefText"])
    review = run.record["review"]["issue"]
    try:
        github = services.github()
        if not progress.get("epic"):
            epic = existing_or_new(github, brief.backlog_marker(review, "epic"), brief.EPIC_LABELS, brief.epic_title(data),
                                   brief.epic_body(review_issue=review, brief=data, excerpts=excerpts))
            progress["epic"] = {"number": epic["number"], "id": epic["id"]}
            run.event("publish", f"created epic #{epic['number']}")
            save()
        epic_number = progress["epic"]["number"]
        for task in data.get("tasks") or []:
            entry = next((t for t in progress["tasks"] if t["taskId"] == task.get("id")), None)
            if entry is None:
                issue = existing_or_new(github, brief.backlog_marker(review, task.get("id")), brief.TASK_LABELS,
                                        brief.task_title(task),
                                        brief.task_body(review_issue=review, epic_issue=epic_number, task=task,
                                                        excerpts=excerpts))
                entry = {"taskId": task.get("id"), "number": issue["number"], "id": issue["id"],
                         "dependsOn": task.get("dependsOn") or [], "linked": False}
                progress["tasks"].append(entry)
                save()
            if not entry["linked"]:
                github.add_sub_issue(epic_number, entry["id"])
                entry["linked"] = True
                run.event("publish", f"created task #{entry['number']} ({entry['taskId']}), a sub-issue of epic #{epic_number}")
                save()
        tasks = {t["taskId"]: t for t in progress["tasks"]}
        for entry in progress["tasks"]:
            for blocker_id in entry["dependsOn"]:
                key = f"{entry['taskId']}<-{blocker_id}"
                blocker = tasks.get(blocker_id)
                if blocker is None or key in progress["blocked"]:
                    continue
                github.add_blocked_by(entry["number"], blocker["id"])
                progress["blocked"].append(key)
                save()
        if progress["blocked"]:
            run.event("publish", f"marked {len(progress['blocked'])} \"blocked by\" dependencies between the tasks")
        numbers = [t["number"] for t in progress["tasks"]]
        if not progress.get("commented"):
            github.comment(review, brief.published_comment(run.id, epic_number, numbers))
            progress["commented"] = True
            save()
        github.close(review, "completed")
    except (ServiceError, TokenMissing) as error:
        stop_publishing(services, run, "publish", "PublishingFailed", str(error))
    run.record["state"] = "published"
    run.event("publish", f"commented the backlog on review Issue #{review} and closed it")
    run.save()
    return None


STEPS = {"draft": draft, "evaluate": evaluate, "publish": publish}


def give_up(services: Services, run_id: str, step: str, error: Exception) -> None:
    """The queue delivered a step for the last time and it raised again: record the failure instead of a poison message."""
    run = Run(services, run_id)
    if run.state in FINISHED:
        return
    reason = f"the {step} step failed on every attempt; the last error: {describe(error)}"
    try:
        if run.state == "publishing":
            stop_publishing(services, run, step, "StepFailed", reason)
        run.fail(step, "StepFailed", f"{reason[:1].upper()}{reason[1:]}")
    except Stop:
        pass


# ---------- cancel and overview ----------
def cancel(services: Services, run_id: str) -> dict:
    """Ends an unfinished run. A publishing run is left alone while it makes progress; one that made none for 5 minutes
    can be cancelled, and the review Issue's comment lists what it had created."""
    for _ in range(3):
        run = Run(services, run_id)
        if run.state in FINISHED:
            return summary(run.record)
        if run.state == "publishing" and run.idle() < PUBLISH_STALE:
            raise Busy("the run is publishing its backlog; wait until it finishes")
        review = (run.record.get("review") or {}).get("issue")
        progress = run.record.get("published") or {}
        epic_number = (progress.get("epic") or {}).get("number")
        created = [t["number"] for t in progress.get("tasks") or []]
        run.record["state"] = "cancelled"
        run.event("cancel", "cancelled in Azure" + (f"; closing review Issue #{review}" if review else ""))
        try:
            run.save()
        except Stop:
            return summary(services.store.load(run_id)[0])
        except Conflict:
            continue
        if review:
            def close() -> None:
                github = services.github()
                github.comment(review, brief.cancelled_comment(run.id, epic_number, created))
                github.close(review, "not_planned")
            best_effort(run, "cancel", "close the review Issue", close)
        return summary(run.record)
    raise Conflict(run_id)


def overview(services: Services) -> dict:
    """GET /api/runs: the runs in progress, the five newest, and whether GitHub accepts the Function app's token."""
    runs = sorted(services.store.list(), key=lambda r: r.get("created", ""), reverse=True)
    try:
        token = services.github().check()
    except Exception as error:  # noqa: BLE001 - reported, never raised: GET /api/runs always answers
        token = {"status": None, "expires": None, "error": describe(error)}
    return {"inProgress": [r for r in runs if r["state"] in ACTIVE], "recent": runs[:5], "github": token}
