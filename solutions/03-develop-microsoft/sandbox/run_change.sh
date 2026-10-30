#!/usr/bin/env bash
# Build and test a pull request's code in an Azure Container Apps dynamic session (Develop phase, Microsoft track).
#
# The Azure pull request reviewer's Logic App takes the pull request's head archive (head.tgz) and this script from
# GitHub, uploads both into a fresh Shell session, and runs:
#
#   bash run_change.sh start     starts the run in the background and returns at once
#   bash run_change.sh status    prints {"state": "running" | "done", "step": ...}
#   bash run_change.sh summary   prints the results as JSON
#
# The results are also in /mnt/data/run/summary.json, which the Logic App downloads as a file, because a session cuts a
# command's output after 4 KB. `start` puts {"state": "not-finished"} there, and the run replaces it when it ends.
#
# The run installs Node 22, the .NET 10 SDK, and PostgreSQL in the session, then runs what the repository's CI runs:
# the API's integration tests (dotnet test, against PostgreSQL in the session), and the web UI's typecheck and unit
# tests. A failed web test run is repeated once, and the summary reports both runs, so a flaky test shows up as flaky.
#
# The pull request's own code runs here, so everything this script reports is evidence from that code, not a verdict.
# The team's rules are checked separately, earlier, in another session that never runs the pull request's code.
# No secret is ever placed in this session.
set -u

DATA=/mnt/data
RUN=$DATA/run
SRC=$RUN/src
PROGRESS=$RUN/progress.json

mark() {  # mark <step>: record the current step for `status` and its start time for the summary
  printf '{"state":"running","step":"%s"}\n' "$1" > "$PROGRESS"
  echo "$1 $(date +%s)" >> "$RUN/timeline"
}

run() {
  mkdir -p "$SRC"
  mark extract
  tar xzf "$DATA/head.tgz" --strip-components=1 -C "$SRC" > "$RUN/extract.log" 2>&1

  # Toolchain: what CI installs (.github/workflows/ci.yml): the latest .NET 10 SDK and Node 22.
  mark setup
  export DEBIAN_FRONTEND=noninteractive DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 PATH=/opt/dotnet:$PATH
  export NVM_DIR=$HOME/.nvm
  {
    . "$NVM_DIR/nvm.sh" && nvm install 22 && nvm alias default 22
    curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
    bash /tmp/dotnet-install.sh --channel 10.0 --install-dir /opt/dotnet
    apt-get update -qq && apt-get install -y -qq postgresql
    service postgresql start
    su postgres -c "psql -q -c \"CREATE USER requesthub WITH SUPERUSER PASSWORD 'devpass';\""
  } > "$RUN/setup.log" 2>&1
  . "$NVM_DIR/nvm.sh" > /dev/null 2>&1; nvm use 22 > /dev/null 2>&1

  # API: the same command as CI, with PostgreSQL in this session.
  if [ -f "$SRC/app/RequestHub.slnx" ]; then
    mark api-tests
    (cd "$SRC" && timeout 600 dotnet test --solution app/RequestHub.slnx) > "$RUN/api.log" 2>&1
    echo $? > "$RUN/api.exit"
  fi

  # Web UI: typecheck and unit tests, as CI runs them. A session has 4 vCPUs that the test workers share, so a test may
  # take longer than on CI: the sandbox allows each test 30 s instead of vitest's 5 s. A failed run is repeated once to
  # tell flaky from failing.
  if [ -f "$SRC/app/web/package.json" ]; then
    mark web-install
    (cd "$SRC/app/web" && timeout 300 npm ci --no-audit --no-fund) > "$RUN/web-install.log" 2>&1
    echo $? > "$RUN/web-install.exit"
    mark web-typecheck
    (cd "$SRC/app/web" && timeout 300 npm run typecheck) > "$RUN/web-typecheck.log" 2>&1
    echo $? > "$RUN/web-typecheck.exit"
    mark web-tests
    (cd "$SRC/app/web" && timeout 300 npm test -- --testTimeout=30000) > "$RUN/web-tests.log" 2>&1
    echo $? > "$RUN/web-tests.exit"
    if [ "$(cat "$RUN/web-tests.exit")" != "0" ]; then
      mark web-tests-rerun
      (cd "$SRC/app/web" && timeout 300 npm test -- --testTimeout=30000) > "$RUN/web-tests-rerun.log" 2>&1
      echo $? > "$RUN/web-tests-rerun.exit"
    fi
  fi
  mark done

  # The summary reads logs and exit codes from files; nothing the pull request prints is ever pasted into code.
  python3 - "$RUN" <<'PY'
import json, re, sys
from pathlib import Path

run = Path(sys.argv[1])

def text(name):
    p = run / name
    return re.sub(r"\x1b\[[0-9;]*m", "", p.read_text(encoding="utf-8", errors="replace")) if p.exists() else ""

def code(name):
    p = run / name
    return int(p.read_text().strip()) if p.exists() and p.read_text().strip().lstrip("-").isdigit() else None

times = {}
for line in text("timeline").splitlines():
    step, _, at = line.partition(" ")
    times.setdefault(step, int(at))
order = list(times)
def seconds(step):
    if step not in times:
        return None
    later = [times[s] for s in order[order.index(step) + 1:]]
    return (later[0] if later else times[step]) - times[step]

def dotnet(log):
    def n(name):
        m = re.findall(rf"^\s*{name}:\s*(\d+)", log, re.M)
        return int(m[-1]) if m else None
    return {"total": n("total"), "passed": n("succeeded"), "failed": n("failed"), "skipped": n("skipped"),
            "failed_tests": sorted(set(re.findall(r"^\s*failed\s+(\S+)", log, re.M)))[:10]}

def vitest(log):
    lines = re.findall(r"^\s*Tests\s+(.*)$", log, re.M)
    line = lines[-1] if lines else ""
    def n(word):
        m = re.search(rf"(\d+)\s+{word}", line)
        return int(m.group(1)) if m else 0
    total = re.search(r"\((\d+)\)", line)
    return {"total": int(total.group(1)) if total else None, "passed": n("passed"), "failed": n("failed"),
            "skipped": n("skipped"), "failed_tests": sorted(set(re.findall(r"^\s*FAIL\s+(.+?)\s*$", log, re.M)))[:10]}

summary = {"setup_seconds": seconds("setup"), "api": {"status": "skipped"}, "web": {"status": "skipped"}}
if code("api.exit") is not None:
    summary["api"] = {"status": "passed" if code("api.exit") == 0 else "failed", "exit_code": code("api.exit"),
                      "seconds": seconds("api-tests"), **dotnet(text("api.log"))}
if code("web-install.exit") is not None:
    first = vitest(text("web-tests.log"))
    rerun = vitest(text("web-tests-rerun.log")) if code("web-tests-rerun.exit") is not None else None
    if code("web-install.exit") != 0:
        status = "error"
    elif code("web-tests.exit") == 0:
        status = "passed"
    else:
        status = "flaky" if code("web-tests-rerun.exit") == 0 else "failed"
    summary["web"] = {"status": status, "install_exit_code": code("web-install.exit"),
                      "typecheck": "passed" if code("web-typecheck.exit") == 0 else "failed",
                      "tests": first, "rerun": rerun,
                      "seconds": sum(s or 0 for s in (seconds("web-install"), seconds("web-typecheck"),
                                                      seconds("web-tests"), seconds("web-tests-rerun")))}
summary["seconds"] = times.get("done", 0) - times.get("extract", 0)
summary["logs"] = [f"/mnt/data/run/{p.name}" for p in sorted(run.glob("*.log"))]
(run / "summary.json").write_text(json.dumps(summary))
PY
  printf '{"state":"done","step":"done"}\n' > "$PROGRESS"
}

case "${1:-}" in
  start)
    mkdir -p "$RUN"
    if [ -f "$PROGRESS" ]; then cat "$PROGRESS"; exit 0; fi  # already started: starting twice changes nothing
    printf '{"state":"running","step":"queued"}\n' > "$PROGRESS"
    printf '{"state":"not-finished"}\n' > "$RUN/summary.json"
    nohup bash "$0" run > "$RUN/run.out" 2>&1 &
    cat "$PROGRESS"
    ;;
  run) run ;;
  status) cat "$PROGRESS" 2>/dev/null || echo '{"state":"not-started"}' ;;
  summary) cat "$RUN/summary.json" 2>/dev/null || echo '{"state":"not-finished"}' ;;
  *) echo "usage: bash run_change.sh start | status | summary" >&2; exit 2 ;;
esac
