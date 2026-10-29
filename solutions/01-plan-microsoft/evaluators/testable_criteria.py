"""Testable criteria: every acceptance criterion reads Given ... When ... Then ..., in that order.

A criterion is testable when its first word is Given, a later word is When, and a word after that is Then, with
more text after it. Words are compared without regular expressions: the evaluator sandbox errors on some of them.
Score: share of the epic's and tasks' criteria that are testable (1.0 = all). Gates publishing.
"""
import json


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def testable(criterion):
    words = "".join(ch if ch.isalpha() else " " for ch in criterion.lower()).split()
    if len(words) < 4 or words[0] != "given" or "when" not in words[1:]:
        return False
    when = words.index("when", 1)
    return "then" in words[when + 1:-1]


def grade(sample, item) -> float:
    try:
        data = load(item)
        criteria = list(data.get("epic", {}).get("acceptanceCriteria", []))
        criteria += [c for task in data.get("tasks", []) for c in task.get("acceptanceCriteria", [])]
        return sum(1 for c in criteria if testable(c)) / len(criteria) if criteria else 0.0
    except Exception:
        return 0.0
