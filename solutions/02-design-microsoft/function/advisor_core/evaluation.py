"""The advisor's evaluation in Microsoft Foundry: the labelled cases, scored by code-based evaluators.

Foundry runs the evaluation, not a script: each run sends the cases' questions to one advisor agent version
(azure_ai_target_completions with an azure_ai_agent target), then scores every answer with five custom code-based
evaluators. Each evaluator embeds checks.py, the same code as the Function's gate, and reports one column:

  advisor_citations   every cited standard exists, has the cited version, and is quoted word for word
  advisor_access      nothing outside the profile's scope was retrieved or cited (negative access test)
  advisor_grounding   an answer cites at least one standard and every standard the case expects
  advisor_abstention  answers or abstains as labelled, and an abstention carries no recommendation
  advisor_conflicts   reports the contradiction the case expects

Each item carries a snapshot of the index (every standard's version and text, and the ids the profile may retrieve),
because evaluators run in a sandbox without network access. One run per profile, because a run targets one agent.
Custom evaluators are a preview feature: their API needs the "Foundry-Features: Evaluations=V1Preview" header.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import checks, standards

PREVIEW = {"Foundry-Features": "Evaluations=V1Preview"}
EVAL_NAME = "Architecture advisor · labelled cases"
CHECKS_SOURCE = Path(checks.__file__).read_text(encoding="utf-8")
EVALUATORS = {
    "citations": ("Citations are real", "Every cited standard exists in the index, has the cited version, and its "
                  "excerpt is quoted word for word without leaving out a negation."),
    "access": ("Scope respected", "Nothing outside the operating profile's scope was retrieved or cited, including the "
               "standards the case forbids."),
    "grounding": ("Grounded", "An answer cites at least one standard, and every standard the case expects."),
    "abstention": ("Abstains when it should", "Answers or abstains as the case expects; an abstention has no "
                   "recommendation and lists what is unknown."),
    "conflicts": ("Conflicts flagged", "Reports the contradiction between standards that the case expects (passes "
                  "when the case expects none)."),
}
GRADE = '''


def grade(sample, item) -> float:
    """Called by Foundry once per evaluation item. 1.0 passes, 0.0 fails."""
    try:
        return 1.0 if verdict(evaluate_item(item), "{kind}") else 0.0
    except Exception:  # a missing or malformed answer fails every check
        return 0.0
'''
ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "profile": {"type": "string"},
        "question": {"type": "string"},
        "expectAnswerable": {"type": "boolean"},
        "expectStandards": {"type": "array", "items": {"type": "string"}},
        "forbidStandards": {"type": "array", "items": {"type": "string"}},
        "expectConflict": {"type": "array", "items": {"type": "string"}},
        "standards": {"type": "string", "description": "JSON: id -> {version, text} of every indexed standard"},
        "permitted": {"type": "string", "description": "JSON: ids the profile's scope filter retrieves"},
    },
    "required": ["id", "profile", "question", "expectAnswerable", "standards", "permitted"],
}


def evaluator_name(kind: str) -> str:
    return f"advisor_{kind}"


def evaluator_code(kind: str) -> str:
    """checks.py plus the grade() entry point Foundry calls."""
    return CHECKS_SOURCE + GRADE.format(kind=kind)


def register_evaluators(project) -> dict[str, str]:
    """Create a new version of each code-based evaluator when its code changed. Returns {kind: version}."""
    from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

    versions = {}
    for kind, (display, description) in EVALUATORS.items():
        name, code = evaluator_name(kind), evaluator_code(kind)
        digest = hashlib.sha256(code.encode()).hexdigest()[:16]
        try:
            existing = list(project.evaluators.list_versions(name=name, headers=PREVIEW))
        except Exception:  # first run: the evaluator does not exist yet
            existing = []
        match = next((e for e in existing if (e.metadata or {}).get("codeHash") == digest), None)
        if match is None:
            match = project.evaluators.create_version(name=name, headers=PREVIEW, evaluator_version={
                "name": name, "display_name": display, "description": description,
                "categories": [EvaluatorCategory.AGENTS],
                "metadata": {"codeHash": digest, "source": "solutions/02-design-microsoft/function/advisor_core/checks.py"},
                "definition": {
                    "type": EvaluatorDefinitionType.CODE,
                    "code_text": code,
                    "init_parameters": {"type": "object", "required": ["pass_threshold"], "properties": {
                        "deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"}}},
                    "metrics": {"result": {"type": "continuous", "desirable_direction": "increase",
                                           "min_value": 0.0, "max_value": 1.0}},
                    "data_schema": {"type": "object", "required": ["item"], "properties": {"item": {"type": "object"}}},
                }})
        versions[kind] = str(match.version)
    return versions


def ensure_eval(openai, model: str, versions: dict[str, str]) -> str:
    """The evaluation (cases schema + the five evaluators at the given versions); reused while nothing changed."""
    import openai as openai_errors

    signature = ",".join(f"{kind}:{versions[kind]}" for kind in EVALUATORS)
    for existing in openai.evals.list(limit=100):
        if existing.name == EVAL_NAME and (existing.metadata or {}).get("evaluators") == signature:
            return existing.id
    criteria = [{"type": "azure_ai_evaluator", "name": evaluator_name(kind), "evaluator_name": evaluator_name(kind),
                 "evaluator_version": versions[kind],
                 "initialization_parameters": {"deployment_name": model, "pass_threshold": 0.5}} for kind in EVALUATORS]
    for _ in range(12):  # a new evaluator version takes a few seconds to appear in the catalog
        try:
            created = openai.evals.create(
                name=EVAL_NAME, metadata={"evaluators": signature},
                data_source_config={"type": "custom", "item_schema": ITEM_SCHEMA, "include_sample_schema": True},
                testing_criteria=criteria)
            break
        except openai_errors.NotFoundError:
            time.sleep(15)
    else:
        raise RuntimeError("the evaluators did not appear in the Foundry evaluator catalog")
    # Keep one evaluation under EVAL_NAME: earlier ones (older evaluator code) keep their runs under another name.
    for existing in openai.evals.list(limit=100):
        if existing.name == EVAL_NAME and existing.id != created.id:
            try:
                openai.evals.update(existing.id, name=f"{EVAL_NAME} (earlier evaluators)")
            except Exception:  # renaming is cosmetic; the new evaluation is ready either way
                pass
    return created.id


def items(cases: list[dict], every: dict[str, dict], permitted: list[str]) -> list[dict]:
    """Evaluation items for one profile's cases: the case, plus the index snapshot the evaluators check against."""
    snapshot, allowed = json.dumps(every, sort_keys=True), json.dumps(sorted(permitted))
    return [{"item": {"id": c["id"], "profile": c["profile"], "question": c["question"],
                      "expectAnswerable": c["expectAnswerable"], "expectStandards": c["expectStandards"],
                      "forbidStandards": c["forbidStandards"], "expectConflict": c["expectConflict"],
                      "standards": snapshot, "permitted": allowed}} for c in cases]


def start(project, model: str, cases: list[dict], search_endpoint: str, credential, index: str,
          published: dict[str, dict], label: str) -> list[dict]:
    """Start one evaluation run per profile against that profile's published agent version."""
    openai = project.get_openai_client()
    eval_id = ensure_eval(openai, model, register_evaluators(project))
    every = standards.snapshot(search_endpoint, credential, index)
    runs = []
    for profile, agent in published.items():
        mine = [c for c in cases if c["profile"] == profile]
        if not mine:
            continue
        permitted = list(standards.snapshot(search_endpoint, credential, index, agent["scopeFilter"]))
        run = openai.evals.runs.create(
            eval_id=eval_id, name=f"{agent['name']} v{agent['version']} · {label}",
            metadata={"profile": profile, "agent": f"{agent['name']}:{agent['version']}", "label": label[:256]},
            data_source={
                "type": "azure_ai_target_completions",
                "source": {"type": "file_content", "content": items(mine, every, permitted)},
                "input_messages": {"type": "template", "template": [
                    {"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.question}}"}}]},
                "target": {"type": "azure_ai_agent", "name": agent["name"], "version": agent["version"]},
            })
        runs.append({"profile": profile, "evalId": eval_id, "runId": run.id, "agent": f"{agent['name']} v{agent['version']}",
                     "cases": [c["id"] for c in mine]})
    return runs


def status(openai, eval_id: str, run_id: str) -> dict:
    """A run's state, its counts, and each evaluator's pass rate."""
    run = openai.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
    counts = run.result_counts
    per_criterion = {}
    for result in getattr(run, "per_testing_criteria_results", None) or []:
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        per_criterion[data.get("testing_criteria")] = f"{data.get('passed', 0)}/{data.get('passed', 0) + data.get('failed', 0)}"
    return {"status": run.status, "passed": getattr(counts, "passed", 0), "failed": getattr(counts, "failed", 0),
            "errored": getattr(counts, "errored", 0), "total": getattr(counts, "total", 0),
            "criteria": per_criterion, "reportUrl": getattr(run, "report_url", None)}
