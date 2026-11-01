"""The release trigger's logic: check one pushed build's event, then start the release job for that build.

Event Grid calls the function (function_app.py) once for each push of the API's image to the registry. Everything the
function decides is here, in plain Python, so test_trigger.py checks it without Azure:

  pushed_build(event)          the event's fields the trigger uses, as text ("" when missing or not text)
  problems(build, settings)    what is wrong with the event: it comes from another registry, it isn't an image push,
                               the image is in another host or repository, it isn't named by a sha256 digest, or its
                               tag isn't the 40-character commit the build was made from
  release_container(...)       the release job's container with two settings added as objects: IMAGE
                               (registry/repository@digest, from the checked values) and COMMIT (the pushed tag)
  start_release(...)           checks the event, then starts one execution of the release job with that container.
                               A rejected event raises EventRejected and starts nothing: the invocation fails, with
                               every failed check in its message. A started release returns Started, whose summary()
                               is what the function logs: the build and the execution's suffix, never a host or
                               resource name. An Azure error names the call, the HTTP status, and Azure's error code.

The release job (release.py) checks the build itself: the image is in the API's own registry, the commit baked into it
is the one the tag names, release steps run one at a time, first come, first served, and a push that Event Grid
delivers twice starts at most one release.

App settings (infra/release.bicep sets them): REGISTRY_ID, REGISTRY_HOST, RELEASE_REPOSITORY, RELEASE_JOB_ID. Azure
calls use the function app's managed identity (IDENTITY_ENDPOINT and IDENTITY_HEADER, set by Azure Functions).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

IMAGE_PUSHED = "Microsoft.ContainerRegistry.ImagePushed"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")  # the build task tags each build with the commit it was made from
SUFFIX = re.compile(r"[a-z0-9]{1,16}")  # what follows a job's name in its executions' names
ERROR_CODE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,63}")  # Azure's error codes, such as AuthorizationFailed
ARM = "https://management.azure.com"
JOBS_API = "2025-07-01"  # Microsoft.App jobs, as in release.py
SETTINGS = ("REGISTRY_ID", "REGISTRY_HOST", "RELEASE_REPOSITORY", "RELEASE_JOB_ID")
ADDED = ("IMAGE", "COMMIT")  # the settings the trigger gives the release job; any value the job already has is replaced


class EventRejected(Exception):
    """The event is not a push of the API's repository to this registry: no release was started."""


@dataclass(frozen=True)
class Settings:
    registry_id: str  # resource id of the registry: the topic of its events
    registry_host: str  # its login server, <name>.azurecr.io
    repository: str
    release_job_id: str  # resource id of the release job

    @classmethod
    def from_environment(cls, environ=None) -> Settings:
        environ = os.environ if environ is None else environ
        missing = [name for name in SETTINGS if not environ.get(name)]
        if missing:
            raise RuntimeError(f"app setting(s) missing: {', '.join(missing)}. Run `azd provision` in the solution.")
        return cls(*(environ[name] for name in SETTINGS))


@dataclass(frozen=True)
class Started:
    """An execution the function started, as the function logs it: the execution's name after its job's name, and the
    build. Logs use placeholders, never a host name, resource name, or GUID (CONTRIBUTING)."""
    execution: str  # the part of the execution's name after the job's name and a hyphen, or "?"
    digest: str
    commit: str

    def summary(self) -> str:
        return f"execution {self.execution} for build {self.commit[:7]}, image {self.digest[:19]}"


def text(value) -> str:
    return value if isinstance(value, str) else ""


def mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def same_name(value: str, expected: str) -> bool:
    """Equal, ignoring ASCII case only: a look-alike such as the Kelvin sign, which lowercases to k, never matches."""
    return value.isascii() and value.lower() == expected.lower()


def pushed_build(event: dict) -> dict[str, str]:
    event = mapping(event)
    data = mapping(event.get("data"))
    target = mapping(data.get("target"))
    return {"topic": text(event.get("topic")), "eventType": text(event.get("eventType")),
            "host": text(mapping(data.get("request")).get("host")), "repository": text(target.get("repository")),
            "digest": text(target.get("digest")), "tag": text(target.get("tag"))}


def problems(build: dict[str, str], settings: Settings) -> list[str]:
    """Every check the event fails, by name; empty when it is a push of the API's repository to this registry."""
    found = []
    if not same_name(build["topic"], settings.registry_id):
        found.append("topic: the event does not come from this registry")
    if build["eventType"] != IMAGE_PUSHED:
        found.append("eventType: the event is not an image push")
    if not same_name(build["host"], settings.registry_host):
        found.append("host: the image is not in this registry")
    if build["repository"] != settings.repository:
        found.append(f"repository: the image is not {settings.repository}")
    if not DIGEST.fullmatch(build["digest"]):
        found.append("digest: the image is not named by sha256 and 64 lowercase hexadecimal characters")
    if not COMMIT.fullmatch(build["tag"]):
        found.append("tag: the image is not tagged with a commit, 40 lowercase hexadecimal characters")
    return found


def image_of(build: dict[str, str], settings: Settings) -> str:
    return f"{settings.registry_host.lower()}/{build['repository']}@{build['digest']}"


def release_container(job: dict, build: dict[str, str], settings: Settings) -> dict:
    """The release job's container for this build: its own image, command, arguments, and resources, its settings
    except IMAGE and COMMIT, then IMAGE and COMMIT for this build. Every setting is an object, and no event value is
    parsed as JSON, so a value can't add or replace a setting."""
    containers = mapping(mapping(mapping(job).get("properties")).get("template")).get("containers")
    if not isinstance(containers, list) or not containers or not isinstance(containers[0], dict):
        raise RuntimeError("the release job has no container to start")
    template = containers[0]
    container = {key: template[key] for key in ("name", "image", "command", "args", "resources") if key in template}
    env = template.get("env") if isinstance(template.get("env"), list) else []
    container["env"] = [entry for entry in env if mapping(entry).get("name") not in ADDED] + [
        {"name": "IMAGE", "value": image_of(build, settings)}, {"name": "COMMIT", "value": build["tag"]}]
    return container


def start_release(event: dict, settings: Settings, arm: Arm) -> Started:
    build = pushed_build(event)
    found = problems(build, settings)
    if found:
        raise EventRejected(f"No release was started: {'; '.join(found)}. Event Grid sends only pushes of the API to "
                            "this registry, so the event came from elsewhere.")
    job = arm.call("read the release job", "GET", f"{settings.release_job_id}?api-version={JOBS_API}")
    container = release_container(job, build, settings)
    execution = arm.call("start the release job", "POST", f"{settings.release_job_id}/start?api-version={JOBS_API}",
                         {"containers": [container]})
    return Started(execution_suffix(text(mapping(execution).get("name")), settings), build["digest"], build["tag"])


def execution_suffix(name: str, settings: Settings) -> str:
    """The part of an execution's name after its job's name: all the function logs of it. "?" for any other name."""
    job_name = settings.release_job_id.rstrip("/").rsplit("/", 1)[-1].lower()
    suffix = name[len(job_name) + 1:] if name.lower().startswith(job_name + "-") else ""
    return suffix if SUFFIX.fullmatch(suffix) else "?"


class Arm:
    """Azure Resource Manager, signed in as the function app's managed identity."""

    def __init__(self, environ=None, opener=urllib.request.urlopen):
        self.environ = os.environ if environ is None else environ
        self.open = opener
        self._token = ""

    def token(self) -> str:
        if not self._token:
            if not (self.environ.get("IDENTITY_ENDPOINT") and self.environ.get("IDENTITY_HEADER")):
                raise RuntimeError("no managed identity: IDENTITY_ENDPOINT and IDENTITY_HEADER are not set")
            query = urllib.parse.urlencode({"api-version": "2019-08-01", "resource": f"{ARM}/"})
            request = urllib.request.Request(f"{self.environ['IDENTITY_ENDPOINT']}?{query}",
                                             headers={"X-IDENTITY-HEADER": self.environ["IDENTITY_HEADER"]})
            with self.open(request, timeout=20) as response:
                self._token = json.load(response)["access_token"]
        return self._token

    def call(self, what: str, method: str, path: str, body: dict | None = None) -> dict:
        """One request, named by what ("read the release job"). An error names only that, the HTTP status, and Azure's
        error code: the request's path and Azure's message name the subscription and its resources, which logs never
        show (CONTRIBUTING). The invocation then fails, and Event Grid delivers the event again (up to five attempts in
        an hour)."""
        request = urllib.request.Request(f"{ARM}{path}", method=method,
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {self.token()}",
                                                  "Content-Type": "application/json"})
        try:
            with self.open(request, timeout=20) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            with error:
                code = text(mapping(mapping(_json(error.read())).get("error")).get("code"))
            raise RuntimeError(f"Could not {what}: HTTP {error.code}"
                               + (f" {code}" if ERROR_CODE.fullmatch(code) else "")) from None
        return mapping(_json(raw))


def _json(raw: bytes):
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return None
