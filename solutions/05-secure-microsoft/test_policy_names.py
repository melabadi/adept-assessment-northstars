"""Tests that what the automation posts names only this solution's policy assignments, run offline.

The Issue (posture-intake), the agent's input (and so its pull request), and the evidence comment (posture-verify) list
every policy assignment that evaluates the storage account. An assignment inherited from a management group or the
subscription belongs to the tenant's governance: its name must not reach GitHub, so it appears only as the kind of scope
it comes from. remediation_agent.assignment_label applies the rule in Python; these tests also pin the Logic Apps'
expressions to the same rule, with the name only in the branch for this resource group.

  python -m unittest test_policy_names.py      (from this folder; no Azure or GitHub access needed)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from remediation_agent import assignment_label

LOGIC = Path(__file__).resolve().parent / "infra" / "logic"
RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ai-sdlc-secure"
SCOPE = "toLower(coalesce(item()?['policyAssignmentScope'], ''))"
IN_THIS_RESOURCE_GROUP = f"startsWith(concat({SCOPE}, '/'), concat(toLower(parameters('resourceGroupId')), '/'))"
NAME_OR_SCOPE = (f"if({IN_THIS_RESOURCE_GROUP}, item()?['policyAssignmentName'], if(contains({SCOPE}, '/managementgroups/'), "
                 "'management group assignment', 'subscription assignment'))")


def label(scope: str | None, name: str = "some-assignment") -> str:
    return assignment_label({"policyAssignmentName": name, "policyAssignmentScope": scope}, RG)


def find_action(actions: dict, name: str) -> dict | None:
    for key, action in actions.items():
        if key == name:
            return action
        for nested in (action.get("actions"), (action.get("else") or {}).get("actions"),
                       *[(c or {}).get("actions") for c in (action.get("cases") or {}).values()]):
            if isinstance(nested, dict) and (found := find_action(nested, name)) is not None:
                return found
    return None


class Python(unittest.TestCase):
    def test_this_resource_group_is_named(self):
        self.assertEqual(label(RG, "requesthub-storage-private-link"), "requesthub-storage-private-link")

    def test_scope_case_does_not_matter(self):
        self.assertEqual(label(RG.upper().replace("RESOURCEGROUPS", "resourcegroups"), "mine"), "mine")

    def test_assignment_on_a_resource_in_this_resource_group_is_named(self):
        self.assertEqual(label(RG + "/providers/Microsoft.Storage/storageAccounts/st1", "mine"), "mine")

    def test_resource_group_sharing_the_prefix_is_not_this_one(self):
        self.assertEqual(label(RG + "2", "theirs"), "subscription assignment")

    def test_management_group_assignment_is_not_named(self):
        scope = "/providers/Microsoft.Management/managementGroups/contoso-root"
        self.assertEqual(label(scope, "Org_Baseline"), "management group assignment")

    def test_subscription_assignment_is_not_named(self):
        self.assertEqual(label("/subscriptions/00000000-0000-0000-0000-000000000000", "Sub_Baseline"),
                         "subscription assignment")

    def test_missing_scope_is_not_named(self):
        self.assertEqual(label(None, "Unknown"), "subscription assignment")


class LogicApps(unittest.TestCase):
    def expression(self, workflow: str, action: str, field: str | None = None) -> str:
        template = json.loads((LOGIC / workflow).read_text(encoding="utf-8"))
        definition = template["resources"][0]["properties"]["definition"]
        select = find_action(definition["actions"], action)["inputs"]["select"]
        return select[field] if field else select

    def assertNamesOnlyThisResourceGroup(self, expression: str):
        self.assertIn(NAME_OR_SCOPE, expression)
        self.assertEqual(expression.count("policyAssignmentName"), 1, "the name appears outside the resource group check")

    def test_issue_rows(self):
        rows = self.expression("intake.json", "Policy_rows")
        self.assertNamesOnlyThisResourceGroup(rows)
        self.assertIn(f"if({IN_THIS_RESOURCE_GROUP}, 'this resource group', 'inherited')", rows)

    def test_agent_input(self):
        self.assertNamesOnlyThisResourceGroup(self.expression("intake.json", "Policy_summary", "assignment"))

    def test_evidence_rows_match_the_issue(self):
        self.assertEqual(self.expression("verify.json", "Policy_rows"), self.expression("intake.json", "Policy_rows"))


if __name__ == "__main__":
    unittest.main()
