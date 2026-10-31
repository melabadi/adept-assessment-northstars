"""Tests that what the automation posts names only this solution's policy assignments, run offline.

The Issue and the agent's input (and so its pull request), filed by the Function intake, and the evidence comment of the
Function verify list every policy assignment that evaluates the storage account. An assignment inherited from a
management group or the subscription belongs to the tenant's governance: its name must not reach GitHub, so it appears
only as the kind of scope it comes from. function/posture/checks.py (assignment_label) applies the rule, and
function/posture/messages.py builds every row and summary from it.

  python -m unittest test_policy_names.py      (from this folder; no Azure or GitHub access needed)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "function"))

from posture import messages  # noqa: E402
from posture.checks import assignment_label  # noqa: E402

RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ai-sdlc-secure"
MANAGEMENT_GROUP = "/providers/Microsoft.Management/managementGroups/contoso-root"
SUBSCRIPTION = "/subscriptions/00000000-0000-0000-0000-000000000000"


def label(scope: str | None, name: str = "some-assignment") -> str:
    return assignment_label({"policyAssignmentName": name, "policyAssignmentScope": scope}, RG)


def state(name: str, scope: str, compliance: str = "NonCompliant") -> dict:
    return {"policyAssignmentName": name, "policyAssignmentScope": scope, "complianceState": compliance,
            "timestamp": "2026-10-30T19:12:00Z"}


STATES = [state("Org_Baseline", MANAGEMENT_GROUP), state("Sub_Baseline", SUBSCRIPTION),
          state("requesthub-storage-private-link", RG)]


class Rule(unittest.TestCase):
    def test_this_resource_group_is_named(self):
        self.assertEqual(label(RG, "requesthub-storage-private-link"), "requesthub-storage-private-link")

    def test_scope_case_does_not_matter(self):
        self.assertEqual(label(RG.upper().replace("RESOURCEGROUPS", "resourcegroups"), "mine"), "mine")

    def test_assignment_on_a_resource_in_this_resource_group_is_named(self):
        self.assertEqual(label(RG + "/providers/Microsoft.Storage/storageAccounts/st1", "mine"), "mine")

    def test_resource_group_sharing_the_prefix_is_not_this_one(self):
        self.assertEqual(label(RG + "2", "theirs"), "subscription assignment")

    def test_management_group_assignment_is_not_named(self):
        self.assertEqual(label(MANAGEMENT_GROUP, "Org_Baseline"), "management group assignment")

    def test_subscription_assignment_is_not_named(self):
        self.assertEqual(label(SUBSCRIPTION, "Sub_Baseline"), "subscription assignment")

    def test_missing_scope_is_not_named(self):
        self.assertEqual(label(None, "Unknown"), "subscription assignment")


class Posted(unittest.TestCase):
    """Everything built from the Policy states: the Issue, the agent's input, and the evidence."""

    def assertOnlyOurs(self, text: str):
        self.assertIn("requesthub-storage-private-link", text)
        self.assertNotIn("Org_Baseline", text)
        self.assertNotIn("Sub_Baseline", text)

    def test_rows(self):
        rows = messages.policy_rows(STATES, RG)
        self.assertEqual(rows[0], "| Azure Policy · `management group assignment` (inherited) | NonCompliant ❌ | "
                                  "evaluated 2026-10-30 19:12 UTC |")
        self.assertIn("`subscription assignment` (inherited)", rows[1])
        self.assertIn("`requesthub-storage-private-link` (this resource group)", rows[2])
        self.assertOnlyOurs("\n".join(rows))

    def test_agent_input(self):
        summary = messages.policy_summary(STATES, RG)
        self.assertEqual([s["assignment"] for s in summary],
                         ["management group assignment", "subscription assignment", "requesthub-storage-private-link"])

    def test_issue_and_evidence(self):
        storage = {"properties": {"publicNetworkAccess": "Disabled", "privateEndpointConnections": []}}
        assessment = {"properties": {"status": {"code": "Unhealthy"}, "metadata": {"severity": "Medium"}}}
        self.assertOnlyOurs(messages.issue_body("rg-ai-sdlc-secure", RG, assessment, storage, STATES, "m", "now"))
        self.assertOnlyOurs(messages.evidence_comment("rg-ai-sdlc-secure", RG, storage, STATES, None, "now"))


if __name__ == "__main__":
    unittest.main()
