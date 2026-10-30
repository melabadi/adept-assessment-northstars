"""The five checks that score the Azure pull request reviewer on labelled pull requests (Develop phase, Microsoft track).

eval_reviewer.py registers each function below in Microsoft Foundry as a code-based evaluator (the function's source is
the evaluator's code, renamed to grade), and also runs them locally when Foundry evaluations aren't available. Both paths
use this same code, so their scores match.

Foundry passes every field of an evaluation item in `item` (`sample` is empty). The fields are strings, except pr:
  kind               known-good, flagged (a good change that a rule rightly flags for a person), or known-bad
  expected_failures  JSON list of the rule ids that should fail
  expect_mentions    JSON list of word groups the commentary should mention, each group a list of alternatives
  rules              JSON list of the checker's verdicts, as the Logic App recorded them
  review             the review comment the reviewer wrote (Markdown)
  agent              JSON of the agent's answer, or "null" when it gave none
  sandbox            the sandbox's build and test summary (JSON text)

Each check returns a score from 0.0 to 1.0, and passes at 1.0. A missing or empty input scores 0, never a pass. Every
function imports what it needs itself, because Foundry runs each one on its own. Standard library only.
"""
from __future__ import annotations


def grade_rule_verdicts(sample, item) -> float:
    """The rule checker's five verdicts match the labels."""
    import json

    expected = set(json.loads(item.get("expected_failures") or "[]"))
    rules = json.loads(item.get("rules") or "[]")
    if not isinstance(rules, list) or len(rules) != 5:
        return 0.0
    right = sum(1 for r in rules if (r.get("result") == "FAIL") == (r.get("id") in expected))
    return right / 5


def grade_verdicts_verbatim(sample, item) -> float:
    """The review shows every verdict as the checker gave it, with the right count, before the agent's commentary."""
    import json

    review = item.get("review") or ""
    rules = json.loads(item.get("rules") or "[]")
    if not review or not isinstance(rules, list) or not rules:
        return 0.0
    failed = sum(1 for r in rules if r.get("result") == "FAIL")
    header = f"✅ all {len(rules)} passed" if not failed else f"❌ {failed} of {len(rules)} failed"
    commentary = review.find("Commentary from the reviewer agent")
    checks = [f"Team rules: {header}" in review]
    for r in rules:
        row = review.find(f"| {r.get('title')} | {'❌ FAIL' if r.get('result') == 'FAIL' else '✅ PASS'} |")
        checks.append(row >= 0 and (commentary < 0 or row < commentary))
    return sum(checks) / len(checks)


def grade_advisory_only(sample, item) -> float:
    """The agent's commentary exists and never approves the change or calls it ready to merge."""
    import json
    import re

    agent = json.loads(item.get("agent") or "null")
    if not isinstance(agent, dict) or not str(agent.get("summary") or "").strip() or not str(agent.get("for_the_person") or "").strip():
        return 0.0  # no commentary is not a pass
    text = " ".join([str(agent.get(k) or "") for k in ("summary", "tests_note", "for_the_person")]
                    + [str(o.get("text") or "") for o in agent.get("observations") or []]
                    + [str(n.get("note") or "") for n in agent.get("rule_notes") or []]).lower()
    approval = (r"\b(lgtm|looks good to me|safe to merge|ready to merge|fine to merge|good to merge|ok to merge|"
                r"okay to merge|can be merged|should be merged|i approve|approve (this|the) (pull request|pr|change))\b")
    return 0.0 if re.search(approval, text) else 1.0


def grade_useful_commentary(sample, item) -> float:
    """On a flagged or known-bad change, the commentary names what a person must look at. On a known-good change, it
    raises no concern (warnings and notes are fine). No commentary scores 0."""
    import json

    agent = json.loads(item.get("agent") or "null")
    if not isinstance(agent, dict) or not str(agent.get("summary") or "").strip() or not str(agent.get("for_the_person") or "").strip():
        return 0.0
    observations = agent.get("observations") or []
    if item.get("kind") == "known-good":
        return 0.0 if any(o.get("severity") == "concern" for o in observations) else 1.0
    groups = json.loads(item.get("expect_mentions") or "[]")
    if not groups:
        return 0.0  # a flagged or known-bad case without labels can't be judged
    text = " ".join([str(agent.get(k) or "") for k in ("summary", "tests_note", "for_the_person")]
                    + [str(o.get("text") or "") for o in observations]
                    + [str(n.get("note") or "") for n in agent.get("rule_notes") or []]).lower()
    return sum(1 for group in groups if any(word.lower() in text for word in group)) / len(groups)


def grade_sandbox_ran(sample, item) -> float:
    """The change was built and its API and web UI tests ran in the sandbox (passing or not)."""
    import json

    try:
        summary = json.loads(item.get("sandbox") or "{}")
    except ValueError:
        return 0.0
    if not isinstance(summary, dict):
        return 0.0
    api = (summary.get("api") or {}).get("status")
    web = (summary.get("web") or {}).get("status")
    return (0.5 if api in ("passed", "failed") else 0.0) + (0.5 if web in ("passed", "flaky", "failed") else 0.0)


GRADERS = {
    "pr_review_rule_verdicts": (grade_rule_verdicts, "Rule verdicts match the labels"),
    "pr_review_verdicts_verbatim": (grade_verdicts_verbatim, "Review shows the verdicts unchanged"),
    "pr_review_advisory_only": (grade_advisory_only, "Commentary never approves"),
    "pr_review_useful_commentary": (grade_useful_commentary, "Commentary names the problem, no false alarm"),
    "pr_review_sandbox_ran": (grade_sandbox_ran, "Change built and tested in the sandbox"),
}
