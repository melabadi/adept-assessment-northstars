"""The two jobs the Function runs from its queues. Azure and GitHub come in as parameters, so the tests run both jobs
offline with fakes.

advise(job)              A design question filed as an Issue: ask the profile's agent, run the gate, and only then
                         create the ADR branch, commit the draft, open the pull request, and comment with the answer.
                         A rejected answer gets one comment with the failed checks and nothing else. Two more comments
                         keep a question from going silent: one when the agent or the gate is unavailable, one when a
                         GitHub step fails after the gate.
publish_standards(job)   A merged change to the standards, agent.yaml, or the cases: re-index the standards of that
                         commit, publish new agent versions only if their definition changed, and start an evaluation.
                         Only for a commit on the default branch: an unmerged proposal never reaches the index.

Every step logs one line that starts with the run's id ("advisor run 3f2a9c1b7d4e: ..."); the issue comment, the ADR
draft, and the pull request show the same id. The lines name the issue, the commit, the agent version, and counts,
never the question, the answer, or a token.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from . import agents, checks, foundry, github, report, standards

SOLUTION = "solutions/02-design-microsoft"
RETRYABLE = ("unavailable", "incomplete")
STALE_SECONDS = 15 * 60  # a run queued or started this long ago that never ended is presumed lost
EMPTY_ANSWER = {"answerable": False, "summary": "", "recommendation": None, "options": [], "constraints": [],
                "conflicts": [], "unknowns": []}


class StepError(RuntimeError):
    """A failure whose message is safe to log: it says what failed, never a secret or a URL."""


def describe(exc: BaseException) -> str:
    """What a log line says about an error: this solution's own messages as they are, anything else only by its type,
    since an SDK's message can echo a URL or a value."""
    if isinstance(exc, (StepError, github.GitHubError, github.GuardError, foundry.FoundryError, standards.StandardsError)):
        return str(exc)
    return type(exc).__name__


def seconds(since: float) -> int:
    return round(time.monotonic() - since)


def retryable(record: dict | None, now: float) -> bool:
    """Whether a new advisor run may take over an issue: its last run couldn't finish (the agent or the gate was
    unavailable, or a GitHub step failed), or a run was queued or started more than 15 minutes ago and never ended.
    An answered or rejected question stays answered: ask it again in a new Issue."""
    state = (record or {}).get("state")
    if state in RETRYABLE:
        return True
    return state in ("queued", "running") and now - float((record or {}).get("since") or 0) > STALE_SECONDS


# ---------------------------------------------------------------- the gate
def check_answer(response: dict, job: dict, *, scope_of, snapshot, index: str) -> dict:
    """The gate's verdict on one answer, as the run record that the comment, the ADR draft, and the pull request are
    built from. Every problem the checks find is in run["checks"]; an empty list means the answer may be published.

    response: the Responses API's result. job: the queued question (id, issue, profile, question).
    scope_of(name, version) -> (profile, scope filter) recorded on that agent version when it was published.
    snapshot(filter or None) -> {id: {version, text}} of the indexed standards: all of them, or those the filter returns.
    Raises only when the index or the agent's metadata can't be read: then nothing can be checked."""
    profile, question = job["profile"], job["question"]
    agent = response.get("agent_reference") or {}
    run = {"issue": job.get("issue"), "question": question, "profile": profile, "runId": str(job.get("id", "")),
           "agent": {"name": agent.get("name", "?"), "version": str(agent.get("version", "?"))},
           "model": response.get("model", ""), "responseId": response.get("id", ""), "index": index}
    created, completed = response.get("created_at"), response.get("completed_at")
    run["startedAt"] = datetime.fromtimestamp(created or time.time(), timezone.utc).isoformat(timespec="seconds")
    run["durationSeconds"] = round(completed - created, 1) if created and completed else None
    output = [item for item in response.get("output") or [] if isinstance(item, dict)]
    run["knowledgeCalls"] = sum(item.get("type") in ("mcp_call", "azure_ai_search_call") for item in output)
    run["retrievedStandards"] = checks.retrieved_ids([item for item in output if item.get("type") != "message"])
    usage = response.get("usage") or {}
    run["usage"] = {"inputTokens": usage.get("input_tokens"), "outputTokens": usage.get("output_tokens")}

    problems, answer = [], None
    if response.get("status") != "completed":
        problems.append(f"response: the agent's response ended with status {response.get('status')}")
    try:
        answer = checks.parse_answer(checks.answer_text(response))
    except ValueError as exc:
        problems.append(f"format: {exc}")
    try:
        agent_profile, scope = scope_of(run["agent"]["name"], run["agent"]["version"])
    except Exception as exc:  # an unknown agent version: nothing can be checked against its scope
        agent_profile, scope = None, ""
        problems.append(f"access: could not read the scope of agent {run['agent']['name']} v{run['agent']['version']} "
                        f"({type(exc).__name__})")
    if agent_profile and agent_profile != profile:
        problems.append(f"access: agent {run['agent']['name']} serves the '{agent_profile}' profile, not '{profile}'")
    run["scopes"] = re.findall(r"scope eq '([^']+)'", scope)
    if answer is not None and scope:
        problems += checks.check(answer, question, run["retrievedStandards"], snapshot(None), list(snapshot(scope)), profile)
    run["result"] = answer or dict(EMPTY_ANSWER)
    run["checks"] = problems
    return run


# ---------------------------------------------------------------- the advisor run
@dataclass
class AdvisorTools:
    ask: Callable[[str, str], dict]      # (question, profile) -> the Responses API's result
    check: Callable[[dict, dict], dict]  # (response, job) -> the run record (check_answer)
    github: Callable[[], object]         # () -> the guarded GitHub client (github.GitHub)


def advise(job: dict, tools: AdvisorTools, log: Callable[[str], None]) -> dict:
    """Answer one question. Returns {"state": answered | rejected | unavailable | incomplete, ...}; never raises."""
    run_id, issue = str(job["id"]), int(job["issue"])
    started = time.monotonic()

    def say(text: str) -> None:
        log(f"advisor run {run_id}: #{issue} {text}")

    def done(state: str, pull_request: int | None = None) -> dict:
        return {"state": state, "run": run_id, "issue": issue, "pullRequest": pull_request, "seconds": seconds(started)}

    def comment_failure(text: str, what: str) -> None:
        try:
            tools.github().comment(issue, text)
            say(f"commented that {what}")
        except Exception as exc:
            say(f"couldn't comment that {what}: {describe(exc)}")

    # Ask and check: without both, nothing may reach GitHub but a note that the advisor is unavailable.
    try:
        asked = time.monotonic()
        response = tools.ask(job["question"], job["profile"])
        agent = response.get("agent_reference") or {}
        say(f"asked {agent.get('name', '?')} v{agent.get('version', '?')}: {response.get('status', '?')} in "
            f"{seconds(asked)} s")
        run = tools.check(response, job)
    except Exception as exc:
        say(f"the advisor is unavailable: {describe(exc)}")
        comment_failure(report.unavailable_markdown(run_id), "the advisor is unavailable")
        return done("unavailable")
    if run["checks"]:
        say(f"the gate rejected the answer: {len(run['checks'])} problem(s)")
    else:
        say(f"the gate passed the answer: {len(checks.cited(run['result']))} standard(s) cited, "
            f"{len(run['retrievedStandards'])} retrieved, all in the {run['profile']} scope")

    # Only now GitHub: the failed checks alone, or the ADR draft, its pull request, and the answer.
    try:
        client = tools.github()
        if run["checks"]:
            client.comment(issue, report.comment_markdown(run))
            say(f"commented the failed checks; no ADR draft; done in {seconds(started)} s")
            return done("rejected")
        branch = client.ensure_branch(issue)
        say(f"branch {branch['branch']} {'created' if branch['created'] else 'reused'}")
        commit = client.put_adr(issue, report.adr_markdown(run), f"Design: Foundry advisor ADR draft for #{issue}")
        say(f"ADR draft {'committed' if commit['created'] else 'updated'} at {commit['commit'][:7]}")
        title, body = report.pull_request_text(run, github.adr_path_for(issue))
        pull = client.open_pull_request(issue, title, body)
        say(f"pull request #{pull['number']} {'opened' if pull['created'] else 'reused'}")
        client.comment(issue, report.comment_markdown(run, pull["number"]))
        say(f"commented the answer; done in {seconds(started)} s")
        return done("answered", pull["number"])
    except Exception as exc:
        say(f"a GitHub step failed: {describe(exc)}")
        comment_failure(report.incomplete_markdown(run_id), "the ADR draft is incomplete")
        return done("incomplete")


# ---------------------------------------------------------------- the standards run (optional step)
@dataclass
class StandardsTools:
    github: Callable[[], object]                       # () -> the guarded GitHub client (github.GitHub)
    reindex: Callable[[list, dict], dict]              # (documents, spec) -> standards.sync's result
    publish: Callable[[dict], dict]                    # spec -> agents.publish's result (knowledge bases updated first)
    evaluate: Callable[[dict, list, dict, str], list]  # (spec, cases, published agents, label) -> evaluation.start's runs


def merged_commit(client, sha: str) -> str:
    """The commit to publish from: a full commit id that is already on the default branch. Unmerged commits are
    proposals; only reviewed and merged standards reach the index and the agents."""
    if not re.fullmatch(r"[0-9a-f]{40}", str(sha or "")):
        raise StepError("the push names no full commit id")
    if not client.on_default_branch(sha):
        raise StepError(f"commit {sha[:7]} is not on the default branch; only merged changes are published")
    return sha


def publish_standards(job: dict, tools: StandardsTools, log: Callable[[str], None]) -> dict:
    """Publish one merged commit. Returns {"state": done | stopped, "step": ...}; never raises. A step that fails stops
    the ones after it, so the agents are never published, nor evaluated, from a partly indexed commit."""
    run_id, sha = str(job["id"]), str(job.get("sha", ""))
    started, step = time.monotonic(), "check the commit"

    def say(text: str) -> None:
        log(f"standards run {run_id}: {text}")

    try:
        client = tools.github()
        merged_commit(client, sha)
        say(f"{sha[:7]} is on {client.default_branch()}; {len(job.get('files') or [])} changed file(s) in the solution")
        step = "read the commit"
        text = client.read_text(f"{SOLUTION}/agent.yaml", sha)
        if text is None:
            raise StepError(f"agent.yaml not found at {sha[:7]}")
        spec = agents.load_spec(text)
        docs, skipped = standards.parse(client.read_folder(standards.SOURCE_DIR, sha), spec)
        cases = [json.loads(line) for line in (client.read_text(f"{SOLUTION}/eval_cases.jsonl", sha) or "").splitlines()
                 if line.strip()]
        step = "re-index the standards"
        result = tools.reindex(docs, spec)
        say(f"re-indexed {result['index']}: {result['approved']} standards ({len(result['new'])} new, "
            f"{len(result['changed'])} changed, {len(result['removed'])} removed, {len(result['failed'])} failed)"
            + (f"; skipped {', '.join(skipped)}: not approved" if skipped else ""))
        if result["failed"]:  # the search service accepted the batch but refused some documents
            raise StepError(f"{len(result['failed'])} standard(s) were not indexed: {', '.join(result['failed'][:10])}")
        step = "publish the agents"
        published = tools.publish(spec)
        say("agents " + ", ".join(f"{a['name']} v{a['version']} ({'reused' if a['reused'] else 'new version'})"
                                  for a in published.values()))
        step = "start the evaluation"
        runs = tools.evaluate(spec, cases, published, f"commit {sha[:7]}")
        say(f"evaluation started in Foundry: {len(runs)} run(s), {sum(len(r['cases']) for r in runs)} case(s); "
            f"done in {seconds(started)} s")
    except Exception as exc:
        say(f"stopped, couldn't {step}: {describe(exc)}")
        return {"state": "stopped", "step": step, "run": run_id, "sha": sha, "seconds": seconds(started)}
    return {"state": "done", "run": run_id, "sha": sha, "seconds": seconds(started)}
