#!/usr/bin/env python3
"""Set up the Design · Microsoft solution in Azure: the azd hooks, and the command a person runs to connect GitHub.

Subcommands
  prepare   azd preprovision hook. Detects this repository (owner/name), which the Function answers and writes ADR
            drafts to, and stores it as GITHUB_REPOSITORY in the azd environment.
  foundry   azd postprovision hook. Publishes, from this folder, what lives inside Azure AI Search and Foundry:
              1. syncs standards/STD-*.md into the architecture-standards index (idempotent: unchanged standards are
                 not rewritten, removed or unapproved ones are deleted);
              2. creates or updates each operating profile's Foundry IQ knowledge source and knowledge base, with the
                 profile's scope filter stored in the knowledge source;
              3. publishes the advisor agents from agent.yaml (a new version only when the definition changed);
              4. registers the five code-based evaluators and the evaluation of the labelled cases in Foundry.
  github    Connects GitHub (a person runs it once). Asks the Function whether it holds a GitHub connection. If not,
            opens the Function's setup page in your browser: GitHub creates a private app from a manifest and hands
            its credentials to the Function, then you install the app on this repository only.
              --check      only report the status (the azd postdeploy hook uses it)
              --print-url  print the setup link instead of opening it; the link carries the Function's key, so keep it private

Configuration: environment variables, or this folder's azd environment (azd env get-values). Your identity needs
the roles infra/resources.bicep grants to whoever runs azd.

Exit codes: 0 done, 1 a step failed, 2 configuration error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "function"))
from azd_env import credential, setting, utf8_stdout  # noqa: E402


def prepare() -> int:
    """Store GITHUB_REPOSITORY in the azd environment (from gh, or from the git remote)."""
    import os
    current = os.environ.get("GITHUB_REPOSITORY")
    if current:
        print(f"GitHub repository: {current}")
        return 0
    repo = ""
    try:
        repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=HERE,
                              capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if not repo:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=HERE, capture_output=True, text=True).stdout
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?\s*$", remote)
        repo = match.group(1) if match else ""
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo):
        print("error: could not detect the GitHub repository; run azd env set GITHUB_REPOSITORY <owner>/<name>", file=sys.stderr)
        return 2
    subprocess.run(["azd", "env", "set", "GITHUB_REPOSITORY", repo], cwd=HERE, check=True)
    print(f"GitHub repository: {repo}")
    return 0


def foundry() -> int:
    """Index, knowledge bases, agents, evaluators: everything the Bicep cannot declare."""
    from azure.ai.projects import AIProjectClient

    from advisor_core import agents, evaluation, knowledge, standards

    spec = agents.load_spec((HERE / "agent.yaml").read_text(encoding="utf-8"))
    files = {path.name: path.read_text(encoding="utf-8") for path in (HERE / "standards").glob("STD-*.md")}
    docs, skipped = standards.parse(files, spec)
    for name in skipped:
        print(f"skipped {name}: only approved standards are indexed")
    signed_in, search = credential(), setting("SEARCH_ENDPOINT")
    print("\n".join(standards.summary_lines(standards.sync(search, signed_in, spec["search"]["index"], docs, spec))))
    if spec["knowledge"] == "foundry-iq":
        print("\n".join(knowledge.sync(search, signed_in, spec, spec["search"]["index"])))
    project = AIProjectClient(endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"), credential=signed_in)
    model = setting("FOUNDRY_MODEL_DEPLOYMENT")
    for profile, agent in agents.publish(project, spec, model, search).items():
        tool = f"knowledge base {knowledge.name(profile)}" if spec["knowledge"] == "foundry-iq" else "Azure AI Search tool"
        print(f"agent {agent['name']} v{agent['version']} ({'reused' if agent['reused'] else 'new version'}): {tool}")
    versions = evaluation.register_evaluators(project)
    evaluation.ensure_eval(project.get_openai_client(), model, versions)
    print("evaluators: " + ", ".join(f"{evaluation.evaluator_name(k)} v{v}" for k, v in versions.items()))
    print(f"evaluation: \"{evaluation.EVAL_NAME}\" (Foundry portal > Evaluations)")
    return 0


def function_access() -> tuple[str, str]:
    """The Function's address and its default key, from Azure Resource Manager (never printed)."""
    import requests

    token = credential().get_token("https://management.azure.com/.default").token
    site = (f"https://management.azure.com/subscriptions/{setting('AZURE_SUBSCRIPTION_ID')}/resourceGroups/"
            f"{setting('AZURE_RESOURCE_GROUP')}/providers/Microsoft.Web/sites/{setting('FUNCTION_APP_NAME')}")
    headers = {"Authorization": f"Bearer {token}"}
    host = requests.get(f"{site}?api-version=2024-04-01", headers=headers, timeout=60)
    host.raise_for_status()
    keys = requests.post(f"{site}/host/default/listkeys?api-version=2024-04-01", headers=headers, timeout=60)
    keys.raise_for_status()
    return f"https://{host.json()['properties']['defaultHostName']}", keys.json()["functionKeys"]["default"]


def github(check_only: bool, print_url: bool) -> int:
    import requests

    base, key = function_access()
    deadline = time.monotonic() + 240  # right after a deployment the host restarts and answers 404 or 503 for a while
    while True:
        status = requests.get(f"{base}/api/github/status", params={"code": key}, timeout=180)
        if status.status_code == 200 or time.monotonic() > deadline:
            break
        time.sleep(15)
    if status.status_code != 200:
        print(f"{'warning' if check_only else 'error'}: the Function answered HTTP {status.status_code}; it may still be "
              "starting. Try again in a minute: python setup_azure.py github --check", file=sys.stderr)
        return 0 if check_only else 1
    data = status.json()
    if data["connected"]:
        kind = "GitHub App" if data["mode"] == "app" else "fine-grained token"
        print(f"GitHub is connected ({kind}) for {data['repository']}; webhook secret stored: {data['webhookSecret']}.")
        return 0
    if check_only:
        print(f"GitHub is not connected yet. To connect {data['repository']}, run: python setup_azure.py github")
        return 0
    url = f"{base}/api/github/setup?code={key}"
    if print_url:
        print(url)
    else:
        webbrowser.open(url)
        print("Your browser shows the setup page. Click Create GitHub App, confirm on GitHub, then install the app on "
              f"{data['repository']} only (Only select repositories). Check with: python setup_azure.py github --check")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog="Settings come from the environment or from this folder's azd environment.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="azd preprovision: store GITHUB_REPOSITORY in the azd environment")
    commands.add_parser("foundry", help="azd postprovision: index, knowledge bases, agents, evaluators")
    connect = commands.add_parser("github", help="connect GitHub (GitHub App from a manifest), or report the status")
    connect.add_argument("--check", action="store_true", help="only report whether GitHub is connected")
    connect.add_argument("--print-url", action="store_true",
                         help="print the setup link instead of opening it (it carries the Function's key)")
    args = parser.parse_args(argv)
    utf8_stdout()
    try:
        if args.command == "prepare":
            return prepare()
        if args.command == "foundry":
            return foundry()
        return github(args.check, args.print_url)
    except SystemExit:
        raise
    except Exception as exc:  # surface service and auth errors clearly; there is no offline fallback
        print(f"error: {args.command} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
