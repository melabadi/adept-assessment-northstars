#!/usr/bin/env python3
"""Write the Azure pull request reviewer's review comment (Develop phase, Microsoft track).

The reviewer's Logic App runs this script last, in the judge's sandbox session: the session where the team's rules were
checked and where the pull request's code never ran. It reads three files:

  judge.json          what review_rules.py wrote there, before any of the pull request's code ran anywhere
  review-input.json   what the Logic App uploads at the end:
                        pr            number, title, head and base commits
                        run           the Logic App run id, for the footer
                        sandbox       run_change.sh's summary (text). The pull request's own code ran there, so it is
                                      evidence, not a verdict.
                        agent_status  the Logic App status of the agent call
                        checker_ref   where the checker came from (main)
  agent.json          the Microsoft Foundry Responses API result of the reviewer agent, or the error that stopped it

It prints one JSON object: {"markdown": the review body, "agent": the agent's answer or null, "agent_error": text or
null, "tool_calls": how many sandbox commands the agent ran}.

The review has three parts, always in this order, and nothing in the second or third part can change the first:
  1. Team rules: the checker's verdict line and its own Markdown table, copied from judge.json word for word.
  2. Sandbox: the build and test results.
  3. Commentary from the reviewer agent: summary, observations, notes on rule results, what the person should decide.
Text that came from the pull request or from the model is made inert: one line, no HTML, no @mentions. GUIDs and Azure
host names are replaced, so not even a manipulated agent can post tenant details. Error messages are never posted, only
error codes; the details stay in the Logic App's run history.

Usage
  python3 format_review.py --judge judge.json --input review-input.json --agent agent.json
  python3 format_review.py --judge judge.json --input review-input.json --agent agent.json --markdown   # only the body

Exit codes: 0 written, 2 unreadable judge.json (the review can't be written without the checker's verdicts).
Standard library only (Python 3.10+).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RULE_IDS = ("approval-authority", "authorization-in-workflow", "contract-additive", "tests-with-changes", "synthetic-data")
SEVERITY = {"concern": "❗ **Concern**", "warning": "⚠️ **Warning**", "info": "ℹ️ **Note**"}
MAX_OBSERVATIONS = 8
CODE_SPAN = re.compile(r"(`[^`\n]*`)")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
AZURE_HOST = re.compile(r"\b[\w.-]+\.(?:azure\.com|azure\.net|windows\.net|dynamicsessions\.io|azurecontainerapps\.io|"
                        r"azurewebsites\.net|azurecr\.io)\b", re.I)
SECRET = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
                    r"\.[A-Za-z0-9_-]{10,})")


def redact(text: str) -> str:
    """Remove what must never reach a public comment, whatever the agent was told to write."""
    text = SECRET.sub("<secret removed>", text)
    text = GUID.sub("<id removed>", text)
    return AZURE_HOST.sub("<host removed>", text)


def plain(value: object, limit: int = 500) -> str:
    """Untrusted text as inert Markdown on one line: no HTML, no @mentions. Code spans are kept as they are."""
    text = redact(" ".join(str(value or "").split()))
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    parts = CODE_SPAN.split(text)
    for i in range(0, len(parts), 2):  # even parts are outside code spans
        parts[i] = parts[i].replace("<", "&lt;").replace(">", "&gt;")
        parts[i] = re.sub(r"@(?=\w)", "@\u200b", parts[i])
    return "".join(parts)


def code(value: object, limit: int = 160) -> str:
    """A file name or test name from the pull request, as a code span it can't break out of."""
    text = redact(" ".join(str(value or "").split())).replace("`", "'")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"`{text}`" if text else ""


def duration(seconds: object) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        return ""
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


# ---------------------------------------------------------------- part 1: the team's rules

def rules_section(judge: dict, checker_ref: str) -> list[str]:
    failed = judge["summary"]["rules_failed"]
    total = len(judge["rules"])
    verdict = f"✅ all {total} passed" if not failed else f"❌ {failed} of {total} failed"
    return [
        f"**Team rules: {verdict}.** Checked by the rule checker from `{plain(checker_ref, 60)}` before any of this pull "
        "request's code ran. The agent below can explain a result but can't change it.",
        "",
        judge["markdown"],
    ]


# ---------------------------------------------------------------- part 2: the sandbox

def counts(tests: object) -> str:
    """'50 of 50 passed' or '1 of 14 failed'."""
    if not isinstance(tests, dict) or not isinstance(tests.get("total"), int):
        return ""
    failed, total = tests.get("failed"), tests["total"]
    if isinstance(failed, int) and failed:
        return f"{failed} of {total} failed"
    return f"{tests['passed']} of {total} passed" if isinstance(tests.get("passed"), int) else f"{total} tests"


def failed_names(tests: object) -> str:
    names = tests.get("failed_tests", []) if isinstance(tests, dict) else []
    shown = [code(n) for n in names[:5] if isinstance(n, str)]
    return f" Failed: {', '.join(shown)}{' …' if len(names) > 5 else ''}." if shown else ""


def sandbox_section(raw: object) -> list[str]:
    lines = ["**Sandbox:** the pull request's own code, built and tested in an Azure Container Apps session. These results "
             "come from that code, so they are evidence, not a verdict."]
    try:
        summary = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        summary = None
    if not isinstance(summary, dict) or "api" not in summary:
        state = summary.get("state") if isinstance(summary, dict) else None
        lines += ["", "- The build didn't finish in time; no test results." if state == "not-finished"
                  else "- No test results came back from the sandbox."]
        return lines
    api, web = summary.get("api") or {}, summary.get("web") or {}
    took = f" ({duration(api.get('seconds'))})" if duration(api.get("seconds")) else ""
    if api.get("status") == "passed":
        api_line = f"✅ {counts(api)}{took}"
    elif api.get("status") == "failed":
        api_line = f"❌ {counts(api) or 'failed, see the log'}{took}.{failed_names(api)}"
    else:
        api_line = "not run (this change has no API solution)"
    lines += ["", f"- API integration tests: {api_line}"]
    web_status = web.get("status")
    if web_status in ("passed", "flaky", "failed"):
        typecheck = "✅ passed" if web.get("typecheck") == "passed" else "❌ failed"
        tests, rerun = web.get("tests"), web.get("rerun")
        if web_status == "passed":
            unit = f"✅ {counts(tests)}"
        elif web_status == "flaky":
            unit = f"⚠️ flaky: {counts(tests)}, then all passed on a rerun.{failed_names(tests)}"
        else:
            unit = f"❌ {counts(rerun or tests)}, also on a rerun.{failed_names(rerun or tests)}"
        lines.append(f"- Web UI: typecheck {typecheck} · unit tests {unit}")
    elif web_status == "error":
        lines.append("- Web UI: ❌ dependencies didn't install, so nothing ran.")
    else:
        lines.append("- Web UI: not run (this change has no web UI)")
    times = [f"toolchain setup {duration(summary.get('setup_seconds'))}" if duration(summary.get("setup_seconds")) else "",
             f"total {duration(summary.get('seconds'))}" if duration(summary.get("seconds")) else ""]
    if any(times):
        lines.append("- " + " · ".join(t for t in times if t).capitalize())
    return lines


# ---------------------------------------------------------------- part 3: the agent

def agent_answer(response: object, status: object) -> tuple[dict | None, str | None, int, str]:
    """(answer, error, tool calls, who) from the Responses API result. Only error codes are kept, never messages."""
    if not isinstance(response, dict):
        return None, f"the call didn't complete ({plain(status, 40) or 'no response'})", 0, ""
    ref = response.get("agent_reference") if isinstance(response.get("agent_reference"), dict) else {}
    who = " ".join(filter(None, [f"v{plain(ref.get('version'), 10)}" if ref.get("version") else "",
                                 f"on {plain(response.get('model'), 40)}" if isinstance(response.get("model"), str) else ""]))
    output = response.get("output") if isinstance(response.get("output"), list) else []
    tool_calls = sum(1 for item in output if isinstance(item, dict) and str(item.get("type", "")).endswith("_call"))
    error = response.get("error")
    if isinstance(error, dict) and error:
        return None, f"the agent returned an error ({plain(error.get('code') or 'unknown', 60)})", tool_calls, who
    if response.get("status") != "completed":
        return None, f"the agent's response is {plain(response.get('status') or status or 'missing', 40)}", tool_calls, who
    texts = [part.get("text") for item in output if isinstance(item, dict) and item.get("type") == "message"
             for part in item.get("content") or [] if isinstance(part, dict) and part.get("type") == "output_text"]
    if not texts:
        return None, "the agent returned no answer", tool_calls, who
    try:
        answer = json.loads(texts[-1])
    except ValueError:
        return None, "the agent's answer wasn't valid JSON", tool_calls, who
    if not isinstance(answer, dict) or not all(isinstance(answer.get(k), str) for k in ("summary", "tests_note", "for_the_person")):
        return None, "the agent's answer didn't match its schema", tool_calls, who
    answer["observations"] = [o for o in answer.get("observations") or []
                              if isinstance(o, dict) and o.get("severity") in SEVERITY and isinstance(o.get("text"), str)]
    answer["rule_notes"] = [n for n in answer.get("rule_notes") or []
                            if isinstance(n, dict) and n.get("rule_id") in RULE_IDS and isinstance(n.get("note"), str)]
    return answer, None, tool_calls, who


def agent_section(answer: dict | None, error: str | None, tool_calls: int, version: str, agent_name: str,
                  titles: dict[str, str]) -> list[str]:
    who = f"`{plain(agent_name, 80)}`{' ' + version if version else ''} in Microsoft Foundry"
    if answer is None:
        return [f"**Commentary from the reviewer agent** ({who}): not available, because {error}. The rule results and "
                "sandbox results above stand on their own."]
    ran = f" It ran {tool_calls} read-only command{'s' if tool_calls != 1 else ''} in the sandbox." if tool_calls else ""
    lines = [f"**Commentary from the reviewer agent** ({who}). Advisory.{ran}", "", f"> {plain(answer['summary'], 800)}", ""]
    for o in answer["observations"][:MAX_OBSERVATIONS]:
        where = code(f"{o['file']}:{o['line']}" if o.get("file") and isinstance(o.get("line"), int) else o.get("file"))
        lines.append(f"- {SEVERITY[o['severity']]}" + (f" · {where}" if where else "") + f" · {plain(o['text'])}")
    if len(answer["observations"]) > MAX_OBSERVATIONS:
        lines.append(f"- … {len(answer['observations']) - MAX_OBSERVATIONS} more not shown.")
    if answer["rule_notes"]:
        lines += ["", "On the rule results:"]
        lines += [f"- **{titles.get(n['rule_id'], n['rule_id'])}:** {plain(n['note'])}" for n in answer["rule_notes"][:5]]
    lines += ["", f"**Tests:** {plain(answer['tests_note'])}", "", f"**For the person who decides:** {plain(answer['for_the_person'])}"]
    return lines


# ---------------------------------------------------------------- the review

def compose(judge: dict, request: dict) -> dict:
    pr = request.get("pr") or {}
    answer, error, tool_calls, version = agent_answer(request.get("agent"), request.get("agent_status"))
    titles = {r["id"]: r["title"] for r in judge["rules"]}
    run = plain(request.get("run"), 80)
    head = str(pr.get("head") or "")
    body = ["### Azure pull request review · advisory", ""]
    body += rules_section(judge, str(request.get("checker_ref") or "main"))
    body += [""] + sandbox_section(request.get("sandbox"))
    body += [""] + agent_section(answer, error, tool_calls, version, str(request.get("agent_name") or "reviewer agent"), titles)
    body += ["", "---",
             f"<sub>The Azure pull request reviewer never approves and never requests changes; a person decides. "
             f"Commit `{head[:7]}` · Logic App run `{run}` · rule checker v{plain(judge['checker']['version'], 10)}.</sub>",
             "", f"<!-- azure-pr-reviewer sha={re.sub(r'[^0-9a-f]', '', head)} run={re.sub(r'[^0-9A-Za-z]', '', run)} -->"]
    return {"markdown": "\n".join(body), "agent": answer, "agent_error": error, "tool_calls": tool_calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--judge", type=Path, required=True, help="judge.json, written by review_rules.py")
    parser.add_argument("--input", type=Path, required=True, help="review-input.json, uploaded by the Logic App")
    parser.add_argument("--agent", type=Path, help="agent.json: the agent's Responses API result, uploaded by the Logic App")
    parser.add_argument("--markdown", action="store_true", help="Print only the review body")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        judge = json.loads(args.judge.read_text(encoding="utf-8"))
        judge["rules"], judge["summary"], judge["markdown"]  # the review can't be written without the verdicts
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": f"cannot read the checker's verdicts: {type(exc).__name__}"}))
        return 2
    request = read_json(args.input)
    request = request if isinstance(request, dict) else {}
    if args.agent:
        request["agent"] = read_json(args.agent)
    result = compose(judge, request)
    print(result["markdown"] if args.markdown else json.dumps(result, ensure_ascii=False))
    return 0


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
