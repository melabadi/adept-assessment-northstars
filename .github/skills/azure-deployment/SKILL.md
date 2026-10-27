---
name: azure-deployment
description: Release RequestHub to Azure Container Apps through a candidate revision that receives no traffic until it passes a gate (readiness, a business smoke test, and a bake period), then promote it with one atomic traffic change. Includes a preflight that checks the app, the release identity's least-privilege roles, and the GitHub environment. Use before the first release, to run a release, or when a release workflow fails before it reaches the gate.
---

# Azure deployment through candidate revisions

The API container app runs in multiple-revision mode. A release adds a **candidate** revision beside the **stable** one,
checks it on its own URL, and only then moves traffic. The old stable revision keeps running as **previous**, so a rollback
is one traffic change. `solutions/06-release-microsoft/release.py` does every step, from a terminal or from the
`Release · Microsoft · roll out a candidate revision` workflow (`.github/workflows/release-microsoft-rollout.yml`).

## When to use
- After `azd up`, before the first release, or after changing roles or the GitHub environment: run the preflight.
- To ship a new build of the API without exposing users to it before it passes the gate.
- When the rollout workflow fails in its build or candidate job before the gate runs: the preflight usually says why.

## Inputs
- Settings from the solution's azd environment (`azd env get-values` in `solutions/06-release-microsoft`), or the
  environment variables `AZURE_RESOURCE_GROUP`, `API_APP_NAME`, and `API_IDENTIFIER_URI`.
- An image in the solution's registry. The workflow builds one per commit (`requesthub-api:<commit>`) and reuses it on
  reruns; from a terminal, `az acr build` does the same.
- An Azure CLI sign-in with Container Apps Contributor on the resource group. The person who ran `azd up` has more.

## Procedure
1. Preflight: `python .github/skills/azure-deployment/preflight.py`. Every line should read PASS.
2. Release from GitHub Actions (preferred: the run is the record):
   ```
   gh workflow run release-microsoft-rollout.yml
   gh run watch
   ```
   Or from a terminal, in `solutions/06-release-microsoft`:
   ```
   python release.py deploy --image <registry>/requesthub-api:<commit> --commit <commit>
   python release.py gate
   python release.py promote
   python release.py verify
   python release.py record
   ```
3. Read the gate output: how long the candidate took to become ready, the ten smoke checks (health, build provenance,
   sign-in enforced, signed in, submit, safe retry, read, attachment round trip, self-approval refused, audit history),
   the bake, and "Users meanwhile", the
   success rate of calls to production while the step ran.
4. If the gate fails, do not promote. Switch to the **deployment-recovery** skill.

## Expected output
```
PASS  Traffic   ca-api-xxxx--run12 serves 100% (label stable)
PASS  Identity  Container Apps Contributor on rg-ai-sdlc-release
12 passed, 0 warnings, 0 failed

Gate: readiness, smoke test, and bake on the candidate's own URL
  · Ready 36 s after it was created. Smoke test on https://ca-api-xxxx---candidate.<domain>
    ✓ build            build d4f49c7215eb, contract requesthub.v1, auth EasyAuth (matches the release commit)
    ✓ approval guard   self-approval: HTTP 403 decision.self_approval
  · Users meanwhile: 39/39 calls to production succeeded (100.0%)
✓ Candidate run12 passed the gate and still has 0% of traffic.
```

## Failure handling
- A preflight FAIL line names the fix, usually `azd provision` in the solution folder (it recreates the federated
  credential, the role assignments, and the GitHub environment values).
- `Traffic is split`: an earlier release stopped halfway. Finish it with `promote`, `abort`, or `rollback`.
- `build ... (expected ...)`: the image does not contain the commit being released. Rebuild it; never pass another
  `--commit` to make the check match.
- Never lower `--ready-timeout`, `--not-ready-grace`, or `--bake`, and never edit a probe, to let a candidate through.
  Fix the candidate.
