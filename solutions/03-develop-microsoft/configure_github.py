"""Connect the Azure pull request reviewer to its GitHub repository. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      1. Finds the GitHub repository (`gh repo view`) and stores it in the azd environment as GITHUB_REPOSITORY: the
         repository whose pull requests the Function reviews.
      2. Generates the webhook secret once and stores it as GITHUB_WEBHOOK_SECRET. GitHub signs every delivery with it,
         and the Function refuses anything not signed with it. The secret goes to azd through a temporary file, never
         on a command line, and is never printed. Provisioning then writes it, and GITHUB_REVIEW_TOKEN, to the
         solution's Key Vault, where only the Function can read them.
      Warns when GITHUB_REVIEW_TOKEN is not set.

  python configure_github.py publish    (azd postdeploy hook)
      1. Creates or updates the review:azure label, which asks for a review.
      2. Checks that GitHub accepts GITHUB_REVIEW_TOKEN for the repository's code and pull requests, as the Function
         will use it, and prints when the token expires.
      3. Waits until the Function refuses an unsigned delivery (HTTP 401): its code is live, it has read the webhook
         secret from Key Vault, and it checks signatures.
      4. Creates or updates one repository webhook that sends pull_request events, signed with GITHUB_WEBHOOK_SECRET, to
         the Function's /api/github/webhook. Only while the token is set: without it, every review would stop at its
         first GitHub call, so without the token it deletes that webhook if there is one.
      The secret is passed to the GitHub CLI on standard input, never on a command line, and never printed. GitHub never
      returns a webhook's secret, so an existing webhook is updated every time, which also keeps its secret current. An
      existing webhook is recognized by the URL's host and path, so webhooks of other solutions are never touched.

  python configure_github.py remove     (azd predown hook)
      Deletes that webhook. The label stays, because past pull requests carry it.

Uses the GitHub CLI of the person running azd, who needs admin rights on the repository (webhooks need them). To target
another repository, run `azd env set GITHUB_REPOSITORY owner/name` first. To skip GitHub, run
`azd env set SKIP_GITHUB true`.

Exit codes: 0 done or nothing to do; 2 a command failed, or GitHub refused the token.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROUTE = "/api/github/webhook"
LABEL_COLOR = "0078D4"
LABEL_DESCRIPTION = "Ask the Azure pull request reviewer to review this pull request"
URL = re.compile(r"https?://\S+")


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        # Never echo the command's input or a URL: a webhook's configuration carries its secret.
        command = URL.sub("<url>", " ".join(args[:3]))
        detail = URL.sub("<url>", (proc.stderr or proc.stdout).strip())[:400]
        raise SystemExit(f"error: {command} failed: {detail}")
    return proc.stdout.strip()


def azd_values() -> dict[str, str]:
    return json.loads(run("azd", "env", "get-values", "--output", "json"))


def store_secret(name: str, value: str) -> None:
    """azd env set, through a file only this user can read, so the value never appears in a process list."""
    handle, path = tempfile.mkstemp(prefix="azd-env-", suffix=".env")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")
        run("azd", "env", "set", "--file", path)
    finally:
        Path(path).unlink(missing_ok=True)


def prepare() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY") or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
    print(f"GitHub repository: {repo}")
    if values.get("GITHUB_WEBHOOK_SECRET"):
        print("Webhook secret: already set.")
    else:
        store_secret("GITHUB_WEBHOOK_SECRET", secrets.token_hex(32))
        print("Webhook secret: generated and stored in the azd environment.")
    if not values.get("GITHUB_REVIEW_TOKEN"):
        print("warning: GITHUB_REVIEW_TOKEN is not set. Azure deploys, but no pull request is reviewed until you create the "
              "fine-grained token (see the README, Set up), store it with `azd env set GITHUB_REVIEW_TOKEN ...`, and run "
              "`azd up` again.")


def webhook_url(values: dict[str, str]) -> str:
    host = values.get("REVIEWER_FUNCTION_HOST")
    if not host:
        raise SystemExit("error: REVIEWER_FUNCTION_HOST is not set. Did `azd provision` succeed?")
    return f"https://{host}{ROUTE}"


def same_endpoint(a: str, b: str) -> bool:
    """Two webhook URLs for the same Function route, whatever their port notation or query."""
    left, right = urlsplit(a), urlsplit(b)
    return bool(left.hostname) and (left.hostname, left.path.rstrip("/")) == (right.hostname, right.path.rstrip("/"))


def our_hooks(repo: str, url: str) -> list[dict]:
    hooks = json.loads(run("gh", "api", f"repos/{repo}/hooks?per_page=100") or "[]")
    return [h for h in hooks if same_endpoint((h.get("config") or {}).get("url", ""), url)]


def check_token(repo: str, token: str) -> str:
    """Reads the repository's commits and pull requests with the token, as the Function does. Returns when the token
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
                             "Then run `azd env set GITHUB_REVIEW_TOKEN ...` and `azd up` again.")
        except OSError as exc:
            raise SystemExit(f"error: couldn't reach GitHub to check GITHUB_REVIEW_TOKEN ({type(exc).__name__}).")
    return expires


def check_function(url: str, attempts: int = 24, delay: float = 5) -> None:
    """The Function refuses an unsigned delivery with 401 once its code is live and it has read the webhook secret from
    Key Vault (until then it answers 404 or 503). Waits up to two minutes after a deployment, so GitHub's first ping
    doesn't arrive before the Function is ready. Stops if an unsigned delivery is accepted."""
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=b"{}", method="POST", headers={
            "Content-Type": "application/json", "X-GitHub-Event": "ping", "User-Agent": "azure-pr-reviewer-setup"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raise SystemExit(f"error: the reviewer's Function accepted an unsigned delivery (HTTP {response.status}). "
                                 "Check GITHUB_WEBHOOK_SECRET and the deployed code before connecting GitHub.")
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 401:
                print("The reviewer's Function refuses unsigned deliveries, as it should.")
                return
        except OSError:
            pass
        if attempt < attempts - 1:
            time.sleep(delay)
    print("warning: the reviewer's Function isn't ready yet: it doesn't refuse an unsigned delivery. Right after the "
          "first `azd up`, its access to Key Vault can take a few minutes, and GitHub's first ping may fail until then. "
          "Run `azd hooks run postdeploy` again in a few minutes.")


def publish() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("error: GITHUB_REPOSITORY is not set. Did `azd provision` succeed?")
    label = values.get("REVIEW_LABEL") or "review:azure"
    run("gh", "label", "create", label, "--repo", repo, "--color", LABEL_COLOR, "--description", LABEL_DESCRIPTION, "--force")
    print(f"Label {label} in {repo}: ready.")
    url = webhook_url(values)
    hooks = our_hooks(repo, url)
    token = os.environ.get("GITHUB_REVIEW_TOKEN") or values.get("GITHUB_REVIEW_TOKEN")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET") or values.get("GITHUB_WEBHOOK_SECRET")
    if not token or not secret:
        for hook in hooks:
            run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        missing = "GITHUB_REVIEW_TOKEN" if not token else "GITHUB_WEBHOOK_SECRET"
        print(f"Webhook: {'deleted' if hooks else 'not created'}, because {missing} is not set. Store it (README, Set up) "
              "and run `azd up` again; until then no pull request is reviewed.")
        return
    expires = check_token(repo, token)
    print(f"GITHUB_REVIEW_TOKEN: GitHub accepts it for {repo}" + (f"; it expires {expires}." if expires else "."))
    check_function(url)
    settings = {"active": True, "events": ["pull_request"],
                "config": {"url": url, "content_type": "json", "insecure_ssl": "0", "secret": secret}}
    if hooks:
        keep = hooks[0]
        run("gh", "api", "-X", "PATCH", f"repos/{repo}/hooks/{keep['id']}", "--input", "-", stdin=json.dumps(settings))
        for extra in hooks[1:]:  # duplicates of the same webhook would review every pull request twice
            run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{extra['id']}")
        hook_id, state = keep["id"], "updated"
    else:
        created = json.loads(run("gh", "api", "-X", "POST", f"repos/{repo}/hooks", "--input", "-",
                                 stdin=json.dumps(dict(settings, name="web"))))
        hook_id, state = created["id"], "created"
    print(f"Webhook {hook_id} in {repo}: signed pull_request events → the reviewer's Function ({state}).")


def remove() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo or not values.get("REVIEWER_FUNCTION_HOST"):
        print("No GitHub repository or Function in the azd environment: nothing to remove.")
        return
    hooks = our_hooks(repo, webhook_url(values))
    for hook in hooks:
        run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        print(f"Webhook {hook['id']} deleted from {repo}.")
    if not hooks:
        print(f"No webhook to the reviewer's Function found in {repo}: nothing to remove.")
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
