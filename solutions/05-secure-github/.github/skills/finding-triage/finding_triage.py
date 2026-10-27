"""Check CodeQL entitlement and summarize real SARIF for the isolated RequestHub lab.

Run `python finding_triage.py --help` for subcommands. Python 3.12+, standard library;
preflight also needs authenticated gh. This reporter does not run or emulate a scanner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import unquote

RULE = "cs/sql-injection"
SOURCE = "app/src/RequestHub.Core/Services/RequestWorkflow.cs"


def api(path: str) -> object:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def preflight(repo: str, ref: str) -> dict:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Expected repository OWNER/REPO")
    if not re.fullmatch(r"(lab/secure-|copilot/)[A-Za-z0-9._/-]+", ref) or ".." in ref:
        raise ValueError("Only lab/secure-* or its copilot/* remediation branch may be scanned")
    repository = api(f"repos/{repo}")
    settings = repository.get("security_and_analysis") or {}
    licensed = any(settings.get(key, {}).get("status") == "enabled"
                   for key in ("advanced_security", "code_security"))
    if repository["private"] and repository["owner"]["type"] == "Organization" and not licensed:
        # Repository security settings are admin-only; a read-only Actions token can probe the service instead.
        try:
            alerts = api(f"repos/{repo}/code-scanning/alerts?per_page=1")
        except subprocess.CalledProcessError as error:
            if not any(status in (error.stderr or "") for status in ("HTTP 403", "HTTP 404")):
                raise
        else:
            if not isinstance(alerts, list):
                raise ValueError("Unexpected code scanning entitlement response")
            licensed = True
    allowed = not repository["private"] or (repository["owner"]["type"] == "Organization" and licensed)
    if not allowed:
        return {"status": "BLOCKED", "repository": repo, "ref": ref, "reason":
                "Private CodeQL analysis requires an organization with GitHub Code Security enabled. "
                "Make the repository public when ready, or move to a licensed organization. "
                "No CodeQL analysis or upload was attempted."}
    if ref.startswith("copilot/"):
        prs = api(f"repos/{repo}/pulls?state=open&head={repository['owner']['login']}:{ref}")
        if not any(pr["base"]["ref"].startswith("lab/secure-") and
                   pr["head"]["repo"]["full_name"] == repo for pr in prs):
            raise ValueError("Copilot branch must have an open same-repository PR targeting lab/secure-*")
    commit = api(f"repos/{repo}/commits/{ref}")
    return {"status": "PASS", "repository": repo, "ref": ref, "scanned_sha": commit["sha"],
            "reason": "Public repository" if not repository["private"] else "Code Security enabled"}


def summarize(folder: Path, expect: str, sha: str) -> dict:
    if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise ValueError("An immutable full commit SHA is required")
    files = sorted(folder.rglob("*.sarif")) if folder.is_dir() else [folder]
    if not files:
        raise ValueError("No SARIF files found")
    findings, versions = [], set()
    run_count = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if document.get("version") != "2.1.0" or not document.get("runs"):
            raise ValueError(f"{path}: expected SARIF 2.1.0 with runs")
        for run in document["runs"]:
            driver = run["tool"]["driver"]
            if driver.get("name") != "CodeQL":
                raise ValueError(f"{path}: not a CodeQL result")
            invocations = run.get("invocations", [])
            if not invocations or any(item.get("executionSuccessful") is not True for item in invocations):
                raise ValueError(f"{path}: missing or unsuccessful scanner invocation")
            versions.add(driver.get("semanticVersion") or driver.get("version") or "unspecified")
            run_count += 1
            rules = driver.get("rules", [])
            for result in run.get("results", []):
                rule = result.get("ruleId")
                if rule is None and "ruleIndex" in result:
                    rule = rules[result["ruleIndex"]]["id"]
                if rule != RULE:
                    continue
                locations = result.get("locations", [])
                if not locations:
                    raise ValueError("SQL injection result has no physical location")
                for location in locations:
                    physical = location["physicalLocation"]
                    uri = unquote(physical["artifactLocation"]["uri"]).replace("\\", "/")
                    if uri == SOURCE or uri.endswith("/" + SOURCE):
                        findings.append({"rule": rule, "path": SOURCE,
                                         "line": physical["region"]["startLine"],
                                         "message": result["message"].get("text", "")})
    passed = bool(findings) if expect == "present" else not findings
    return {"status": "PASS" if passed else "FAIL", "scanned_sha": sha, "expect": expect,
            "rule": RULE, "tool": "CodeQL", "versions": sorted(versions), "runs": run_count,
            "findings": findings, "reason": f"{RULE} {expect} ({len(findings)} finding(s))"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight", help="Check live repository entitlement before using CodeQL")
    check.add_argument("--repo", required=True, help="GitHub repository OWNER/REPO")
    check.add_argument("--ref", required=True, help="lab/secure-* branch, or its copilot/* PR branch")
    scan = commands.add_parser("sarif", help="Summarize CodeQL SARIF; never substitute for a scanner run")
    scan.add_argument("--input", type=Path, required=True, help="SARIF file or directory from the scan run")
    scan.add_argument("--expect", choices=["present", "absent"], required=True, help="Required finding state")
    scan.add_argument("--sha", required=True, help="Full SHA of the code actually analyzed")
    for command in (check, scan):
        command.add_argument("--out", type=Path, required=True, help="Machine-readable evidence JSON to write")
    args = parser.parse_args()
    try:
        result = preflight(args.repo, args.ref) if args.command == "preflight" else summarize(
            args.input, args.expect, args.sha)
    except (ValueError, KeyError, IndexError, OSError, subprocess.CalledProcessError) as error:
        result = {"status": "FAIL", "reason": str(error)}
        if isinstance(error, subprocess.CalledProcessError):
            result["reason"] += ": " + error.stderr.strip()
    result.update(schema_version="1.0", timestamp_utc=datetime.now(timezone.utc).isoformat())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['status']}: {result['reason']}")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## CodeQL lab evidence\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n")
    if output := os.environ.get("GITHUB_OUTPUT"):
        if result["status"] == "PASS" and "scanned_sha" in result:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"sha={result['scanned_sha']}\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
