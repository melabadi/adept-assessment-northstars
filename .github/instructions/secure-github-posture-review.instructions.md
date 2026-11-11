---
applyTo: "solutions/05-secure-microsoft/infra/**"
excludeAgent: "cloud-agent"
---

# Reviewing a cloud posture fix

A change here usually comes from the Microsoft Foundry agent `posture-remediator`, which drafts the smallest Bicep fix for a finding from Azure Policy or Microsoft Defender for Cloud. Before it opened the pull request, code in Azure checked that the edit stays between the `// posture:editable-begin` and `// posture:editable-end` lines of `resources.bicep`. An Azure what-if preview then reports on the pull request, and a person decides whether to deploy it. Spend your review on what that person needs:

- **Azure's preview.** Read the pull request's `posture/what-if` commit status and its comment titled "Azure what-if preview". Say whether the preview ran on the head commit and passed. Compare the resources it lists with the description's **Expected changes**: name each expected change the preview does not show, and each change it shows that the description does not expect. The preview, not the description, says what a deployment would do.
- **Controls.** Flag anything that weakens a control or hides the finding instead of fixing it: a policy exemption, a changed policy assignment or effect, public network access, shared key access, or a new role assignment.
- **The module.** Check the changed parameter against the module it configures, `app/infra/requesthub.bicep`. Does the description say what the module really does with it?
- **Comments.** The comment above a changed value should explain the new value.

Do not rewrite the fix. Say what the person should check before they deploy it.
