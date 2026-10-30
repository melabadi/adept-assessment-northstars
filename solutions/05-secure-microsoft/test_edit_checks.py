"""Tests for the checks posture-intake applies to the remediation agent's proposal, run offline.

remediation_agent.edit_problems mirrors the Logic App's Edit_problems (infra/logic/intake.json): both apply one exact
replacement to infra/resources.bicep, then require everything outside the posture:editable markers to stay byte-identical
and every line between them (split at LF and CR, as Bicep's lexer does) to be a // comment or exactly
storagePrivateEndpoint: true or false. These cases include edits that a check on the agent's texts alone would let
through.

  python -m unittest test_edit_checks.py      (from this folder; no Azure access needed)
"""
from __future__ import annotations

import unittest
from pathlib import Path

import remediation_agent as ra

CONTENT = (Path(__file__).resolve().parent / "infra" / "resources.bicep").read_text(encoding="utf-8")
SETTING = "storagePrivateEndpoint: false"
INSIDE = CONTENT[CONTENT.index("    // Without a private endpoint"):CONTENT.index(SETTING) + len(SETTING)]
BEGIN_LINE = CONTENT[CONTENT.index("    // posture:editable-begin"):CONTENT.index("\n", CONTENT.index("// posture:editable-begin")) + 1]
GOOD = "    // Reach Blob storage through a private endpoint in the app's virtual network.\n    storagePrivateEndpoint: true"


def problems(find: str, replace: str) -> list[str]:
    return ra.edit_problems(CONTENT, {"decision": "change", "path": ra.EDITABLE, "find": find, "replace": replace})


class Accepted(unittest.TestCase):
    def test_the_fix(self):
        self.assertEqual(problems(INSIDE, GOOD), [])

    def test_marker_lines_reproduced_verbatim(self):
        end = CONTENT.index("// posture:editable-end") + len("// posture:editable-end")
        find = CONTENT[CONTENT.index(BEGIN_LINE):end]
        self.assertEqual(problems(find, BEGIN_LINE + GOOD + "\n    // posture:editable-end"), [])


class Rejected(unittest.TestCase):
    def assertRejected(self, find: str, replace: str, reason: str):
        found = problems(find, replace)
        self.assertTrue(any(reason in p for p in found), f"expected '{reason}' in {found}")

    def test_federated_credential_parameters_inside_the_region(self):
        self.assertRejected("    " + SETTING, "    storagePrivateEndpoint: true\n    githubRepository: 'someone/elsewhere'\n"
                            "    githubEnvironment: 'any'", "neither a // comment")

    def test_name_completed_by_text_outside_the_search(self):
        self.assertRejected("PrivateEndpoint: false", "AllowSharedKeyAccess: true\n    storagePrivateEndpoint: true",
                            "neither a // comment")

    def test_closing_the_module_to_declare_a_resource(self):
        self.assertRejected("    " + SETTING, "    storagePrivateEndpoint: true\n  }\n}\n"
                            "resource s 'Microsoft.Resources/deploymentScripts@2023-08-01' = {\n  name: 's'\n"
                            "  location: location\n  kind: 'AzureCLI'\n  properties: {}\n}\nmodule n 'resources.bicep' = {\n"
                            "  name: 'n'\n  params: {", "neither a // comment")

    def test_unicode_escape_in_a_quoted_name(self):
        self.assertRejected("    " + SETTING, "    storagePrivateEndpoint: true\n    'storage\\u{41}llowSharedKeyAccess': true",
                            "neither a // comment")

    def test_bare_carriage_return_ends_the_comment(self):
        replace = ("    // Reach Blob storage through a private endpoint.\r    githubRepository: 'someone/elsewhere'\r"
                   "    githubEnvironment: 'any'\n    storagePrivateEndpoint: true")
        self.assertRejected(INSIDE, replace, "carriage return")
        self.assertRejected(INSIDE, replace, "neither a // comment")

    def test_search_starting_inside_the_begin_marker_line(self):
        rest_of_marker_line = BEGIN_LINE.strip()[len("// posture:editable-begin"):]
        self.assertRejected(rest_of_marker_line, " Edited.\n    storagePrivateEndpoint: true //", "outside the lines")

    def test_policy_effect_outside_the_region(self):
        self.assertRejected("value: 'AuditIfNotExists'", "value: 'Disabled'", "outside the lines")

    def test_case_only_change_outside_the_region(self):
        self.assertRejected("    tags: tags\n" + BEGIN_LINE + INSIDE, "    tags: TAGS\n" + BEGIN_LINE + GOOD, "outside the lines")

    def test_rewritten_marker_line(self):
        self.assertRejected(BEGIN_LINE + INSIDE, "    // posture:editable-begin. Anything goes now.\n" + GOOD, "outside the lines")

    def test_role_named_inside_the_region(self):
        self.assertRejected("    " + SETTING, "    storagePrivateEndpoint: true\n    automationRoleDefinitionIds: []",
                            "protected setting")

    def test_trailing_comment_on_the_setting(self):
        self.assertRejected(INSIDE, GOOD + " // fixed", "neither a // comment")

    def test_setting_removed(self):
        self.assertRejected(INSIDE, "    // No setting: the module default applies.", "exactly once")

    def test_empty_replacement(self):
        self.assertRejected(INSIDE, "   ", "replacement is empty")

    def test_text_too_long(self):
        self.assertRejected(INSIDE, GOOD + "\n    // " + "x" * 2100, "longer than 2,000")

    def test_search_text_not_unique(self):
        self.assertRejected(": false", ": true", "exactly once in the file")

    def test_other_file(self):
        found = ra.edit_problems(CONTENT, {"decision": "change", "path": "app/infra/requesthub.bicep", "find": INSIDE,
                                           "replace": GOOD})
        self.assertTrue(any("other than" in p for p in found), found)


if __name__ == "__main__":
    unittest.main()
