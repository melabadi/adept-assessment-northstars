"""Settings of the posture Function app, from its app settings (infra/automation.bicep sets every one of them)."""
from __future__ import annotations

import os
from dataclasses import dataclass

APP_SETTINGS = {
    "repository": "GITHUB_REPOSITORY",                       # owner/name
    "resource_group_id": "POSTURE_RESOURCE_GROUP_ID",
    "storage_account_id": "POSTURE_STORAGE_ACCOUNT_ID",       # RequestHub's attachment storage, the audited resource
    "assessment_key": "POSTURE_ASSESSMENT_KEY",               # the Defender for Cloud recommendation
    "policy_definition_name": "POSTURE_POLICY_DEFINITION",    # the built-in policy behind it
    "policy_assignment_name": "POSTURE_POLICY_ASSIGNMENT",    # this solution's assignment of that policy
    "marker": "POSTURE_MARKER",                               # identifies this finding's Issue
    "foundry_project_endpoint": "FOUNDRY_PROJECT_ENDPOINT",
    "agent_name": "REMEDIATION_AGENT_NAME",
    "editable_path": "POSTURE_EDITABLE_PATH",                 # the one file the agent may change
    "module_path": "POSTURE_MODULE_PATH",                     # the module it reads
    "infra_prefix": "POSTURE_INFRA_PREFIX",                   # pull requests that change this folder get a preview
    "whatif_job_id": "POSTURE_WHATIF_JOB_ID",
}


@dataclass(frozen=True)
class Settings:
    repository: str
    resource_group_id: str
    storage_account_id: str
    assessment_key: str
    policy_definition_name: str
    policy_assignment_name: str
    marker: str
    foundry_project_endpoint: str
    agent_name: str
    editable_path: str
    module_path: str
    infra_prefix: str
    whatif_job_id: str

    @property
    def resource_group_name(self) -> str:
        return self.resource_group_id.rstrip("/").rsplit("/", 1)[-1]

    @classmethod
    def from_environment(cls, environ=None) -> "Settings":
        environ = os.environ if environ is None else environ
        values = {field: environ.get(name, "") for field, name in APP_SETTINGS.items()}
        missing = [APP_SETTINGS[field] for field, value in values.items() if not value]
        if missing:
            raise RuntimeError(f"app settings missing: {', '.join(missing)}")
        return cls(**values)
