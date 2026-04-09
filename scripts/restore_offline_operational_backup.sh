#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${OFFLINE_POS_ENV_FILE:-$HOME/Library/Application Support/BMM-POS/offline/offline-pos.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

export SECRET_KEY="${SECRET_KEY:-offline-pos-local}"
export OFFLINE_RESTORE_DATABASE_URL="${OFFLINE_RESTORE_DATABASE_URL:-${DATABASE_URL:-}}"
SNAPSHOT_PATH="${OFFLINE_SNAPSHOT_PATH:-$HOME/Library/Application Support/BMM-POS/offline/current-operational-backup.json.gz}"

if [[ -z "${OFFLINE_RESTORE_DATABASE_URL:-}" ]]; then
  echo "OFFLINE_RESTORE_DATABASE_URL or DATABASE_URL is required" >&2
  exit 2
fi

cd "$REPO_ROOT"

PYTHON_CMD=(/usr/bin/env python3)
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_CMD=("$REPO_ROOT/.venv/bin/python")
fi

exec "${PYTHON_CMD[@]}" "$SCRIPT_DIR/offline_operational_restore.py" \
  --input "$SNAPSHOT_PATH" \
  --database-url "$OFFLINE_RESTORE_DATABASE_URL" \
  --force
