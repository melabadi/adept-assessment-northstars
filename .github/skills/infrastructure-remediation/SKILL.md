---
name: infrastructure-remediation
description: Fix a cloud posture finding in Bicep, and prove with an Azure what-if preview that the change touches only the intended resources before anyone deploys it. Use when remediating a posture Issue, reviewing an infrastructure pull request, or before running azd provision.
---

# Infrastructure remediation

A posture fix is a code change, reviewed like any other. The deployment preview turns "it only adds a private path to
storage" into evidence a reviewer can read before anything is deployed.

## When to use
- Remediating an Issue labelled `posture`.
- Reviewing a pull request that changes `solutions/05-secure-microsoft/infra/`.
- Before applying an infrastructure change with `azd provision`.

## Inputs
- The finding: control, resource, and the setting that satisfies it (from the Issue or the **cloud-posture** skill).
- For the preview: Azure sign-in that can read the resource group and run deployment operations. You (after `az login`)
  and the solution's GitHub identity in the `secure-microsoft` environment both can. Neither the preview nor this skill
  deploys anything.

## Procedure
1. Locate the setting. `solutions/05-secure-microsoft/infra/main.bicep` creates the resource group and deploys
   `resources.bicep`, which composes `app/infra/requesthub.bicep`. Solution-specific values, such as
   `storagePrivateEndpoint`, are set in `resources.bicep`. Change them there; the shared module belongs to every solution.
2. Check the change is safe. For private link: the app must reach storage with a token credential over the SDK (no keys,
   no connection strings), and run in the virtual network that the private DNS zone is linked to.
3. Make the smallest change. Keep comments accurate.
4. Compile: `az bicep build --file solutions/05-secure-microsoft/infra/main.bicep --stdout` and check there are no errors.
5. Preview against the live resource group:

   ```
   python .github/skills/infrastructure-remediation/whatif.py --markdown out/preview.md \
     --expect Microsoft.Storage/storageAccounts --expect Microsoft.Network/virtualNetworks --expect "Microsoft.Network/private*"
   ```

   The script resolves `infra/main.parameters.json` from the environment or the solution's azd environment, runs a
   resource-group what-if of `infra/resources.bicep`, and also previews the template that is deployed now (the
   `resources` deployment). Differences that show up in both previews are what-if noise, so it reports only what your
   change adds. It fails on any created, modified, or deleted resource type that matches no `--expect` pattern.
6. Put the preview in the pull request. The **Secure · Microsoft · preview the infrastructure change** check runs the same
   script on every pull request that touches the solution's infrastructure and comments the result.
7. After review and merge, a person applies it: `azd provision` in `solutions/05-secure-microsoft`. Then verify with the
   **cloud-posture** skill.

## Expected output
```
### Deployment preview (Azure what-if) · `rg-ai-sdlc-secure`
- **Create** `Microsoft.Network/privateDnsZones` `privatelink.blob.core.windows.net` ✅ expected
- **Create** `Microsoft.Network/privateDnsZones/virtualNetworkLinks` `vnet-link` ✅ expected
- **Create** `Microsoft.Network/privateEndpoints` `pe-blob-...` ✅ expected
- **Create** `Microsoft.Network/privateEndpoints/privateDnsZoneGroups` `default` ✅ expected
- **Modify** `Microsoft.Network/virtualNetworks` `vnet-...` ✅ expected
  - `properties.subnets[2]`: added `{"name": "snet-private-endpoints", ...}`
- **Modify** `Microsoft.Storage/storageAccounts` `st...` ✅ expected
  - `properties.networkAcls.defaultAction`: `"Allow"` → `"Deny"`
- 12 other resource(s) show differences what-if reports on every run ... not counted.
**PASS**: every change is an expected resource type (...).
```

## Failure handling
- `FAIL: unexpected change(s)`: read each ⚠️ line. Remove the unintended change, or, if it is intended, explain it in the
  pull request. Never widen `--expect` in the workflow to make a check pass.
- `... is not set`: run `azd provision` in the solution folder (locally), or rerun the azd hooks so the GitHub environment
  has its variables.
- `AuthorizationFailed`: the identity needs read access and `Microsoft.Resources/deployments/*` on the resource group.
- No baseline (`compared with the deployed ... template` missing from the first line): the resource group has no
  `resources` deployment yet, so the preview lists raw changes. Run `azd provision` once.
- What-if does not evaluate Microsoft Graph objects (the app registration and its role assignments). They change only
  when their Bicep changes.
