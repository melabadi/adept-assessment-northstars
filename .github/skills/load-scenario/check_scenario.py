#!/usr/bin/env python3
"""Check the RequestHub load scenario before it runs: criteria, guardrails, sign-in, and engine compatibility.

Azure Load Testing runs whatever the scenario says against a real environment, so these checks run first, locally and
in the workflow:
  1. The test configuration is complete: Locust test type, an existing test plan, one or more engines.
  2. Every pass/fail criterion parses and names a request the journey actually makes (name="..." in the locustfile).
  3. The thresholds keep the gate meaningful: an error-rate criterion of at most 5 %, and p95 criteria of at most
     2000 ms on the team queue (the endpoint the slowdown rehearsal targets) and on submit and decide.
  4. The workload stays at rehearsal scale for a demo environment: at most 50 users, 600 seconds, and 2 engines.
  5. Every setting the configuration passes is read by the locustfile, so nothing is silently ignored.
  6. The locustfile runs on the engines: it parses as Python 3.9, has no `X | Y` annotations (an error at run time on
     3.9) and no `from __future__` import (the service adds lines before the script, and such imports must come
     first), and imports only the standard library, locust, and gevent.
  7. No secrets or environment-specific ids are committed: no bearer tokens, keys, or GUIDs (load_test.py adds the
     deployment's values at run time).

Usage
  python .github/skills/load-scenario/check_scenario.py
  python .github/skills/load-scenario/check_scenario.py --config path/to/test.yaml   # another scenario

Exit codes: 0 every check passes, 1 at least one check failed.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO / "solutions/04-test-microsoft/loadtest/requesthub-journey.yaml"
CRITERION = re.compile(r"^(?P<aggregate>[a-z0-9]+)\((?P<metric>[a-z_]+)\)\s*(?P<condition>[<>])\s*(?P<value>\d+(\.\d+)?)$")
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SECRET = re.compile(r"(Bearer\s+ey[A-Za-z0-9_-]{10,}|client_secret|AccountKey=|SharedAccessSignature|sig=[A-Za-z0-9%]{20,})")
LOCUST_SETTINGS = {"LOCUST_HOST", "LOCUST_USERS", "LOCUST_SPAWN_RATE", "LOCUST_RUN_TIME"}
ALLOWED_IMPORTS = {"locust", "gevent"}
LIMITS = {"users": 50, "run_time": 600, "engines": 2, "error_pct": 5, "p95_ms": 2000}
REQUIRED_P95 = {"team-queue", "submit", "decide"}


def check(config_path: Path) -> list[str]:
    problems: list[str] = []
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("testType") != "Locust":
        problems.append(f"testType is {config.get('testType')!r}; this scenario is a Locust test")
    plan = config_path.parent / str(config.get("testPlan", ""))
    if not plan.is_file():
        return problems + [f"testPlan {config.get('testPlan')!r} does not exist next to {config_path.name}"]
    engines = config.get("engineInstances")
    if not isinstance(engines, int) or not 1 <= engines <= LIMITS["engines"]:
        problems.append(f"engineInstances must be 1 to {LIMITS['engines']} for a demo environment, got {engines!r}")

    source = plan.read_text(encoding="utf-8")
    names = set(re.findall(r'name="([^"]+)"', source))
    env = {str(item["name"]): str(item["value"]) for item in config.get("env", [])}

    # 2 and 3: criteria
    criteria = (config.get("failureCriteria") or {}).get("clientMetrics") or []
    error_ok, p95_targets = False, set()
    for item in criteria:
        request, text = (next(iter(item.items())) if isinstance(item, dict) else (None, item))
        match = CRITERION.match(str(text).strip())
        label = f"{request + ': ' if request else ''}{text}"
        if not match:
            problems.append(f"criterion '{label}' does not parse as aggregate(metric) > or < value")
            continue
        if request and request not in names:
            problems.append(f"criterion '{label}' names request '{request}', which the locustfile never makes (names: {', '.join(sorted(names))})")
        value = float(match["value"])
        if match["metric"] == "error" and match["aggregate"] == "percentage" and match["condition"] == ">":
            error_ok = error_ok or value <= LIMITS["error_pct"]
        if match["metric"] == "response_time_ms" and match["aggregate"] == "p95" and match["condition"] == ">" and request:
            if value <= LIMITS["p95_ms"]:
                p95_targets.add(request)
            else:
                problems.append(f"criterion '{label}' allows a p95 above {LIMITS['p95_ms']} ms; the gate would miss the slowdown")
    if not error_ok:
        problems.append(f"add an error-rate criterion of at most {LIMITS['error_pct']} %, for example 'percentage(error) > 1'")
    for request in sorted(REQUIRED_P95 - p95_targets):
        problems.append(f"add a p95 criterion of at most {LIMITS['p95_ms']} ms for '{request}'")

    # 4: workload guardrails
    try:
        if int(env.get("LOCUST_USERS", "0")) > LIMITS["users"]:
            problems.append(f"LOCUST_USERS {env['LOCUST_USERS']} exceeds {LIMITS['users']}, the rehearsal limit for a demo environment")
        if int(env.get("LOCUST_RUN_TIME", "0")) > LIMITS["run_time"]:
            problems.append(f"LOCUST_RUN_TIME {env['LOCUST_RUN_TIME']} s exceeds {LIMITS['run_time']} s")
        if float(env.get("PACING_SECONDS", "1")) < 1:
            problems.append("PACING_SECONDS below 1 turns the journey into a stress test; keep realistic pacing")
    except ValueError as exc:
        problems.append(f"workload settings must be numbers: {exc}")
    if env.get("CLEANUP", "before") not in {"before", "after", "both", "none"}:
        problems.append(f"CLEANUP must be before, after, both, or none, got {env.get('CLEANUP')!r}")

    # 5: every setting is read
    read = set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', source))
    for name in sorted(set(env) - read - LOCUST_SETTINGS):
        problems.append(f"setting {name} is passed to the test but the locustfile never reads it")

    # 6: engine compatibility
    try:
        tree = ast.parse(source, feature_version=(3, 9))
    except SyntaxError as exc:
        problems.append(f"{plan.name} is not valid Python 3.9 (line {exc.lineno}): {exc.msg}")
        tree = None
    if tree is not None:
        stdlib = set(sys.stdlib_module_names)
        annotations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotations += [a.annotation for a in node.args.args + node.args.kwonlyargs if a.annotation] + [node.returns]
            elif isinstance(node, ast.AnnAssign):
                annotations.append(node.annotation)
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                problems.append(f"{plan.name} line {node.lineno}: remove `from __future__ import ...`; Azure Load Testing adds "
                                "lines before the script, so the import would no longer come first")
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for module in modules:
                top = module.split(".")[0]
                if top and top not in stdlib and top not in ALLOWED_IMPORTS and top != "__future__":
                    problems.append(f"{plan.name} imports '{module}', which the engines do not install")
        for annotation in filter(None, annotations):
            if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation)):
                problems.append(f"{plan.name} line {annotation.lineno}: `X | Y` annotations fail on Python 3.9; use typing.Optional or Union")

    # 7: nothing secret or environment-specific
    for path in (config_path, plan):
        text = path.read_text(encoding="utf-8")
        if SECRET.search(text):
            problems.append(f"{path.name} contains what looks like a credential; sign in with managed identities instead")
        if GUID.search(text):
            problems.append(f"{path.name} contains an id ({GUID.search(text).group(0)}); load_test.py adds deployment values at run time")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__.split("\n", 2)[2],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Azure Load Testing YAML configuration to check (default: the RequestHub journey)")
    args = parser.parse_args(argv)
    problems = check(args.config)
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"{len(problems)} problem(s) in {args.config.relative_to(REPO) if args.config.is_relative_to(REPO) else args.config}")
        return 1
    print(f"PASS {args.config.name}: criteria name real requests, thresholds and workload within guardrails, "
          "every setting read, Python 3.9 compatible, no secrets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
