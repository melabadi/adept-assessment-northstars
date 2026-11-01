"""Unit tests for the release trigger (trigger/release_trigger.py and function_app.py), checked without Azure.

They cover what a reviewer must be able to trust without a live run:
  - a push of requesthub-api:<commit> to this registry, named by digest, starts the release job once, with IMAGE built
    from the checked values and COMMIT from the tag, each setting an object;
  - any other event starts nothing, and the invocation fails with every failed check by name: another topic, event
    type, host, or repository, a digest that isn't sha256 and 64 lowercase hexadecimal characters, a tag that isn't
    a 40-character commit, a look-alike character, or a missing or malformed field;
  - event values stay values: even a value with quotes, braces, or new lines can't add or replace a setting of the job;
  - the job keeps its own image, arguments, resources, and settings, and only IMAGE and COMMIT are replaced;
  - Azure calls use the function's managed identity, and an Azure error fails the invocation, so Event Grid delivers
    the event again;
  - logs use placeholders: the success line names the build and the execution's suffix, and an Azure error names the
    call, the HTTP status, and Azure's error code, never a host name, resource name, or GUID;
  - Event Grid calls the function by its name, one event per call, and its filter and the function's check use the
    repository set once, in infra/release.bicep;
  - azd runs these tests before every deploy, and connects Event Grid to the function only after every service is
    deployed;
  - the preflight fails when the function isn't deployed or running, when anything else may start the release job (a
    Logic App left from the earlier trigger, or another principal with Container Apps Jobs Operator), or when Event
    Grid's topic or subscription differs from what the trigger expects.

Run them from this folder (Python 3.12+, standard library only; function_app.py itself needs Azure Functions, so it is
read, not imported):

  python -m unittest -v
"""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER / "trigger"))

import release  # noqa: E402
import release_trigger as trigger  # noqa: E402

REGISTRY_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ContainerRegistry/registries/crdesk"
HOST = "crdesk.azurecr.io"
JOB_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/jobs/caj-release-example"
SETTINGS = trigger.Settings(REGISTRY_ID, HOST, release.REPOSITORY, JOB_ID)
DIGEST = "sha256:" + "ab" * 32
SHA = "4f0a" * 10  # a commit, in lowercase hexadecimal
JOB = {"properties": {"template": {"containers": [{
    "name": "release", "image": f"{HOST}/release-tools@sha256:{'cd' * 32}", "args": ["release"],
    "resources": {"cpu": 0.25, "memory": "0.5Gi"}, "probes": [],
    "env": [{"name": "AZURE_CONTAINER_REGISTRY_ENDPOINT", "value": HOST}, {"name": "RELEASE_STEP", "value": "release"}]}]}}}


def push(**changes) -> dict:
    """A push of requesthub-api:<commit> as Event Grid delivers it; each change sets one field (None removes it)."""
    fields = {"topic": REGISTRY_ID.replace("resourceGroups", "resourcegroups"), "eventType": trigger.IMAGE_PUSHED,
              "host": HOST, "repository": release.REPOSITORY, "digest": DIGEST, "tag": SHA}
    fields.update(changes)
    target = {key: fields[key] for key in ("repository", "digest", "tag") if fields[key] is not None}
    event = {"topic": fields["topic"], "eventType": fields["eventType"],
             "data": {"request": {"host": fields["host"]}, "target": target}}
    return {key: value for key, value in event.items() if value is not None}


class FakeArm:
    def __init__(self, job: dict = JOB, fail_on: str = "", execution: str = "caj-release-example-x1"):
        self.job, self.fail_on, self.execution, self.calls = job, fail_on, execution, []

    def call(self, what: str, method: str, path: str, body: dict | None = None) -> dict:
        self.calls.append((what, method, path, copy.deepcopy(body)))
        if method == self.fail_on:
            raise RuntimeError(f"Could not {what}: HTTP 503")
        return copy.deepcopy(self.job) if method == "GET" else {"id": f"{JOB_ID}/executions/x", "name": self.execution}


def started_container(arm: FakeArm) -> dict:
    _, method, _, body = arm.calls[-1]
    assert method == "POST"
    return json.loads(json.dumps(body))["containers"][0]  # what Azure receives


class AcceptedPush(unittest.TestCase):
    def test_a_push_of_the_api_starts_the_release_job_once(self):
        arm = FakeArm()
        started = trigger.start_release(push(), SETTINGS, arm)
        self.assertEqual([(w, m, p) for w, m, p, _ in arm.calls],
                         [("read the release job", "GET", f"{JOB_ID}?api-version=2025-07-01"),
                          ("start the release job", "POST", f"{JOB_ID}/start?api-version=2025-07-01")])
        env = started_container(arm)["env"]
        self.assertEqual(env[-2:], [{"name": "IMAGE", "value": f"{HOST}/requesthub-api@{DIGEST}"},
                                    {"name": "COMMIT", "value": SHA}])
        self.assertEqual(started, trigger.Started("x1", DIGEST, SHA))

    def test_the_job_keeps_its_own_container_and_settings(self):
        arm = FakeArm()
        trigger.start_release(push(), SETTINGS, arm)
        container = started_container(arm)
        template = JOB["properties"]["template"]["containers"][0]
        for key in ("name", "image", "args", "resources"):
            self.assertEqual(container[key], template[key])
        self.assertNotIn("probes", container)  # not part of a job execution's container
        self.assertEqual(container["env"][:2], template["env"])

    def test_an_earlier_image_or_commit_is_replaced_not_repeated(self):
        job = copy.deepcopy(JOB)
        job["properties"]["template"]["containers"][0]["env"] += [{"name": "IMAGE", "value": "elsewhere.example/x:1"},
                                                                  {"name": "COMMIT", "value": "0" * 40}]
        arm = FakeArm(job)
        trigger.start_release(push(), SETTINGS, arm)
        env = started_container(arm)["env"]
        names = [entry["name"] for entry in env]
        self.assertEqual(sorted(names), sorted(["AZURE_CONTAINER_REGISTRY_ENDPOINT", "RELEASE_STEP", "IMAGE", "COMMIT"]))
        self.assertEqual({e["name"]: e["value"] for e in env}["IMAGE"], f"{HOST}/requesthub-api@{DIGEST}")

    def test_topic_and_host_ignore_ascii_case_and_the_image_names_the_host_in_lowercase(self):
        arm = FakeArm()
        trigger.start_release(push(topic=REGISTRY_ID.upper(), host=HOST.upper()), SETTINGS, arm)
        self.assertEqual(started_container(arm)["env"][-2]["value"], f"{HOST}/requesthub-api@{DIGEST}")

    def test_an_azure_error_fails_the_invocation_so_event_grid_delivers_again(self):
        for method in ("GET", "POST"):
            with self.subTest(method=method), self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                trigger.start_release(push(), SETTINGS, FakeArm(fail_on=method))


class LoggedText(unittest.TestCase):
    """Logs use placeholders, never a host name, resource name, or GUID (CONTRIBUTING): the function logs the build and
    the execution's suffix, and an Azure error names only the call, the HTTP status, and Azure's error code."""

    IDENTIFIERS = (HOST, "crdesk", "caj-release-example", "rg-example", "/subscriptions/", "00000000-")

    def test_the_success_line_names_the_build_and_the_execution_suffix_only(self):
        line = trigger.start_release(push(), SETTINGS, FakeArm()).summary()
        self.assertEqual(line, f"execution x1 for build {SHA[:7]}, image {DIGEST[:19]}")
        for identifier in self.IDENTIFIERS + (release.REPOSITORY, SHA):
            self.assertNotIn(identifier, line)

    def test_an_unexpected_execution_name_logs_none_of_it(self):
        for name in ("caj-release-example", "caj-release-other-x1", "x1", "", "caj-release-example-X1/../y",
                     "caj-release-example-" + "a" * 40):
            with self.subTest(name=name):
                line = trigger.start_release(push(), SETTINGS, FakeArm(execution=name)).summary()
                self.assertTrue(line.startswith("execution ? for build "), line)
                for identifier in self.IDENTIFIERS + ("other", "X1"):
                    self.assertNotIn(identifier, line)

    def test_the_function_logs_only_the_summary(self):
        source = (FOLDER / "trigger/function_app.py").read_text(encoding="utf-8")
        self.assertIn("started.summary()", source)
        for raw in ("started.image", "started.execution", "started.digest", "started.commit"):
            self.assertNotIn(raw, source)


class RejectedEvents(unittest.TestCase):
    def rejected(self, event: dict) -> str:
        arm = FakeArm()
        with self.assertRaises(trigger.EventRejected) as caught:
            trigger.start_release(event, SETTINGS, arm)
        self.assertEqual(arm.calls, [], "a rejected event must not even read the job")
        return str(caught.exception)

    def test_each_check_rejects_by_name(self):
        cases = {
            "topic": [push(topic=REGISTRY_ID.replace("crdesk", "crother")), push(topic="")],
            "eventType": [push(eventType="Microsoft.ContainerRegistry.ImageDeleted"),
                          push(eventType="microsoft.containerregistry.imagepushed")],
            "host": [push(host="crother.azurecr.io"), push(host=HOST + ".example"), push(host=None)],
            "repository": [push(repository="requesthub-web"), push(repository="RequestHub-api"),
                           push(repository="requesthub-api "), push(repository="team/requesthub-api")],
            "digest": [push(digest=DIGEST.upper()), push(digest="sha256:" + "AB" * 32), push(digest=DIGEST[:-1]),
                       push(digest=DIGEST + "\n"), push(digest=DIGEST + "0"), push(digest="sha512:" + "ab" * 32),
                       push(digest=" " + DIGEST), push(digest=None)],
            "tag": [push(tag="main"), push(tag=""), push(tag=None), push(tag=SHA[:7]), push(tag=SHA.upper()),
                    push(tag=SHA + "0"), push(tag="g" * 40), push(tag=SHA + "\n"), push(tag=" " + SHA)],
        }
        for check, events in cases.items():
            for event in events:
                with self.subTest(check=check, event=event["data"]):
                    message = self.rejected(event)
                    self.assertIn(f"{check}: ", message)
                    self.assertTrue(message.startswith("No release was started: "))

    def test_every_failed_check_is_named(self):
        message = self.rejected(push(topic="/elsewhere", host="crother.azurecr.io", digest="latest", tag="main"))
        for check in ("topic: ", "host: ", "digest: ", "tag: "):
            self.assertIn(check, message)
        self.assertNotIn("repository: ", message)

    def test_a_look_alike_character_never_matches(self):
        kelvin = "\u212a"  # lowercases to k
        self.assertEqual(f"crdes{kelvin}.azurecr.io".lower(), HOST)
        self.assertIn("host: ", self.rejected(push(host=f"crdes{kelvin}.azurecr.io")))
        self.assertIn("topic: ", self.rejected(push(topic=REGISTRY_ID.replace("crdesk", f"crdes{kelvin}"))))

    def test_missing_or_malformed_fields_are_rejected_without_an_error(self):
        for event in ({}, {"data": "text"}, {"data": {"target": ["requesthub-api"]}}, {"topic": 5, "data": None},
                      push(repository=["requesthub-api"]), push(digest={"value": DIGEST})):
            with self.subTest(event=event):
                self.assertTrue(self.rejected(event))
        self.assertEqual(set(trigger.pushed_build("not an event").values()), {""})


class ForgedValues(unittest.TestCase):
    FORGED = ('x","name":"AZURE_CONTAINER_REGISTRY_ENDPOINT","value":"evil.example',
              '"},{"name":"IMAGE","value":"evil.example/x:1"}', 'x\nRELEASE-RECORD {"step": "release"}')

    def test_quotes_in_the_repository_are_rejected(self):
        for repository in ('requesthub-api","name":"AZURE_CONTAINER_REGISTRY_ENDPOINT', 'requesthub-api"}'):
            with self.subTest(repository=repository), self.assertRaisesRegex(trigger.EventRejected, "repository: "):
                trigger.start_release(push(repository=repository), SETTINGS, FakeArm())

    def test_a_forged_tag_is_rejected(self):
        for tag in self.FORGED:
            with self.subTest(tag=tag), self.assertRaisesRegex(trigger.EventRejected, "tag: "):
                trigger.start_release(push(tag=tag), SETTINGS, FakeArm())

    def test_values_stay_values_in_the_job_settings(self):
        # Behind the checks, the settings are built as objects: even a value that got through stays one value.
        for tag in self.FORGED:
            with self.subTest(tag=tag):
                env = json.loads(json.dumps(trigger.release_container(JOB, trigger.pushed_build(push(tag=tag)), SETTINGS)))["env"]
                names = [entry["name"] for entry in env]
                self.assertEqual(len(names), len(set(names)), "a value added a setting")
                values = {entry["name"]: entry["value"] for entry in env}
                self.assertEqual(values["COMMIT"], tag)
                self.assertEqual(values["IMAGE"], f"{HOST}/requesthub-api@{DIGEST}")
                self.assertEqual(values["AZURE_CONTAINER_REGISTRY_ENDPOINT"], HOST)


class RequiredSettings(unittest.TestCase):
    def test_every_setting_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "REGISTRY_ID, REGISTRY_HOST, RELEASE_REPOSITORY, RELEASE_JOB_ID"):
            trigger.Settings.from_environment({})
        values = dict(zip(trigger.SETTINGS, ("id", "host", "repo", "job")))
        self.assertEqual(trigger.Settings.from_environment(values), trigger.Settings("id", "host", "repo", "job"))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ManagedIdentity(unittest.TestCase):
    environ = {"IDENTITY_ENDPOINT": "http://localhost:8081/msi/token", "IDENTITY_HEADER": "header-value"}

    def opener(self, *responses):
        requests = []

        def open_(request, timeout):
            requests.append(request)
            response = responses[len(requests) - 1]
            if isinstance(response, Exception):
                raise response
            return FakeResponse(json.dumps(response).encode())
        return open_, requests

    def test_calls_sign_in_as_the_function_with_one_token(self):
        open_, requests = self.opener({"access_token": "t0ken"}, JOB, {"name": "x1"})
        arm = trigger.Arm(self.environ, open_)
        self.assertEqual(arm.call("read the release job", "GET", f"{JOB_ID}?api-version=2025-07-01"), JOB)
        self.assertEqual(arm.call("start the release job", "POST", f"{JOB_ID}/start?api-version=2025-07-01",
                                  {"containers": []}), {"name": "x1"})
        identity, read, start = requests
        self.assertTrue(identity.full_url.startswith(self.environ["IDENTITY_ENDPOINT"] + "?"))
        self.assertIn("resource=https%3A%2F%2Fmanagement.azure.com%2F", identity.full_url)
        self.assertEqual(identity.get_header("X-identity-header"), "header-value")
        for request in (read, start):
            self.assertTrue(request.full_url.startswith("https://management.azure.com/subscriptions/"))
            self.assertEqual(request.get_header("Authorization"), "Bearer t0ken")
        self.assertEqual(start.get_method(), "POST")
        self.assertEqual(json.loads(start.data), {"containers": []})

    def arm_error(self, status: int, body: bytes, what: str = "start the release job") -> str:
        error = urllib.error.HTTPError("https://management.azure.com/x", status, "Error", {}, io.BytesIO(body))
        open_, _ = self.opener({"access_token": "t0ken"}, error)
        with self.assertRaises(RuntimeError) as caught:
            trigger.Arm(self.environ, open_).call(what, "POST", f"{JOB_ID}/start?api-version=2025-07-01", {})
        return str(caught.exception)

    def test_an_azure_error_names_the_call_its_status_and_code_only(self):
        # Azure's messages name the subscription, the resource group, and the resource: none of it is logged.
        body = json.dumps({"error": {"code": "AuthorizationFailed", "message": (
            "The client 'release-trigger' with object id '11111111-2222-3333-4444-555555555555' does not have "
            "authorization to perform action 'Microsoft.App/jobs/start/action' over scope "
            f"'{JOB_ID}' or the scope is invalid. Registry {HOST}.")}}).encode()
        message = self.arm_error(403, body)
        self.assertEqual(message, "Could not start the release job: HTTP 403 AuthorizationFailed")
        for identifier in ("caj-release-example", "rg-example", "/subscriptions/", "00000000-", "11111111-", HOST, "t0ken"):
            self.assertNotIn(identifier, message)

    def test_an_unexpected_error_code_or_body_leaves_only_the_status(self):
        for body in (json.dumps({"error": {"code": f"Denied at {JOB_ID}"}}).encode(), b"<html>Bad gateway</html>", b""):
            with self.subTest(body=body[:40]):
                self.assertEqual(self.arm_error(502, body, "read the release job"), "Could not read the release job: HTTP 502")

    def test_no_managed_identity_no_call(self):
        open_, requests = self.opener()
        with self.assertRaisesRegex(RuntimeError, "no managed identity"):
            trigger.Arm({}, open_).call("read the release job", "GET", JOB_ID)
        self.assertEqual(requests, [])


class Wiring(unittest.TestCase):
    """The function, Event Grid's subscription, and the settings agree; read from the files, as azd deploys them."""

    def read(self, name: str) -> str:
        return (FOLDER / name).read_text(encoding="utf-8")

    def test_the_function_only_adapts_the_event(self):
        source = self.read("trigger/function_app.py")
        self.assertIn("@app.event_grid_trigger(", source)
        self.assertIn("def release_on_push(event: func.EventGridEvent)", source)
        self.assertIn("release_trigger.start_release(", source)
        for logic in ("urllib", "management.azure.com", "api-version", release.REPOSITORY):
            self.assertNotIn(logic, source)

    def test_event_grid_calls_the_function_by_name_one_event_at_a_time(self):
        import preflight
        subscription = self.read("infra/release-on-push.bicep")
        self.assertIn("endpointType: 'AzureFunction'", subscription)
        self.assertIn(f"resourceId: '${{trigger.id}}/functions/{preflight.TRIGGER_FUNCTION}'", subscription)
        self.assertIn(f"def {preflight.TRIGGER_FUNCTION}(event: func.EventGridEvent)", self.read("trigger/function_app.py"))
        self.assertIn("maxEventsPerBatch: 1", subscription)
        self.assertIn("includedEventTypes: ['Microsoft.ContainerRegistry.ImagePushed']", subscription)

    def test_the_repository_is_set_in_one_place(self):
        bicep = self.read("infra/release.bicep")
        self.assertIn(f"var repository = '{release.REPOSITORY}'", bicep)
        self.assertEqual(bicep.count(f"'{release.REPOSITORY}'"), 1)
        self.assertIn("{ name: 'RELEASE_REPOSITORY', value: repository }", bicep)
        self.assertIn("output repository string = repository", bicep)
        self.assertIn("output RELEASE_REPOSITORY string = release.outputs.repository", self.read("infra/main.bicep"))
        azure_yaml = self.read("azure.yaml")
        self.assertIn("repository=$env:RELEASE_REPOSITORY", azure_yaml)
        self.assertIn('repository="$RELEASE_REPOSITORY"', azure_yaml)
        subscription = self.read("infra/release-on-push.bicep")
        self.assertIn("subjectBeginsWith: '${repository}:'", subscription)
        self.assertNotIn(release.REPOSITORY, subscription + self.read("trigger/release_trigger.py"))

    def test_the_trigger_settings_are_the_ones_bicep_sets(self):
        bicep = self.read("infra/release.bicep")
        for name in trigger.SETTINGS:
            self.assertIn(f"{{ name: '{name}', value: ", bicep)

    def test_azd_tests_before_every_deploy_and_connects_event_grid_after_every_service(self):
        services, separator, hooks = self.read("azure.yaml").partition("\nhooks:\n")
        self.assertTrue(separator, "the project's own hooks, which run once for the whole deploy")
        self.assertNotIn("hooks:", services, "a service's hook can run while other services are still deploying")
        predeploy, _, postdeploy = hooks.partition("\n  postdeploy:\n")
        self.assertIn("\n  predeploy:\n", "\n" + predeploy)
        self.assertIn("run: python -m unittest", predeploy)
        self.assertIn("run: python3 -m unittest", predeploy)
        for shell in ("pwsh", "sh"):
            self.assertIn(f"shell: {shell}", postdeploy)
        self.assertEqual(postdeploy.count("--template-file infra/release-on-push.bicep"), 2)
        self.assertEqual(postdeploy.count("--function-name release_on_push"), 2, "connect only once the function exists")
        self.assertEqual(postdeploy.count("-ne 3"), 2, "wait only while Azure says not found (exit code 3)")
        self.assertGreaterEqual(postdeploy.count("exit 1"), 2, "anything else stops the deploy, visibly")
        for name in ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "RELEASE_TRIGGER_NAME", "RELEASE_TOPIC_NAME", "RELEASE_REPOSITORY"):
            self.assertIn(f"'{name}'", postdeploy, "the PowerShell hook checks every setting it needs first")
            self.assertIn(f'"${{{name}:?', postdeploy, "the POSIX hook checks every setting it needs first")


class TriggerCheck(unittest.TestCase):
    """preflight.py, check Trigger: the function is deployed and running; it alone may start the release job, with
    Container Apps Jobs Operator on that job only, so a Logic App left from the earlier trigger, or any other role
    assignment of Jobs Operator on the job or its resource group, fails, even when the function app is missing; and
    Event Grid's topic watches this registry and its subscription sends the function each push of the API's repository
    except :main, one event per call. Any other subscription fails."""

    RG_ID = "/subscriptions/0/resourceGroups/rg"
    APP_ID = RG_ID + "/providers/Microsoft.Web/sites/func-release-x"
    JOB_ID = RG_ID + "/providers/Microsoft.App/jobs/caj-release-x"
    REGISTRY_ID = RG_ID + "/providers/Microsoft.ContainerRegistry/registries/crx"
    FUNCTION = "principal-of-the-function"

    def setUp(self) -> None:
        self.state, self.deployed, self.workflows, self.app_missing = "Running", True, [], False
        self.assignments = [self.operator(self.FUNCTION, self.JOB_ID)]
        self.topic: dict | None = {"name": "evgt-x", "topicType": "Microsoft.ContainerRegistry.Registries",
                                   "source": self.REGISTRY_ID.lower()}
        self.subscription: dict | None = {
            "provisioningState": "Succeeded",
            "destination": {"endpointType": "AzureFunction", "maxEventsPerBatch": 1,
                            "resourceId": f"{self.APP_ID.lower()}/functions/release_on_push"},
            "filter": {"includedEventTypes": ["Microsoft.ContainerRegistry.ImagePushed"],
                       "subjectBeginsWith": "requesthub-api:", "isSubjectCaseSensitive": None,
                       "advancedFilters": [{"key": "data.target.tag", "operatorType": "StringNotIn", "values": ["main"]}]}}

    @staticmethod
    def operator(principal: str, scope: str, role: str = "Container Apps Jobs Operator") -> dict:
        return {"id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/{principal}-{role[:4]}",
                "principalId": principal, "roleDefinitionName": role, "scope": scope}

    def check(self) -> list[tuple[str, str]]:
        return [(level, message) for level, message, _ in self.check_with_fixes()]

    def check_with_fixes(self) -> list[tuple[str, str, str]]:
        import preflight

        def fake_az(*args):
            if args[:2] == ("resource", "show"):
                if self.app_missing:
                    raise RuntimeError("(ResourceNotFound) The Resource 'Microsoft.Web/sites/func-release-x' was not found.")
                return {"id": self.APP_ID, "name": "func-release-x", "properties": {"state": self.state},
                        "identity": {"principalId": self.FUNCTION}}
            if args[0] == "rest":
                if not self.deployed:
                    raise RuntimeError("(NotFound) Error retrieving function.")
                return {"name": "func-release-x/release_on_push"}
            if args[:2] == ("resource", "list"):
                self.assertIn("Microsoft.Logic/workflows", args)
                return self.workflows
            if args[:3] == ("role", "assignment", "list"):
                self.assertEqual(args[args.index("--scope") + 1], self.JOB_ID)
                self.assertIn("--include-inherited", args)
                return self.assignments
            if args[:3] == ("eventgrid", "system-topic", "show"):
                self.assertEqual(args[args.index("--name") + 1], "evgt-x")
                if self.topic is None:
                    raise RuntimeError("(ResourceNotFound)")
                return self.topic
            if args[:4] == ("eventgrid", "system-topic", "event-subscription", "show"):
                if self.subscription is None:
                    raise RuntimeError("(ResourceNotFound) Event subscription doesn't exist.")
                return self.subscription
            raise AssertionError(f"unexpected az call: {args}")

        reports: list[tuple[str, str, str]] = []
        settings = {"rg": "rg", "trigger": "func-release-x", "registry": "crx", "topic": "evgt-x",
                    "repository": release.REPOSITORY}
        with mock.patch.object(preflight, "az", side_effect=fake_az), \
                mock.patch.object(preflight, "report",
                                  side_effect=lambda level, area, message, fix="": reports.append((level, message, fix))):
            preflight.check_trigger(settings, {"release": {"id": self.JOB_ID}})
        return reports

    def failures(self) -> list[str]:
        return [message for level, message in self.check() if level != "PASS"]

    def test_passes_when_only_the_function_may_start_the_job_and_event_grid_calls_it(self):
        reports = self.check()
        self.assertEqual([level for level, _ in reports], ["PASS"] * 4, reports)

    def test_fails_when_the_function_is_not_deployed_or_stopped(self):
        self.deployed = False
        self.assertEqual(self.check()[0], ("FAIL", "function release_on_push is not deployed"))
        self.deployed, self.state = True, "Stopped"
        self.assertEqual(self.check()[0], ("FAIL", "function release_on_push deployed, app stopped"))

    def test_fails_while_a_logic_app_from_the_earlier_trigger_is_left(self):
        self.workflows = [{"name": "logic-release-x", "id": self.RG_ID + "/providers/Microsoft.Logic/workflows/logic-release-x"},
                          {"name": "logic-other", "id": self.RG_ID + "/providers/Microsoft.Logic/workflows/logic-other"}]
        self.assertEqual(self.failures(), ["Logic App logic-release-x, the earlier trigger, still exists"])

    def test_fails_when_another_role_assignment_may_start_the_release_job(self):
        for scope in (self.JOB_ID, self.RG_ID, self.JOB_ID.upper()):
            with self.subTest(scope=scope):
                other = self.operator("principal-of-a-logic-app", scope)
                self.assignments = [self.operator(self.FUNCTION, self.JOB_ID), other]
                failures = [(message, fix) for level, message, fix in self.check_with_fixes() if level != "PASS"]
                self.assertEqual([message for message, _ in failures],
                                 ["1 other role assignment may start the release job too (Container Apps Jobs Operator)"])
                self.assertTrue(failures[0][1].endswith(f"az role assignment delete --ids {other['id']}"), failures[0][1])

    def test_the_function_may_start_the_release_job_only(self):
        # Jobs Operator on the resource group would let it start promote, abort, rollback, and drill too.
        broad = self.operator(self.FUNCTION, self.RG_ID)
        self.assignments = [broad]
        self.assertEqual(self.failures(), ["the function may not start the release job (Container Apps Jobs Operator on it)",
                                           "1 other role assignment may start the release job too (Container Apps Jobs Operator)"])
        self.assignments = [self.operator(self.FUNCTION, self.JOB_ID), broad]
        self.assertEqual(self.failures(), ["1 other role assignment may start the release job too (Container Apps Jobs Operator)"])

    def test_principal_ids_are_compared_ignoring_case(self):
        self.assignments = [self.operator(self.FUNCTION.upper(), self.JOB_ID.lower())]
        self.assertEqual(self.failures(), [])

    def test_a_missing_function_app_still_checks_what_else_may_start_releases(self):
        self.app_missing = True
        self.workflows = [{"name": "logic-release-x", "id": self.RG_ID + "/providers/Microsoft.Logic/workflows/logic-release-x"}]
        self.assignments = [self.operator("principal-of-a-logic-app", self.JOB_ID)]
        failures = self.failures()
        self.assertTrue(failures[0].startswith("function app func-release-x not found"), failures)
        self.assertEqual(failures[1:], [
            "Logic App logic-release-x, the earlier trigger, still exists",
            "the function may not start the release job (Container Apps Jobs Operator on it)",
            "1 other role assignment may start the release job too (Container Apps Jobs Operator)",
            "Event Grid's subscription release-on-push sends events elsewhere (AzureFunction)"])

    def test_other_roles_and_grants_outside_the_resource_group_are_not_this_checks_business(self):
        self.assignments = [self.operator(self.FUNCTION, self.JOB_ID), self.operator("someone", "/subscriptions/0"),
                            self.operator("release-identity", self.RG_ID, role="Container Apps Contributor")]
        self.assertEqual(self.failures(), [])

    def test_fails_when_the_function_may_not_start_the_job(self):
        self.assignments = [self.operator(self.FUNCTION, self.JOB_ID, role="Reader")]
        self.assertEqual(self.failures(), ["the function may not start the release job (Container Apps Jobs Operator on it)"])

    def test_fails_when_the_topic_is_missing_or_watches_another_registry(self):
        self.topic["source"] = self.REGISTRY_ID.replace("crx", "crx2")
        self.assertEqual(self.failures(), ["Event Grid topic evgt-x does not watch registry crx"])
        self.topic = None
        self.assertEqual(len(self.failures()), 1)
        self.assertTrue(self.failures()[0].startswith("Event Grid topic evgt-x not found"))

    def test_fails_on_any_difference_in_the_subscription(self):
        changes = {
            "no subscription": lambda s: None,
            "not provisioned": lambda s: s.update(provisioningState="Failed"),
            "a webhook, such as the earlier Logic App": lambda s: s.update(
                destination={"endpointType": "WebHook", "endpointBaseUrl": "https://example.invalid/triggers/manual"}),
            "another function": lambda s: s["destination"].update(resourceId=f"{self.APP_ID}/functions/another"),
            "batches": lambda s: s["destination"].update(maxEventsPerBatch=10),
            "other events": lambda s: s["filter"].update(includedEventTypes=[trigger.IMAGE_PUSHED, "Microsoft.ContainerRegistry.ImageDeleted"]),
            "every event": lambda s: s["filter"].update(includedEventTypes=None),
            "other repositories": lambda s: s["filter"].update(subjectBeginsWith=""),
            "another repository": lambda s: s["filter"].update(subjectBeginsWith="requesthub-web:"),
            "main too": lambda s: s["filter"].update(advancedFilters=[]),
            "main too, another filter": lambda s: s["filter"].update(advancedFilters=[
                {"key": "data.target.tag", "operatorType": "StringNotIn", "values": ["latest"]}]),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.setUp()
                if name == "no subscription":
                    self.subscription = None
                else:
                    change(self.subscription)
                failures = self.failures()
                self.assertEqual(len(failures), 1, failures)
                self.assertTrue(failures[0].startswith(("Event Grid's subscription release-on-push", "Event Grid has no subscription")), failures)


if __name__ == "__main__":
    unittest.main()
