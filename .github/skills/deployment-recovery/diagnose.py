"""Explain why a Container Apps revision is not serving, from the platform's own evidence. It changes nothing.

For one revision (default: the revision labelled candidate, else the newest one) it prints:
  1. State: active, running state, health, replicas, share of traffic, and labels.
  2. Containers in each replica: started, ready, restarts, and the platform's detail text.
  3. Probes the platform runs against the API container, and any fault-injection settings.
  4. Azure's warnings for the revision (probe failures, crashes, image pulls) from the live system log stream.
  5. The app's own error lines (for example a failing health check) from the live console log stream.
Then it suggests the next step: remove a candidate that never got traffic, or roll back if users are affected.

It uses documented Azure CLI commands (`az containerapp show`, `revision list`, `replica list`, `logs show`), so the
same evidence is available to anyone with Reader access and log stream rights on the app.

  python .github/skills/deployment-recovery/diagnose.py
  python .github/skills/deployment-recovery/diagnose.py --revision t1027140538
  python .github/skills/deployment-recovery/diagnose.py --resource-group rg-ai-sdlc-release --app ca-api-xxxx
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RELEASE = "solutions/06-release-microsoft/release.py"


def run(tool: str, *args: str, cwd: Path | None = None) -> tuple[int, str]:
    exe = shutil.which(tool)
    if not exe:
        return 127, f"{tool} is not installed"
    proc = subprocess.run([exe, *args], capture_output=True, text=True, cwd=cwd)
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr or proc.stdout).strip()


def az(*args: str):
    code, out = run("az", *args, "--output", "json")
    if code:
        raise SystemExit(f"error: az {' '.join(args[:3])} failed: {out}")
    return json.loads(out or "null")


def default_azd_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "solutions" / "06-release-microsoft").is_dir():
            return parent / "solutions" / "06-release-microsoft"
    return Path.cwd()


def settings(args) -> tuple[str, str]:
    values: dict[str, str] = {}
    if Path(args.azd_dir).is_dir():
        code, out = run("azd", "env", "get-values", "--output", "json", cwd=Path(args.azd_dir))
        values = json.loads(out) if code == 0 else {}
    rg = args.resource_group or os.environ.get("AZURE_RESOURCE_GROUP") or values.get("AZURE_RESOURCE_GROUP")
    app = args.app or os.environ.get("API_APP_NAME") or values.get("API_APP_NAME")
    if not rg or not app:
        raise SystemExit("error: pass --resource-group and --app, or run `azd up` in the solution folder first.")
    return rg, app


def log_lines(rg: str, app: str, *args: str) -> list[str]:
    code, out = run("az", "containerapp", "logs", "show", "--name", app, "--resource-group", rg, "--tail", "300", *args)
    return out.splitlines() if code == 0 else [f"(log stream unavailable: {out.splitlines()[-1] if out else code})"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--revision", help="revision name or suffix (default: the candidate, else the newest revision)")
    parser.add_argument("--resource-group", help="resource group of the app (default: AZURE_RESOURCE_GROUP)")
    parser.add_argument("--app", help="container app (default: API_APP_NAME)")
    parser.add_argument("--container", default="api", help="container to read console logs from (default api)")
    parser.add_argument("--azd-dir", default=str(default_azd_dir()), help="folder whose azd environment supplies missing settings")
    args = parser.parse_args()
    rg, app_name = settings(args)

    app = az("containerapp", "show", "--name", app_name, "--resource-group", rg)
    revisions = sorted(az("containerapp", "revision", "list", "--name", app_name, "--resource-group", rg, "--all"),
                       key=lambda r: r["properties"].get("createdTime", ""), reverse=True)
    latest_ready = app["properties"].get("latestReadyRevisionName")
    weights: dict[str, int] = {}
    labels: dict[str, list[str]] = {}
    for entry in app["properties"]["configuration"]["ingress"].get("traffic") or []:
        name = entry.get("revisionName") or (latest_ready if entry.get("latestRevision") else None)
        weights[name] = weights.get(name, 0) + int(entry.get("weight") or 0)
        if entry.get("label"):
            labels.setdefault(name, []).append(entry["label"])
    if args.revision:
        wanted = args.revision if args.revision.startswith(f"{app_name}--") else f"{app_name}--{args.revision}"
    else:
        wanted = next((n for n, l in labels.items() if "candidate" in l), revisions[0]["name"] if revisions else "")
    revision = next((r for r in revisions if r["name"] == wanted), None)
    if not revision:
        raise SystemExit(f"error: revision {wanted} not found in {app_name}.")
    props = revision["properties"]
    traffic = weights.get(wanted, 0)
    healthy = props.get("active") and props.get("healthState") == "Healthy" and props.get("runningState") == "Running"

    print(f"\n1. State of {wanted}")
    print(f"   active {props.get('active')}, {props.get('runningState')}, health {props.get('healthState')}, "
          f"{props.get('replicas', 0)} replica(s), {traffic}% of traffic, labels: {', '.join(labels.get(wanted, [])) or 'none'}")
    if props.get("runningStateDetails"):
        print(f"   {props['runningStateDetails']}")

    print("\n2. Containers")
    replicas = az("containerapp", "replica", "list", "--name", app_name, "--resource-group", rg, "--revision", wanted) if props.get("active") else []
    for replica in replicas:
        for c in replica["properties"].get("containers", []):
            print(f"   {replica['name'].removeprefix(wanted + '-')}/{c['name']}: started {c.get('started')}, ready {c.get('ready')}, "
                  f"restarts {c.get('restartCount')}, {c.get('runningState')}: {c.get('runningStateDetails')}")
    if not replicas:
        print("   no running replicas (inactive revision or scaled to zero)")

    print("\n3. Probes and fault settings")
    template = props.get("template", {})
    container = next((c for c in template.get("containers", []) if c.get("name") == args.container), {})
    for probe in container.get("probes") or []:
        http = probe.get("httpGet") or {}
        print(f"   {probe.get('type'):<9} GET {http.get('path')} every {probe.get('periodSeconds', 10)} s, "
              f"fails after {probe.get('failureThreshold', 3)} misses")
    faults = {e["name"]: e.get("value") for e in container.get("env", []) if e.get("name", "").startswith("Faults__")}
    if faults:
        print(f"   fault injection: {', '.join(f'{k}={v}' for k, v in faults.items())}")

    print("\n4. Azure's warnings for this revision (system log stream)")
    warnings: dict[str, int] = {}
    for line in log_lines(rg, app_name, "--type", "system", "--format", "json"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("RevisionName") == wanted and event.get("Type") == "Warning":
            warnings[event.get("Msg", "")] = warnings.get(event.get("Msg", ""), 0) + 1
    for message, count in warnings.items():
        print(f"   {message}" + (f" (x{count})" if count > 1 else ""))
    if not warnings:
        print("   none")

    print("\n5. The app's own error lines (console log stream)")
    errors: dict[str, int] = {}
    if replicas:
        for line in log_lines(rg, app_name, "--type", "console", "--revision", wanted, "--container", args.container, "--format", "text"):
            message = re.sub(r"^\S+ (stdout|stderr) [FP] ", "", line).strip()
            if re.fullmatch(r"\w+: [\w.]+\[\d+\]", message):  # a .NET log header; the message is on the next line
                continue
            if re.search(r"Unhealthy|Exception|failed", message):
                key = re.sub(r" completed after [\d.]+ms", "", message)[:240]
                errors[key] = errors.get(key, 0) + 1
    for message, count in list(errors.items())[:8]:
        print(f"   {message}" + (f" (x{count})" if count > 1 else ""))
    if not errors:
        print("   none" if replicas else "   no running replica to read from")

    print("\nNext step")
    if healthy:
        print("   The revision is healthy. Nothing to recover.")
    elif traffic == 0:
        print(f"   It has no traffic, so no user reached it. Remove it: python {RELEASE} abort")
        print("   Then fix the cause above and release again; never relax the probe or the gate to let it through.")
    else:
        print(f"   Users are on this revision ({traffic}% of traffic). Roll back first: python {RELEASE} rollback")
        print("   (or run the Release · Microsoft · roll back workflow), then fix the cause and release again.")
    if faults:
        print("   This revision has fault injection switched on; it is a rehearsal, not a defect in the code.")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
