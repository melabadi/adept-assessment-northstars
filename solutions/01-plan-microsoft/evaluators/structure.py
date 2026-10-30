"""Structure: the backlog shape that structured outputs can't enforce, and honest decisions.

The agent's JSON schema is enforced by structured outputs, but structured outputs drop counts and patterns. This
evaluator checks them, the task dependency graph, and that no decision settles a conflict nobody decided.
Score: share of checks that pass (1.0 = all). Gates publishing.
"""
import json
import re

PATTERNS = {"requirements": r"R[0-9]+", "openQuestions": r"Q[0-9]+", "conflicts": r"C[0-9]+", "decisions": r"D[0-9]+"}


def load(item):
    value = item.get("response") if isinstance(item, dict) else None
    return value if isinstance(value, dict) else json.loads(value or "")


def has_cycle(graph):
    state = {}

    def visit(node):
        state[node] = 1
        for dep in graph.get(node, []):
            if state.get(dep) == 1 or (dep in graph and state.get(dep) is None and visit(dep)):
                return True
        state[node] = 2
        return False

    return any(state.get(node) is None and visit(node) for node in graph)


def grade(sample, item) -> float:
    try:
        data = load(item)
        brief, tasks = data.get("brief", {}), data.get("tasks", [])
        checks = [
            len(tasks) == 4,
            len(brief.get("requirements", [])) >= 4,
            len(brief.get("goals", [])) >= 1,
            bool(re.fullmatch(r"EPIC-[A-Z0-9-]+", data.get("epic", {}).get("id", ""))),
            len(data.get("epic", {}).get("acceptanceCriteria", [])) >= 1,
            all(len(task.get("acceptanceCriteria", [])) >= 2 for task in tasks),
        ]
        ids = [task.get("id", "") for task in tasks]
        checks.append(len(ids) == len(set(ids)) and all(re.fullmatch(r"TASK-[0-9]+", i) for i in ids))
        items = {"requirements": brief.get("requirements", []), "openQuestions": data.get("openQuestions", []),
                 "conflicts": data.get("conflicts", []), "decisions": data.get("decisions", [])}
        checks.append(all(re.fullmatch(PATTERNS[key], entry.get("id", "")) for key, entries in items.items() for entry in entries))
        graph = {task.get("id"): list(task.get("dependsOn", [])) for task in tasks}
        checks.append(all(dep in graph and dep != task_id for task_id, deps in graph.items() for dep in deps))
        checks.append(not has_cycle(graph))
        unresolved = {s for c in data.get("conflicts", []) if not c.get("resolution") for s in c.get("sources", [])}
        checks.append(all(not set(d.get("sources", [])) & unresolved for d in data.get("decisions", [])))
        decision_sources = {s for d in data.get("decisions", []) for s in d.get("sources", [])}
        for conflict in data.get("conflicts", []):
            if conflict.get("resolution"):
                deciding = conflict.get("resolvedBy")
                checks.append(bool(deciding) and deciding not in conflict.get("sources", []) and deciding in decision_sources)
        return sum(checks) / len(checks)
    except Exception:
        return 0.0
