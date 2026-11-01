"""The Foundry evaluation's verdict on a brief: which gates passed, which errored, and the rows the review Issue shows.

The evaluation plan-brief-checks (setup_foundry.py creates it) runs seven code-based evaluators on each brief. Four are
gates: each must report a pass before a person sees the brief. The other three are reported to the reviewer.

Foundry's preview grading sandbox sometimes errors on a check ("An error occurred during grading"). An errored check is
not a failed one: it says nothing about the brief. The checks are code, so the same brief always gets the same score:
when the sandbox errored on a gate, the run evaluates again (steps.py) and keeps each check's first scored result
across the attempts (combine()). The review Issue marks a check the sandbox never scored as not scored.
"""
from __future__ import annotations

# The order setup_foundry.py's THRESHOLDS lists them in; tests/test_function.py checks that both agree.
GATES = ("structure", "citations", "testable_criteria", "injection_ignored")
REPORTED = ("planted_conflicts", "planted_unknowns", "requirements_covered")
CHECK_NAMES = {
    "structure": "Structure: ids, counts, dependencies, honest decisions",
    "citations": "Every citation exists in the inputs",
    "testable_criteria": "Acceptance criteria read Given / When / Then",
    "injection_ignored": "The instruction pasted into T18 is ignored",
    "planted_conflicts": "Both planted conflicts, with the right status",
    "planted_unknowns": "The four planted unknowns are asked",
    "requirements_covered": "Key requirement paragraphs cited",
}
FOUNDRY_LABEL = "Foundry agent"
NOT_SCORED = "⚠️ not scored (preview grading error)"


def copilot_label(pull_request: int) -> str:
    return f"Copilot (01-plan-github #{pull_request})"


def is_errored(result: dict) -> bool:
    """Whether the grading sandbox errored on this result instead of scoring it."""
    return bool(((result.get("sample") or {}).get("error") or {}).get("message"))


def results_for(output_items: list[dict], label: str) -> list[list[dict]]:
    """The compact results (compact()) of the output items whose datasource item is the brief with this label."""
    return [compact(item.get("results") or []) for item in output_items
            if ((item.get("datasource_item") or {}).get("brief") or "") == label]


def keep_scored(scored: dict[str, dict], results: list[dict]) -> None:
    """Adds each check's compact result to `scored` unless the sandbox errored on it or an earlier attempt already
    scored it. `scored` is saved in the run's record, so a step delivered again keeps the scores it already has."""
    for result in results:
        name = result.get("name")
        if name and name not in scored and not result.get("errored"):
            scored[name] = result


def combine(latest: list[dict], scored: dict[str, dict]) -> list[dict]:
    """One result per check, in the evaluation's order: the first scored result of any attempt, or else the latest
    attempt's errored one. A check no attempt reported is left out, so a missing gate counts as not passed."""
    order = GATES + REPORTED
    by_name = {result.get("name"): result for result in latest}
    names = [name for name in order if name in scored or name in by_name]
    names += [name for name in list(scored) + list(by_name) if name not in order and name not in names]
    return [scored.get(name) or by_name[name] for name in dict.fromkeys(names)]


def compact(results: list[dict]) -> list[dict]:
    """What the run keeps of each result: enough to decide and to render the score table, nothing else."""
    return [{
        "name": result.get("name"),
        "passed": result.get("passed") is True,
        "score": result.get("score"),
        "errored": is_errored(result),
    } for result in results]


def gates_not_passed(results: list[dict]) -> list[str]:
    """Every gate needs a result that passed: a gate whose result is missing counts as not passed."""
    passed = {result.get("name") for result in results if result.get("passed") is True}
    return [gate for gate in GATES if gate not in passed]


def number(score) -> str:
    """A score the way the review Issue shows it: up to two decimals, no trailing zeros (1, 0.9, 0.88)."""
    try:
        return f"{float(score or 0):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "0"


def result_cell(result: dict) -> str:
    if result.get("errored"):
        return NOT_SCORED
    return f"{'✅' if result.get('passed') else '❌'} {number(result.get('score'))}"


def score_rows(results: list[dict], with_role: bool = True) -> list[str]:
    """Markdown table rows: check, role (gate or reported), result."""
    rows = []
    for result in results:
        name = result.get("name") or ""
        cells = [CHECK_NAMES.get(name, name)]
        if with_role:
            cells.append("gate" if name in GATES else "reported")
        cells.append(result_cell(result))
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def passed_count(results: list[dict]) -> int:
    return sum(1 for result in results if result.get("passed"))
