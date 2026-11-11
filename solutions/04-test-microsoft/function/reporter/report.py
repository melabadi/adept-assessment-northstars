"""The report that the function posts to GitHub for a finished Azure Load Testing run: its verdict and its Markdown.

The run comes from Azure Load Testing (name, result, timing, pass/fail criteria, and per-request statistics), and the
server side from report.kql on the Log Analytics workspace that holds RequestHub's Application Insights data. The
report never contains host names, resource names with their random suffix, GUIDs, or subscription details: GitHub
Issues are visible to everyone who can read the repository. It names the run's id only when the id is readable, as
the ones the README's commands and candidate.py give; the portal gives a run a GUID, which the report leaves out.

The build under test: the API's telemetry names the revision that served each request, and the report lists the
revisions it found in the run's window. A run started by candidate.py is a candidate run: its description names a
commit and the API revision it was deployed as ("Commit <sha> on API revision c1a2b3c4 for Issue #284"), and the report
says whether the telemetry confirms that revision. A description is written by someone who may start load tests;
only a 40-character commit, a revision suffix, and an Issue number are taken from it.

Verdicts (`outcome`):
  accepted          PASSED, and no server request carried the rehearsal slowdown. Only this one closes an Issue.
  warning           PASSED while the slowdown was still on: it proves nothing about a fix.
  expected-failure  FAILED, and requests carried the slowdown: the rehearsal of the gate.
  regression        FAILED with no injected delay in the telemetry: a real problem.
  no-telemetry      Application Insights has no server requests for the run yet.
  no-verdict        the run ended without PASSED or FAILED.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

QUERY = Path(__file__).with_name("report.kql").read_text(encoding="utf-8")
FINAL = ("PASSED", "FAILED")
# The newest request in the telemetry must reach the run's last 90 seconds before the report counts as complete.
TELEMETRY_LAG = timedelta(seconds=90)
RUN_NAME = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
REVISION = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
DESCRIBED_COMMIT = re.compile(r"\bcommit\s+([0-9a-f]{40})\b", re.I)
DESCRIBED_REVISION = re.compile(r"\brevision\s+([a-z0-9][a-z0-9-]*)", re.I)
DESCRIBED_ISSUE = re.compile(r"\bissue\s+#(\d{1,7})\b", re.I)
SAMPLING_NOTE = ("Application Insights keeps only a sample of the API's requests under load, so these counts can be lower "
                 "than the client's.")
VERDICTS = {
    "accepted": "**Accepted:** the journey met every criterion, and no server request carried the rehearsal slowdown.",
    "warning": ("**Passed with the slowdown on:** the journey met every criterion, but {delayed} server requests carried "
                "`requesthub.fault.queue_delay_ms`, so this run does not prove a fix. The function does not close a "
                "load-test Issue on it."),
    "expected-failure": ("**Expected failure:** the API ran with the rehearsal slowdown ({delayed} server requests carried "
                         "`requesthub.fault.queue_delay_ms`), and the criteria caught it. This run proves the gate works; "
                         "it is not an acceptance run."),
    "regression": "**Regression:** no injected delay in the telemetry for this window. Find the cause before you ship.",
    "no-telemetry": ("**Telemetry not available:** Application Insights has no server requests for this run yet, so the "
                     "report cannot tell a rehearsal from a regression, and the function does not close a load-test Issue "
                     "on it. To report the run again within an hour of its end, see Troubleshooting in "
                     "`solutions/04-test-microsoft/README.md`."),
    "no-verdict": "**{result}:** the run did not produce a verdict.",
}


def parse_time(value) -> datetime | None:
    """A time from Azure or GitHub (ISO 8601, with Z or an offset, up to 7 fractional digits), or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def server_query(started: datetime, ended: datetime) -> str:
    """report.kql for one run. Only datetime objects reach the query, never text from a request."""
    def kql(moment: datetime) -> str:
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return QUERY.replace("__START__", kql(started)).replace("__END__", kql(ended))


def telemetry_ready(rows: list[dict], ended: datetime) -> bool:
    """Whether Application Insights holds requests from the run's last 90 seconds."""
    newest = [parse_time(row.get("newest")) for row in rows]
    newest = [moment for moment in newest if moment]
    return bool(newest) and max(newest) >= ended - TELEMETRY_LAG


def candidate(run: dict) -> dict:
    """What a candidate run's description says it tests: {"commit": sha, "revision": suffix, "issue": number}, with
    "revision" and "issue" only when named. Empty when the description names no commit."""
    text = str(run.get("description") or "")
    commit = DESCRIBED_COMMIT.search(text)
    if not commit:
        return {}
    found: dict = {"commit": commit.group(1).lower()}
    revision = DESCRIBED_REVISION.search(text)
    if revision and REVISION.fullmatch(revision.group(1).lower()):
        found["revision"] = revision.group(1).lower()
    issue = DESCRIBED_ISSUE.search(text)
    if issue and int(issue.group(1)) > 0:
        found["issue"] = int(issue.group(1))
    return found


def revisions(rows: list[dict]) -> list[str]:
    """The API revisions (their suffixes) that served the run's requests, from report.kql's `revisions` column, which
    Log Analytics returns as JSON text."""
    found: set[str] = set()
    for row in rows:
        value = row.get("revisions")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = []
        if isinstance(value, list):
            found |= {item for item in value if isinstance(item, str) and REVISION.fullmatch(item)}
    return sorted(found)


def run_name(run: dict) -> str:
    """The run's id when it is readable (candidate-1a2b3c4-20261110-051500), else '' (the portal's runs get a GUID)."""
    value = str(run.get("testRunId") or "")
    return value if RUN_NAME.fullmatch(value) and not GUID.search(value) else ""


def _names(items: list[str]) -> str:
    quoted = [f"`{item}`" for item in items]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


def build_line(run: dict, rows: list[dict]) -> str:
    """Which build the run tested: the commit and revision a candidate run names, checked against the revisions that
    served the run's requests. Empty when neither is known."""
    claim, served = candidate(run), revisions(rows)
    came_from = (f"the server requests in the run's window came from {'revision' if len(served) == 1 else 'revisions'} "
                 f"{_names(served)}") if served else ""
    if not claim:
        return f"**API revision:** {came_from}." if served else ""
    commit, named = claim["commit"], claim.get("revision")
    if named is None:
        return (f"**Build under test:** commit {commit}, as the run's description says; it names no API revision. "
                + (f"{came_from[0].upper()}{came_from[1:]}." if served else
                   "No server request in the run's window shows the revision yet."))
    if not served:
        return (f"**Build under test:** commit {commit} on API revision `{named}`, as the run's description says. No "
                "server request in the run's window confirms the revision yet.")
    if served == [named]:
        return (f"**Build under test:** commit {commit} on API revision `{named}`. Every server request in the run's "
                "window came from that revision.")
    return (f"**Build under test:** the run's description names commit {commit} on API revision `{named}`, but "
            f"{came_from}. This run does not show how that commit performs.")


def _count(rows: list[dict], column: str) -> int:
    return sum(int(row.get(column) or 0) for row in rows)


def outcome(result: str | None, rows: list[dict]) -> str:
    """The verdict of a run from its result and the server rows (see the module docstring)."""
    if result not in FINAL:
        return "no-verdict"
    if _count(rows, "requests") == 0:
        return "no-telemetry"
    delayed = _count(rows, "delayed")
    if result == "PASSED":
        return "warning" if delayed else "accepted"
    return "expected-failure" if delayed else "regression"


def whole_ms(value) -> str:
    """Whole milliseconds with a thousands separator, rounding halves up: 1560.5 -> '1,561'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{math.floor(number + 0.5):,}"


def one_decimal(value) -> str:
    try:
        return str(Decimal(str(float(value))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    except (TypeError, ValueError):
        return ""


def _criteria_lines(run: dict) -> list[str]:
    metrics = ((run.get("passFailCriteria") or {}).get("passFailMetrics") or {}).values()
    lines = []
    for c in metrics:
        request = c.get("requestName") or "all requests"
        unit = "%" if c.get("clientMetric") == "error" else " ms"
        lines.append(f"| {request} {c.get('aggregate')}({c.get('clientMetric')}) | {c.get('condition')} "
                     f"{whole_ms(c.get('value'))}{unit} | {whole_ms(c.get('actualValue'))}{unit} | {c.get('result')} |")
    return sorted(lines)


def _client_line(name: str, s: dict) -> str:
    return (f"| {name} | {int(float(s.get('sampleCount') or 0))} | {one_decimal(s.get('errorPct') or 0)}% | "
            f"{whole_ms(s.get('medianResTime'))} | {whole_ms(s.get('pct2ResTime'))} | {whole_ms(s.get('pct3ResTime'))} |")


def render(run: dict, rows: list[dict], verdict: str, resource_group: str) -> str:
    """The Markdown report for the Issue."""
    result = str(run.get("testResult") or "")
    name = run.get("displayName") or ""
    duration = int(float(run.get("duration") or 0) / 1000)
    readable = run_name(run)
    run_part = f" · run `{readable}`" if readable else ""
    statistics = run.get("testRunStatistics") or {}
    client = sorted(_client_line(key, value) for key, value in statistics.items() if key != "Total")
    total = [_client_line("Total", statistics["Total"])] if "Total" in statistics else []
    server = sorted(f"| {row.get('Name')} | {int(row.get('requests') or 0)} | {int(row.get('server_errors') or 0)} | "
                    f"{int(row.get('denied') or 0)} | {whole_ms(row.get('p95'))} | {int(row.get('delayed') or 0)} |"
                    for row in rows)
    parts = [
        f"## Load test: {name}",
        f"**{result}** · test `{run.get('testId')}`{run_part} · {run.get('virtualUsers', '')} virtual users · {duration} s",
        VERDICTS[verdict].format(delayed=_count(rows, "delayed"), result=result),
        *filter(None, [build_line(run, rows)]),
        "### Pass/fail criteria\n\n| Criterion | Fails when | Actual | Result |\n|---|---|---|---|\n"
        + "\n".join(_criteria_lines(run)),
        "### Client side (Azure Load Testing)\n\n| Request | Requests | Errors | p50 ms | p95 ms | p99 ms |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(client + total),
        "### Server side (Application Insights, same window)",
    ]
    if server:
        parts.append("| Operation | Requests | Server errors | Denied (401/403) | p95 ms | With injected delay |\n"
                     "|---|---|---|---|---|---|\n" + "\n".join(server))
        parts.append(SAMPLING_NOTE)
    else:
        parts.append("No server-side telemetry for this window yet.")
    parts.append(f"Open the run in the Azure portal for client and server metrics side by side, and its AI insights: "
                 f"resource group `{resource_group}` › the Load Testing resource › Tests › `{run.get('testId')}` › `{name}`.")
    return "\n\n".join(parts)
