"""Key requirements covered: the brief builds on the ten paragraphs that carry the workshop's requirements.

A paragraph counts when the problem, a goal, a requirement, the epic, or a task cites it.
Score: share of the ten. Reported to the reviewer; doesn't gate.
"""
import json

KEY_REQUIREMENTS = ["T03", "T04", "T08", "T09", "T10", "T11", "T13", "T14", "T16", "T17"]


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def grade(sample, item) -> float:
    try:
        data = load(item)
        brief = data.get("brief", {})
        cited = set(brief.get("problem", {}).get("sources", []))
        for key in ("goals", "requirements"):
            cited |= {s for entry in brief.get(key, []) for s in entry.get("sources", [])}
        cited |= set(data.get("epic", {}).get("sources", []))
        cited |= {s for task in data.get("tasks", []) for s in task.get("sources", [])}
        return sum(1 for paragraph in KEY_REQUIREMENTS if paragraph in cited) / len(KEY_REQUIREMENTS)
    except Exception:
        return 0.0
