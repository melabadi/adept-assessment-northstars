"""Connect GitHub with the app-manifest flow: GitHub creates the app and hands its credentials to the Function.

1. A person opens the setup page (the link azd prints, with the Function's key). It holds GitHub's "register a new
   GitHub App" form, prefilled with this manifest and a one-time state.
2. The person confirms on GitHub. GitHub creates a private app on their account and redirects to the completion
   page with a one-hour, single-use code.
3. The Function exchanges the code for the app's id, private key, and webhook secret, stores only those three in
   Key Vault (through its private endpoint), and shows the link to install the app on this repository only.

Nobody downloads a private key or pastes a secret, and the Function never logs what GitHub returns.
"""
from __future__ import annotations

import html
import json

from . import github

STYLE = ("body{font-family:Segoe UI,system-ui,sans-serif;max-width:46rem;margin:3rem auto;padding:0 1rem;line-height:1.5;"
         "color:#1f2328}button{font-size:1rem;padding:.6rem 1.2rem;background:#1f883d;color:#fff;border:0;"
         "border-radius:6px;cursor:pointer}code{background:#f6f8fa;padding:.1rem .3rem;border-radius:4px}"
         "li{margin:.3rem 0}")


def manifest(repo: str, base_url: str, name: str) -> dict:
    """The app GitHub creates: private, only the advisor's permissions and events, webhooks to this Function."""
    return {
        "name": name,
        "url": f"https://github.com/{repo}",
        "description": "Design phase architecture advisor (Microsoft Foundry): answers design-advisor issues and opens "
                       "ADR draft pull requests. Runs in Azure.",
        "hook_attributes": {"url": f"{base_url}/api/github/webhook", "active": True},
        "redirect_url": f"{base_url}/api/github/setup/complete",
        "public": False,
        "default_permissions": dict(github.PERMISSIONS),
        "default_events": ["issues", "push"],
    }


def _page(title: str, body: str, status: int = 200) -> tuple[int, str]:
    return status, (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
                    f"<style>{STYLE}</style></head><body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>")


def setup_page(repo: str, owner_is_org: bool, state: str, app_manifest: dict) -> tuple[int, str]:
    owner = repo.split("/", 1)[0]
    action = (f"https://github.com/organizations/{owner}/settings/apps/new" if owner_is_org
              else "https://github.com/settings/apps/new") + f"?state={state}"
    permissions = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in app_manifest["default_permissions"].items())
    body = (f"<p>This creates a <strong>private GitHub App</strong> on <code>{html.escape(owner)}</code> for the Design "
            f"phase architecture advisor, then you install it on <code>{html.escape(repo)}</code> only.</p><ul>"
            f"<li>Permissions: {html.escape(permissions)}</li>"
            f"<li>Events: {html.escape(', '.join(app_manifest['default_events']))}</li>"
            "<li>GitHub generates the private key and webhook secret and hands them to this Azure Function, which "
            "stores them in Key Vault. Nobody downloads or pastes a secret.</li></ul>"
            f"<form action=\"{html.escape(action)}\" method=\"post\">"
            f"<input type=\"hidden\" name=\"manifest\" value=\"{html.escape(json.dumps(app_manifest))}\">"
            "<button type=\"submit\">Create GitHub App</button></form>"
            "<p>GitHub shows the app's name, which you can change, then returns here. This link works once, for one hour.</p>")
    return _page("Connect the architecture advisor to GitHub", body)


def done_page(repo: str, slug: str) -> tuple[int, str]:
    install = f"https://github.com/apps/{slug}/installations/new"
    body = ("<p>The app is created, and its id, private key, and webhook secret are in Key Vault.</p>"
            f"<p><strong>Last step:</strong> <a href=\"{html.escape(install)}\">install the app</a>, choose "
            f"<em>Only select repositories</em>, and select <code>{html.escape(repo)}</code>.</p>")
    return _page("GitHub App created", body)


def connected_page() -> tuple[int, str]:
    return _page("Already connected", "<p>A GitHub connection is already stored in Key Vault, so this page does nothing. "
                 "To connect a different app, delete the github-* secrets first (see the README's reset section).</p>", 409)


def error_page(message: str, status: int = 400) -> tuple[int, str]:
    return _page("Could not connect GitHub", f"<p>{html.escape(message)}</p><p>Open the setup link again to start over.</p>",
                 status)
