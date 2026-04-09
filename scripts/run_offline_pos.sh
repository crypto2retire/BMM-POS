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

export OFFLINE_MODE="${OFFLINE_MODE:-true}"
export SECRET_KEY="${SECRET_KEY:-offline-pos-local}"
export DATABASE_URL="${DATABASE_URL:-${OFFLINE_RESTORE_DATABASE_URL:-}}"
export OFFLINE_RESTORE_DATABASE_URL="${OFFLINE_RESTORE_DATABASE_URL:-${DATABASE_URL:-}}"
export OFFLINE_SNAPSHOT_PATH="${OFFLINE_SNAPSHOT_PATH:-$HOME/Library/Application Support/BMM-POS/offline/current-operational-backup.json.gz}"
export LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
export LOCAL_LLM_CHAT_MODEL="${LOCAL_LLM_CHAT_MODEL:-llama3.2:latest}"

cd "$REPO_ROOT"

PYTHON_CMD=(/usr/bin/env python3)
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_CMD=("$REPO_ROOT/.venv/bin/python")
fi

if [[ "${OFFLINE_RESTORE_ON_START:-0}" == "1" ]]; then
  "$SCRIPT_DIR/restore_offline_operational_backup.sh"
fi

exec "${PYTHON_CMD[@]}" -m uvicorn app.main:app \
  --host "${OFFLINE_POS_HOST:-127.0.0.1}" \
  --port "${OFFLINE_POS_PORT:-8001}"
