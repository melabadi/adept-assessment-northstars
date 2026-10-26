#!/usr/bin/env python3
"""Compare two OpenAPI documents and classify every change as additive or breaking (contract-impact skill).

Used by the Design phase (impact of a proposed design), by CI on every PR that touches app/contracts/openapi.json,
and by the Release phase. Rules follow STD-API-001: within a major contract version only additive changes are allowed.

Breaking: removed path or operation, removed response property, changed property type, new required request property,
          new required parameter, removed enum value.
Additive: new path or operation, new optional request property, new response property, new optional parameter, new enum value.

Usage
  python contract_diff.py --base-ref origin/main                      # compare the committed contract with a git ref
  python contract_diff.py --base old.json --head app/contracts/openapi.json --markdown impact.md
  python contract_diff.py --base-ref origin/main --fail-on-breaking   # CI gate

Exit codes: 0 no breaking change (or not gating), 1 breaking change with --fail-on-breaking, 2 usage or file error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACT = "app/contracts/openapi.json"
METHODS = ("get", "post", "put", "patch", "delete")


def load_ref(ref: str, path: str = CONTRACT) -> dict:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    if proc.returncode != 0:
        raise SystemExit(f"error: cannot read {path} at {ref}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def type_of(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "type" in schema:
        t = schema["type"]
        return "|".join(sorted(t)) if isinstance(t, list) else t
    for key in ("oneOf", "anyOf", "allOf"):
        if key in schema:
            return f"{key}(" + ",".join(type_of(s) for s in schema[key]) + ")"
    return "any"


def schema_changes(name: str, old: dict, new: dict, request_schemas: set[str]) -> list[tuple[str, str]]:
    changes = []
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    old_req, new_req = set(old.get("required", [])), set(new.get("required", []))
    is_request = name in request_schemas
    for prop in sorted(old_props.keys() - new_props.keys()):
        changes.append(("breaking", f"schema {name}: property `{prop}` removed"))
    for prop in sorted(new_props.keys() - old_props.keys()):
        if is_request and prop in new_req:
            changes.append(("breaking", f"schema {name}: new required request property `{prop}`"))
        else:
            changes.append(("additive", f"schema {name}: property `{prop}` added"))
    for prop in sorted(old_props.keys() & new_props.keys()):
        if type_of(old_props[prop]) != type_of(new_props[prop]):
            changes.append(("breaking", f"schema {name}: property `{prop}` type {type_of(old_props[prop])} -> {type_of(new_props[prop])}"))
        removed_enum = set(old_props[prop].get("enum", [])) - set(new_props[prop].get("enum", []))
        if removed_enum:
            changes.append(("breaking", f"schema {name}: property `{prop}` enum values removed {sorted(removed_enum)}"))
    if is_request:
        for prop in sorted((new_req - old_req) & old_props.keys()):
            changes.append(("breaking", f"schema {name}: request property `{prop}` became required"))
    return changes


def request_schema_names(doc: dict) -> set[str]:
    names = set()
    for item in doc.get("paths", {}).values():
        for method in METHODS:
            body = item.get(method, {}).get("requestBody", {})
            for media in body.get("content", {}).values():
                ref = media.get("schema", {}).get("$ref")
                if ref:
                    names.add(ref.split("/")[-1])
    return names


def diff(old: dict, new: dict) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    old_paths, new_paths = old.get("paths", {}), new.get("paths", {})
    for path in sorted(old_paths.keys() - new_paths.keys()):
        changes.append(("breaking", f"path `{path}` removed"))
    for path in sorted(new_paths.keys() - old_paths.keys()):
        changes.append(("additive", f"path `{path}` added"))
    for path in sorted(old_paths.keys() & new_paths.keys()):
        for method in METHODS:
            before, after = old_paths[path].get(method), new_paths[path].get(method)
            if before and not after:
                changes.append(("breaking", f"{method.upper()} {path} removed"))
            elif after and not before:
                changes.append(("additive", f"{method.upper()} {path} added"))
            elif before and after:
                old_params = {(p.get("name"), p.get("in")): p for p in before.get("parameters", [])}
                new_params = {(p.get("name"), p.get("in")): p for p in after.get("parameters", [])}
                for key in sorted(new_params.keys() - old_params.keys()):
                    kind = "breaking" if new_params[key].get("required") else "additive"
                    changes.append((kind, f"{method.upper()} {path}: parameter `{key[0]}` ({key[1]}) added{' as required' if kind == 'breaking' else ''}"))
                for key in sorted(old_params.keys() - new_params.keys()):
                    changes.append(("breaking", f"{method.upper()} {path}: parameter `{key[0]}` ({key[1]}) removed"))
    old_schemas = old.get("components", {}).get("schemas", {})
    new_schemas = new.get("components", {}).get("schemas", {})
    requests = request_schema_names(old) | request_schema_names(new)
    for name in sorted(old_schemas.keys() - new_schemas.keys()):
        changes.append(("breaking", f"schema {name} removed"))
    for name in sorted(new_schemas.keys() - old_schemas.keys()):
        changes.append(("additive", f"schema {name} added"))
    for name in sorted(old_schemas.keys() & new_schemas.keys()):
        changes.extend(schema_changes(name, old_schemas[name], new_schemas[name], requests))
    return changes


def report(changes: list[tuple[str, str]], base_label: str, version: str) -> str:
    breaking = [c for k, c in changes if k == "breaking"]
    additive = [c for k, c in changes if k == "additive"]
    verdict = ("**Breaking change**: requires a new major contract version and a migration plan (STD-API-001)."
               if breaking else "**Compatible**: additive-only changes are allowed within the current contract version (STD-API-001).")
    lines = [f"## API contract impact ({version} vs {base_label})", "", verdict, "",
             f"- Breaking changes: {len(breaking)}", f"- Additive changes: {len(additive)}", ""]
    if breaking:
        lines += ["### Breaking", "", *[f"- ❌ {c}" for c in breaking], ""]
    if additive:
        lines += ["### Additive", "", *[f"- ➕ {c}" for c in additive], ""]
    if not changes:
        lines += ["No contract changes.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    base = parser.add_mutually_exclusive_group(required=True)
    base.add_argument("--base", type=Path, help="Base OpenAPI JSON file")
    base.add_argument("--base-ref", help="Git ref whose app/contracts/openapi.json is the base (e.g. origin/main)")
    parser.add_argument("--head", type=Path, default=REPO / CONTRACT, help="Changed OpenAPI JSON file (default: working tree contract)")
    parser.add_argument("--markdown", type=Path, help="Write the report to this file")
    parser.add_argument("--fail-on-breaking", action="store_true", help="Exit 1 when a breaking change is found")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        old = load_ref(args.base_ref) if args.base_ref else json.loads(args.base.read_text(encoding="utf-8"))
        new = json.loads(args.head.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    changes = diff(old, new)
    text = report(changes, args.base_ref or str(args.base), new.get("info", {}).get("version", "?"))
    print(text)
    if args.markdown:
        args.markdown.write_text(text + "\n", encoding="utf-8")
    breaking = any(k == "breaking" for k, _ in changes)
    return 1 if breaking and args.fail_on_breaking else 0


if __name__ == "__main__":
    sys.exit(main())
