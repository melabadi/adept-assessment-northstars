"""Connect this solution's Azure automation to its GitHub repository. azd runs it as hooks; you rarely call it yourself.

  python configure_github.py prepare    (azd preprovision hook)
      Finds the GitHub repository (`gh repo view`) and stores it in the azd environment as GITHUB_REPOSITORY, so the
      Function app and the what-if job know where to file Issues and pull requests. Generates POSTURE_WEBHOOK_SECRET once,
      the secret GitHub signs the webhook's deliveries with (Key Vault gets it at provision). Warns when
      POSTURE_GITHUB_TOKEN is not set.

  python configure_github.py publish    (azd postprovision hook)
      Creates or updates one repository webhook that sends pull_request events, signed with that secret, to the Function's
      preview route, so a push to a pull request that changes this solution's infra/ gets a new Azure what-if preview.
      The secret goes to `gh` on standard input; the URL and the secret are never printed.

  python configure_github.py remove     (azd predown hook)
      Deletes that webhook.

Uses the GitHub CLI of the person running azd, who needs admin rights on the repository (webhooks need them). To target
another repository, run `azd env set GITHUB_REPOSITORY owner/name` first. To skip GitHub, run
`azd env set SKIP_GITHUB true`.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROUTE = "/api/preview"


def run(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        # Never echo the command line or the input: they can contain the webhook secret.
        raise SystemExit(f"error: {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout.strip()


def azd_values() -> dict[str, str]:
    return json.loads(run("azd", "env", "get-values", "--output", "json"))


def prepare() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY") or run("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    run("azd", "env", "set", "GITHUB_REPOSITORY", repo)
    print(f"GitHub repository: {repo}")
    if not values.get("POSTURE_WEBHOOK_SECRET"):
        run("azd", "env", "set", "POSTURE_WEBHOOK_SECRET", secrets.token_hex(32))
        print("Generated the webhook secret (POSTURE_WEBHOOK_SECRET in the azd environment).")
    if not values.get("POSTURE_GITHUB_TOKEN"):
        print("warning: POSTURE_GITHUB_TOKEN is not set. The Function and the what-if job cannot reach GitHub until you "
              "create the fine-grained token (see the README, Set up) and run `azd provision` again.")


def webhook_url(values: dict[str, str]) -> str:
    host = values.get("POSTURE_FUNCTION_HOST")
    if not host:
        raise SystemExit("error: POSTURE_FUNCTION_HOST is not set. Did `azd provision` succeed?")
    return f"https://{host}{ROUTE}"


def same_endpoint(a: str, b: str) -> bool:
    left, right = urlsplit(a), urlsplit(b)
    return (left.hostname, left.path.rstrip("/")) == (right.hostname, right.path.rstrip("/"))


def existing_hook(repo: str, url: str) -> dict | None:
    hooks = json.loads(run("gh", "api", f"repos/{repo}/hooks?per_page=100") or "[]")
    return next((h for h in hooks if same_endpoint((h.get("config") or {}).get("url", ""), url)), None)


def publish() -> None:
    values = azd_values()
    repo, secret = values.get("GITHUB_REPOSITORY"), values.get("POSTURE_WEBHOOK_SECRET")
    if not repo or not secret:
        raise SystemExit("error: GITHUB_REPOSITORY or POSTURE_WEBHOOK_SECRET is not set. Run `azd provision` again.")
    url = webhook_url(values)
    config = {"url": url, "content_type": "json", "insecure_ssl": "0", "secret": secret}
    hook = existing_hook(repo, url)
    if hook:
        run("gh", "api", "-X", "PATCH", f"repos/{repo}/hooks/{hook['id']}", "--input", "-",
            stdin=json.dumps({"active": True, "events": ["pull_request"], "config": config}))
        print(f"Webhook {hook['id']} in {repo}: pull_request events → the Function's preview route (updated).")
    else:
        created = json.loads(run("gh", "api", "-X", "POST", f"repos/{repo}/hooks", "--input", "-",
                                 stdin=json.dumps({"name": "web", "active": True, "events": ["pull_request"],
                                                   "config": config})))
        print(f"Webhook {created['id']} in {repo}: pull_request events → the Function's preview route (created).")


def remove() -> None:
    values = azd_values()
    repo = values.get("GITHUB_REPOSITORY")
    if not repo or not values.get("POSTURE_FUNCTION_HOST"):
        print("No GitHub repository or Function in the azd environment: nothing to remove.")
        return
    hook = existing_hook(repo, webhook_url(values))
    if hook:
        run("gh", "api", "-X", "DELETE", f"repos/{repo}/hooks/{hook['id']}")
        print(f"Webhook {hook['id']} deleted from {repo}.")
    else:
        print("No webhook for the Function's preview route: nothing to remove.")


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
