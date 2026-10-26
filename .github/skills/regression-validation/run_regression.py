#!/usr/bin/env python3
"""Run the regression checks that cover a change and summarize what failed (regression-validation skill).

It looks at the files changed since the merge base of --base (committed and uncommitted) and runs only the suites that
cover them, so an agent or a developer gets one honest answer before asking for review:

  app/src, app/tests          dotnet build + integration tests (PostgreSQL on localhost:5432)
  app/web                     TypeScript typecheck + web unit tests
  app/contracts/openapi.json  additive-only contract check (contract-impact skill)
  --e2e                       also builds the web UI into the API, starts it, and runs the Playwright tests

Usage
  python .github/skills/regression-validation/run_regression.py              # suites for files changed vs origin/main
  python .github/skills/regression-validation/run_regression.py --all --e2e  # everything, including browser tests
  python .github/skills/regression-validation/run_regression.py --base main

Exit codes: 0 every selected suite passed, 1 at least one failed, 2 configuration error.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
NPM = shutil.which("npm") or "npm"


def run(name: str, cmd: list[str], cwd: Path = REPO, env: dict | None = None) -> tuple[bool, str]:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = proc.stdout + proc.stderr
    print("\n".join(output.splitlines()[-15:]))
    return proc.returncode == 0, output


def failures(output: str) -> list[str]:
    """Failing test names from dotnet test (MTP), vitest, and Playwright output."""
    patterns = [r"^\s*failed (\S.*?) \(\d", r"^\s*(?:FAIL|×|✗)\s+(.+)$", r"^\s*\d+\) \[.*?\] › (.+)$", r"error (CS\d+: .+?) \["]
    found: list[str] = []
    for pattern in patterns:
        found += [m.strip() for m in re.findall(pattern, output, re.M)]
    return list(dict.fromkeys(found))[:10]


def changed_files(base: str) -> list[str]:
    merge_base = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if not merge_base:
        raise SystemExit(f"error: cannot find the merge base with {base}")
    diff = subprocess.run(["git", "diff", "--name-only", merge_base], cwd=REPO, capture_output=True, text=True).stdout.split()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO, capture_output=True, text=True).stdout.split()
    return [p.replace("\\", "/") for p in diff + untracked]


def e2e() -> tuple[bool, str]:
    ok, out = run("Build web UI into the API", [NPM, "run", "build", "--prefix", "app/web"])
    if not ok:
        return ok, out
    ok, out = run("Build API", ["dotnet", "build", "app/src/RequestHub.Api", "-c", "Release"])
    if not ok:
        return ok, out
    env = {**os.environ, "ASPNETCORE_ENVIRONMENT": "Development", "ASPNETCORE_URLS": "http://localhost:5080"}
    api = subprocess.Popen(["dotnet", "run", "--project", "app/src/RequestHub.Api", "-c", "Release", "--no-build", "--no-launch-profile"],
                           cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://localhost:5080/health/ready", timeout=2)
                break
            except Exception:
                time.sleep(2)
        else:
            return False, "API did not become ready on http://localhost:5080"
        return run("Playwright browser tests", [NPM, "run", "e2e"], cwd=REPO / "app/web", env={"BASE_URL": "http://localhost:5080"})
    finally:
        api.terminate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="Base branch or ref used to find changed files (default origin/main)")
    parser.add_argument("--all", action="store_true", help="Run every suite regardless of what changed")
    parser.add_argument("--e2e", action="store_true", help="Also run the Playwright browser tests against a local API")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    files = [] if args.all else changed_files(args.base)
    touched = lambda prefix: args.all or any(f.startswith(prefix) for f in files)  # noqa: E731
    results: list[tuple[str, bool, list[str]]] = []

    if touched("app/src") or touched("app/tests") or touched("app/Directory."):
        ok, out = run("API and worker integration tests", ["dotnet", "test", "--solution", "app/RequestHub.slnx"])
        results.append(("API and worker tests", ok, failures(out)))
    if touched("app/web"):
        for name, script in (("Web typecheck", "typecheck"), ("Web unit tests", "test")):
            ok, out = run(name, [NPM, "run", script, "--prefix", "app/web"])
            results.append((name, ok, failures(out)))
    if touched("app/contracts"):
        has_base = subprocess.run(["git", "cat-file", "-e", f"{args.base}:app/contracts/openapi.json"], cwd=REPO, capture_output=True).returncode == 0
        if has_base:
            ok, out = run("Contract is additive", [sys.executable, ".github/skills/contract-impact/contract_diff.py", "--base-ref", args.base, "--fail-on-breaking"])
            results.append(("Contract is additive", ok, []))
        else:
            print(f"\n=== Contract check skipped: {args.base} has no app/contracts/openapi.json yet")
    if args.e2e:
        ok, out = e2e()
        results.append(("Browser tests", ok, failures(out)))

    if not results:
        print("No app files changed; nothing to run. Use --all to run everything.")
        return 0
    print("\n## Regression summary")
    for name, ok, failed in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        for test in failed:
            print(f"        - {test}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
