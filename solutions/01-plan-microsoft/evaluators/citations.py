"""Citations: every source the brief cites exists in the inputs.

A citation is a transcript paragraph id (T07) or a policy id (POL-ROUTE-004). setup_foundry.py fills VALID_SOURCES
from inputs/ when it publishes this evaluator, so an invented citation can't pass.
Score: share of citations that exist (1.0 = all). Gates publishing.
"""
import json

VALID_SOURCES = set()  # filled in by setup_foundry.py from inputs/


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def cited(data):
    brief = data.get("brief", {})
    yield from brief.get("problem", {}).get("sources", [])
    for key in ("goals", "requirements", "outOfScope", "successMeasures"):
        for entry in brief.get(key, []):
            yield from entry.get("sources", [])
    yield from data.get("epic", {}).get("sources", [])
    for key in ("tasks", "openQuestions", "conflicts", "decisions"):
        for entry in data.get(key, []):
            yield from entry.get("sources", [])
    for conflict in data.get("conflicts", []):
        if conflict.get("resolvedBy"):
            yield conflict["resolvedBy"]


def grade(sample, item) -> float:
    try:
        sources = list(cited(load(item)))
        return sum(1 for source in sources if source in VALID_SOURCES) / len(sources) if sources else 0.0
    except Exception:
        return 0.0
