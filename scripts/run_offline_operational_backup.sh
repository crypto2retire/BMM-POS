#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${OFFLINE_BACKUP_ENV_FILE:-$HOME/Library/Application Support/BMM-POS/offline/offline-backup.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

exec /usr/bin/env python3 "$SCRIPT_DIR/offline_operational_backup.py"
