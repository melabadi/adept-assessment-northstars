"""The five checks that score the Azure pull request reviewer on labelled pull requests (Develop phase, Microsoft track).

eval_reviewer.py registers each function below in Microsoft Foundry as a code-based evaluator (the function's source is
the evaluator's code, renamed to grade), and also runs them locally when Foundry evaluations aren't available. Both paths
use this same code, so their scores match.

Foundry passes every field of an evaluation item in `item` (`sample` is empty). The fields are strings, except pr:
  kind               known-good, flagged (a good change that a rule rightly flags for a person), or known-bad
  expected_failures  JSON list of the rule ids that should fail
  expect_findings    JSON list of what the commentary must state, each {"states": [claims], "file": path}: a claim is a
                     few words that say the problem ("sql injection", "alter* the query"), the file is where it is
  rules              JSON list of the checker's verdicts, as the reviewer returned them
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
    """On a flagged or known-bad change, the commentary states each labelled finding and points at where it is. Half
    of a finding's credit is the conclusion: a known-bad finding must be a concern that asserts the problem, and a
    flagged one may be stated anywhere in the commentary. The other half is the evidence: an observation in the
    finding's file, or a rule note that names it. A denial that uses the right words ("There is no SQL injection here")
    states nothing, so the right file alone earns half, which fails. On a known-good change, the commentary raises no
    concern (warnings and notes are fine). No commentary scores 0.

    A claim is a few words in order, at most three words apart; a trailing * matches any ending. A clause (text between
    punctuation, or before but, because, if, which, without, ...) asserts it unless the clause starts with a condition
    or a comparison (if, unless, until, before, than, ...) or holds an odd number of negations: not, no, never, ..., and
    the verbs that deny what they govern (prevents, avoids, stops, protects, guards, forbids, excludes, ...). So "The
    query prevents SQL injection" states no injection, like "There is no SQL injection here", and "Nothing prevents SQL
    injection" states it."""
    import json
    import re

    agent = json.loads(item.get("agent") or "null")
    if not isinstance(agent, dict) or not str(agent.get("summary") or "").strip() or not str(agent.get("for_the_person") or "").strip():
        return 0.0
    observations = [o for o in agent.get("observations") or [] if isinstance(o, dict)]
    if item.get("kind") == "known-good":
        return 0.0 if any(o.get("severity") == "concern" for o in observations) else 1.0
    findings = json.loads(item.get("expect_findings") or "[]")
    if not findings:
        return 0.0  # a flagged or known-bad case without labels can't be judged
    notes = [str(n.get("note") or "") for n in agent.get("rule_notes") or [] if isinstance(n, dict)]
    everything = ([str(agent.get(k) or "") for k in ("summary", "tests_note", "for_the_person")]
                  + [str(o.get("text") or "") for o in observations] + notes)
    concerns = [str(o.get("text") or "") for o in observations if o.get("severity") == "concern"]
    negations = ("not", "no", "never", "nor", "neither", "none", "nothing", "without", "cannot", "rather", "instead",
                 "prevent*", "avoid*", "forbid*", "prohibit*", "disallow*", "exclud*", "stop*", "protect*", "mitigat*",
                 "eliminat*", "guard", "guards", "guarded", "guarding")
    unasserted = ("if", "unless", "whether", "until", "before", "than")
    breaks = (r"[.!?]+(?=\s|$)|[;:,()\n–—]+|\s-+\s|\s+(?=(?:but|however|unless|except|while|whereas|although|though|"
              r"because|since|so|if|otherwise|until|before|than|which|without|rather|instead)\b)")

    def words(text: str) -> list:
        return re.findall(r"[a-z0-9%]+", re.sub(r"n['’]t\b", " not", str(text).lower()))

    def matches(word: str, pattern: str) -> bool:
        return word.startswith(pattern[:-1]) if pattern.endswith("*") else word == pattern

    def asserted(text: str, claim: str) -> bool:
        pattern = claim.lower().split()
        for clause in re.split(breaks, str(text).lower()):
            found = words(clause)
            if not found or found[0] in unasserted:
                continue

            def place(index: int, start: int) -> bool:
                if index == len(pattern):
                    return True
                end = len(found) if index == 0 else min(len(found), start + 4)
                return any(matches(found[at], pattern[index]) and place(index + 1, at + 1) for at in range(start, end))

            if pattern and place(0, 0) and sum(1 for w in found if any(matches(w, c) for c in negations)) % 2 == 0:
                return True
        return False

    score = 0.0
    for finding in findings:
        texts = concerns if item.get("kind") == "known-bad" else everything
        if any(asserted(text, claim) for text in texts for claim in finding.get("states") or []):
            score += 0.5
        path = str(finding.get("file") or "")
        name = path.rsplit("/", 1)[-1].lower()
        if path and (any(str(o.get("file") or "").replace("\\", "/").endswith(path) for o in observations)
                     or any(name in note.lower() for note in notes)):
            score += 0.5
    return score / len(findings)


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
