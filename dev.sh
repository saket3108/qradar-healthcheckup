#!/usr/bin/env bash
# Start the QRadar Health Checkup platform locally (dev mode: SQLite + in-process workers).
#   ./dev.sh start | stop | restart | status
# Data lives in ./data (git-ignored), so it survives restarts and reboots.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN="$ROOT/data/run"; mkdir -p "$RUN" "$ROOT/data/storage"
export PATH="$HOME/.local/bin:$PATH"                       # npm was bootstrapped here on this Mac
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"   # Homebrew Python 3.12 pyexpat fix

: "${QHC_ADMIN_EMAIL:=admin@example.com}"
: "${QHC_ADMIN_PASSWORD:=AdminPass12345}"
export QHC_ADMIN_EMAIL QHC_ADMIN_PASSWORD
export QHC_DATABASE_URL="${QHC_DATABASE_URL:-sqlite:///$ROOT/data/qhc.db}"
export QHC_STORAGE_DIR="${QHC_STORAGE_DIR:-$ROOT/data/storage}"
export QHC_SECRET_KEY="${QHC_SECRET_KEY:-dev-secret-dev-secret-dev-secret-123}"
export QHC_CORS_ORIGINS='["http://localhost:5173"]'

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

# detach <name> <cwd> <cmd...>: run in its own session so it survives this shell/terminal closing.
# Uses the venv python (not SIP-protected) so DYLD_LIBRARY_PATH is preserved.
detach() {
  local name="$1" cwd="$2"; shift 2
  "$ROOT/backend/.venv/bin/python" - "$RUN/$name.pid" "$RUN/$name.log" "$cwd" "$@" <<'PY'
import subprocess, sys
pid, log, cwd, *cmd = sys.argv[1:]
with open(log, "wb") as lf:
    p = subprocess.Popen(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
open(pid, "w").write(str(p.pid))
PY
}

start() {
  if alive "$RUN/api.pid"; then echo "api already running"; else
    detach api "$ROOT/backend" .venv/bin/python -m uvicorn app.main:app --port 8000
  fi
  if alive "$RUN/web.pid"; then echo "web already running"; else
    detach web "$ROOT/frontend" npx vite --port 5173 --strictPort
  fi
  for _ in $(seq 1 30); do curl -sf localhost:8000/api/health >/dev/null && curl -sf -o /dev/null localhost:5173/ && break; sleep 1; done
  status
  echo; echo "Open http://localhost:5173   login: $QHC_ADMIN_EMAIL / $QHC_ADMIN_PASSWORD"
}
stop() {
  for n in api web; do
    if alive "$RUN/$n.pid"; then kill -TERM -- "-$(cat "$RUN/$n.pid")" 2>/dev/null || kill -TERM "$(cat "$RUN/$n.pid")" 2>/dev/null || true; echo "stopped $n"; fi
    rm -f "$RUN/$n.pid"
  done
}
status() {
  curl -sf localhost:8000/api/health >/dev/null && echo "api : UP   http://localhost:8000/api/docs" || echo "api : DOWN (see data/run/api.log)"
  curl -sf -o /dev/null localhost:5173/ && echo "web : UP   http://localhost:5173" || echo "web : DOWN (see data/run/web.log)"
}
case "${1:-status}" in start) start;; stop) stop;; restart) stop; sleep 1; start;; status) status;; *) echo "usage: $0 start|stop|restart|status"; exit 1;; esac
