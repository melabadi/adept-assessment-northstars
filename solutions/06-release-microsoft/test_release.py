"""Unit tests for release.py: the rules that keep a release safe, checked without Azure.

They cover what a reviewer must be able to trust without a live run:
  - only builds of requesthub-api from the API's own registry are released, whatever an event or a person names;
  - the Logic App passes event values to the job as values, starts it only when every check passed, and fails its run
    when it rejects an event;
  - nothing untrusted can print a line that looks like a release record;
  - promote needs the gate's verdict for exactly this candidate and image, with the standard bake;
  - a release that fails removes its own candidate, even while another step waits for its turn;
  - steps take turns first come, first served, and any execution that has not finished counts as running;
  - a build without a known commit is never released;
  - rollback goes only to the revision that served users just before: never a drill revision or the candidate.

Run them from this folder (Python 3.12+, standard library only):

  python -m unittest -v
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import release

REGISTRY = "crexample.azurecr.io"
SHA = "4" * 40
OTHER_SHA = "5" * 40
DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32
NOW = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)


def revision(image_digest: str = DIGEST, commit: str = SHA, *, active: bool = True, fault: bool = False) -> dict:
    env = [{"name": "RELEASE_COMMIT", "value": commit}]
    if fault:
        env.append({"name": "Faults__FailReadiness", "value": "true"})
    return {"properties": {"active": active, "healthState": "Healthy", "runningState": "Running",
                           "createdTime": "2026-10-29T17:00:00Z", "fqdn": "ca-api--x.env.region.azurecontainerapps.io",
                           "template": {"containers": [{"name": "api", "image": f"{REGISTRY}/requesthub-api@{image_digest}",
                                                        "env": env}]}}}


class FakeApp:
    """Just enough of ContainerApp for the commands: revisions, traffic, and tags, kept in memory."""
    name = "ca-api"
    resource_group = "rg"
    group_url = "https://management.azure.com/subscriptions/s/resourceGroups/rg"
    url = group_url + "/providers/Microsoft.App/containerApps/ca-api"

    def __init__(self, revisions: dict[str, dict], traffic: list[dict], tags: dict | None = None, *,
                 merge_tags: bool = False):
        self._revisions = {name: copy.deepcopy(r) for name, r in revisions.items()}
        self.traffic = traffic
        self.tags = dict(tags or {})
        self.merge_tags = merge_tags
        self.patches: list[dict] = []
        self.deactivated: list[str] = []
        self.activated: list[str] = []

    def get(self) -> dict:
        return {"tags": dict(self.tags), "properties": {
            "latestReadyRevisionName": None,
            "configuration": {"ingress": {"fqdn": "ca-api.env.region.azurecontainerapps.io", "traffic": self.traffic},
                              "registries": [{"server": REGISTRY}]}}}

    def revisions(self) -> list[dict]:
        return [{"name": name, **data} for name, data in self._revisions.items()]

    def revision(self, name: str) -> dict:
        return {"name": name, **self._revisions[name]}

    def patch(self, body: dict) -> float:
        self.patches.append(copy.deepcopy(body))
        if "tags" in body:
            # Azure replaces all tags on a PATCH that includes them (verified live); merge_tags plays an API that
            # merged them instead, which the verdict must survive too.
            self.tags = {**self.tags, **body["tags"]} if self.merge_tags else dict(body["tags"])
        traffic = body.get("properties", {}).get("configuration", {}).get("ingress", {}).get("traffic")
        if traffic is not None:
            self.traffic = traffic
        return 1.0

    def deactivate(self, name: str) -> None:
        self.deactivated.append(name)
        self._revisions[name]["properties"]["active"] = False

    def activate(self, name: str) -> None:
        self.activated.append(name)
        self._revisions[name]["properties"]["active"] = True

    def traffic_patches(self) -> list[dict]:
        return [p for p in self.patches if "properties" in p]


class NoProbe:
    def __init__(self, *args, **kwargs):
        pass

    def start(self) -> None:
        pass

    def stop(self) -> dict:
        return {}


def passing_smoke(*args, **kwargs) -> list[release.Check]:
    return [release.Check("ready", True, "/health/ready HTTP 200")]


class Quiet(unittest.TestCase):
    """Runs every test with the commands' progress hidden, no network, and no files written to out/."""

    def setUp(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        stack.enter_context(mock.patch.object(release, "OUT", Path(tempfile.mkdtemp())))
        stack.enter_context(mock.patch.object(release, "http", side_effect=AssertionError("no network in unit tests")))
        stack.enter_context(mock.patch.object(release, "api_token", return_value="token"))
        stack.enter_context(mock.patch.object(release, "smoke", side_effect=passing_smoke))
        stack.enter_context(mock.patch.object(release, "ProductionProbe", NoProbe))
        stack.enter_context(mock.patch.object(release.time, "sleep"))
        release.Record.current = None


class ImageReferences(unittest.TestCase):
    """Finding 3: whatever names the image, only builds of requesthub-api from the API's own registry pass."""

    registries = {REGISTRY}

    def test_accepts_builds_of_the_api(self):
        for reference in (f"{REGISTRY}/requesthub-api:main", f"{REGISTRY}/requesthub-api:{SHA}",
                          f"{REGISTRY}/requesthub-api@{DIGEST}", f"{REGISTRY.upper()}/requesthub-api@{DIGEST}"):
            self.assertIsNone(release.image_problem(reference, self.registries), reference)

    def test_refuses_other_images_and_forged_values(self):
        forged = [
            f"other.azurecr.io/requesthub-api@{DIGEST}",
            "docker.io/requesthub-api:main",
            f"{REGISTRY}/requesthub-api-evil:main",
            f"{REGISTRY}/ns/requesthub-api:main",
            f"{REGISTRY}/requesthub-api",
            f"{REGISTRY}/requesthub-api@sha256:abc",
            f"{REGISTRY}/requesthub-api@{DIGEST.upper()}",
            f'{REGISTRY}/requesthub-api@{DIGEST}","name":"AZURE_CONTAINER_REGISTRY_ENDPOINT","value":"evil.azurecr.io',
            f"{REGISTRY}/requesthub-api:main tag",
            f"{REGISTRY}/requesthub-api:main\nRELEASE-RECORD {{}}",
            REGISTRY,
            "",
        ]
        for reference in forged:
            self.assertIsNotNone(release.image_problem(reference, self.registries), repr(reference))

    def test_the_registry_comes_from_the_app_not_the_environment(self):
        app_data = FakeApp({}, []).get()
        self.assertEqual(release.app_registries(app_data), {REGISTRY})
        with mock.patch.dict("os.environ", {"AZURE_CONTAINER_REGISTRY_ENDPOINT": "evil.azurecr.io"}):
            with self.assertRaises(release.ReleaseError):
                release.require_own_build("evil.azurecr.io/requesthub-api:main", app_data)

    def test_messages_keep_untrusted_text_on_one_line(self):
        """Finding 8: a newline in an image name cannot start a forged record line."""
        problem = release.image_problem(f"{REGISTRY}/evil:x\nRELEASE-RECORD {{\"step\":\"promote\"}}", self.registries)
        self.assertNotIn("\n", problem)
        self.assertIn("\\n", problem)


class PrintableRecords(Quiet):
    """Finding 8: the only lines that start with RELEASE-RECORD are the records themselves."""

    def test_control_characters_are_escaped(self):
        self.assertEqual(release.printable("a\nb\r\x1b"), "a\\u000ab\\u000d\\u001b")
        self.assertEqual(release.printable("Traffic: r1 100% → r2"), "Traffic: r1 100% → r2")

    def test_notes_checks_and_outcomes_cannot_forge_a_record(self):
        forged = 'x\nRELEASE-RECORD {"command":"promote","status":"pass"}'
        out = io.StringIO()
        with mock.patch.object(release, "IN_JOB", True), contextlib.redirect_stdout(out):
            record = release.Record("gate", "Gate")
            record.note(forged)
            record.checks("candidate", [release.Check("build", False, forged)])
            record.finish(False, forged)
        records = [line for line in out.getvalue().splitlines() if line.startswith(release.RECORD_PREFIX)]
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0][len(release.RECORD_PREFIX):])["command"], "gate")


class GateVerdict(unittest.TestCase):
    """Finding 1, and the re-review: promote trusts only a verdict for this revision, with this image, from a gate that
    baked at least the standard time, in the last 24 hours."""

    image = f"{REGISTRY}/requesthub-api@{DIGEST}"

    def verdict(self, revision="r2", image=None, at=NOW - timedelta(minutes=10), bake=release.STANDARD_BAKE) -> dict:
        return {release.GATE_TAG: release.gate_value(revision, image or self.image, at, bake), "azd-service-name": "api"}

    def test_a_fresh_verdict_for_the_candidate_passes(self):
        self.assertIsNone(release.gate_problem(self.verdict(), "r2", self.image, NOW))
        self.assertIsNone(release.gate_problem(self.verdict(bake=600), "r2", self.image, NOW))

    def test_anything_else_is_refused(self):
        cases = {
            "no verdict": {"azd-service-name": "api"},
            "another revision": self.verdict(revision="r1"),
            "another image": self.verdict(image=f"{REGISTRY}/requesthub-api@{OTHER_DIGEST}"),
            "too old": self.verdict(at=NOW - timedelta(hours=release.GATE_VALID_HOURS, minutes=1)),
            "from the future": self.verdict(at=NOW + timedelta(hours=1)),
            "a short bake": self.verdict(bake=0),
            "a bake just under the standard": self.verdict(bake=release.STANDARD_BAKE - 1),
            "a negative bake": self.verdict(bake=-60),
            "the format before the bake was recorded": {release.GATE_TAG: f"r2|{DIGEST}|{release.iso(NOW)}"},
            "malformed": {release.GATE_TAG: "r2|" + DIGEST},
            "not a time": {release.GATE_TAG: f"r2|{DIGEST}|yesterday|60"},
            "not a number": {release.GATE_TAG: f"r2|{DIGEST}|{release.iso(NOW)}|６０"},
            "cleared": {release.GATE_TAG: release.cleared_gate(NOW)},
        }
        for case, tags in cases.items():
            self.assertIsNotNone(release.gate_problem(tags, "r2", self.image, NOW), case)
        self.assertIsNotNone(release.gate_problem(self.verdict(), "r2", f"{REGISTRY}/requesthub-api:main", NOW),
                             "an image not pinned by digest")
        self.assertIn("bake", release.gate_problem(self.verdict(bake=0), "r2", self.image, NOW))
        self.assertEqual(release.gate_problem({release.GATE_TAG: release.cleared_gate(NOW)}, "r2", self.image, NOW),
                         "the gate has not passed it")

    def test_tags_keep_every_other_tag(self):
        tags = {"azd-env-name": "env", "azd-service-name": "api", release.GATE_TAG: "old"}
        cleared = release.tags_with_gate(tags, release.cleared_gate(NOW))
        self.assertEqual({k: v for k, v in cleared.items() if k != release.GATE_TAG},
                         {"azd-env-name": "env", "azd-service-name": "api"})
        self.assertTrue(cleared[release.GATE_TAG].startswith(f"{release.CLEARED}|"))
        self.assertEqual(release.tags_with_gate(tags, "new")[release.GATE_TAG], "new")
        self.assertEqual(release.tags_with_gate(tags, "new")["azd-service-name"], "api")


class Promote(Quiet):
    """Finding 1, end to end: promote moves traffic only with the gate's verdict, and consumes it."""

    def app(self, tags: dict, *, merge_tags: bool = False) -> FakeApp:
        return FakeApp({"ca-api--r1": revision(OTHER_DIGEST, OTHER_SHA), "ca-api--r2": revision()},
                       [{"revisionName": "ca-api--r1", "weight": 100, "label": "stable"},
                        {"revisionName": "ca-api--r2", "weight": 0, "label": "candidate"}], tags, merge_tags=merge_tags)

    def promote(self, app: FakeApp) -> int:
        with mock.patch.object(release, "connect", return_value=app), \
                mock.patch.object(release, "busy_executions", return_value=[]):
            return release.cmd_promote(argparse.Namespace())

    def verdict(self, digest: str = DIGEST, bake: int = release.STANDARD_BAKE) -> str:
        return release.gate_value("r2", f"{REGISTRY}/requesthub-api@{digest}", release.utc_now(), bake)

    def test_refuses_without_a_verdict(self):
        app = self.app({"azd-service-name": "api"})
        self.assertEqual(self.promote(app), 1)
        self.assertEqual(app.traffic_patches(), [])

    def test_refuses_a_verdict_for_another_image(self):
        app = self.app({release.GATE_TAG: self.verdict(digest=OTHER_DIGEST)})
        self.assertEqual(self.promote(app), 1)
        self.assertEqual(app.traffic_patches(), [])

    def test_refuses_a_gate_with_a_short_bake(self):
        app = self.app({release.GATE_TAG: self.verdict(bake=0)})
        self.assertEqual(self.promote(app), 1)
        self.assertEqual(app.traffic_patches(), [])

    def test_promotes_with_a_verdict_and_consumes_it(self):
        for merge_tags in (False, True):
            app = self.app({"azd-service-name": "api", release.GATE_TAG: self.verdict()}, merge_tags=merge_tags)
            self.assertEqual(self.promote(app), 0)
            stable = next(t for t in app.traffic if t["label"] == "stable")
            self.assertEqual((stable["revisionName"], stable["weight"]), ("ca-api--r2", 100))
            # Consumed whether Azure replaces tags or merges them: the verdict is overwritten, not just left out.
            self.assertIsNotNone(release.gate_problem(app.tags, "r2", f"{REGISTRY}/requesthub-api@{DIGEST}",
                                                      release.utc_now()), f"merge_tags={merge_tags}")
            self.assertEqual(app.tags.get("azd-service-name"), "api")


class GateRecordsItsBake(Quiet):
    """The re-review: a gate run with a short bake (gate --bake 0 from a terminal) records a verdict promote refuses."""

    def run_gate_with_bake(self, bake: int) -> FakeApp:
        app = FakeApp({"ca-api--r1": revision(OTHER_DIGEST, OTHER_SHA), "ca-api--r2": revision()},
                      [{"revisionName": "ca-api--r1", "weight": 100, "label": "stable"},
                       {"revisionName": "ca-api--r2", "weight": 0, "label": "candidate"}], {"azd-service-name": "api"})
        with mock.patch.object(release, "connect", return_value=app), \
                mock.patch.object(release, "run_gate", return_value=(True, "passed", None)):
            self.assertEqual(release.cmd_gate(argparse.Namespace(bake=bake)), 0)
        return app

    def test_the_verdict_records_the_bake_and_promote_needs_the_standard_one(self):
        image = f"{REGISTRY}/requesthub-api@{DIGEST}"
        short = self.run_gate_with_bake(0)
        self.assertTrue(short.tags[release.GATE_TAG].endswith("|0"))
        self.assertIn("bake", release.gate_problem(short.tags, "r2", image, release.utc_now()))
        standard = self.run_gate_with_bake(release.STANDARD_BAKE)
        self.assertIsNone(release.gate_problem(standard.tags, "r2", image, release.utc_now()))
        self.assertEqual(standard.tags.get("azd-service-name"), "api")


class OwnCandidateCleanup(Quiet):
    """Finding 2: a release removes the candidate it created itself, without waiting for anyone."""

    def setUp(self) -> None:
        super().setUp()
        self.app = FakeApp({"ca-api--r1": revision(OTHER_DIGEST, OTHER_SHA)},
                           [{"revisionName": "ca-api--r1", "weight": 100, "label": "stable"}])
        lock = mock.patch.object(release, "busy_executions",
                                 side_effect=AssertionError("removing its own candidate must not wait for the lock"))
        lock.start()
        self.addCleanup(lock.stop)
        connect = mock.patch.object(release, "connect", return_value=self.app)
        connect.start()
        self.addCleanup(connect.stop)

    def fake_deploy(self, *args, created=None, **kwargs) -> int:
        created["revision"] = "ca-api--r2"
        self.app._revisions["ca-api--r2"] = revision()
        self.app.traffic = self.app.traffic + [{"revisionName": "ca-api--r2", "weight": 0, "label": "candidate"}]
        return 0

    def run_release(self, gate, *, keep=True) -> int:
        with mock.patch.object(release, "deploy_candidate", side_effect=self.fake_deploy), \
                mock.patch.object(release, "cmd_gate", side_effect=gate):
            return release.deploy_and_gate(self.app, argparse.Namespace(), "img", SHA, "none", "r", keep=keep)

    def assert_removed(self) -> None:
        self.assertIn("ca-api--r2", self.app.deactivated)
        self.assertNotIn("candidate", [t.get("label") for t in self.app.traffic])
        self.assertEqual([(t["revisionName"], t["weight"]) for t in self.app.traffic if t["weight"]], [("ca-api--r1", 100)])

    def test_a_failed_gate_removes_the_candidate_while_another_release_waits(self):
        self.assertEqual(self.run_release(lambda args, result=None: 1), 1)
        self.assert_removed()

    def test_an_error_during_the_gate_removes_the_candidate_and_is_reported(self):
        records: list[release.Record] = []

        def gate(args, result=None):
            records.append(release.Record("gate", "Gate"))
            raise release.ReleaseError("Could not get a token from the managed identity")
        with self.assertRaises(release.ReleaseError):
            self.run_release(gate)
        self.assert_removed()
        self.assertEqual(records[0].data["status"], "fail")
        self.assertTrue(records[0].data["outcome"].startswith("Stopped: Could not get a token"))

    def test_a_passed_gate_keeps_the_candidate_for_a_person(self):
        self.assertEqual(self.run_release(lambda args, result=None: 0), 0)
        self.assertEqual(self.app.deactivated, [])

    def test_the_drill_always_removes_its_candidate(self):
        self.assertEqual(self.run_release(lambda args, result=None: 0, keep=False), 0)
        self.assert_removed()

    def test_nothing_is_removed_when_no_candidate_was_created(self):
        with mock.patch.object(release, "deploy_candidate", return_value=1), \
                mock.patch.object(release, "cmd_gate", side_effect=AssertionError("no gate without a candidate")):
            self.assertEqual(release.deploy_and_gate(self.app, argparse.Namespace(), "img", SHA, "none", "r", keep=True), 1)
        self.assertEqual(self.app.deactivated, [])
        self.assertEqual(self.app.traffic_patches(), [])


class Turns(unittest.TestCase):
    """Finding 5: steps take turns first come, first served, the same way in every execution."""

    t0 = NOW

    def step(self, name: str, seconds: float | None) -> dict:
        return {"step": "release", "name": name, "status": "Running",
                "start": None if seconds is None else self.t0 + timedelta(seconds=seconds)}

    def test_the_earliest_goes_first(self):
        running = [self.step("first", 0), self.step("second", 5)]
        self.assertEqual(release.ahead_of(running, "first"), [])
        self.assertEqual([r["name"] for r in release.ahead_of(running, "second")], ["first"])

    def test_ties_are_broken_by_name_in_both_executions(self):
        running = [self.step("b", 0), self.step("a", 0)]
        self.assertEqual(release.ahead_of(running, "a"), [])
        self.assertEqual([r["name"] for r in release.ahead_of(running, "b")], ["a"])

    def test_two_waiting_releases_never_wait_for_each_other(self):
        running = [self.step("gating", 0), self.step("waiting-1", 10), self.step("waiting-2", 20)]
        self.assertEqual([r["name"] for r in release.ahead_of(running, "waiting-1")], ["gating"])
        self.assertNotIn("waiting-2", [r["name"] for r in release.ahead_of(running, "waiting-1")])

    def test_another_step_without_a_start_time_counts_as_ahead(self):
        running = [self.step("me", 0), self.step("new", None)]
        self.assertEqual([r["name"] for r in release.ahead_of(running, "me")], ["new"])

    def test_a_start_time_listed_late_never_lets_both_steps_run(self):
        # B started first, but its start time is not listed yet when A looks: A must wait for B.
        self.assertEqual([r["name"] for r in release.ahead_of([self.step("a", 5), self.step("b", None)], "a")], ["b"])
        # Once both are listed, B goes first and A keeps waiting: at no moment do both go ahead.
        listed = [self.step("a", 5), self.step("b", 0)]
        self.assertEqual([r["name"] for r in release.ahead_of(listed, "a")], ["b"])
        self.assertEqual(release.ahead_of(listed, "b"), [])

    def test_two_steps_without_start_times_both_wait(self):
        running = [self.step("a", None), self.step("b", None)]
        self.assertEqual([r["name"] for r in release.ahead_of(running, "a")], ["b"])
        self.assertEqual([r["name"] for r in release.ahead_of(running, "b")], ["a"])

    def test_a_terminal_or_an_unlisted_execution_waits_for_everyone(self):
        running = [self.step("first", 0), self.step("second", 5)]
        self.assertEqual(len(release.ahead_of(running, None)), 2)
        self.assertEqual(len(release.ahead_of(running, "not-listed")), 2)
        self.assertEqual(len(release.ahead_of([self.step("me", None), self.step("other", 5)], "me")), 1)


class Provenance(Quiet):
    """Finding 6: a build is released only as the commit baked into it."""

    def test_the_baked_commit_is_the_release_commit(self):
        self.assertEqual(release.release_commit(SHA, ""), (SHA, None))
        self.assertEqual(release.release_commit(SHA, SHA), (SHA, None))

    def test_an_unknown_or_conflicting_commit_is_refused(self):
        for baked, claimed in (("", ""), ("", SHA), ("local", ""), (SHA, OTHER_SHA), (SHA, "main")):
            commit, problem = release.release_commit(baked, claimed)
            self.assertEqual(commit, "", (baked, claimed))
            self.assertIsNotNone(problem, (baked, claimed))

    def release(self, app: FakeApp, baked: str, env: dict | None = None) -> tuple[int, mock.Mock]:
        args = argparse.Namespace(image=None, commit=None, wait=0, force=False)
        image = f"{REGISTRY}/requesthub-api@{DIGEST}"
        with mock.patch.object(release, "connect", return_value=app), \
                mock.patch.object(release, "wait_for_turn", return_value=True), \
                mock.patch.object(release, "resolve_image", return_value=(image, baked)), \
                mock.patch.object(release, "deploy_and_gate", return_value=0) as deploy, \
                mock.patch.dict("os.environ", env or {"IMAGE": image, "COMMIT": SHA}):
            return release.cmd_release(args), deploy

    def stable_app(self, tags: dict | None = None, candidate: dict | None = None) -> FakeApp:
        revisions = {"ca-api--r1": revision(OTHER_DIGEST, OTHER_SHA)}
        traffic = [{"revisionName": "ca-api--r1", "weight": 100, "label": "stable"}]
        if candidate:
            revisions["ca-api--r2"] = candidate
            traffic.append({"revisionName": "ca-api--r2", "weight": 0, "label": "candidate"})
        return FakeApp(revisions, traffic, tags)

    def test_a_build_without_a_known_commit_is_not_released(self):
        code, deploy = self.release(self.stable_app(), baked="")
        self.assertEqual(code, 1)
        deploy.assert_not_called()

    def test_a_pushed_build_whose_tag_disagrees_with_the_image_is_not_released(self):
        code, deploy = self.release(self.stable_app(), baked=OTHER_SHA)
        self.assertEqual(code, 1)
        deploy.assert_not_called()

    def test_a_duplicate_push_is_skipped_only_when_its_candidate_passed_the_gate(self):
        image = f"{REGISTRY}/requesthub-api@{DIGEST}"
        code, deploy = self.release(self.stable_app(candidate=revision()), baked=SHA)
        self.assertEqual(code, 0)
        deploy.assert_called_once()  # the candidate has no verdict: release it again
        gated = {release.GATE_TAG: release.gate_value("r2", image, release.utc_now(), release.STANDARD_BAKE)}
        code, deploy = self.release(self.stable_app(tags=gated, candidate=revision()), baked=SHA)
        self.assertEqual(code, 0)
        deploy.assert_not_called()


class Rollback(Quiet):
    """Finding 7: rollback's only target is the revision that served users just before; never a drill revision, the
    candidate, or a revision that lost the candidate label."""

    def rollback(self, app: FakeApp) -> int:
        args = argparse.Namespace(ready_timeout=1, not_ready_grace=1)
        with mock.patch.object(release, "connect", return_value=app), \
                mock.patch.object(release, "busy_executions", return_value=[]), \
                mock.patch.object(release, "wait_until_ready", return_value=(True, "ready")):
            return release.cmd_rollback(args)

    def app(self, previous: str = "ca-api--r1", candidate: str = "ca-api--r5") -> FakeApp:
        return FakeApp({"ca-api--r1": revision(OTHER_DIGEST, OTHER_SHA), "ca-api--r2": revision(),
                        "ca-api--d3": revision(fault=True, active=False), "ca-api--r4": revision(active=False),
                        "ca-api--r5": revision()},
                       [{"revisionName": "ca-api--r2", "weight": 100, "label": "stable"},
                        {"revisionName": previous, "weight": 0, "label": "previous"},
                        {"revisionName": candidate, "weight": 0, "label": "candidate"}])

    def test_refuses_a_drill_revision_and_the_candidate(self):
        for app in (self.app(previous="ca-api--d3"), self.app(previous="ca-api--r5")):
            self.assertEqual(self.rollback(app), 1)
            self.assertEqual(app.traffic_patches(), [])

    def test_a_revision_that_lost_the_candidate_label_can_never_be_named(self):
        with mock.patch("sys.argv", ["release.py", "rollback", "--to", "r4"]), self.assertRaises(SystemExit):
            release.main()

    def test_refuses_without_a_previous_revision(self):
        app = FakeApp({"ca-api--r2": revision()}, [{"revisionName": "ca-api--r2", "weight": 100, "label": "stable"}])
        self.assertEqual(self.rollback(app), 1)
        self.assertEqual(app.traffic_patches(), [])

    def test_the_rollback_keeps_a_waiting_candidate(self):
        app = self.app()
        self.assertEqual(self.rollback(app), 0)
        labels = {t["label"]: (t["revisionName"], t["weight"]) for t in app.traffic}
        self.assertEqual(labels, {"stable": ("ca-api--r1", 100), "previous": ("ca-api--r2", 0),
                                  "candidate": ("ca-api--r5", 0)})


class RunningRule(unittest.TestCase):
    """The re-review: any execution that has not finished counts as running, unless it started longer ago than its
    job's time limit plus the margin. The preflight uses the same function."""

    def props(self, status, minutes_ago=None) -> dict:
        return {"status": status, "startTime": None if minutes_ago is None else release.iso(NOW - timedelta(minutes=minutes_ago))}

    def test_only_succeeded_failed_and_stopped_are_finished(self):
        for status in ("Running", "Processing", "Degraded", "Unknown", "", None, "SomethingNew"):
            self.assertTrue(release.still_running(self.props(status, 1), 900, NOW), status)
        for status in ("Succeeded", "Failed", "Stopped"):
            self.assertFalse(release.still_running(self.props(status, 1), 900, NOW), status)

    def test_an_execution_past_its_time_limit_and_the_margin_is_not_running(self):
        margin = release.STALE_MARGIN.total_seconds() / 60
        self.assertTrue(release.still_running(self.props("Running", 15 + margin - 1), 900, NOW))
        self.assertFalse(release.still_running(self.props("Running", 15 + margin + 1), 900, NOW))
        self.assertTrue(release.still_running(self.props("Degraded"), 900, NOW), "no start time: it cannot be aged")
        self.assertTrue(release.still_running(self.props("Running", 30 + margin - 1), None, NOW), "unknown limit: 30 min")
        self.assertFalse(release.still_running(self.props("Running", 30 + margin + 1), None, NOW))

    def test_running_steps_lists_unfinished_executions_of_the_release_jobs_only(self):
        jobs = [{"id": "/jobs/caj-release-x", "tags": {"requesthub-release": "release"},
                 "properties": {"configuration": {"replicaTimeout": 1800}}},
                {"id": "/jobs/another", "tags": {}, "properties": {"configuration": {"replicaTimeout": 1800}}}]
        executions = {"/jobs/caj-release-x": [{"name": "running", "properties": self.props("Running", 1)},
                                              {"name": "degraded", "properties": self.props("Degraded", 2)},
                                              {"name": "succeeded", "properties": self.props("Succeeded", 3)},
                                              {"name": "stale", "properties": self.props("Running", 600)}],
                      "/jobs/another": [{"name": "not-a-release-step", "properties": self.props("Running", 1)}]}

        def fake_list(url: str) -> list[dict]:
            if url.endswith("/providers/Microsoft.App/jobs"):
                return jobs
            return executions[url.removeprefix(release.ARM).removesuffix("/executions")]
        with mock.patch.object(release, "arm_list", side_effect=fake_list), \
                mock.patch.object(release, "utc_now", return_value=NOW):
            running = release.running_steps(FakeApp({}, []))
        self.assertEqual([(r["name"], r["status"]) for r in running], [("running", "Running"), ("degraded", "Degraded")])


class TriggerDefinition(unittest.TestCase):
    """Finding 3 and the re-review, on the Logic App's definition (infra/release-trigger.json): what reaches the job,
    and what a rejected event leaves behind."""

    folder = Path(__file__).resolve().parent / "infra"

    def setUp(self) -> None:
        self.definition = json.loads((self.folder / "release-trigger.json").read_text(encoding="utf-8"))
        self.text = json.dumps(self.definition)
        self.actions: dict[str, tuple[dict, list[tuple[str, str]]]] = {}

        def walk(actions: dict, ancestors: list[tuple[str, str]]) -> None:
            for name, action in actions.items():
                self.actions[name] = (action, ancestors)
                walk(action.get("actions") or {}, ancestors + [(name, action["type"])])
                walk((action.get("else") or {}).get("actions") or {}, ancestors + [(name, action["type"] + ":else")])
        walk(self.definition["actions"], [])

    def test_the_repository_is_set_in_one_place(self):
        self.assertNotIn(release.REPOSITORY, self.text)
        self.assertIn("repository", self.definition["parameters"])
        bicep = (self.folder / "release.bicep").read_text(encoding="utf-8")
        self.assertIn(f"var repository = '{release.REPOSITORY}'", bicep)
        self.assertIn("subjectBeginsWith: '${repository}:'", bicep)
        self.assertIn("repository: { value: repository }", bicep)

    def test_event_values_reach_the_job_as_values_never_as_json_text(self):
        self.assertNotIn("json(concat(", self.text)
        env = self.actions["Release_this_build"][0]["inputs"]["env"]
        self.assertIn("addProperty(", env)
        self.assertIn("outputs('Pushed_build')?['repository'], '@', outputs('Pushed_build')?['digest']", env)

    def test_the_job_starts_only_when_every_check_passed(self):
        _, ancestors = self.actions["Start_release_job"]
        condition, kind = ancestors[-1]
        self.assertEqual(kind, "If")
        self.assertIn("outputs('Check_pushed_build')", json.dumps(self.actions[condition][0]["expression"]))
        check = self.actions["Check_pushed_build"][0]["inputs"]
        for name in ("topic:", "eventType:", "host:", "repository:", "digest:"):
            self.assertIn(name, check)
        self.assertNotIn("startsWith(", check)  # not case-sensitive in Logic Apps, while replace() is

    def test_a_rejected_event_fails_the_run_after_the_loop(self):
        terminates = [(action, ancestors) for action, ancestors in self.actions.values() if action["type"] == "Terminate"]
        self.assertEqual(len(terminates), 1)
        action, ancestors = terminates[0]
        self.assertEqual(action["inputs"]["runStatus"], "Failed")
        self.assertFalse([kind for _, kind in ancestors if kind.startswith(("Foreach", "Until"))],
                         "Logic Apps cannot run Terminate inside a loop")
        note, note_ancestors = self.actions["Note_the_rejection"]
        self.assertEqual(note["type"], "AppendToArrayVariable")
        self.assertEqual(note_ancestors[-1], ("Is_a_push_of_the_API_to_this_registry", "If:else"))


if __name__ == "__main__":
    unittest.main()
