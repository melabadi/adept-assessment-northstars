"""Connect this solution's Azure resources to GitHub Actions. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and its OIDC subject prefix, and stores them in the azd
      environment as GITHUB_REPOSITORY and GITHUB_OIDC_SUBJECT_PREFIX. Bicep uses them to create the federated
      credential that lets this solution's GitHub environment sign in to Azure without a stored secret.

  python configure_github.py publish    (azd postprovision hook)
      Creates or updates the GitHub environment `release-microsoft` and stores what the release workflows need. The
      Azure sign-in values and every value that names a deployed resource (the app's name, its API identifier, the
      registry's host name) are secrets: GitHub masks secrets wherever they appear in logs and job summaries, while it
      prints variables in every step's environment listing. Only the resource group, whose name identifies nothing,
      is a variable. With OIDC there is no password or key to store. Variables that earlier versions published for the
      other values are deleted.

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

ENVIRONMENT = "release-microsoft"
# GitHub secret name -> azd environment value
SECRETS = {
    "AZURE_CLIENT_ID": "AUTOMATION_CLIENT_ID",
    "AZURE_TENANT_ID": "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID": "AZURE_SUBSCRIPTION_ID",
    "API_APP_NAME": "API_APP_NAME",
    "API_IDENTIFIER_URI": "API_IDENTIFIER_URI",
    "AZURE_CONTAINER_REGISTRY_ENDPOINT": "AZURE_CONTAINER_REGISTRY_ENDPOINT",
}
# GitHub variable name -> azd environment value
VARIABLES = {
    "AZURE_RESOURCE_GROUP": "AZURE_RESOURCE_GROUP",
}
# Published as variables by earlier versions, so they appeared in workflow logs. Deleted when present.
OBSOLETE_VARIABLES = ["API_APP_NAME", "API_URL", "API_IDENTIFIER_URI", "AZURE_CONTAINER_REGISTRY_ENDPOINT"]


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
    run("gh", "api", "-X", "PUT", f"repos/{repo}/environments/{ENVIRONMENT}")
    for secret, source in SECRETS.items():
        run("gh", "secret", "set", secret, "--env", ENVIRONMENT, "--repo", repo, stdin=values[source])
    for variable, source in VARIABLES.items():
        run("gh", "variable", "set", variable, "--env", ENVIRONMENT, "--repo", repo, "--body", values[source])
    existing = {v["name"] for v in json.loads(run("gh", "variable", "list", "--env", ENVIRONMENT, "--repo", repo, "--json", "name"))}
    removed = [name for name in OBSOLETE_VARIABLES if name in existing]
    for name in removed:
        run("gh", "variable", "delete", name, "--env", ENVIRONMENT, "--repo", repo)
    print(f"GitHub environment '{ENVIRONMENT}' in {repo}: {len(SECRETS)} secrets, {len(VARIABLES)} variable set"
          + (f"; deleted the old variables {', '.join(removed)}." if removed else "."))


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
