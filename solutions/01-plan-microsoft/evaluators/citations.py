"""Citations: every item cites at least one source, and every source exists in the inputs.

A citation is a transcript paragraph id (T07) or a policy id (POL-ROUTE-004). setup_foundry.py fills VALID_SOURCES
from inputs/ when it publishes this evaluator, so an invented citation can't pass. The response schema can't require a
non-empty list, so this check does: the problem, goals, requirements, out-of-scope items, success measures, the epic,
tasks, open questions, conflicts, and decisions must each cite something.
Score: 0.0 if any of those items cites nothing, otherwise the share of citations that exist (1.0 = all). Gates
publishing.
"""
import json

VALID_SOURCES = set()  # filled in by setup_foundry.py from inputs/


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def citing_items(data):
    brief = data.get("brief") or {}
    yield brief.get("problem") or {}
    for key in ("goals", "requirements", "outOfScope", "successMeasures"):
        yield from brief.get(key) or []
    yield data.get("epic") or {}
    for key in ("tasks", "openQuestions", "conflicts", "decisions"):
        yield from data.get(key) or []


def grade(sample, item) -> float:
    try:
        data = load(item)
        entries = list(citing_items(data))
        if any(not isinstance(entry, dict) or not isinstance(entry.get("sources"), list) or not entry["sources"]
               for entry in entries):
            return 0.0
        sources = [source for entry in entries for source in entry["sources"]]
        sources += [conflict["resolvedBy"] for conflict in data.get("conflicts") or [] if conflict.get("resolvedBy")]
        return sum(1 for source in sources if source in VALID_SOURCES) / len(sources)
    except Exception:
        return 0.0
