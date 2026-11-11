"""Offline tests for the incident record rules in configure_sre_agent.py.

A person files the record that Azure SRE Agent drafts: as this solution's record, or as an incident through a team's
incident form, such as 07-operate-github's, whose triage then starts. The tests check that the record template states
every fact such a form asks for, so the person adds none; that its labels never start another team's automation; that
the environment's name renders; and that a record in this layout passes the guard hook while a revision name in it is
blocked.

They need no Azure access. Run from this folder:
  python -m unittest -q test_configure_sre_agent
"""
from __future__ import annotations

import json
import unittest
from dataclasses import replace

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


if __name__ == "__main__":
    unittest.main()
