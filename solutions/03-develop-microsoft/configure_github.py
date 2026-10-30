"""Connect the Azure pull request reviewer to its GitHub repository. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and stores it in the azd environment as GITHUB_REPOSITORY: the
      repository whose pull requests the Logic App reviews. Warns when GITHUB_REVIEW_TOKEN is not set.

  python configure_github.py publish    (azd postprovision hook)
      1. Creates or updates the review:azure label, which asks for a review.
      2. Checks that GitHub accepts GITHUB_REVIEW_TOKEN for the repository's code and pull requests, as the Logic App will
         use it, and prints when the token expires.
      3. Creates or updates one repository webhook that sends pull_request events to the Logic App logic-pr-reviewer.
         Only while the token is set: without it, every review would stop at its first GitHub call, so without the token
         it deletes that webhook if there is one.
      The webhook's URL is the Logic App's trigger URL, which carries a signature: it is read from Azure each time, passed
      to the GitHub CLI on standard input, and never printed or saved. An existing webhook is recognized by the URL's host
      and path, so webhooks of other solutions are never touched.

  python configure_github.py remove     (azd predown hook)
      Deletes that webhook. The label stays, because past pull requests carry it.

Uses the GitHub CLI of the person running azd, who needs admin rights on the repository (webhooks need them), and the
Azure CLI. To target another repository, run `azd env set GITHUB_REPOSITORY owner/name` first. To skip GitHub, run
`azd env set SKIP_GITHUB true`.

Exit codes: 0 done or nothing to do; 2 a command failed, or GitHub refused the token.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TRIGGER = "When_a_pull_request_event_arrives"
LABEL_COLOR = "0078D4"
LABEL_DESCRIPTION = "Ask the Azure pull request reviewer to review this pull request"
URL = re.compile(r"https?://\S+")


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        # Never echo the command line or a URL: for webhooks they can carry the trigger URL and its signature.
        command = URL.sub("<url>", " ".join(args[:3]))
        detail = URL.sub("<url>", (proc.stderr or proc.stdout).strip())[:400]
        raise SystemExit(f"error: {command} failed: {detail}")
    return proc.stdout.strip()


def azd_values() -> dict[str, str]:
    return json.loads(run("azd", "env", "get-values", "--output", "json"))


def prepare() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY") or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
    print(f"GitHub repository: {repo}")
    if not values.get("GITHUB_REVIEW_TOKEN"):
        print("warning: GITHUB_REVIEW_TOKEN is not set. Azure deploys, but no pull request is reviewed until you create the "
              "fine-grained token (see the README, Set up), store it with `azd env set GITHUB_REVIEW_TOKEN ...`, and run "
              "`azd provision` again.")


def trigger_url(values: dict[str, str]) -> str:
    az = shutil.which("az") or "az"
    workflow = values.get("REVIEWER_LOGIC_APP") or "logic-pr-reviewer"
    subscription = values.get("AZURE_SUBSCRIPTION_ID") or run(az, "account", "show", "--query", "id", "-o", "tsv")
    url = (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{values['AZURE_RESOURCE_GROUP']}"
           f"/providers/Microsoft.Logic/workflows/{workflow}/triggers/{TRIGGER}/listCallbackUrl?api-version=2019-05-01")
    return run(az, "rest", "--method", "post", "--url", url, "--query", "value", "-o", "tsv")


def same_endpoint(a: str, b: str) -> bool:
    """Two trigger URLs for the same Logic App trigger, whatever their signature or port notation."""
    left, right = urlsplit(a), urlsplit(b)
    return bool(left.hostname) and (left.hostname, left.path.rstrip("/")) == (right.hostname, right.path.rstrip("/"))


def our_hooks(repo: str, url: str) -> list[dict]:
    hooks = json.loads(run("gh", "api", f"repos/{repo}/hooks?per_page=100") or "[]")
    return [h for h in hooks if same_endpoint((h.get("config") or {}).get("url", ""), url)]


def check_token(repo: str, token: str) -> str:
    """Reads the repository's commits and pull requests with the token, as the Logic App does. Returns when the token
    expires ("" when GitHub doesn't say). The token is sent to GitHub only, and never printed."""
    expires = ""
    for path, needs in (("commits?per_page=1", "Contents: Read-only"),
                        ("pulls?state=all&per_page=1", "Pull requests: Read and write")):
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "azure-pr-reviewer-setup"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                expires = response.headers.get("github-authentication-token-expiration") or expires
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"error: GitHub refused GITHUB_REVIEW_TOKEN for {repo} (HTTP {exc.code}). Check that the token "
                             f"hasn't expired, that its repository access includes {repo}, and that it has {needs}. "
                             "Then run `azd env set GITHUB_REVIEW_TOKEN ...` and `azd provision` again.")
        except OSError as exc:
            raise SystemExit(f"error: couldn't reach GitHub to check GITHUB_REVIEW_TOKEN ({type(exc).__name__}).")
    return expires


def publish() -> None:
    values = azd_values()
    repo, group = values.get("GITHUB_REPOSITORY"), values.get("AZURE_RESOURCE_GROUP")
    if not repo or not group:
        raise SystemExit("error: GITHUB_REPOSITORY or AZURE_RESOURCE_GROUP is not set. Did `azd provision` succeed?")
    workflow = values.get("REVIEWER_LOGIC_APP") or "logic-pr-reviewer"
    label = values.get("REVIEW_LABEL") or "review:azure"
    run("gh", "label", "create", label, "--repo", repo, "--color", LABEL_COLOR, "--description", LABEL_DESCRIPTION, "--force")
    print(f"Label {label} in {repo}: ready.")
    url = trigger_url(values)
    hooks = our_hooks(repo, url)
    token = os.environ.get("GITHUB_REVIEW_TOKEN") or values.get("GITHUB_REVIEW_TOKEN")
    if not token:
        for hook in hooks:
            run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        print(f"Webhook: {'deleted' if hooks else 'not created'}, because GITHUB_REVIEW_TOKEN is not set. Store the token "
              "(README, Set up) and run `azd provision` again; until then no pull request is reviewed.")
        return
    expires = check_token(repo, token)
    print(f"GITHUB_REVIEW_TOKEN: GitHub accepts it for {repo}" + (f"; it expires {expires}." if expires else "."))
    config = {"url": url, "content_type": "json", "insecure_ssl": "0"}
    if hooks:
        keep = hooks[0]
        current = keep.get("config") or {}
        if (keep.get("active") and keep.get("events") == ["pull_request"] and current.get("url") == url
                and current.get("content_type") == "json"):
            state = "unchanged"
        else:
            run("gh", "api", "-X", "PATCH", f"repos/{repo}/hooks/{keep['id']}", "--input", "-",
                stdin=json.dumps({"active": True, "events": ["pull_request"], "config": config}))
            state = "updated"
        for extra in hooks[1:]:  # duplicates of the same webhook would review every pull request twice
            run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{extra['id']}")
        hook_id = keep["id"]
    else:
        created = json.loads(run("gh", "api", "-X", "POST", f"repos/{repo}/hooks", "--input", "-",
                                 stdin=json.dumps({"name": "web", "active": True, "events": ["pull_request"],
                                                   "config": config})))
        hook_id, state = created["id"], "created"
    print(f"Webhook {hook_id} in {repo}: pull_request events → Logic App {workflow} ({state}).")


def remove() -> None:
    values = azd_values()
    repo, group = values.get("GITHUB_REPOSITORY"), values.get("AZURE_RESOURCE_GROUP")
    workflow = values.get("REVIEWER_LOGIC_APP") or "logic-pr-reviewer"
    if not repo or not group:
        print("No GitHub repository or resource group in the azd environment: nothing to remove.")
        return
    try:
        url = trigger_url(values)
    except SystemExit:
        print(f"The Logic App {workflow} no longer exists; if its webhook remains, delete it in the repository's "
              "Settings > Webhooks.")
        return
    hooks = our_hooks(repo, url)
    for hook in hooks:
        run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        print(f"Webhook {hook['id']} deleted from {repo}.")
    if not hooks:
        print(f"No webhook to Logic App {workflow} found in {repo}: nothing to remove.")
    print("The review:azure label stays on past pull requests; `gh label delete review:azure` removes it. Delete the "
          "fine-grained token on GitHub if nothing else uses it.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    commands = {"prepare": prepare, "publish": publish, "remove": remove}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 1 or argv[0] not in commands:
        print(__doc__)
        return 2
    if os.environ.get("SKIP_GITHUB", "").lower() == "true":
        print("SKIP_GITHUB is true: GitHub not configured.")
        return 0
    if not shutil.which("gh"):
        raise SystemExit("error: the GitHub CLI (gh) is required. Install it, run `gh auth login`, or set SKIP_GITHUB=true.")
    commands[argv[0]]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
