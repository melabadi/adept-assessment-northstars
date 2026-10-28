"""Connect this solution's Azure resources to GitHub Actions. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and its OIDC subject prefix, and stores them in the azd
      environment as GITHUB_REPOSITORY and GITHUB_OIDC_SUBJECT_PREFIX. Bicep uses them to create the federated
      credential that lets this solution's GitHub environment sign in to Azure without a stored secret.

  python configure_github.py publish    (azd postprovision hook)
      Creates or updates the GitHub environment, limits it to the main branch (only main applies the agent's
      configuration), and stores what the workflow reads. The Azure sign-in values and the resource names that carry
      the deployment's random suffix are secrets, so GitHub masks them in every log line; names without a suffix and
      the alert threshold are variables. With OIDC there is no password or key to store.

Needs the GitHub CLI signed in with admin rights on the repository (environments and secrets need them).
To target another repository, run `azd env set GITHUB_REPOSITORY owner/name` first.
To skip the GitHub side entirely, run `azd env set SKIP_GITHUB true`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

ENVIRONMENT = "operate-microsoft"
# GitHub secret name -> azd environment value. Workflow logs list every variable a step receives, and anyone can read
# a public repository's logs, so anything that names a deployed resource with its random suffix is a secret.
SECRETS = {
    "AZURE_CLIENT_ID": "AUTOMATION_CLIENT_ID",
    "AZURE_TENANT_ID": "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID": "AZURE_SUBSCRIPTION_ID",
    "WORKER_APP_NAME": "WORKER_APP_NAME",
    "API_APP_NAME": "API_APP_NAME",
    "APPLICATIONINSIGHTS_NAME": "APPLICATIONINSIGHTS_NAME",
    "LOG_ANALYTICS_NAME": "LOG_ANALYTICS_NAME",
}
# GitHub variable name -> azd environment value: fixed names and settings that identify nothing.
VARIABLES = {
    "AZURE_RESOURCE_GROUP": "AZURE_RESOURCE_GROUP",
    "SRE_AGENT_NAME": "SRE_AGENT_NAME",
    "BACKLOG_ALERT_NAME": "BACKLOG_ALERT_NAME",
    "BACKLOG_ALERT_THRESHOLD_SECONDS": "BACKLOG_ALERT_THRESHOLD_SECONDS",
}


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"error: {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip()


def azd_values() -> dict[str, str]:
    return json.loads(run("azd", "env", "get-values", "--output", "json"))


def prepare() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY") or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    claims = json.loads(run("gh", "api", f"repos/{repo}/actions/oidc/customization/sub"))
    prefix = claims.get("sub_claim_prefix", "") if claims.get("use_immutable_subject") else ""
    run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
    run("azd", "env", "set", "GITHUB_OIDC_SUBJECT_PREFIX", prefix)
    print(f"GitHub repository {repo}, OIDC subject prefix: {prefix or 'repo:' + repo + ' (classic)'}")


def publish() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("error: GITHUB_REPOSITORY is not set; run `azd provision` again so the preprovision hook sets it.")
    missing = [name for name in [*SECRETS.values(), *VARIABLES.values()] if not values.get(name)]
    if missing:
        raise SystemExit(f"error: azd outputs missing: {', '.join(missing)}. Did `azd provision` succeed?")
    run("gh", "api", "-X", "PUT", f"repos/{repo}/environments/{ENVIRONMENT}", "--input", "-",
        stdin=json.dumps({"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}))
    policies = json.loads(run("gh", "api", f"repos/{repo}/environments/{ENVIRONMENT}/deployment-branch-policies"))
    if not any(p.get("name") == "main" for p in policies.get("branch_policies", [])):
        run("gh", "api", "-X", "POST", f"repos/{repo}/environments/{ENVIRONMENT}/deployment-branch-policies",
            "-f", "name=main", "-f", "type=branch")
    for secret, source in SECRETS.items():
        run("gh", "secret", "set", secret, "--env", ENVIRONMENT, "--repo", repo, stdin=values[source])
    for variable, source in VARIABLES.items():
        run("gh", "variable", "set", variable, "--env", ENVIRONMENT, "--repo", repo, "--body", values[source])
    # Earlier versions stored the suffixed names as variables; a secret and a variable with one name would both exist.
    existing = json.loads(run("gh", "api", f"repos/{repo}/environments/{ENVIRONMENT}/variables?per_page=100"))
    stale = [v["name"] for v in existing.get("variables", []) if v["name"] in SECRETS]
    for variable in stale:
        run("gh", "variable", "delete", variable, "--env", ENVIRONMENT, "--repo", repo)
    print(f"GitHub environment '{ENVIRONMENT}' in {repo} (main only): {len(SECRETS)} secrets, {len(VARIABLES)} variables set"
          + (f", {len(stale)} old variables removed." if stale else "."))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "publish"}:
        print(__doc__)
        return 2
    if os.environ.get("SKIP_GITHUB", "").lower() == "true":
        print("SKIP_GITHUB is true: GitHub environment not configured.")
        return 0
    if not shutil.which("gh"):
        raise SystemExit("error: the GitHub CLI (gh) is required. Install it, run `gh auth login`, or set SKIP_GITHUB=true.")
    if sys.argv[1] == "prepare":
        prepare()
    else:
        publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
