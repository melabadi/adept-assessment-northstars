#!/usr/bin/env python3
"""Deploy one commit of RequestHub to the API as a revision named after it, then load-test it (Test phase, Microsoft track).

Use it when a commit already passed another check, for example a repair whose regression tests 04-test-github proves
failing before the fix and passing after it, and you want to know how that exact commit performs under load:

  python candidate.py deploy <sha>        build the commit's API image in Azure Container Registry, as
                                          requesthub-api:<sha> with BUILD_SHA=<sha> baked in; deploy it as API revision
                                          c<first 7 characters of the sha>; wait until that revision serves all traffic,
                                          deactivate the others, and check that /api/meta reports the commit
  python candidate.py run --issue <n>     start a load test run against the candidate that serves now. Its id, display
                                          name, and description name the commit and the revision, for example
                                          "Commit <sha> on API revision c1a2b3c4 for Issue #284", and the reporting
                                          function's report names them too. With --issue, the function also comments
                                          its report on that GitHub Issue.
  python candidate.py restore             put the API back on its normal image (the newest revision that runs no
                                          candidate build) as a new revision, and deactivate the candidate

The build comes from git, not from your working copy: `git archive` exports the commit's app/ folder under out/, and
Azure Container Registry builds it, so no local Docker is needed. `deploy` builds only a commit that is on a branch of
origin, this repository: GitHub also serves a fork's pull request commits through this repository, and a fork's code
never reaches Azure. It fetches origin's branches to check, into refs of its own that it deletes afterwards. An image
that is already in the registry is not built again. A revision can't be deleted, so a second deployment of the same
commit gets the suffix c<7 characters>t<MMDDhhmm>. Suffixes have no hyphens: Azure's system logs cut a revision name at
the first hyphen of its suffix.

Settings come from environment variables, else from this solution's azd environment (after `azd up`):
  AZURE_RESOURCE_GROUP, API_APP_NAME, API_URL, AZURE_CONTAINER_REGISTRY_NAME, AZURE_CONTAINER_REGISTRY_ENDPOINT,
  LOAD_TEST_NAME.
Needs git, and the Azure CLI with the `load` extension, signed in with rights to build in the registry, update the
container app, and run load tests (you, after `azd up`).

Exit codes: 0 done, 2 configuration or service error.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from azd_env import REPO, setting, utf8_stdout  # noqa: E402
from slowdown import DELAY, EXPIRY, AzError, app_args, az, short, wait_for  # noqa: E402

REPOSITORY = "requesthub-api"
SHA = re.compile(r"^[0-9a-f]{40}$")
OUT = HERE / "out"
TEMPLATE = HERE / "loadtest" / "requesthub-journey.yaml"
# Where the branch check fetches origin's branches. Only refs/heads/* lands here, never refs/pull/*/head.
CHECK_REFS = "refs/candidate-check/"


def commit(value: str) -> str:
    """A full commit SHA, lowercase; argparse reports anything else."""
    sha = str(value).strip().lower()
    if not SHA.fullmatch(sha):
        raise argparse.ArgumentTypeError("give the commit's full 40-character SHA, for example from "
                                         "`gh pr view <pr> --json headRefOid -q .headRefOid`")
    return sha


def issue_number(value: str) -> int:
    if not str(value).isdigit() or not 0 < int(value) < 10_000_000:
        raise argparse.ArgumentTypeError("give the Issue's number, for example 284")
    return int(value)


def suffix_for(sha: str, taken: set[str], now: datetime) -> str:
    """The new revision's suffix: c and the commit's first 7 characters, plus the time if an earlier deployment of the
    same commit already took that suffix."""
    suffix = f"c{sha[:7]}"
    return suffix if suffix not in taken else f"{suffix}t{now:%m%d%H%M}"


def candidate_sha(image: str | None) -> str:
    """The commit of a candidate image (<registry>/requesthub-api:<sha>), or '' for any other image."""
    repository, _, tag = str(image or "").split("/", 1)[-1].rpartition(":")
    return tag if repository == REPOSITORY and SHA.fullmatch(tag) else ""


def normal_revision(revisions: list[dict]) -> dict | None:
    """The newest revision that runs a normal build (not a candidate): the one `restore` goes back to."""
    normal = [r for r in revisions if r.get("image") and not candidate_sha(r["image"])]
    return max(normal, key=lambda r: str(r.get("created") or ""), default=None)


def run_id(sha: str, now: datetime) -> str:
    return f"candidate-{sha[:7]}-{now:%Y%m%d-%H%M%S}"


def run_description(sha: str, suffix: str, issue: int | None = None) -> str:
    """The run's description, in the form the reporting function reads (function/reporter/report.py)."""
    return f"Commit {sha} on API revision {suffix}" + (f" for Issue #{issue}" if issue else "")


class CandidateError(RuntimeError):
    pass


def git(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, input=stdin)


def branches_with(sha: str) -> list[str]:
    """The branches of origin, this repository, that contain the commit. Only people with write access push branches
    here, or the Copilot cloud agent when one of them assigns it. GitHub also serves a fork's pull request commits
    through this repository (refs/pull/<n>/head), so the check fetches only refs/heads/*, into refs of its own, and
    deletes those refs afterwards."""
    fetched = git("fetch", "--quiet", "--prune", "--no-tags", "origin", f"+refs/heads/*:{CHECK_REFS}*")
    try:
        if fetched.returncode != 0:
            raise CandidateError("couldn't fetch origin's branches to check that the commit is on one of them")
        found = git("for-each-ref", "--contains", sha, "--format=%(refname)", CHECK_REFS)
        if found.returncode != 0:  # the commit isn't in any fetched branch's history, so git doesn't know it
            return []
        return sorted(ref.removeprefix(CHECK_REFS) for ref in found.stdout.decode("utf-8", "replace").split())
    finally:
        refs = git("for-each-ref", "--format=delete %(refname)", CHECK_REFS)
        if refs.returncode == 0 and refs.stdout.strip():
            git("update-ref", "--stdin", stdin=refs.stdout)


def export(sha: str) -> Path:
    """The commit's app/ folder, exported from git under out/ (no working copy, no untracked or ignored files)."""
    archive = git("archive", "--format=tar", sha, "app")
    if archive.returncode != 0:
        raise CandidateError(f"couldn't export app/ from commit {sha[:12]}")
    folder = OUT / f"candidate-{sha[:12]}"
    shutil.rmtree(folder, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter="data")
    return folder / "app"


def build(sha: str) -> str:
    """The commit's API image in the registry, built there unless it already exists."""
    registry = setting("AZURE_CONTAINER_REGISTRY_NAME")
    image = f"{setting('AZURE_CONTAINER_REGISTRY_ENDPOINT')}/{REPOSITORY}:{sha}"
    try:
        az("acr", "repository", "show", "--name", registry, "--image", f"{REPOSITORY}:{sha}")
        print(f"Image {REPOSITORY}:{sha[:12]} is already in the registry: no build needed.")
        return image
    except AzError:
        pass
    source = export(sha)
    try:
        print(f"Building {REPOSITORY}:{sha[:12]} in Azure Container Registry, with BUILD_SHA={sha[:12]} baked in ...")
        started = time.monotonic()
        # --no-logs waits for the build without streaming its log, which can fail to print on Windows consoles.
        result = az("acr", "build", "--registry", registry, "--image", f"{REPOSITORY}:{sha}", "--build-arg",
                    f"BUILD_SHA={sha}", "--file", str(source / "Dockerfile"), "--no-logs", str(source))
        status = result.get("status") if isinstance(result, dict) else None
        if status and status != "Succeeded":
            raise CandidateError(f"the image build ended with status {status}; see `az acr task list-runs --top 1`")
        print(f"Built in {int(time.monotonic() - started)} s.")
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)
    return image


def served_build(expect: str | None = None, attempts: int = 12) -> str:
    """The build that /api/meta reports (it needs no sign-in). With `expect`, retries for up to two minutes until the
    API reports that build, so a revision that just took the traffic has time to answer every call."""
    url = setting("API_URL").rstrip("/") + "/api/meta"
    reported = ""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                reported = str(json.loads(response.read().decode("utf-8")).get("buildSha") or "")
        except (urllib.error.URLError, OSError, ValueError):
            reported = ""
        if (expect is None and reported) or reported == expect:
            return reported
        if attempt + 1 < attempts:
            time.sleep(10)
    return reported


def deploy(sha: str) -> int:
    branches = branches_with(sha)
    if not branches:
        raise CandidateError(f"commit {sha[:12]} is on no branch of origin, this repository, so it isn't built: a fork's "
                             "pull request never reaches Azure. Deploy a commit that someone with write access pushed "
                             "here, such as the head of a pull request from this repository.")
    image = build(sha)
    app = az("containerapp", "show", *app_args(), "--query", "properties.template.containers[0].env[].name") or []
    taken = {short(name) for name in az("containerapp", "revision", "list", *app_args(), "--all", "--query", "[].name") or []}
    suffix = suffix_for(sha, taken, datetime.now(timezone.utc))
    # The deployment template sets BUILD_SHA, which would hide the commit baked into the image: remove it, so /api/meta
    # reports what the image says. A rehearsal slowdown never carries over to a candidate either.
    remove = [name for name in ("BUILD_SHA", DELAY, EXPIRY) if name in app]
    print(f"Deploying commit {sha[:12]} as API revision {suffix} ...")
    args = ["containerapp", "update", *app_args(), "--container-name", "api", "--image", image, "--revision-suffix", suffix]
    revision = az(*args, *(["--remove-env-vars", *remove] if remove else []), "--query", "properties.latestRevisionName")
    wait_for(revision)
    reported = served_build(expect=sha)
    if reported != sha:
        raise CandidateError(f"/api/meta reports build {reported[:12] or 'nothing'}, not {sha[:12]}")
    print(f"API revision {short(revision)} serves all traffic, and /api/meta reports build {sha[:12]}, the commit "
          "baked into its image.")
    print("Next: python candidate.py run --issue <the GitHub Issue the commit fixes>")
    return 0


def run(issue: int | None) -> int:
    app = az("containerapp", "show", *app_args(), "--query",
             "{revision:properties.latestRevisionName, image:properties.template.containers[0].image}")
    sha = candidate_sha(app["image"])
    if not sha:
        raise CandidateError(f"API revision {short(app['revision'])} runs no candidate build. Deploy one first: "
                             "python candidate.py deploy <sha>")
    reported = served_build(expect=sha)
    if reported != sha:
        raise CandidateError(f"/api/meta reports build {reported[:12] or 'nothing'}, not {sha[:12]}: the candidate "
                             "does not serve the traffic yet. Run `python candidate.py deploy` again.")
    suffix = short(app["revision"])
    test_run = run_id(sha, datetime.now(timezone.utc))
    description = run_description(sha, suffix, issue)
    test_id = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["testId"]
    az("load", "test-run", "create", "--load-test-resource", setting("LOAD_TEST_NAME"), "--resource-group",
       setting("AZURE_RESOURCE_GROUP"), "--test-id", test_id, "--test-run-id", test_run, "--display-name",
       f"Candidate {sha[:7]}", "--description", description, "--no-wait")
    print(f"Load test run {test_run} started against API revision {suffix}.")
    print(f"Description: {description}")
    print("Its verdict comes 8 to 9 minutes after the start, and the reporting function reports it about 2 minutes "
          "later" + (f", on Issue #{issue} too." if issue else "."))
    return 0


def restore() -> int:
    app = az("containerapp", "show", *app_args(), "--query",
             "{revision:properties.latestRevisionName, image:properties.template.containers[0].image, "
             "env:properties.template.containers[0].env[].name}")
    if not candidate_sha(app["image"]):
        print(f"API revision {short(app['revision'])} runs the normal image. Nothing to restore.")
        return 0
    revisions = az("containerapp", "revision", "list", *app_args(), "--all", "--query",
                   "[].{name:name, created:properties.createdTime, image:properties.template.containers[0].image, "
                   "env:properties.template.containers[0].env}") or []
    normal = normal_revision(revisions)
    if normal is None:
        raise CandidateError("no revision with the normal image is left. Run `azd deploy api` from an up-to-date main.")
    build_sha = next((e.get("value") for e in normal.get("env") or [] if e.get("name") == "BUILD_SHA"), None) or "local"
    remove = [name for name in (DELAY, EXPIRY) if name in (app["env"] or [])]
    print(f"Putting the API back on the image of revision {short(normal['name'])} ...")
    args = ["containerapp", "update", *app_args(), "--container-name", "api", "--image", normal["image"],
            "--set-env-vars", f"BUILD_SHA={build_sha}"]
    revision = az(*args, *(["--remove-env-vars", *remove] if remove else []), "--query", "properties.latestRevisionName")
    wait_for(revision)
    print(f"API revision {short(revision)} runs the normal image again; the candidate is deactivated.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__.split("\n", 2)[2],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    deploy_parser = sub.add_parser("deploy", help="build a commit and deploy it as API revision c<sha7>")
    deploy_parser.add_argument("sha", type=commit, help="the commit's full 40-character SHA")
    run_parser = sub.add_parser("run", help="start a load test run against the candidate that serves now")
    run_parser.add_argument("--issue", type=issue_number,
                            help="a GitHub Issue of this repository that the reporting function also comments its report on")
    sub.add_parser("restore", help="put the API back on its normal image")
    args = parser.parse_args(argv)
    utf8_stdout()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    try:
        if args.command == "deploy":
            return deploy(args.sha)
        if args.command == "run":
            return run(args.issue)
        return restore()
    except (AzError, CandidateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
