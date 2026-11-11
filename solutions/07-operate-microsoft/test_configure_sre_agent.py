"""Offline tests for configure_sre_agent.py: the incident record rules, the tool policy's Azure DevOps denials, and the
retries of the agent's API.

A person files the record that Azure SRE Agent drafts: as this solution's record, or as an incident through a team's
incident form, such as 07-operate-github's, whose triage then starts. The tests check that the record template states
every fact such a form asks for, so the person adds none; that its labels never start another team's automation; that
the environment's name renders; and that a record in this layout passes the guard hook while a revision name in it is
blocked. They also check that the policy denies the tools that run Azure DevOps pipelines or connect repositories, and
the Azure DevOps MCP server's tools; and that a dropped connection or a timeout is retried for a request that is safe to
repeat, and only for one.

They need no Azure access. Run from this folder:
  python -m unittest -q test_configure_sre_agent
"""
from __future__ import annotations

import http.client
import json
import unittest
from dataclasses import replace
from unittest import mock

import configure_sre_agent as cfg

RECORD = """## Summary
Requesters and reviewers received notifications up to 15 minutes late.

## Impact
| Measure | Value |
| --- | --- |
| Alert fired (UTC) | 2026-10-29 14:05:12 |

## Timeline (UTC)
| Time | Event | Evidence |
| --- | --- | --- |
| 13:58:40 | The worker was updated. | Activity Log entry |

## Recent changes
At 13:58:40 UTC a configuration change created the new worker revision with `Faults__WorkerDelayMs=10000`.

## Status
| Field | Value |
| --- | --- |
| Status | Resolved |
| Environment | `ai-sdlc-operate` (Azure) |
| Detected at (UTC) | 2026-10-29T14:05Z |
"""


class RecordTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = cfg.load()
        cls.record = next(s for s in cls.config.skills if s.name == cfg.RECORD_SKILL)

    def test_the_record_states_every_fact_an_incident_form_asks_for(self):
        self.assertEqual(cfg.record_problems(self.record), [])

    def test_a_record_without_one_of_those_facts_is_rejected(self):
        for fact, marker in cfg.RECORD_FIELDS.items():
            with self.subTest(fact=fact):
                problems = cfg.record_problems(replace(self.record, content=self.record.content.replace(marker, "")))
                self.assertEqual(len(problems), 1)
                self.assertIn(fact, problems[0])

    def test_the_record_never_gets_the_label_that_starts_the_triage(self):
        for labels in ("ai-sdlc, phase:operate, incident", "ai-sdlc, incident-followup", "ai-sdlc"):
            with self.subTest(labels=labels):
                content = self.record.content.replace("`Labels: ai-sdlc, phase:operate`", f"`Labels: {labels}`")
                self.assertTrue(any("labels" in p for p in cfg.record_problems(replace(self.record, content=content))))

    def test_without_the_record_skill_nothing_drafts_the_record(self):
        self.assertEqual(len(cfg.record_problems(None)), 1)

    def test_the_check_runs_the_record_rules(self):
        skills = [replace(s, content=s.content.replace("## Recent changes", "")) if s.name == cfg.RECORD_SKILL else s
                  for s in self.config.skills]
        problems = cfg.check(replace(self.config, skills=skills))
        self.assertTrue(any("recent changes" in p for p in problems), problems)

    def test_the_environment_name_renders(self):
        rendered = cfg.render(self.record.content, {"AZURE_ENV_NAME": "ai-sdlc-operate",
                                                    "GITHUB_REPOSITORY": "contoso/requesthub"})
        self.assertIn("| Environment | `ai-sdlc-operate` (Azure) |", rendered)
        self.assertNotIn("{{", rendered)


class RecordGuardTests(unittest.TestCase):
    """The guard hook defines what counts as an identifier. A record in the new layout must pass it, and the form's
    "Recent changes" field, which asks for revisions, must not let a revision name through."""

    @classmethod
    def setUpClass(cls):
        config = cfg.load()
        deny = list(config.github["deny"])
        cls.script = (config.guard_script.replace("{{RESOURCE_SUFFIXES}}", "z9y8x7w6v5u4t")
                      .replace("{{GITHUB_DENIED_TOOLS}}", cfg.glob_regex(deny)))
        cls.tool = next(t for t in cfg.GITHUB_ISSUE_SAMPLES if not cfg.matches(t, deny))

    def verdict(self, body: str) -> str:
        call = {"hook_event_name": "PreToolUse", "tool_name": self.tool,
                "tool_input": {"title": "Incident record: notification backlog, 2026-10-29", "body": body}}
        return cfg.run_guard(self.script, json.dumps(call))[0]

    def test_a_record_written_with_placeholders_waits_for_a_person(self):
        self.assertEqual(self.verdict(RECORD), "ask")

    def test_a_revision_name_in_the_recent_changes_is_blocked(self):
        leak = RECORD.replace("the new worker revision", "revision ca-worker-z9y8x7w6v5u4t--0000015")
        self.assertEqual(self.verdict(leak), "block")


class DevOpsPolicyTests(unittest.TestCase):
    """The tools that run Azure DevOps pipelines or connect repositories are disabled in the agent, but their default
    permission is allow: enabled in the portal, they would run without asking. The policy must deny them."""

    @classmethod
    def setUpClass(cls):
        cls.config = cfg.load()

    def problems(self, deny: list[str]) -> list[str]:
        with mock.patch.object(cfg, "guard_problems", return_value=[]):  # the guard hook has tests of its own
            return cfg.check(replace(self.config, policy={**self.config.policy, "deny": deny}))

    def test_the_policy_denies_them(self):
        self.assertEqual(self.problems(list(self.config.policy["deny"])), [])

    def test_the_check_fails_when_one_is_not_denied(self):
        for tool in cfg.DEVOPS_TOOLS:
            with self.subTest(tool=tool):
                problems = self.problems([d for d in self.config.policy["deny"] if d != tool])
                self.assertTrue(any(f"must deny {tool}:" in p for p in problems), problems)

    def test_the_check_fails_when_the_mcp_servers_tools_are_not_denied(self):
        problems = self.problems([d for d in self.config.policy["deny"] if d != "*DevOps*_*"])
        self.assertTrue(any("Azure DevOps MCP server's tools" in p for p in problems), problems)
        # A pattern for one connection name isn't enough: the server's connection has no id until someone connects it.
        problems = self.problems([d for d in self.config.policy["deny"] if d != "*DevOps*_*"] + ["AzureDevOps_*"])
        self.assertTrue(any("system-mcp-azuredevops_pipelines_run" in p for p in problems), problems)


class Answer:
    """What urllib.request.urlopen returns: a response with a status, headers, and a JSON body."""

    def __init__(self, status: int, body: object):
        self.status, self.headers, self.body = status, {"Content-Type": "application/json"}, json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


class RetryTests(unittest.TestCase):
    """At 14:11:42 UTC on 11 November 2026, the agent's endpoint closed the connection on GET /api/v2/repos without an
    answer, and the run stopped before it wrote anything. A dropped connection or a timeout is retried as a 5xx is, for
    a request that is safe to repeat."""

    def setUp(self):
        self.client = cfg.Client.__new__(cfg.Client)  # a cached token instead of the Azure CLI sign-in
        self.client.tokens = {cfg.DATA_PLANE_SCOPE: ("token", cfg.time.time() + 3600)}
        sleep = mock.patch.object(cfg.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        quiet = mock.patch.object(cfg, "print", create=True)  # the "retrying in 20s" lines
        quiet.start()
        self.addCleanup(quiet.stop)

    def answers(self, *answers) -> mock.Mock:
        urlopen = mock.patch.object(cfg.urllib.request, "urlopen", side_effect=list(answers))
        self.addCleanup(urlopen.stop)
        return urlopen.start()

    def test_the_run_of_14_11_42_continues(self):
        repository = {"properties": {"url": "https://github.com/contoso/requesthub", "cloneStatus": "Ready",
                                     "connection": {"isHealthy": True}}}
        urlopen = self.answers(http.client.RemoteDisconnected("Remote end closed connection without response"),
                               Answer(200, {"value": [repository]}))
        connected, detail = cfg.github_connection(self.client, "https://agent.example", "contoso/requesthub")
        self.assertTrue(connected, detail)
        self.assertEqual(urlopen.call_count, 2)

    def test_a_timeout_is_retried(self):
        urlopen = self.answers(TimeoutError("timed out"), Answer(200, {}))
        status, _, _ = self.client.call("PUT", "https://agent.example/skill", cfg.DATA_PLANE_SCOPE, {}, attempts=3)
        self.assertEqual((status, urlopen.call_count), (200, 2))

    def test_a_request_that_is_not_safe_to_repeat_is_sent_once(self):
        urlopen = self.answers(http.client.RemoteDisconnected("Remote end closed connection without response"))
        with self.assertRaises(http.client.RemoteDisconnected):
            self.client.call("DELETE", "https://agent.example/skill", cfg.DATA_PLANE_SCOPE)
        self.assertEqual(urlopen.call_count, 1)
        self.sleep.assert_not_called()

    def test_it_stops_after_the_last_attempt(self):
        urlopen = self.answers(*[TimeoutError("timed out")] * 3)
        with self.assertRaises(TimeoutError):
            self.client.call("GET", "https://agent.example/skills", cfg.DATA_PLANE_SCOPE, attempts=3)
        self.assertEqual(urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
