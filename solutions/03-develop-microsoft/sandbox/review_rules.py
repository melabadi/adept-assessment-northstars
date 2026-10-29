#!/usr/bin/env python3
"""Check a pull request against RequestHub's team rules (Develop phase, Microsoft track): the reviewer's judge.

The Azure pull request reviewer runs this script in a sandbox session that never executes the pull request's code, before
the change is built or tested anywhere, and reads its verdicts first. The script only reads the two source trees as data:
the merge base and the pull request's head, as the .tar.gz archives GitHub serves. The review shows its verdicts word for
word. The reviewer agent may explain a verdict, but never overrides a FAIL.

Rules
  approval-authority         RequestWorkflow.DecideAsync and the approval rules in PermissionsFor are unchanged, and no
                             other code starts recording decisions or calling the decision API.
  authorization-in-workflow  Authorization stays in RequestWorkflow: no role or department checks added in other API
                             code, and no endpoint loses RequireAuthorization or gains AllowAnonymous.
  contract-additive          app/contracts/openapi.json changes only additively (STD-API-001).
  tests-with-changes         A change to app code (beyond comments) comes with a test change, and no test case is removed or
                             skipped.
  synthetic-data             Added lines contain no secrets, no e-mail addresses outside the synthetic domains, and no
                             GUID that names a tenant, subscription, principal, or client. Public built-in ids, such as
                             Azure role and policy definitions, are fine.

Usage
  python3 review_rules.py --base base.tgz --head head.tgz             # JSON on stdout: the verdicts, the same verdicts
                                                                      # as a Markdown table ("markdown"), and the change
                                                                      # as a unified diff for the reviewer agent ("diff")
  python3 review_rules.py --base base.tgz --head head.tgz --markdown  # only the verdicts as a Markdown table
  python3 review_rules.py --base old-tree/ --head new-tree/           # directories work too

Exit codes: 0 every rule passed, 1 at least one rule failed, 2 input error. Standard library only (Python 3.10+).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tarfile
from pathlib import Path

VERSION = "1"
WORKFLOW = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"
MIGRATIONS = "app/src/RequestHub.Core/Data/Migrations/"
CONTRACT = "app/contracts/openapi.json"
DECIDE = "public async Task<Result<DecisionDto>> DecideAsync("
PERMISSIONS = "public static PermissionsDto PermissionsFor("

TEST_FILE = re.compile(r"(^app/tests/.*\.cs$)|(\.(test|spec)\.tsx?$)")
CODE_FILE = re.compile(r"^app/(src|web/src)/.*\.(cs|tsx?)$")
API_CODE = re.compile(r"^app/src/.*\.cs$")
CS_TEST = re.compile(r"\[(Fact|Theory)\b")
TS_TEST = re.compile(r"^\s*(test|it)(\.\w+)?\(", re.M)
SKIPPED = re.compile(r"\bSkip\s*=|\b(test|it|describe)\.(skip|fixme|only)\(")
DECISION_WRITE = re.compile(
    r"\bnew\s+ApprovalDecision\b|\bDecisions\s*\.\s*Add(Range)?\s*\(|\bStatus\s*=(?!=)[^;,(){}]*\bRequestStatus\s*\.\s*(Approved|Rejected)\b")
DECISION_CALL = re.compile(r"\bapi\s*\.\s*decide\s*\(")
ROLE_CHECK = re.compile(r"\bHasRole\s*\(|\bIsInRole\s*\(|\bIsAdmin\b|\bRoles\s*\.\s*(Admin|Approver|Reviewer|Requester)\b|"
                        r"\bCanAccessDepartment\s*\(|\[Authorize\b")
REQUIRE_AUTH = re.compile(r"\.RequireAuthorization\s*\(")
ALLOW_ANON = re.compile(r"AllowAnonymous")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"(@example\.(com|org|net)|@([a-z0-9-]+\.)*contoso\.com|@noreply\.github\.com|"
                           r"@users\.noreply\.github\.com)$", re.I)
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# A GUID is private when its line says what it identifies: a tenant, subscription, principal, object, client, or directory.
# Built-in ids that are the same in every tenant (role and policy definitions) are public.
PRIVATE_ID_CONTEXT = re.compile(r"(?i)\btenant|\bsubscription(?!ResourceId)|principal|object[\s_-]*id|client[\s_-]*id|"
                                r"directory|microsoftonline\.com|\bAZURE_\w*ID\b")
BUILT_IN_ID_CONTEXT = re.compile(r"(?i)role\s*definition|roleDefinitions|policy(set)?\s*definition|built-?in")
SECRETS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("cloud access key", re.compile(r"\b(AKIA[0-9A-Z]{16}|AccountKey=[A-Za-z0-9+/=]{20,}|SharedAccessKey=[A-Za-z0-9+/=]{20,})")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("bearer token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("password", re.compile(r"(?i)\b(password|pwd)\s*[=:]\s*(?!devpass\b)['\"]?[^\s'\";,]{6,}")),
]
TEXT_SUFFIXES = {".cs", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".yml", ".yaml", ".py", ".bicep", ".sql", ".html",
                 ".css", ".csproj", ".props", ".slnx", ".txt", ".ps1", ".sh", ".xml", ".jsonl", ".http", ".env", ".config"}
METHODS = ("get", "post", "put", "patch", "delete")


# ---------------------------------------------------------------- source trees

def load_tree(source: Path) -> dict[str, bytes]:
    """Every regular file of a tree, path -> content. Archives are read in memory: nothing is extracted to disk, and
    links are skipped, so a crafted archive can't write or read outside the tree."""
    if source.is_dir():
        return {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(source).parts}
    files: dict[str, bytes] = {}
    with tarfile.open(source, "r:gz") as archive:
        for m in archive:
            if not m.isfile():
                continue  # directories, links, and devices are never needed to judge a change
            # GitHub archives hold one top-level folder named <owner>-<repo>-<sha>; drop it.
            parts = m.name.replace("\\", "/").split("/")[1:]
            if not parts or ".." in parts:
                continue
            data = archive.extractfile(m)
            if data is not None:
                files["/".join(parts)] = data.read()
    return files


def is_text(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES or Path(path).name in {"Dockerfile", ".gitignore", "global.json"}


class Change:
    """The files a pull request touches, with their content at the merge base and at the head."""

    def __init__(self, base: dict[str, bytes], head: dict[str, bytes]):
        self.base_files, self.head_files = base, head
        self.files: list[tuple[str, str]] = []
        for path in sorted(base.keys() | head.keys()):
            if path not in head:
                self.files.append(("D", path))
            elif path not in base:
                self.files.append(("A", path))
            elif base[path] != head[path]:
                self.files.append(("M", path))
        # A moved test file is compared with its old self: same file name, deleted in one place and added in another.
        deleted = {Path(p).name: p for k, p in self.files if k == "D"}
        self.renamed = {p: deleted[Path(p).name] for k, p in self.files if k == "A" and Path(p).name in deleted}

    def before(self, path: str) -> str:
        return self.base_files.get(path, b"").decode("utf-8", errors="replace")

    def after(self, path: str) -> str:
        return self.head_files.get(path, b"").decode("utf-8", errors="replace")

    def added_lines(self, path: str) -> list[tuple[int, str]]:
        """(line number in the head, text) for every line the change adds to a text file."""
        if not is_text(path):
            return []
        old, new = self.before(path).splitlines(), self.after(path).splitlines()
        added = []
        for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag in ("replace", "insert"):
                added += [(j + 1, new[j]) for j in range(j1, j2)]
        return added


# ---------------------------------------------------------------- helpers shared by the rules

def member(source: str, signature: str) -> str:
    """Whitespace-normalized text of the C# member whose declaration contains `signature` ('' when absent)."""
    start = source.find(signature)
    if start < 0:
        return ""
    depth, i = 0, source.find("{", start)
    if i < 0:
        return ""
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return re.sub(r"\s+", " ", source[start:j + 1])
    return ""


def approval_rules(source: str) -> list[str]:
    """The parts of PermissionsFor that decide who may approve: the `blocked` reason chain and CanDecide."""
    body = member(source, PERMISSIONS)
    return (re.findall(r"(?:if|else if) \([^;]*blocked = \"[a-z_]+\";", body)
            + re.findall(r"\b(?:CanDecide|DecideBlockedReason):[^,)]*", body))


def test_cases(path: str, text: str) -> int:
    return len((CS_TEST if path.endswith(".cs") else TS_TEST).findall(text))


def behavior(source: str) -> str:
    """Code without comments and blank lines: an edit that changes only comments changes no behavior."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(line.strip() for line in source.splitlines() if line.strip() and not line.strip().startswith("//"))


def short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def masked(value: str) -> str:
    return value[:4] + "…" if len(value) > 4 else "…"


# ---------------------------------------------------------------- the API contract (same rules as contract-impact)

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


def contract_changes(old: dict, new: dict) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    old_paths, new_paths = old.get("paths", {}), new.get("paths", {})
    for path in sorted(old_paths.keys() - new_paths.keys()):
        changes.append(("breaking", f"path {path} removed"))
    for path in sorted(new_paths.keys() - old_paths.keys()):
        changes.append(("additive", f"path {path} added"))
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
                    changes.append((kind, f"{method.upper()} {path}: parameter {key[0]} ({key[1]}) added"
                                          + (" as required" if kind == "breaking" else "")))
                for key in sorted(old_params.keys() - new_params.keys()):
                    changes.append(("breaking", f"{method.upper()} {path}: parameter {key[0]} ({key[1]}) removed"))
    old_schemas = old.get("components", {}).get("schemas", {})
    new_schemas = new.get("components", {}).get("schemas", {})
    requests = request_schema_names(old) | request_schema_names(new)
    for name in sorted(old_schemas.keys() - new_schemas.keys()):
        changes.append(("breaking", f"schema {name} removed"))
    for name in sorted(new_schemas.keys() - old_schemas.keys()):
        changes.append(("additive", f"schema {name} added"))
    for name in sorted(old_schemas.keys() & new_schemas.keys()):
        old_s, new_s = old_schemas[name], new_schemas[name]
        old_props, new_props = old_s.get("properties", {}), new_s.get("properties", {})
        old_req, new_req = set(old_s.get("required", [])), set(new_s.get("required", []))
        is_request = name in requests
        for prop in sorted(old_props.keys() - new_props.keys()):
            changes.append(("breaking", f"schema {name}: property {prop} removed"))
        for prop in sorted(new_props.keys() - old_props.keys()):
            kind = "breaking" if is_request and prop in new_req else "additive"
            changes.append((kind, f"schema {name}: " + (f"new required request property {prop}" if kind == "breaking"
                                                         else f"property {prop} added")))
        for prop in sorted(old_props.keys() & new_props.keys()):
            if type_of(old_props[prop]) != type_of(new_props[prop]):
                changes.append(("breaking", f"schema {name}: property {prop} type {type_of(old_props[prop])} -> "
                                            f"{type_of(new_props[prop])}"))
            removed_enum = set(old_props[prop].get("enum", [])) - set(new_props[prop].get("enum", []))
            if removed_enum:
                changes.append(("breaking", f"schema {name}: property {prop} enum values removed {sorted(removed_enum)}"))
        if is_request:
            for prop in sorted((new_req - old_req) & old_props.keys()):
                changes.append(("breaking", f"schema {name}: request property {prop} became required"))
    return changes


# ---------------------------------------------------------------- the rules

def rule(rule_id: str, title: str, evidence: list[str], passed_detail: str) -> dict:
    return {"id": rule_id, "title": title, "result": "FAIL" if evidence else "PASS",
            "evidence": evidence[:12] + ([f"… and {len(evidence) - 12} more"] if len(evidence) > 12 else []),
            "detail": passed_detail if not evidence else f"{len(evidence)} finding(s)"}


def approval_authority(change: Change) -> dict:
    evidence = []
    base_wf, head_wf = change.before(WORKFLOW), change.after(WORKFLOW)
    if member(base_wf, DECIDE) != member(head_wf, DECIDE):
        evidence.append(f"{WORKFLOW}: DecideAsync differs from the base")
    if approval_rules(base_wf) != approval_rules(head_wf):
        evidence.append(f"{WORKFLOW}: the approval rules in PermissionsFor differ from the base")
    for kind, path in change.files:
        if kind == "D" or not CODE_FILE.match(path) or TEST_FILE.search(path) or path.startswith(MIGRATIONS):
            continue
        for line_no, text in change.added_lines(path):
            if DECISION_WRITE.search(text) and path != WORKFLOW:
                evidence.append(f"{path}:{line_no}: records a decision or sets Approved/Rejected: {short(text)}")
            if DECISION_CALL.search(text):
                evidence.append(f"{path}:{line_no}: calls the decision API: {short(text)}")
    return rule("approval-authority", "Approval authority is untouched", evidence,
                "DecideAsync and the approval rules are unchanged, and no new code records decisions")


def authorization_in_workflow(change: Change) -> dict:
    evidence = []
    for kind, path in change.files:
        if kind == "D" or not API_CODE.match(path) or path == WORKFLOW or path.startswith(MIGRATIONS):
            continue
        for line_no, text in change.added_lines(path):
            if ROLE_CHECK.search(text):
                evidence.append(f"{path}:{line_no}: role or department check outside RequestWorkflow: {short(text)}")
            if ALLOW_ANON.search(text):
                evidence.append(f"{path}:{line_no}: endpoint allows anonymous access: {short(text)}")
        before, after = change.before(path), change.after(path)
        removed = len(REQUIRE_AUTH.findall(before)) - len(REQUIRE_AUTH.findall(after))
        if removed > 0:
            evidence.append(f"{path}: {removed} RequireAuthorization call(s) removed")
    return rule("authorization-in-workflow", "Authorization stays in RequestWorkflow", evidence,
                "no role or department checks added outside RequestWorkflow, and no endpoint lost its authorization")


def contract_additive(change: Change) -> tuple[dict, list[str]]:
    title = "The API contract changes only additively"
    if not any(path == CONTRACT for _, path in change.files):
        return rule("contract-additive", title, [], "the contract is unchanged"), []
    try:
        old = json.loads(change.before(CONTRACT) or "{}")
        new = json.loads(change.after(CONTRACT) or "{}")
    except json.JSONDecodeError as exc:
        return rule("contract-additive", title, [f"{CONTRACT} is not valid JSON at the head: {exc}"], ""), []
    changes = contract_changes(old, new)
    breaking = [f"breaking: {text}" for kind, text in changes if kind == "breaking"]
    additive = [text for kind, text in changes if kind == "additive"]
    return rule("contract-additive", title, breaking, f"{len(additive)} additive change(s), none breaking"), additive


def tests_with_changes(change: Change) -> dict:
    evidence = []
    changed = [path for kind, path in change.files if kind != "D"]
    moved_away = set(change.renamed.values())
    for kind, path in change.files:
        if not TEST_FILE.search(path) or (kind == "D" and path in moved_away):
            continue
        origin = change.renamed.get(path, path)
        before, after = change.before(origin), change.after(path)
        if test_cases(path, after) < test_cases(origin, before):
            evidence.append(f"{path}: {test_cases(path, after)} test case(s) at the head, {test_cases(origin, before)} at the base")
        added_skips = len(SKIPPED.findall(after)) - len(SKIPPED.findall(before))
        if added_skips > 0:
            evidence.append(f"{path}: {added_skips} Skip/.skip/.only marker(s) added")
    code = [p for p in changed if CODE_FILE.match(p) and not TEST_FILE.search(p) and not p.startswith(MIGRATIONS)
            and behavior(change.before(p)) != behavior(change.after(p))]
    tests = [p for _, p in change.files if TEST_FILE.search(p)]
    if code and not tests:
        evidence.append(f"app code changed without a test change: {', '.join(code[:5])}" + (" …" if len(code) > 5 else ""))
    detail = (f"{len(code)} code file(s) and {len(tests)} test file(s) changed; no test case removed or skipped"
              if code or tests else "no app code or test changed")
    return rule("tests-with-changes", "Behavior changes come with tests", evidence, detail)


def synthetic_data(change: Change) -> dict:
    evidence = []
    for kind, path in change.files:
        if kind == "D" or path.startswith(MIGRATIONS):
            continue
        for line_no, text in change.added_lines(path):
            for m in EMAIL.findall(text):
                if not ALLOWED_EMAIL.search(m):
                    evidence.append(f"{path}:{line_no}: e-mail address outside the synthetic domains ({masked(m)})")
            for m in GUID.findall(text):
                # Placeholders such as 00000000-… are synthetic: a random GUID has about two zeros among its 32 digits.
                if m.count("0") >= 12 or len(set(m.replace("-", ""))) <= 2:
                    continue
                if PRIVATE_ID_CONTEXT.search(text) and not BUILT_IN_ID_CONTEXT.search(text):
                    evidence.append(f"{path}:{line_no}: GUID that names a tenant, subscription, or principal ({masked(m)})")
            for label, pattern in SECRETS:
                m = pattern.search(text)
                if m:
                    evidence.append(f"{path}:{line_no}: possible {label} ({masked(m.group(0))})")
    return rule("synthetic-data", "Data is synthetic", evidence,
                "no secrets, tenant or subscription ids, or real-looking e-mail addresses in added lines")


def judge(base: dict[str, bytes], head: dict[str, bytes], diff_limit: int = 60000) -> dict:
    change = Change(base, head)
    contract, additive = contract_additive(change)
    rules = [approval_authority(change), authorization_in_workflow(change), contract, tests_with_changes(change),
             synthetic_data(change)]
    counts = {k: sum(1 for kind, _ in change.files if kind == k) for k in "AMD"}
    outside = [p for _, p in change.files if not p.startswith("app/")]
    diff, truncated = unified_diff(change, diff_limit)
    return {
        "checker": {"name": "RequestHub review rules", "version": VERSION},
        "summary": {"changed_files": len(change.files), "added": counts["A"], "modified": counts["M"], "deleted": counts["D"],
                    "outside_app": len(outside), "rules_failed": sum(r["result"] == "FAIL" for r in rules)},
        "rules": rules,
        "contract_additive_changes": additive[:20],
        "changed": [{"status": kind, "path": path} for kind, path in change.files[:300]],
        "diff": diff,
        "diff_truncated": truncated,
    }


def unified_diff(change: Change, limit: int) -> tuple[str, bool]:
    """The change as a unified diff for the reviewer agent: app code first, then tests and the contract, then the rest, so
    a long diff loses documentation before code. Generated migrations and binary files are listed, not shown."""
    def order(path: str) -> int:
        if path.startswith(("app/src/", "app/web/src/")) and not TEST_FILE.search(path):
            return 0
        return 1 if TEST_FILE.search(path) or path == CONTRACT else 2
    parts = []
    for kind, path in sorted(change.files, key=lambda f: (order(f[1]), f[1])):
        if not is_text(path) or path.startswith(MIGRATIONS):
            parts.append(f"# {'added' if kind == 'A' else 'deleted' if kind == 'D' else 'changed'}, not shown: {path}\n")
            continue
        old = change.before(path).splitlines(keepends=True)
        new = change.after(path).splitlines(keepends=True)
        parts.append("".join(difflib.unified_diff(old, new, "/dev/null" if kind == "A" else f"a/{path}",
                                                  "/dev/null" if kind == "D" else f"b/{path}")))
    text = "".join(p if p.endswith("\n") else p + "\n" for p in parts if p)
    return text[:limit], len(text) > limit


def markdown(result: dict) -> str:
    """The verdicts as a Markdown table. The review copies this table word for word."""
    lines = ["| Rule | Result | Evidence |", "| --- | --- | --- |"]
    for r in result["rules"]:
        evidence = "<br>".join(cell(e) for e in r["evidence"]) or cell(r["detail"])
        lines.append(f"| {r['title']} | {'❌ FAIL' if r['result'] == 'FAIL' else '✅ PASS'} | {evidence} |")
    return "\n".join(lines)


def cell(text: str) -> str:
    """Evidence quotes the pull request, so it goes in the table inert: no column breaks, no HTML, no @mentions."""
    text = text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"@(?=\w)", "@\u200b", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, required=True, help="Merge base: a .tar.gz archive or a directory")
    parser.add_argument("--head", type=Path, required=True, help="Pull request head: a .tar.gz archive or a directory")
    parser.add_argument("--markdown", action="store_true", help="Print the verdicts as a Markdown table instead of JSON")
    parser.add_argument("--diff-limit", type=int, default=60000, help="Characters of the unified diff to include (default 60000)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = judge(load_tree(args.base), load_tree(args.head), args.diff_limit)
    except (OSError, tarfile.TarError) as exc:
        print(json.dumps({"error": f"cannot read the source trees: {exc}"}))
        return 2
    result["markdown"] = markdown(result)
    print(result["markdown"] if args.markdown else json.dumps(result, ensure_ascii=False))
    return 1 if result["summary"]["rules_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
