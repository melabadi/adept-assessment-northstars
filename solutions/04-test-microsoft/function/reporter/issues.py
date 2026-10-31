"""Which GitHub Issue a finished run belongs to, and what the function does with it.

One Issue per test tracks a failing journey. Its title starts with `[load-test <test id>] `, and it carries the
`load-test` label. A failing run opens it, or comments on it when it is already open. A passing run closes it only when
the run started after the Issue opened and the report accepts the run (no injected delay, telemetry present);
otherwise it says why the Issue stays open. A replayed or repeated delivery of a run changes nothing: every post ends
with a hidden marker naming the run (by a short hash, never its id) and the verdict, and the function looks for it first.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .report import parse_time

LABEL = "load-test"
TITLE = "[load-test {test_id}] RequestHub journey missed its performance criteria"


def title_prefix(test_id: str) -> str:
    return f"[load-test {test_id}] "


def choose(issues: list[dict], test_id: str) -> dict | None:
    """The open Issue for this test: the first whose title starts with the full prefix. Pull requests don't count."""
    prefix = title_prefix(test_id)
    for issue in issues or []:
        if issue.get("pull_request") is None and str(issue.get("title") or "").startswith(prefix):
            return issue
    return None


def run_key(test_run_id: str) -> str:
    """A short, stable name for a run that is safe to put in an Issue (run ids can be GUIDs)."""
    return hashlib.sha256(test_run_id.encode("utf-8")).hexdigest()[:12]


def marker(test_run_id: str, verdict: str) -> str:
    return f"<!-- load-test-report: {run_key(test_run_id)} {verdict} -->"


@dataclass(frozen=True)
class Action:
    """What to do on GitHub: open, comment, close (comment if there is a body, then close), keep-open (comment), none."""
    kind: str
    reason: str
    number: int | None = None
    title: str | None = None
    body: str | None = None


def decide(run: dict, verdict: str, report: str, issue: dict | None, earlier: list[str], test_id: str,
           resource_group: str) -> Action:
    """The GitHub change for a run. `earlier` holds the open Issue's body and its comments since the run started."""
    test_run_id = str(run.get("testRunId") or "")
    name = run.get("displayName") or test_run_id
    tag = marker(test_run_id, verdict)
    already = any(tag in text for text in earlier)
    reported_before = any(f"load-test-report: {run_key(test_run_id)} " in text for text in earlier)
    result = run.get("testResult")
    if result == "PASSED" and issue is not None and verdict == "accepted" and already:
        # The closing comment is there, but closing failed last time: close without commenting again.
        return Action("close", "the run's closing comment is already on the Issue", issue["number"])
    if already:
        return Action("none", "this run's report is already on the Issue")
    if result == "FAILED":
        if issue is None:
            body = (f"`{name}` missed its performance criteria. Azure Load Testing sent the finished run to an Azure "
                    f"Function in resource group `{resource_group}`, which wrote this report. The function closes this "
                    f"Issue when a run passes again.\n\n{report}\n\n{tag}")
            return Action("open", "no Issue is open for this test", title=TITLE.format(test_id=test_id), body=body)
        lead = (f"`{name}`: the report again, with the telemetry that has arrived since." if reported_before
                else f"`{name}` also missed its performance criteria.")
        return Action("comment", "an Issue is already open for this test", issue["number"], body=f"{lead}\n\n{report}\n\n{tag}")
    if result == "PASSED":
        if issue is None:
            return Action("none", "no Issue is open for this test")
        started, opened = parse_time(run.get("startDateTime")), parse_time(issue.get("created_at"))
        if not (started and opened and started > opened):
            return Action("none", "the run started before the open Issue was created, so it does not close it")
        if verdict == "accepted":
            return Action("close", "the run passed and the report accepts it", issue["number"],
                          body=f"`{name}` passed every criterion. Closing.\n\n{report}\n\n{tag}")
        return Action("keep-open", f"the run passed, but the report's verdict is {verdict}", issue["number"],
                      body=(f"`{name}` passed its criteria, but the report does not accept it, so this Issue stays open."
                            f"\n\n{report}\n\n{tag}"))
    return Action("none", "the run has no verdict")
