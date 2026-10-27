"""Connect this solution's Azure resources to GitHub Actions. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and its OIDC subject prefix, and stores them in the azd
      environment as GITHUB_REPOSITORY and GITHUB_OIDC_SUBJECT_PREFIX. Bicep uses them to create the federated
      credential that lets this solution's GitHub environment sign in to Azure without a stored secret.

  python configure_github.py publish    (azd postprovision hook)
      Creates or updates the GitHub environment `secure-microsoft` and stores the Azure sign-in values (secrets) and the
      names and endpoints the workflows read (variables): the resource group to scan, the deployment parameters for the
      what-if preview, and the RequestHub API for the post-deployment check. With OIDC there is no password or key to store.

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

ENVIRONMENT = "secure-microsoft"
# GitHub secret name -> azd environment value
SECRETS = {
    "AZURE_CLIENT_ID": "AUTOMATION_CLIENT_ID",
    "AZURE_TENANT_ID": "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID": "AZURE_SUBSCRIPTION_ID",
}
# GitHub variable name -> azd environment value
VARIABLES = {
    "AZURE_ENV_NAME": "AZURE_ENV_NAME",
    "AZURE_LOCATION": "AZURE_LOCATION",
    "AZURE_RESOURCE_GROUP": "AZURE_RESOURCE_GROUP",
    "POLICY_ASSIGNMENT_NAME": "POLICY_ASSIGNMENT_NAME",
    "API_URL": "API_URL",
    "API_IDENTIFIER_URI": "API_IDENTIFIER_URI",
}
# Deployment parameters the what-if preview needs to reproduce `azd provision` exactly. Set only when present: the prefix is
# empty for repositories with classic OIDC subjects (and GitHub variable names cannot start with GITHUB_). The presenter's
# object id is not a credential; it is stored as a secret only to keep it out of logs.
OPTIONAL_VARIABLES = {"OIDC_SUBJECT_PREFIX": "GITHUB_OIDC_SUBJECT_PREFIX"}
OPTIONAL_SECRETS = {"AZURE_PRINCIPAL_ID": "AZURE_PRINCIPAL_ID"}


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
    # azd passes AZURE_PRINCIPAL_ID to hooks as an environment variable but does not always save it; fall back to the
    # signed-in Azure CLI user, who is the person running azd.
    principal = values.get("AZURE_PRINCIPAL_ID") or os.environ.get("AZURE_PRINCIPAL_ID")
    if not principal and (az := shutil.which("az")):
        proc = subprocess.run([az, "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"], capture_output=True, text=True)
        principal = proc.stdout.strip() if proc.returncode == 0 else ""
    if principal:
        values["AZURE_PRINCIPAL_ID"] = principal
    repo = values.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("error: GITHUB_REPOSITORY is not set; run `azd provision` again so the preprovision hook sets it.")
    missing = [name for name in [*SECRETS.values(), *VARIABLES.values()] if not values.get(name)]
    if missing:
        raise SystemExit(f"error: azd outputs missing: {', '.join(missing)}. Did `azd provision` succeed?")
    run("gh", "api", "-X", "PUT", f"repos/{repo}/environments/{ENVIRONMENT}")
    secrets = {**SECRETS, **{k: v for k, v in OPTIONAL_SECRETS.items() if values.get(v)}}
    variables = {**VARIABLES, **{k: v for k, v in OPTIONAL_VARIABLES.items() if values.get(v)}}
    for secret, source in secrets.items():
        run("gh", "secret", "set", secret, "--env", ENVIRONMENT, "--repo", repo, stdin=values[source])
    for variable, source in variables.items():
        run("gh", "variable", "set", variable, "--env", ENVIRONMENT, "--repo", repo, "--body", values[source])
    print(f"GitHub environment '{ENVIRONMENT}' in {repo}: {len(secrets)} secrets, {len(variables)} variables set.")


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
