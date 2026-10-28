"""Preflight for gated releases on Azure Container Apps: are the app, its release identity, and GitHub ready?

Run it after `azd up`, before the first release, or when a release workflow fails before it reaches the gate.
Each check prints PASS, WARN, or FAIL with what to do. The exit code is 1 when any check fails. It changes nothing.

  Azure CLI   you are signed in
  App         multiple-revision mode (a candidate runs beside the stable revision), external ingress
  Traffic     exactly one revision serves 100%, and no candidate is left over from an interrupted release
  Probes      the revision users get has startup, liveness, and readiness probes (the gate trusts readiness)
  Database    the PostgreSQL server is Ready: a tenant policy can stop it on a schedule, and then every revision fails
              readiness, so a gate would fail for the wrong reason
  Production  the production URL's readiness endpoint answers 200
  Identity    the GitHub Actions identity trusts the GitHub environment through OIDC and holds the two roles a
              release needs: Container Apps Contributor on the resource group and AcrPush on the registry
  GitHub      the environment exists and holds, as secrets, the Azure sign-in values and every value that names a
              deployed resource (GitHub masks secrets in logs; it prints variables), plus the resource group variable

Settings come from the options, then environment variables, then the azd environment in --azd-dir:

  python .github/skills/azure-deployment/preflight.py
  python .github/skills/azure-deployment/preflight.py --resource-group rg-ai-sdlc-release --app ca-api-xxxx --repo owner/name
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def default_azd_dir() -> Path:
    """The solution folder, whether this runs from the root .github mirror or from the solution's own copy."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "solutions" / "06-release-microsoft").is_dir():
            return parent / "solutions" / "06-release-microsoft"
    return Path.cwd()


RELEASE_ROLES = {"Container Apps Contributor": "resourcegroups/{rg}", "AcrPush": "/registries/"}
BROAD_ROLES = {"Owner", "Contributor", "User Access Administrator", "Role Based Access Control Administrator"}
SECRETS = ["AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID", "API_APP_NAME", "API_IDENTIFIER_URI",
           "AZURE_CONTAINER_REGISTRY_ENDPOINT"]
VARIABLES = ["AZURE_RESOURCE_GROUP"]
counts = {"PASS": 0, "WARN": 0, "FAIL": 0}


def run(tool: str, *args: str, cwd: Path | None = None) -> tuple[int, str]:
    exe = shutil.which(tool)
    if not exe:
        return 127, f"{tool} is not installed"
    proc = subprocess.run([exe, *args], capture_output=True, text=True, cwd=cwd)
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr or proc.stdout).strip()


def az(*args: str):
    code, out = run("az", *args, "--output", "json")
    if code:
        raise RuntimeError(out.splitlines()[-1] if out else f"az {' '.join(args[:3])} failed")
    return json.loads(out or "null")


def report(level: str, area: str, message: str, fix: str = "") -> None:
    counts[level] += 1
    print(f"{level:<4}  {area:<9} {message}")
    if fix and level != "PASS":
        print(f"{'':15}→ {fix}")


def settings(args) -> dict[str, str]:
    values: dict[str, str] = {}
    azd_dir = Path(args.azd_dir)
    if azd_dir.is_dir():
        code, out = run("azd", "env", "get-values", "--output", "json", cwd=azd_dir)
        if code == 0:
            values = json.loads(out)
    pick = lambda option, name: option or os.environ.get(name) or values.get(name, "")  # noqa: E731
    return {
        "rg": pick(args.resource_group, "AZURE_RESOURCE_GROUP"),
        "app": pick(args.app, "API_APP_NAME"),
        "repo": pick(args.repo, "GITHUB_REPOSITORY"),
        "environment": args.environment,
    }


def check_app(s: dict) -> dict | None:
    try:
        app = az("containerapp", "show", "--name", s["app"], "--resource-group", s["rg"])
    except RuntimeError as error:
        report("FAIL", "App", f"{s['app']} not found in {s['rg']}: {error}", "Run `azd up` in the solution folder.")
        return None
    config = app["properties"]["configuration"]
    mode = config.get("activeRevisionsMode")
    report("PASS" if mode == "Multiple" else "FAIL", "App", f"{s['app']}: activeRevisionsMode {mode}",
           "Set activeRevisionsMode to Multiple (app/infra/api.bicep does) so a candidate can run beside stable.")
    ingress = config.get("ingress") or {}
    report("PASS" if ingress.get("external") else "FAIL", "App", f"ingress {'external' if ingress.get('external') else 'internal or off'}: {ingress.get('fqdn')}",
           "The release reaches the candidate through its label URL, which needs ingress.")
    kept = config.get("maxInactiveRevisions")
    report("PASS" if (kept or 0) >= 2 else "WARN", "App", f"maxInactiveRevisions {kept}",
           "Keep a few inactive revisions so older builds can be reactivated for a rollback.")
    return app


def check_database(s: dict) -> None:
    servers = az("postgres", "flexible-server", "list", "--resource-group", s["rg"])
    if not servers:
        report("WARN", "Database", f"no PostgreSQL flexible server in {s['rg']}", "The app's database lives in its resource group; check `azd up` finished.")
        return
    for server in servers:
        state = server.get("state")
        fix = (f"Start it: az postgres flexible-server start -g {s['rg']} -n {server['name']} (3 to 5 minutes). A tenant policy "
               "can stop servers on a schedule; a stopped database makes every revision fail readiness.")
        if state == "Ready":
            report("PASS", "Database", f"{server['name']} is Ready")
        elif state in ("Starting", "Updating"):
            report("WARN", "Database", f"{server['name']} is {state}", "Wait until it is Ready (a few minutes), then run the preflight again.")
        else:
            report("FAIL", "Database", f"{server['name']} is {state}", fix)


def check_production(app: dict) -> None:
    fqdn = app["properties"]["configuration"]["ingress"].get("fqdn")
    try:
        with urllib.request.urlopen(f"https://{fqdn}/health/ready", timeout=20) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        status = f"no answer ({getattr(error, 'reason', error)})"
    report("PASS" if status == 200 else "FAIL", "Production", f"/health/ready answers {status}",
           "The revision users get is not ready. Check the Database line, then run the deployment-recovery skill's diagnose.py.")


def check_traffic_and_probes(s: dict, app: dict) -> None:
    revisions = {r["name"]: r for r in az("containerapp", "revision", "list", "--name", s["app"],
                                          "--resource-group", s["rg"], "--all")}
    latest_ready = app["properties"].get("latestReadyRevisionName")
    weights: dict[str, int] = {}
    labels: dict[str, str] = {}
    for entry in app["properties"]["configuration"]["ingress"].get("traffic") or []:
        name = entry.get("revisionName") or (latest_ready if entry.get("latestRevision") else None)
        weights[name] = weights.get(name, 0) + int(entry.get("weight") or 0)
        if entry.get("label"):
            labels[entry["label"]] = name
    serving = [name for name, weight in weights.items() if weight > 0]
    if len(serving) != 1:
        report("FAIL", "Traffic", "traffic is split: " + ", ".join(f"{n} {weights[n]}%" for n in serving),
               "Finish the release with release.py promote, abort, or rollback.")
        return
    stable = serving[0]
    report("PASS", "Traffic", f"{stable} serves 100%" + (" (label stable)" if labels.get("stable") == stable else
                                                       " (no stable label yet: the first release adds it)"))
    if labels.get("candidate"):
        report("WARN", "Traffic", f"candidate {labels['candidate']} is left over from a release that did not finish",
               "Run release.py gate then promote, or release.py abort. The next deploy also replaces it.")
    containers = revisions.get(stable, {}).get("properties", {}).get("template", {}).get("containers") or []
    probes = {p.get("type"): p for c in containers for p in (c.get("probes") or [])}
    missing = [kind for kind in ("Startup", "Liveness", "Readiness") if kind not in probes]
    readiness = probes.get("Readiness", {}).get("httpGet", {}).get("path")
    report("FAIL" if "Readiness" in missing else "WARN" if missing else "PASS", "Probes",
           f"readiness {readiness or 'missing'}" + (f"; missing {', '.join(missing)}" if missing else "; startup and liveness present"),
           "The gate trusts the readiness probe: give the container an HTTP readiness probe that checks its dependencies.")


def check_identity(s: dict) -> None:
    trusted = []
    for identity in az("identity", "list", "--resource-group", s["rg"]):
        credentials = az("identity", "federated-credential", "list", "--identity-name", identity["name"], "--resource-group", s["rg"])
        for credential in credentials:
            if "token.actions.githubusercontent.com" in credential.get("issuer", "") and \
                    credential.get("subject", "").endswith(f":environment:{s['environment']}"):
                trusted.append((identity, credential))
    if not trusted:
        report("FAIL", "Identity", f"no identity in {s['rg']} trusts GitHub environment {s['environment']}",
               "Run `azd provision` in the solution folder; its preprovision hook sets the repository for the federated credential.")
        return
    identity, credential = trusted[0]
    report("PASS", "Identity", f"{identity['name']} trusts {credential['subject']}")
    assignments = az("role", "assignment", "list", "--all", "--assignee", identity["principalId"])
    held = [(a.get("roleDefinitionName"), a.get("scope", "").lower()) for a in assignments]
    for role, scope_hint in RELEASE_ROLES.items():
        hint = scope_hint.format(rg=s["rg"].lower()).lower()
        scopes = [scope for name, scope in held if name == role and hint in scope]
        report("PASS" if scopes else "FAIL", "Identity", f"{role} " + ("on " + scopes[0].split("/")[-1] if scopes else "missing"),
               f"Grant {role} ({'automationRoleDefinitionIds in app/infra/requesthub.bicep' if role != 'AcrPush' else 'requesthub.bicep grants it on the registry'}) and run `azd provision`.")
    broad = [f"{name} on {scope.split('/')[-1]}" for name, scope in held if name in BROAD_ROLES]
    if broad:
        report("WARN", "Identity", f"broader roles than a release needs: {', '.join(broad)}", "Remove them; a release needs only the two roles above.")


def check_github(s: dict) -> None:
    repo = s["repo"]
    if not repo:
        code, out = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
        repo = out if code == 0 else ""
    if not repo:
        report("FAIL", "GitHub", "repository unknown", "Pass --repo owner/name, or run from a clone with `gh auth login` done.")
        return
    code, out = run("gh", "api", f"repos/{repo}/environments/{s['environment']}")
    if code:
        report("FAIL", "GitHub", f"environment {s['environment']} not found in {repo}", "Run `azd provision`; the postprovision hook creates it.")
        return
    rules = [rule.get("type") for rule in json.loads(out).get("protection_rules", [])]
    report("PASS", "GitHub", f"environment {s['environment']} in {repo}" + (f" (protection: {', '.join(rules)})" if rules else " (no protection rules)"))
    code, out = run("gh", "secret", "list", "--env", s["environment"], "--repo", repo, "--json", "name")
    names = {item["name"] for item in json.loads(out)} if code == 0 else set()
    missing = [name for name in SECRETS if name not in names]
    report("FAIL" if missing else "PASS", "GitHub", "secrets " + (f"missing {', '.join(missing)}" if missing else ", ".join(SECRETS)),
           "Run `python configure_github.py publish` in the solution folder (or `azd provision`) to publish them.")
    code, out = run("gh", "variable", "list", "--env", s["environment"], "--repo", repo, "--json", "name,value")
    variables = {item["name"]: item["value"] for item in json.loads(out)} if code == 0 else {}
    missing = [name for name in VARIABLES if name not in variables]
    stale = [name for name in VARIABLES if variables.get(name) and variables[name] != s["rg"]]
    report("FAIL" if missing or stale else "PASS", "GitHub",
           "variable " + (f"missing {', '.join(missing)}" if missing else f"points to another resource group: {', '.join(stale)}" if stale else "AZURE_RESOURCE_GROUP points at this app's resource group"),
           "Run `python configure_github.py publish` in the solution folder (or `azd provision`) to publish it.")
    exposed = [name for name in variables if name not in VARIABLES]
    if exposed:
        report("WARN", "GitHub", f"variables {', '.join(exposed)} name your resources, and workflow logs print every variable",
               "Run `python configure_github.py publish` in the solution folder: it publishes them as secrets and deletes the variables.")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resource-group", help="resource group of the app (default: AZURE_RESOURCE_GROUP)")
    parser.add_argument("--app", help="container app to release (default: API_APP_NAME)")
    parser.add_argument("--environment", default="release-microsoft", help="GitHub environment of the release workflows (default release-microsoft)")
    parser.add_argument("--repo", help="GitHub repository owner/name (default: GITHUB_REPOSITORY or the current clone)")
    parser.add_argument("--azd-dir", default=str(default_azd_dir()), help="folder whose azd environment supplies missing settings (default: solutions/06-release-microsoft)")
    args = parser.parse_args()
    s = settings(args)
    if not s["rg"] or not s["app"]:
        raise SystemExit("error: pass --resource-group and --app, or run `azd up` in the solution folder first.")

    code, out = run("az", "account", "show", "--query", "user.name", "--output", "tsv")
    report("PASS" if code == 0 else "FAIL", "Azure CLI", f"signed in as {out}" if code == 0 else "not signed in", "Run `az login`.")
    if code == 0:
        app = check_app(s)
        if app:
            check_traffic_and_probes(s, app)
        check_database(s)
        if app:
            check_production(app)
        check_identity(s)
    check_github(s)
    print(f"\n{counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
