#!/usr/bin/env bash
# Build and test a pull request's code in an Azure Container Apps dynamic session (Develop phase, Microsoft track).
#
# The Azure pull request reviewer takes the pull request's head archive (head.tgz) and this script from GitHub, uploads
# both into a fresh Shell session, and runs:
#
#   bash run_change.sh start     starts the run in the background and returns at once
#   bash run_change.sh status    prints {"state": "running" | "done", "step": ...}
#   bash run_change.sh summary   prints the results as JSON
#
# The results are also in /mnt/data/run/summary.json, which the reviewer downloads as a file, because a session cuts a
# command's output after 4 KB. `start` puts {"state": "not-finished"} there, and the run replaces it when it ends.
#
# The run installs Node 26, the .NET 10 SDK, and PostgreSQL 16 in the session, then runs what the repository's CI runs:
# the API's integration tests (dotnet test, against PostgreSQL in the session), and the web UI's typecheck and unit
# tests. A failed web test run is repeated once, and the summary reports both runs, so a flaky test shows up as flaky.
#
# Each setup step has a time limit, and keeps its log, its exit code, and why it failed. When a step fails, the tests
# that need it don't run: the summary reports them as an error with that reason, and the other tests still run. So a
# broken download fails within minutes and says why, instead of running tests against a missing toolchain or database
# until the reviewer's own 20-minute limit.
#
# PostgreSQL comes from the zonky project's builds of PostgreSQL (github.com/zonkyio/embedded-postgres-binaries),
# published on Maven Central and pinned here by version and SHA-256. That needs no apt, so nothing comes from Ubuntu's
# archive, whose DNS failed on 11 November 2026, and the whole step, from download to a running server, takes about 6 s.
#
# The pull request's own code runs here, so everything this script reports is evidence from that code, not a verdict.
# The team's rules are checked separately, earlier, in another session that never runs the pull request's code.
# No secret is ever placed in this session.
set -u

DATA=/mnt/data
RUN=$DATA/run
SRC=$RUN/src
PROGRESS=$RUN/progress.json

PG_VERSION=16.15.0
PG_SHA256=653abc065c682b85d3da50168fb95dc524bd85426cdec9ce3695a550ef431df2
PG_URL=https://repo1.maven.org/maven2/io/zonky/test/postgres/embedded-postgres-binaries-linux-amd64/$PG_VERSION/embedded-postgres-binaries-linux-amd64-$PG_VERSION.jar
PG_HOME=/opt/postgresql
PG_DATA=/opt/postgresql-data

mark() {  # mark <step>: record the current step for `status` and its start time for the summary
  printf '{"state":"running","step":"%s"}\n' "$1" > "$PROGRESS"
  echo "$1 $(date +%s)" >> "$RUN/timeline"
}

setup() {  # setup <name> <time limit in s> <command...>: one setup step; keeps its log, its exit code, and why it failed
  local name=$1 limit=$2 code
  shift 2
  mark "setup-$name"
  timeout "$limit" "$@" > "$RUN/setup-$name.log" 2>&1
  code=$?
  echo "$code" > "$RUN/setup-$name.exit"
  if [ "$code" -eq 124 ]; then echo "timed out after $limit s" > "$RUN/setup-$name.reason"; fi
}

ok() {  # ok <name>: the setup step succeeded
  [ "$(cat "$RUN/setup-$1.exit" 2>/dev/null)" = 0 ]
}

# Toolchain: what CI installs (.github/workflows/ci.yml): the latest .NET 10 SDK and Node 26.
install_node() {
  . "$NVM_DIR/nvm.sh" && nvm install 26 && nvm alias default 26
}

install_dotnet() {
  curl -fsSL --max-time 60 https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh &&
    bash /tmp/dotnet-install.sh --channel 10.0 --install-dir /opt/dotnet
}

install_postgres() {  # PostgreSQL 16 run by a non-root user, with the superuser the API tests sign in as
  local why=$RUN/setup-postgres.reason jar=/tmp/postgresql.jar code
  curl -fsS --max-time 60 -o "$jar" "$PG_URL"
  code=$?
  case $code in
    0) ;;
    6) echo "couldn't resolve repo1.maven.org to download PostgreSQL $PG_VERSION" > "$why"; return 1 ;;
    28) echo "the download of PostgreSQL $PG_VERSION from Maven Central timed out" > "$why"; return 1 ;;
    *) echo "couldn't download PostgreSQL $PG_VERSION from Maven Central (curl exit code $code)" > "$why"; return 1 ;;
  esac
  if ! echo "$PG_SHA256  $jar" | sha256sum --check --status; then
    echo "the download of PostgreSQL $PG_VERSION doesn't match its pinned SHA-256" > "$why"; return 1
  fi
  if ! python3 -c 'import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); open(sys.argv[2], "wb").write(z.read(next(n for n in z.namelist() if n.endswith(".txz"))))' \
         "$jar" /tmp/postgresql.txz || ! { mkdir -p "$PG_HOME" && tar xJf /tmp/postgresql.txz -C "$PG_HOME"; }; then
    echo "couldn't unpack PostgreSQL $PG_VERSION" > "$why"; return 1
  fi
  # PostgreSQL refuses to run as root. The password is the test database's, the same as in app/tests/ApiFixture.cs.
  id -u postgres > /dev/null 2>&1 || useradd --system --create-home --shell /bin/bash postgres
  mkdir -p "$PG_DATA" && chown postgres "$PG_DATA"
  # The server's log stays with the run's other logs; the run folder is root's, so the file is made here and handed over.
  touch "$RUN/postgres.log" && chown postgres "$RUN/postgres.log"
  printf 'devpass\n' > /tmp/pgpass && chown postgres /tmp/pgpass
  if ! su postgres -c "$PG_HOME/bin/initdb -D $PG_DATA -U requesthub --pwfile=/tmp/pgpass -E UTF8 --locale=C.UTF-8 --auth-local=trust --auth-host=scram-sha-256"; then
    echo "initdb failed for PostgreSQL $PG_VERSION" > "$why"; return 1
  fi
  if ! su postgres -c "$PG_HOME/bin/pg_ctl -D $PG_DATA -l $RUN/postgres.log -o '-p 5432 -k /tmp' -w -t 60 start"; then
    echo "PostgreSQL $PG_VERSION didn't start" > "$why"; return 1
  fi
}

run() {
  mkdir -p "$SRC"
  mark extract
  tar xzf "$DATA/head.tgz" --strip-components=1 -C "$SRC" > "$RUN/extract.log" 2>&1

  export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 PATH=/opt/dotnet:$PATH NVM_DIR=$HOME/.nvm
  setup node 300 bash "$0" install-node
  setup dotnet 300 bash "$0" install-dotnet
  setup postgres 120 bash "$0" install-postgres
  . "$NVM_DIR/nvm.sh" > /dev/null 2>&1; nvm use 26 > /dev/null 2>&1

  # API: the same command as CI, with PostgreSQL in this session. Without the SDK or the database, nothing runs and the
  # summary says why.
  if [ -f "$SRC/app/RequestHub.slnx" ] && ok dotnet && ok postgres; then
    mark api-tests
    (cd "$SRC" && timeout 600 dotnet test --solution app/RequestHub.slnx) > "$RUN/api.log" 2>&1
    echo $? > "$RUN/api.exit"
  fi

  # Web UI: typecheck and unit tests, as CI runs them. A session has 4 vCPUs that the test workers share, so a test may
  # take longer than on CI: the sandbox allows each test 30 s instead of vitest's 5 s. A failed run is repeated once to
  # tell flaky from failing.
  if [ -f "$SRC/app/web/package.json" ] && ok node; then
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

def setup_step(name):
    exit_code = code(f"setup-{name}.exit")
    reason = " ".join(text(f"setup-{name}.reason").split())[:200]
    if exit_code not in (None, 0) and not reason:
        reason = f"exit code {exit_code}"
    return {"exit_code": exit_code, "seconds": seconds(f"setup-{name}"), "reason": reason or None}

setup = {name: setup_step(name) for name in ("node", "dotnet", "postgres")}
MISSING = {"node": "Node 26 didn't install", "dotnet": "the .NET 10 SDK didn't install", "postgres": "PostgreSQL isn't running"}

def missing(*names):
    """Why the tests that need these setup steps couldn't run."""
    for name in names:
        if setup[name]["exit_code"] != 0:
            return f"{MISSING[name]}: {setup[name]['reason'] or 'its setup step never ran'}"
    return "the tests didn't start"

summary = {"setup": setup, "setup_seconds": sum(s["seconds"] or 0 for s in setup.values()) or None,
           "api": {"status": "skipped"}, "web": {"status": "skipped"}}
if code("api.exit") is not None:
    summary["api"] = {"status": "passed" if code("api.exit") == 0 else "failed", "exit_code": code("api.exit"),
                      "seconds": seconds("api-tests"), **dotnet(text("api.log"))}
elif (run / "src/app/RequestHub.slnx").exists():
    summary["api"] = {"status": "error", "reason": missing("dotnet", "postgres")}
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
    if status == "error":
        summary["web"]["reason"] = f"npm ci failed (exit code {code('web-install.exit')})"
elif (run / "src/app/web/package.json").exists():
    summary["web"] = {"status": "error", "reason": missing("node")}
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
  install-node) install_node ;;
  install-dotnet) install_dotnet ;;
  install-postgres) install_postgres ;;
  status) cat "$PROGRESS" 2>/dev/null || echo '{"state":"not-started"}' ;;
  summary) cat "$RUN/summary.json" 2>/dev/null || echo '{"state":"not-finished"}' ;;
  *) echo "usage: bash run_change.sh start | status | summary" >&2; exit 2 ;;
esac
