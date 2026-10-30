"""Planted conflicts: the brief finds the two disagreements planted in the transcript, each with the right status.

- Automatic routing (T05) versus mandatory human confirmation (T04): resolved by the decision in T19.
- Expensive computers: Finance (T06, POL-ROUTE-004) versus IT (T07, POL-ROUTE-001): nobody decided.
A conflict counts when it cites both paragraphs and is resolved (or not) correctly. A decision citing one side
and the deciding paragraph also counts for the resolved one.
Score: share of the two found with the right status. Reported to the reviewer; doesn't gate.
"""
import json

PLANTED = [
    {"sources": {"T04", "T05"}, "resolved_by": "T19"},
    {"sources": {"T06", "T07"}, "resolved_by": None},
]


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def grade(sample, item) -> float:
    try:
        data = load(item)
        correct = 0
        for planted in PLANTED:
            match = next((c for c in data.get("conflicts", []) if planted["sources"] <= set(c.get("sources", []))), None)
            if match is not None:
                correct += bool(match.get("resolution")) == bool(planted["resolved_by"])
            elif planted["resolved_by"]:
                correct += any(planted["sources"] & set(d.get("sources", [])) and planted["resolved_by"] in d.get("sources", [])
                               for d in data.get("decisions", []))
        return correct / len(PLANTED)
    except Exception:
        return 0.0
