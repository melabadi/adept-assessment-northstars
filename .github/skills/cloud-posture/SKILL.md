---
name: cloud-posture
description: Read, triage, and verify cloud posture findings for RequestHub's Azure resources, keeping Azure Policy compliance and Microsoft Defender for Cloud recommendations separate. Use when a posture Issue arrives, before claiming a remediation is done, or to explain why Policy and Defender disagree.
---

# Cloud posture

Two services judge the same control, each on its own clock. `solutions/05-secure-microsoft/posture.py` reads both, the
resource itself, and the app, and never merges their answers. The control is **Storage accounts should use private link**
on RequestHub's attachment storage.

| Source | What it is | How fast it reflects a change |
|---|---|---|
| Resource configuration | Approved private endpoints, public network access, and network rules on the live account, read from Azure Resource Manager. Ground truth. | Immediately |
| Azure Policy | Compliance of each assignment that evaluates the policy definition: this solution's `requesthub-storage-private-link` on its resource group, and inherited ones such as the Microsoft cloud security benchmark. | About 15 to 30 minutes after a change, or minutes after an on-demand evaluation |
| Defender for Cloud | The recommendation whose metadata names the same policy definition (found by `policyDefinitionId`, never by a hard-coded assessment id). | On Defender's schedule, usually within 24 hours. New resources can take up to 24 hours to appear. |
| App check | Uploads and downloads an attachment through the RequestHub API, which stores it in Blob storage. | Immediately |

## When to use
- A GitHub Issue labelled `posture` asks for a fix.
- Before a demo, to see what each source reports right now.
- After a fix is deployed, to verify it and close the Issue with evidence.

## Inputs
- The solution deployed with `azd up` in `solutions/05-secure-microsoft` (or the GitHub environment `secure-microsoft`).
- Azure sign-in with Reader and Policy Insights rights on the resource group. The solution's GitHub identity has Reader and
  Policy Enrollments Contributor: it can query and start evaluations but cannot change anything.

## Procedure
1. Scan: `python solutions/05-secure-microsoft/posture.py scan`. Add `--refresh` to run an Azure Policy evaluation first
   (a few minutes), and `--issue` to open or update the deduplicated Issue. In GitHub:
   `gh workflow run secure-microsoft-scan.yml` (add `-f refresh=true`).
2. Read the Issue table row by row. Before the fix: configuration `no private endpoint` ❌, Policy `NonCompliant`, Defender
   `Unhealthy` (or `not assessed yet` for a new resource), and the app check `fails` where an organization-wide policy
   closed the public endpoint, or `works` (over the internet) where it did not.
3. Fix it in Bicep with the **infrastructure-remediation** skill.
4. After a person applies the fix, verify: `python solutions/05-secure-microsoft/posture.py verify --issue <n>`, or
   `gh workflow run secure-microsoft-verify.yml -f issue=<n>`.
5. If Defender has not reassessed yet, the Issue says so. Record its result later with `--timeout 0`.

## Expected output
```
Storage accounts should use private link · rg-ai-sdlc-secure/st...
  Resource configuration
      no private endpoint ❌  ·  public network access Disabled, network rules default Allow; read from Azure Resource Manager at ...
  Azure Policy · requesthub-storage-private-link (this resource group)
      NonCompliant ❌  ·  evaluated ..., definition version 2.1.0
  Microsoft Defender for Cloud · Storage account should use a private link connection
      Unhealthy ❌  ·  Medium severity, status since ..., assessment ...
  App check · attachment upload and download through the RequestHub API
      fails ❌  ·  upload to REQ-... returned HTTP 500 (An error occurred while processing your request.)
st...: opened https://github.com/<owner>/<repo>/issues/<n>
```
`verify` ends with **Verified** (private endpoint in place, Policy Compliant, app check passed), **Pending**, **Not fixed**,
or **Not verified** (configuration fixed but the app check failed).

## Failure handling
- `MISCONFIGURED, but neither Azure Policy nor Defender for Cloud has reported it yet`: the services have not evaluated the
  resource. Run `scan --refresh`. No Issue is filed for a finding no service reported.
- Policy `Compliant` while the configuration is ❌: Policy has not re-evaluated since the change. Trust the configuration.
- `AuthorizationFailed` on `triggerEvaluation`: the identity lacks Policy Enrollments Contributor on the resource group.
  Run `azd provision` in the solution folder.
- Verify stays **Pending**: Policy evaluates changed resources within about 30 minutes; run it again. Never close the Issue
  by hand to skip verification, and never add an exemption.
- App check fails after the fix: the private DNS zone must be linked to the app's virtual network. Check
  `az network private-dns link vnet list -g <resource group> -z privatelink.blob.core.windows.net`.
