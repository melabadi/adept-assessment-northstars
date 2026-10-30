"""Connect this solution's Azure automation to its GitHub repository. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and stores it in the azd environment as GITHUB_REPOSITORY, so the Logic
      Apps and the what-if job know where to file Issues and pull requests. Warns when POSTURE_GITHUB_TOKEN is not set.

  python configure_github.py publish    (azd postprovision hook)
      Creates or updates one repository webhook that sends pull_request events to the Logic App posture-preview, so a push
      to a pull request that changes this solution's infra/ gets a new Azure what-if preview. The webhook's URL is the
      Logic App's trigger URL, which carries a signature: it is read from Azure each time and never printed or saved.

  python configure_github.py remove     (azd predown hook)
      Deletes that webhook.

Uses the GitHub CLI of the person running azd, who needs admin rights on the repository (webhooks need them). To target
another repository, run `azd env set GITHUB_REPOSITORY owner/name` first. To skip GitHub, run
`azd env set SKIP_GITHUB true`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

TRIGGER = "Pull_request_event"


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        # Never echo the command line: for webhooks it can contain the trigger URL.
        raise SystemExit(f"error: {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout.strip()


def azd_values() -> dict[str, str]:
    return json.loads(run("azd", "env", "get-values", "--output", "json"))


def prepare() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY") or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
    print(f"GitHub repository: {repo}")
    if not values.get("POSTURE_GITHUB_TOKEN"):
        print("warning: POSTURE_GITHUB_TOKEN is not set. The Logic Apps and the what-if job cannot reach GitHub until you "
              "create the fine-grained token (see the README, Set up) and run `azd provision` again.")


def trigger_url(values: dict[str, str]) -> str:
    az = shutil.which("az") or "az"
    workflow = values.get("PREVIEW_WORKFLOW_NAME", "posture-preview")
    subscription = values.get("AZURE_SUBSCRIPTION_ID") or run(az, "account", "show", "--query", "id", "-o", "tsv")
    url = (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{values['AZURE_RESOURCE_GROUP']}"
           f"/providers/Microsoft.Logic/workflows/{workflow}/triggers/{TRIGGER}/listCallbackUrl?api-version=2019-05-01")
    return run(az, "rest", "--method", "post", "--url", url, "--query", "value", "-o", "tsv")


def same_endpoint(a: str, b: str) -> bool:
    """Two trigger URLs for the same Logic App trigger, whatever their signature."""
    left, right = urlsplit(a), urlsplit(b)
    return (left.hostname, left.path.rstrip("/")) == (right.hostname, right.path.rstrip("/"))


def existing_hook(repo: str, url: str) -> dict | None:
    hooks = json.loads(run("gh", "api", f"repos/{repo}/hooks?per_page=100") or "[]")
    return next((h for h in hooks if same_endpoint((h.get("config") or {}).get("url", ""), url)), None)


def publish() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo or not values.get("AZURE_RESOURCE_GROUP"):
        raise SystemExit("error: GITHUB_REPOSITORY or AZURE_RESOURCE_GROUP is not set. Did `azd provision` succeed?")
    url = trigger_url(values)
    config = {"url": url, "content_type": "json", "insecure_ssl": "0"}
    hook = existing_hook(repo, url)
    if hook:
        run("gh", "api", "-X", "PATCH", f"repos/{repo}/hooks/{hook['id']}", "--input", "-",
            stdin=json.dumps({"active": True, "events": ["pull_request"], "config": config}))
        print(f"Webhook {hook['id']} in {repo}: pull_request events → Logic App posture-preview (updated).")
    else:
        created = json.loads(run("gh", "api", "-X", "POST", f"repos/{repo}/hooks", "--input", "-",
                                 stdin=json.dumps({"name": "web", "active": True, "events": ["pull_request"],
                                                   "config": config})))
        print(f"Webhook {created['id']} in {repo}: pull_request events → Logic App posture-preview (created).")


def remove() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo or not values.get("AZURE_RESOURCE_GROUP"):
        print("No GitHub repository or resource group in the azd environment: nothing to remove.")
        return
    try:
        url = trigger_url(values)
    except SystemExit:
        print("The Logic App posture-preview no longer exists; delete the webhook by hand if it remains "
              "(repository Settings > Webhooks).")
        return
    hook = existing_hook(repo, url)
    if hook:
        run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        print(f"Webhook {hook['id']} deleted from {repo}.")
    else:
        print("No posture-preview webhook found: nothing to remove.")


def main() -> int:
    commands = {"prepare": prepare, "publish": publish, "remove": remove}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__)
        return 2
    if os.environ.get("SKIP_GITHUB", "").lower() == "true":
        print("SKIP_GITHUB is true: GitHub not configured.")
        return 0
    if not shutil.which("gh"):
        raise SystemExit("error: the GitHub CLI (gh) is required. Install it, run `gh auth login`, or set SKIP_GITHUB=true.")
    commands[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
