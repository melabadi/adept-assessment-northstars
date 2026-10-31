"""The report that the function posts to GitHub for a finished Azure Load Testing run: its verdict and its Markdown.

The run comes from Azure Load Testing (name, result, timing, pass/fail criteria, and per-request statistics), and the
server side from report.kql on the Log Analytics workspace that holds RequestHub's Application Insights data. The
report never contains host names, resource names with their random suffix, ids, or subscription details: GitHub Issues
are visible to everyone who can read the repository.

Verdicts (`outcome`):
  accepted          PASSED, and no server request carried the rehearsal slowdown. Only this one closes an Issue.
  warning           PASSED while the slowdown was still on: it proves nothing about a fix.
  expected-failure  FAILED, and requests carried the slowdown: the rehearsal of the gate.
  regression        FAILED with no injected delay in the telemetry: a real problem.
  no-telemetry      Application Insights has no server requests for the run yet.
  no-verdict        the run ended without PASSED or FAILED.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

QUERY = Path(__file__).with_name("report.kql").read_text(encoding="utf-8")
FINAL = ("PASSED", "FAILED")
# The newest request in the telemetry must reach the run's last 90 seconds before the report counts as complete.
TELEMETRY_LAG = timedelta(seconds=90)
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
    statistics = run.get("testRunStatistics") or {}
    client = sorted(_client_line(key, value) for key, value in statistics.items() if key != "Total")
    total = [_client_line("Total", statistics["Total"])] if "Total" in statistics else []
    server = sorted(f"| {row.get('Name')} | {int(row.get('requests') or 0)} | {int(row.get('server_errors') or 0)} | "
                    f"{int(row.get('denied') or 0)} | {whole_ms(row.get('p95'))} | {int(row.get('delayed') or 0)} |"
                    for row in rows)
    parts = [
        f"## Load test: {name}",
        f"**{result}** · test `{run.get('testId')}` · {run.get('virtualUsers', '')} virtual users · {duration} s",
        VERDICTS[verdict].format(delayed=_count(rows, "delayed"), result=result),
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
