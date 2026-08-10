#!/usr/bin/env bash
#
# One command to run the whole thing.
#
# Creates the Python virtualenv, installs both halves if needed, and starts the
# API and the web app together. Safe to re-run; it skips work already done.
#
#   ./dev.sh
#
# API   http://localhost:8000   (docs at /docs)
# App   http://localhost:5173

set -euo pipefail

cd "$(dirname "$0")"

API_PORT=8000
WEB_PORT=5173

# --- local settings ----------------------------------------------------------

# .env holds the database URL when running against Postgres. It is gitignored,
# because a connection string contains a password. Without it the app falls back
# to a local SQLite file, which is what makes the default setup zero-config.
if [ -f .env ]; then
  echo "==> loading .env"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ -n "${FIELD_ESTIMATE_DATABASE_URL:-}" ]; then
  # Print only the host, never the credentials.
  echo "==> database: ${FIELD_ESTIMATE_DATABASE_URL##*@}"
else
  echo "==> database: local SQLite (api/field_estimate.db)"
fi

# --- python ------------------------------------------------------------------

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo "error: no python3 found. Install Python 3.10 or newer." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "error: $PYTHON is $("$PYTHON" --version); this project needs 3.10+." >&2
  echo "       Set PYTHON=/path/to/python3.x and re-run." >&2
  exit 1
fi

if [ ! -d api/.venv ]; then
  echo "==> creating virtualenv with $($PYTHON --version)"
  "$PYTHON" -m venv api/.venv
fi

echo "==> installing python dependencies"
api/.venv/bin/pip install --quiet --upgrade pip
api/.venv/bin/pip install --quiet -r api/requirements.txt

# The Postgres driver is only fetched when a Postgres URL is actually configured,
# so the default setup stays lean.
case "${FIELD_ESTIMATE_DATABASE_URL:-}" in
  postgres*)
    echo "==> installing postgres driver"
    api/.venv/bin/pip install --quiet -r api/requirements-postgres.txt
    ;;
esac

# --- node --------------------------------------------------------------------

if ! command -v npm >/dev/null 2>&1; then
  echo "error: npm not found. Install Node 18 or newer." >&2
  exit 1
fi

if [ ! -d web/node_modules ]; then
  echo "==> installing web dependencies"
  (cd web && npm install --silent)
fi

# --- run ---------------------------------------------------------------------

# Kill the API when this script exits, however it exits, so a Ctrl-C does not
# leave an orphan holding port 8000.
cleanup() {
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "==> starting API on http://localhost:$API_PORT (docs at /docs)"
(cd api && exec .venv/bin/uvicorn app.main:app --port "$API_PORT" --reload) &
API_PID=$!

# Wait for the API to answer before starting the UI, so the first page load does
# not race the server and show a connection error.
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "==> starting web app on http://localhost:$WEB_PORT"
cd web && exec npm run dev -- --port "$WEB_PORT"
