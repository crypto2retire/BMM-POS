#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${OFFLINE_BACKUP_ENV_FILE:-$HOME/Library/Application Support/BMM-POS/offline/offline-backup.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi
export SECRET_KEY="${SECRET_KEY:-offline-backup-local}"
cd "$REPO_ROOT"
PYTHON_CMD=(/usr/bin/env python3)
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_CMD=("$REPO_ROOT/.venv/bin/python")
fi
"${PYTHON_CMD[@]}" "$SCRIPT_DIR/offline_operational_backup.py"
