"""Planted unknowns: the brief asks about the four things nobody decided instead of inventing an answer.

The response-time target (T12), a confidence threshold (T15), who may override a suggestion (T21), and how long
recommendations are kept (T22). An unknown counts when an open question, or an unresolved conflict, cites it.
Score: share of the four. Reported to the reviewer; doesn't gate.
"""
import json

UNKNOWNS = ["T12", "T15", "T21", "T22"]


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def grade(sample, item) -> float:
    try:
        data = load(item)
        asked = {s for q in data.get("openQuestions", []) for s in q.get("sources", [])}
        asked |= {s for c in data.get("conflicts", []) if not c.get("resolution") for s in c.get("sources", [])}
        return sum(1 for unknown in UNKNOWNS if unknown in asked) / len(UNKNOWNS)
    except Exception:
        return 0.0
