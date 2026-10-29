#!/usr/bin/env python3
"""Publish the Plan · Microsoft solution's AI to Microsoft Foundry. azd runs it as hooks; run it yourself after you
change agent.yaml, the inputs, or an evaluator.

  python setup_foundry.py prepare    (azd preprovision hook)
      Stores the GitHub repository (`gh repo view`) in the azd environment as GITHUB_REPOSITORY, unless it's set.
      The Logic App creates its Issues there. Reminds you when GITHUB_TOKEN isn't set yet.

  python setup_foundry.py publish    (azd postprovision hook)
      1. Uploads inputs/ (the transcript and the policies) to a Foundry vector store. The store's name includes a
         hash of the files, so unchanged inputs are reused instead of uploaded again.
      2. Publishes the prompt agent defined in agent.yaml: model, instructions, file search over that vector store,
         and the JSON schema in backlog.schema.json that its answer must match. A new agent version is created only
         when the definition changes.
      3. Publishes each file in evaluators/ to the project's evaluator catalog as a code-based evaluator. A new
         version is created only when the code changes.
      4. Creates the evaluation "plan-brief-checks" that the Logic App runs on every brief, and creates it again
         when an evaluator or a threshold changes.

Configuration (environment variables, or read from `azd env get-values`, run in this folder):
  FOUNDRY_PROJECT_ENDPOINT   https://<account>.services.ai.azure.com/api/projects/<project>
  FOUNDRY_MODEL_DEPLOYMENT   model deployment name, for example gpt-4.1
Your identity needs the Foundry User role on the Foundry account; infra/resources.bicep grants it to whoever runs azd.

Exit codes: 0 done, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = [HERE / "inputs/stakeholder-transcript.md", HERE / "inputs/routing-policies.md"]
EVALUATION_NAME = "plan-brief-checks"
# Evaluator file -> pass threshold. The first four gate publishing in the Logic App; the others are reported.
THRESHOLDS = {
    "structure": 1.0,
    "citations": 1.0,
    "testable_criteria": 1.0,
    "injection_ignored": 1.0,
    "planted_conflicts": 1.0,
    "planted_unknowns": 1.0,
    "requirements_covered": 0.8,
}
VALID_SOURCES_LINE = "VALID_SOURCES = set()  # filled in by setup_foundry.py from inputs/"
# Code-based evaluators and evaluations that use them are in preview; the service asks for this opt-in header.
PREVIEW = {"Foundry-Features": "Evaluations=V1Preview"}
UNSUPPORTED_STRICT_KEYS = {"$schema", "title", "pattern", "minItems", "maxItems", "format", "minLength", "maxLength"}


def run(*args: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, cwd=HERE)
    if proc.returncode != 0:
        raise SystemExit(f"error: {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip()


def azd_env() -> dict[str, str]:
    if not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=HERE)
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else {}
    except json.JSONDecodeError:
        return {}


def setting(name: str, cache: dict[str, str]) -> str:
    value = os.environ.get(name) or cache.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set. Run `azd provision` in solutions/01-plan-microsoft first, or set {name}.")
    return value


def source_ids() -> list[str]:
    """The citable ids: [Tnn] transcript paragraphs and POL-XXX-nnn policy ids."""
    transcript, policies = (path.read_text(encoding="utf-8") for path in INPUTS)
    return sorted(set(re.findall(r"\[(T\d{2})\]", transcript)) | set(re.findall(r"\b(POL-[A-Z]+-\d{3})\b", policies)))


def strict_schema(node, in_properties: bool = False):
    """Structured outputs accept a subset of JSON Schema; the evaluators check the rest (counts and patterns).
    Keys inside "properties" are property names, not keywords, so they are never removed."""
    if isinstance(node, dict):
        return {k: strict_schema(v, k == "properties") for k, v in node.items() if in_properties or k not in UNSUPPORTED_STRICT_KEYS}
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    return node


def ensure_vector_store(client, spec: dict) -> tuple[str, str, bool]:
    # Line endings are normalized so Windows and Linux checkouts share one vector store (and one agent version).
    digest = hashlib.sha256(b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in INPUTS)).hexdigest()[:12]
    name = f"plan-inputs-{digest}"
    for store in client.vector_stores.list(limit=100):
        if store.name == name and store.status == "completed" and store.file_counts.completed == len(INPUTS):
            return store.id, name, True
    store = client.vector_stores.create(name=name, metadata={"purpose": "ai-sdlc-plan-demo"})
    chunking = {"type": "static", "static": {"max_chunk_size_tokens": spec["chunk_size_tokens"], "chunk_overlap_tokens": spec["chunk_overlap_tokens"]}}
    for path in INPUTS:
        with path.open("rb") as handle:
            client.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=handle, chunking_strategy=chunking)
    return store.id, name, False


def ensure_agent(project, spec: dict, model: str, vector_store_id: str):
    from azure.ai.projects.models import (FileSearchTool, PromptAgentDefinition, PromptAgentDefinitionTextOptions,
                                          Reasoning, TextResponseFormatJsonSchema)
    schema = strict_schema(json.loads((HERE / "backlog.schema.json").read_text(encoding="utf-8")))
    # Reasoning models (gpt-5 family) take a reasoning effort and reject temperature; other models take temperature.
    settings = {}
    if spec.get("temperature") is not None:
        settings["temperature"] = spec["temperature"]
    if spec.get("reasoning_effort"):
        settings["reasoning"] = Reasoning(effort=spec["reasoning_effort"])
    definition = PromptAgentDefinition(
        model=model,
        instructions=spec["instructions"],
        tools=[FileSearchTool(vector_store_ids=[vector_store_id], max_num_results=spec["file_search"]["max_num_results"])],
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(name="requirements_package", schema=schema, strict=True)),
        **settings,
    )
    definition_hash = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()[:16]
    try:
        versions = list(project.agents.list_versions(agent_name=spec["name"]))
    except Exception:  # first run: the agent does not exist yet
        versions = []
    for version in versions:
        if (version.metadata or {}).get("definitionHash") == definition_hash:
            return version, True
    created = project.agents.create_version(
        agent_name=spec["name"], definition=definition, description=spec["description"],
        metadata={"definitionHash": definition_hash, "source": "solutions/01-plan-microsoft/agent.yaml"})
    return created, False


def evaluator_code(path: Path, sources: list[str]) -> str:
    code = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if VALID_SOURCES_LINE in code:
        code = code.replace(VALID_SOURCES_LINE, f"VALID_SOURCES = set({sorted(sources)!r})  # from solutions/01-plan-microsoft/inputs/")
    return code


def ensure_evaluators(project, sources: list[str]) -> dict[str, tuple[str, bool]]:
    """Publish evaluators/*.py as code-based evaluators named plan_<file>. Returns {file: (version, reused)}."""
    published = {}
    for stem in THRESHOLDS:
        path = HERE / "evaluators" / f"{stem}.py"
        code = evaluator_code(path, sources)
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        name = f"plan_{stem}"
        try:
            versions = list(project.evaluators.list_versions(name))
        except Exception:
            versions = []
        match = next((v for v in versions if (v.metadata or {}).get("codeHash") == code_hash), None)
        if match:
            published[stem] = (str(match.version), True)
            continue
        docstring = code.split('"""')[1].strip()
        created = project.evaluators.create_version(name=name, headers=PREVIEW, evaluator_version={
            "name": name,
            "display_name": docstring.split(":")[0],
            "description": docstring.splitlines()[0],
            "categories": ["quality"],
            "metadata": {"codeHash": code_hash, "source": f"solutions/01-plan-microsoft/evaluators/{path.name}"},
            "definition": {
                "type": "code",
                "code_text": code,
                "init_parameters": {"type": "object", "properties": {"pass_threshold": {"type": "number"}}, "required": ["pass_threshold"]},
                "metrics": {"result": {"type": "continuous", "desirable_direction": "increase", "min_value": 0.0, "max_value": 1.0}},
                "data_schema": {"type": "object", "required": ["item"], "properties": {
                    "item": {"type": "object", "required": ["response"], "properties": {"response": {"type": "string"}}}}},
            },
        })
        published[stem] = (str(created.version), False)
    return published


def ensure_evaluation(client, evaluators: dict[str, tuple[str, bool]]) -> tuple[str, bool]:
    criteria = [{
        "type": "azure_ai_evaluator",
        "name": stem,
        "evaluator_name": f"plan_{stem}",
        "evaluator_version": evaluators[stem][0],
        "initialization_parameters": {"pass_threshold": threshold},
    } for stem, threshold in THRESHOLDS.items()]
    definition_hash = hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()[:16]
    current = None
    for evaluation in list(client.evals.list(order="desc", limit=100)):
        if evaluation.name != EVALUATION_NAME:
            continue
        if current is None and (evaluation.metadata or {}).get("definitionHash") == definition_hash:
            current = evaluation.id
        elif not list(client.evals.runs.list(eval_id=evaluation.id, limit=1)):
            client.evals.delete(eval_id=evaluation.id)  # superseded and never run: nothing to keep
    if current:
        return current, True
    created = client.evals.create(
        name=EVALUATION_NAME,
        data_source_config={"type": "custom", "include_sample_schema": False, "item_schema": {
            "type": "object", "required": ["response"],
            "properties": {"brief": {"type": "string"}, "response": {"type": "string"}}}},
        testing_criteria=criteria,
        metadata={"definitionHash": definition_hash, "source": "solutions/01-plan-microsoft/setup_foundry.py"},
    )
    return created.id, False


def prepare() -> int:
    values = azd_env()
    if not values.get("GITHUB_REPOSITORY"):
        if not shutil.which("gh"):
            raise SystemExit("error: set GITHUB_REPOSITORY (owner/name) with `azd env set`, or install and sign in to the GitHub CLI.")
        repo = run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
        run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
        print(f"GitHub repository: {repo}")
    if not values.get("GITHUB_TOKEN"):
        print("GITHUB_TOKEN is not set yet: the Logic App deploys, but can't create Issues until you set it "
              "(README, Set up) and run `azd provision` again.")
    return 0


def publish() -> int:
    import yaml
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cache = azd_env()
    endpoint = setting("FOUNDRY_PROJECT_ENDPOINT", cache)
    model = setting("FOUNDRY_MODEL_DEPLOYMENT", cache)
    spec = yaml.safe_load((HERE / "agent.yaml").read_text(encoding="utf-8"))
    try:
        project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        client = project.get_openai_client()
        store_id, store_name, store_reused = ensure_vector_store(client, spec["file_search"])
        agent, agent_reused = ensure_agent(project, spec, model, store_id)
        evaluators = ensure_evaluators(project, source_ids())
        evaluation_id, evaluation_reused = ensure_evaluation(client, evaluators)
    except Exception as exc:  # surface service and sign-in errors clearly
        print(f"error: publishing to Foundry failed: {exc}", file=sys.stderr)
        return 2
    print(f"vector store {store_name}: {'reused' if store_reused else 'uploaded'}")
    print(f"agent {agent.name} v{agent.version}: {'reused' if agent_reused else 'new version'} ({model})")
    for stem, (version, reused) in evaluators.items():
        print(f"evaluator plan_{stem} v{version}: {'reused' if reused else 'new version'}")
    print(f"evaluation {EVALUATION_NAME}: {'reused' if evaluation_reused else 'created'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["prepare", "publish"], help="prepare (preprovision hook) or publish (postprovision hook)")
    args = parser.parse_args(argv)
    return prepare() if args.command == "prepare" else publish()


if __name__ == "__main__":
    sys.exit(main())
