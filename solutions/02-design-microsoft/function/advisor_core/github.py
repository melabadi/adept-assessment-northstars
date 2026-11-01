"""GitHub access for the advisor: a GitHub App installation token, and a client that can only write ADR drafts.

How the Function authenticates:
  - GitHub App (default): a 10-minute JWT signed with the app's private key buys a 1-hour installation token, scoped
    to this repository only and to the permissions the advisor uses (contents, issues, pull requests: write).
  - Fine-grained personal access token (fallback): used as is, when the Key Vault holds github-token instead.

What the client may write, whatever its token allows (Contents: write would otherwise let a bug push to main):
  - a branch whose ref matches refs/heads/design/advisor-* (created from the default branch's head),
  - a file under solutions/02-design-microsoft/adr/ on such a branch,
  - a pull request whose head is such a branch,
  - a comment on an issue.
Every other write raises GuardError before any request is sent. Tokens and keys never appear in logs, return values,
or error messages.

What the client reads to decide: a branch named design/advisor-issue-N in this repository, and an open pull request
from it. Only people with write access, and the app, can push a branch here, so both come from someone the repository
trusts. A pull request from a fork never counts, even when its branch has the same name.
"""
from __future__ import annotations

import base64
import calendar
import re
import threading
import time

import requests

API = "https://api.github.com"
BRANCH_PREFIX = "design/advisor-"
ADR_DIR = "solutions/02-design-microsoft/adr/"
WRITABLE_REF = re.compile(r"refs/heads/design/advisor-[A-Za-z0-9._-]+")
PERMISSIONS = {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"}


class GuardError(PermissionError):
    """A write the advisor is never allowed to make."""


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub returned HTTP {status}: {message}")
        self.status = status


def branch_for(issue) -> str:
    return f"{BRANCH_PREFIX}issue-{int(issue)}"


def adr_path_for(issue) -> str:
    return f"{ADR_DIR}issue-{int(issue)}.md"


def assert_writable_ref(ref: str) -> None:
    if not WRITABLE_REF.fullmatch(ref or "") or ".." in ref:
        raise GuardError(f"refusing to write to {ref!r}: only refs/heads/{BRANCH_PREFIX}* is writable")


def assert_writable_path(path: str) -> None:
    if not (path or "").startswith(ADR_DIR) or ".." in path or not path.endswith(".md"):
        raise GuardError(f"refusing to write {path!r}: only Markdown files under {ADR_DIR} are writable")


def same_repository(pull: dict, repository: str) -> bool:
    """Whether a pull request's branch is in this repository (only people with write access, and the app, push there)."""
    head = (((pull or {}).get("head") or {}).get("repo") or {}).get("full_name") or ""
    return bool(head) and head.lower() == repository.lower()


def app_jwt(app_id: str, private_key: str) -> str:
    """The GitHub App's own JWT (RS256, valid for 9 minutes, issued a minute early for clock drift)."""
    import jwt

    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, private_key, algorithm="RS256")


def installation_token(repo: str, app_id: str, private_key: str, session=None) -> tuple[str, float]:
    """A 1-hour installation token for this repository only, with only the advisor's permissions.
    Returns (token, expiry as epoch seconds)."""
    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {app_jwt(app_id, private_key)}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    found = http.get(f"{API}/repos/{repo}/installation", headers=headers, timeout=30)
    if found.status_code == 404:
        raise GitHubError(404, f"the GitHub App is not installed on {repo}; install it on this repository only")
    if found.status_code >= 300:
        raise GitHubError(found.status_code, "could not find the app's installation")
    issued = http.post(f"{API}/app/installations/{found.json()['id']}/access_tokens", headers=headers, timeout=30,
                       json={"repositories": [repo.split("/", 1)[1]], "permissions": PERMISSIONS})
    if issued.status_code >= 300:
        raise GitHubError(issued.status_code, "could not create an installation token")
    data = issued.json()
    return data["token"], calendar.timegm(time.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))


class TokenCache:
    """Keeps one token until five minutes before it expires. fetch() returns (token, expiry epoch seconds)."""

    def __init__(self, fetch):
        self._fetch, self._token, self._expires = fetch, None, 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token is None or self._expires - time.time() < 300:
                self._token, self._expires = self._fetch()
            return self._token


class GitHub:
    """Repository client with the advisor's write guard. token: a callable that returns a current token."""

    def __init__(self, repo: str, token, session=None):
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or ""):
            raise ValueError("GITHUB_REPOSITORY must be owner/name")
        self.repo, self._token = repo, token
        self._http = session or requests.Session()
        self._default_branch = None

    # ---------- transport ----------
    def _request(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        response = self._http.request(method, f"{API}/repos/{self.repo}{path}", headers=headers, timeout=30, **kwargs)
        if response.status_code >= 300 and response.status_code != 404:
            try:
                message = response.json().get("message", "")
            except ValueError:
                message = ""
            raise GitHubError(response.status_code, f"{method} {path}: {message}"[:300])
        return response

    def _write(self, method: str, path: str, body: dict):
        """Every write goes through here, and only the advisor's four writes pass."""
        if method == "POST" and path == "/git/refs":
            assert_writable_ref(body.get("ref", ""))
        elif method == "PUT" and path.startswith("/contents/"):
            assert_writable_path(path[len("/contents/"):])
            assert_writable_ref(f"refs/heads/{body.get('branch', '')}")
        elif method == "POST" and path == "/pulls":
            assert_writable_ref(f"refs/heads/{body.get('head', '')}")
        elif method == "POST" and re.fullmatch(r"/issues/\d+/comments", path):
            pass
        else:
            raise GuardError(f"refusing {method} {path}: not one of the advisor's writes")
        response = self._request(method, path, json=body)
        if response.status_code == 404:
            raise GitHubError(404, f"{method} {path}: not found")
        return response.json()

    def _get(self, path: str, **params):
        response = self._request("GET", path, params=params or None)
        return None if response.status_code == 404 else response.json()

    # ---------- reads ----------
    def default_branch(self) -> str:
        if self._default_branch is None:
            self._default_branch = self._get("")["default_branch"]
        return self._default_branch

    def read_text(self, path: str, ref: str) -> str | None:
        data = self._get(f"/contents/{path}", ref=ref)
        if not data or isinstance(data, list):
            return None
        return base64.b64decode(data["content"]).decode("utf-8")

    def read_folder(self, folder: str, ref: str) -> dict[str, str]:
        """{file name: text} of the files directly in a folder at a commit."""
        listing = self._get(f"/contents/{folder}", ref=ref) or []
        return {entry["name"]: self.read_text(entry["path"], ref) for entry in listing if entry.get("type") == "file"}

    def on_default_branch(self, sha: str) -> bool:
        """True when the commit is the default branch's head or one of its ancestors: merged, not a proposal."""
        compared = self._get(f"/compare/{self.default_branch()}...{sha}")
        return bool(compared) and compared.get("status") in ("identical", "behind")

    # ---------- the advisor's writes ----------
    def ensure_branch(self, issue) -> dict:
        branch = branch_for(issue)
        assert_writable_ref(f"refs/heads/{branch}")
        existing = self._get(f"/git/ref/heads/{branch}")
        if existing:
            return {"branch": branch, "sha": existing["object"]["sha"], "created": False}
        base = self._get(f"/git/ref/heads/{self.default_branch()}")
        created = self._write("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base["object"]["sha"]})
        return {"branch": branch, "sha": created["object"]["sha"], "created": True}

    def put_adr(self, issue, content: str, message: str) -> dict:
        branch, path = branch_for(issue), adr_path_for(issue)
        current = self._get(f"/contents/{path}", ref=branch)
        body = {"message": message, "branch": branch, "content": base64.b64encode(content.encode("utf-8")).decode()}
        if current and not isinstance(current, list):
            body["sha"] = current["sha"]
        result = self._write("PUT", f"/contents/{path}", body)
        return {"path": path, "branch": branch, "commit": result["commit"]["sha"], "created": not current}

    def open_pull_request(self, issue, title: str, body: str) -> dict:
        branch = branch_for(issue)
        owner = self.repo.split("/", 1)[0]
        for existing in self._get("/pulls", head=f"{owner}:{branch}", state="open") or []:
            if same_repository(existing, self.repo):
                return {"number": existing["number"], "url": existing["html_url"], "created": False}
        created = self._write("POST", "/pulls", {"title": title, "head": branch, "base": self.default_branch(), "body": body})
        return {"number": created["number"], "url": created["html_url"], "created": True}

    def comment(self, issue, body: str) -> dict:
        created = self._write("POST", f"/issues/{int(issue)}/comments", {"body": body})
        return {"id": created["id"], "url": created["html_url"]}
