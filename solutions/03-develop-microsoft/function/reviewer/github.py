"""GitHub's REST API, called with the reviewer's fine-grained token (Contents read, Pull requests read and write).

The token is sent only to api.github.com, in the Authorization header. It is never logged, never put in an error
message, and never sent anywhere else: GitHub answers an archive request with a redirect to a short-lived download link
on codeload.github.com, and that second request carries no token. The link itself carries a token, so it isn't logged
either. Errors name the call and the HTTP status, never a URL.

Reviews are always COMMENT reviews: nothing here can approve a pull request or request changes.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
USER_AGENT = "azure-pr-reviewer"
ARCHIVE_HOSTS = ("codeload.github.com",)
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024


class GitHubError(RuntimeError):
    """A GitHub call failed. The message names the call and the HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report redirects instead of following them, so the token never follows a redirect to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_open(request: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


class GitHub:
    """The calls the reviewer makes, for one repository."""

    def __init__(self, repository: str, token: str, open_url=_default_open, sleep=time.sleep):
        if not token:
            raise GitHubError("GITHUB_REVIEW_TOKEN is not set")
        self.repository = repository
        self._token = token
        self._open = open_url
        self._sleep = sleep

    def __repr__(self) -> str:  # never the token
        return f"GitHub({self.repository!r})"

    # ------------------------------------------------------------------ plumbing
    def _call(self, what: str, method: str, path: str, body: object = None, accept: str = "application/vnd.github+json",
              retries: int = 2, timeout: float = 60) -> tuple[int, dict, bytes]:
        url = f"{API}/repos/{self.repository}/{path}"
        headers = {"Accept": accept, "Authorization": f"Bearer {self._token}", "User-Agent": USER_AGENT,
                   "X-GitHub-Api-Version": "2022-11-28"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        for attempt in range(retries + 1):
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._open(request, timeout) as response:
                    return response.status, dict(response.headers), response.read()
            except urllib.error.HTTPError as exc:
                exc.close()
                if 300 <= exc.code < 400:
                    return exc.code, dict(exc.headers or {}), b""
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                    self._sleep(2 * (attempt + 1))
                    continue
                raise GitHubError(f"{what}: GitHub answered HTTP {exc.code}", exc.code) from None
            except (urllib.error.URLError, OSError) as exc:
                if attempt < retries:
                    self._sleep(2 * (attempt + 1))
                    continue
                raise GitHubError(f"{what}: {type(exc).__name__}") from None
        raise GitHubError(f"{what}: no answer")  # pragma: no cover

    def _json(self, what: str, path: str) -> dict:
        _, _, data = self._call(what, "GET", path)
        try:
            value = json.loads(data)
        except ValueError:
            raise GitHubError(f"{what}: GitHub's answer isn't JSON") from None
        if not isinstance(value, dict):
            raise GitHubError(f"{what}: unexpected answer")
        return value

    # ------------------------------------------------------------------ reads
    def pull(self, number: int) -> dict:
        """The pull request as GitHub sees it now: head and base commits, branch repository, state, draft, labels."""
        return self._json(f"read pull request #{number}", f"pulls/{int(number)}")

    def merge_base(self, base_sha: str, head_sha: str) -> str:
        """The commit the pull request branched from: the rule checker compares the head with it."""
        compare = self._json("find the merge base", f"compare/{_ref(base_sha)}...{_ref(head_sha)}?per_page=1")
        sha = (compare.get("merge_base_commit") or {}).get("sha")
        if not isinstance(sha, str) or len(sha) != 40:
            raise GitHubError("find the merge base: GitHub returned no merge base")
        return sha

    def file(self, path: str, ref: str) -> bytes:
        """One file's raw content at a ref (the scripts come from main, never from the pull request)."""
        quoted = urllib.parse.quote(path.strip("/"))
        _, _, data = self._call(f"read {path.rsplit('/', 1)[-1]} at {ref}", "GET",
                                f"contents/{quoted}?ref={urllib.parse.quote(ref, safe='')}", accept="application/vnd.github.raw")
        return data

    def archive(self, sha: str) -> bytes:
        """The repository at a commit, as a .tar.gz. GitHub redirects to a short-lived link, which is followed without
        the token, and only to GitHub's archive host."""
        what = f"download the code at {sha[:7]}"
        status, headers, data = self._call(what, "GET", f"tarball/{_ref(sha)}")
        if status == 200:
            return data
        location = next((v for k, v in headers.items() if k.lower() == "location"), "")
        parts = urllib.parse.urlsplit(location)
        if not (300 <= status < 400) or parts.scheme != "https" or parts.hostname not in ARCHIVE_HOSTS:
            raise GitHubError(f"{what}: GitHub didn't redirect to its archive host (HTTP {status})", status)
        request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT})  # no Authorization header
        for attempt in range(3):
            try:
                with self._open(request, 300) as response:
                    data = response.read(MAX_ARCHIVE_BYTES + 1)
                break
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    self._sleep(2 * (attempt + 1))
                    continue
                raise GitHubError(f"{what}: the archive host answered HTTP {exc.code}", exc.code) from None
            except (urllib.error.URLError, OSError) as exc:
                if attempt < 2:
                    self._sleep(2 * (attempt + 1))
                    continue
                raise GitHubError(f"{what}: {type(exc).__name__}") from None
        if len(data) > MAX_ARCHIVE_BYTES:
            raise GitHubError(f"{what}: the archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
        return data

    # ------------------------------------------------------------------ the only write
    def comment_review(self, number: int, body: str, commit_id: str | None = None) -> str:
        """Posts one COMMENT review: it never approves and never requests changes. Not retried, so a review is never
        posted twice. Returns the review's link."""
        payload = {"event": "COMMENT", "body": body}
        if commit_id:
            payload["commit_id"] = commit_id
        _, _, data = self._call(f"post the review on #{number}", "POST", f"pulls/{int(number)}/reviews", body=payload,
                                retries=0)
        try:
            return str(json.loads(data).get("html_url") or "")
        except ValueError:
            return ""


def _ref(value: str) -> str:
    """A commit sha or ref in a URL path."""
    return urllib.parse.quote(str(value), safe="")
