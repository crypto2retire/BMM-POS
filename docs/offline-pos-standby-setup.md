# BMM-POS Offline Standby Setup

## Purpose

Run BMM-POS locally on the Mac Mini as the outage-mode POS at `127.0.0.1:8001`, backed by the operational snapshot and a local Postgres database.

## Files added for this setup

- `scripts/run_offline_pos.sh`
- `scripts/restore_offline_operational_backup.sh`
- `scripts/launchd/offline-pos.env.example`
- `scripts/launchd/com.bmmpos.offline-pos.plist.example`

## 1. Create the local Postgres database

Example:

```bash
createdb bmm_pos_offline
```

Use that database URL in the offline env file.

## 2. Create the offline env file

Copy:

```bash
cp scripts/launchd/offline-pos.env.example "$HOME/Library/Application Support/BMM-POS/offline/offline-pos.env"
```

Set at minimum:

- `SECRET_KEY`
- `DATABASE_URL`
- `OFFLINE_RESTORE_DATABASE_URL`
- `OFFLINE_MODE=true`
- `LOCAL_LLM_BASE_URL`
- `LOCAL_LLM_CHAT_MODEL`

Optional:

- `LOCAL_LLM_VISION_MODEL` for image search
- `OFFLINE_RESTORE_ON_START=1` to restore snapshot before each app launch

## 3. Restore the latest operational snapshot into local Postgres

```bash
scripts/restore_offline_operational_backup.sh
```

That loads:

- `~/Library/Application Support/BMM-POS/offline/current-operational-backup.json.gz`

into the local Postgres database specified by `OFFLINE_RESTORE_DATABASE_URL`.

## 4. Start the local outage-mode app

```bash
scripts/run_offline_pos.sh
```

Expected local health check:

```bash
curl http://127.0.0.1:8001/health
```

Expected runtime check:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8001/api/v1/pos/runtime
```

## 5. Install the launch agent

Copy the plist example to:

```bash
~/Library/LaunchAgents/com.bmmpos.offline-pos.plist
```

Update:

- repo path
- username
- env file path
- log paths

Then load it:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.bmmpos.offline-pos.plist
launchctl kickstart -k "gui/$(id -u)/com.bmmpos.offline-pos"
```

## Offline behavior in this setup

- cash works
- gift card works
- split payment supports gift card plus cash
- card processing is blocked
- `crypto_blackbox` is available as a manually confirmed payment type
- assistant chat routes to the local LLM when `OFFLINE_MODE=true`

## Important note

This gives the Mac a local outage runtime and restore path. It does not replace the need to refresh the operational snapshot regularly so the local database stays current before an outage occurs.
