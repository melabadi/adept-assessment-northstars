#!/usr/bin/env python3
"""Check the contract between the Foundry triage agent's declared tools and the tools RequestHub executes.

The in-app agent can only do what the API executes for it. This check keeps both sides aligned and read-only:
  1. Every tool declared in solutions/03-develop-microsoft/triage-agent.yaml is executed by FoundryTriageProvider, and
     the provider executes no undeclared tool.
  2. No tool can change state: tool names must not contain approve/reject/decide/delete/update/reroute and similar verbs.
  3. Every tool's parameters are a closed JSON schema (type object, additionalProperties false, all properties required),
     which strict function calling requires.
  4. The output schema is closed and requires policyIds and needsHumanReview (citations and the human-review flag).

Usage
  python .github/skills/foundry-tools/check_tools.py

Exit codes: 0 all checks pass, 1 at least one check failed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "solutions/03-develop-microsoft/triage-agent.yaml"
PROVIDER = REPO / "app/src/RequestHub.Api/Triage/FoundryTriageProvider.cs"
STATE_CHANGING = re.compile(r"(approve|reject|decide|decision|delete|remove|update|modify|reroute|assign|status|write|create|confirm)", re.I)
EXECUTED = re.compile(r'^\s*"(?P<name>[a-z_]+)"\s*=>', re.M)


def closed_schema_problems(where: str, schema: dict) -> list[str]:
    problems = []
    if schema.get("type") != "object":
        problems.append(f"{where}: type must be object")
    if schema.get("additionalProperties") is not False:
        problems.append(f"{where}: additionalProperties must be false")
    missing = set(schema.get("properties", {})) - set(schema.get("required", []))
    if missing:
        problems.append(f"{where}: strict mode needs every property in required (missing {', '.join(sorted(missing))})")
    return problems


def main() -> int:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    declared = {t["name"]: t for t in spec.get("tools", [])}
    executed = set(EXECUTED.findall(PROVIDER.read_text(encoding="utf-8")))
    problems: list[str] = []

    for name in sorted(set(declared) - executed):
        problems.append(f"tool '{name}' is declared in triage-agent.yaml but FoundryTriageProvider does not execute it")
    for name in sorted(executed - set(declared)):
        problems.append(f"FoundryTriageProvider executes '{name}' but triage-agent.yaml does not declare it")
    for name, tool in declared.items():
        if STATE_CHANGING.search(name):
            problems.append(f"tool '{name}' looks state-changing; the triage agent may only read (POL-GOV-001)")
        problems += closed_schema_problems(f"tool '{name}' parameters", tool.get("parameters", {}))

    output = spec.get("output_schema", {})
    problems += closed_schema_problems("output_schema", output)
    for field in ("policyIds", "needsHumanReview"):
        if field not in output.get("required", []):
            problems.append(f"output_schema must require {field}")

    print(f"declared tools: {', '.join(sorted(declared)) or 'none'}")
    print(f"executed tools: {', '.join(sorted(executed)) or 'none'}")
    for problem in problems:
        print(f"FAIL {problem}")
    print("PASS tool contract is aligned, read-only, and strict" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
