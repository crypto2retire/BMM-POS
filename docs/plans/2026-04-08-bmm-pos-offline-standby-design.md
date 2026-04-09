# BMM-POS Offline Standby Design

Date: 2026-04-08

## Goal

Run BMM-POS on the Mac Mini as an outage-mode standby instance that can take over when internet access is down. The local app must use locally restored operational data, accept offline-safe payment types, and route AI features to a locally hosted model.

## Scope

This implementation covers the first four setup steps for outage mode:

1. Dedicated local offline runtime env
2. Local Postgres-backed app runtime using the operational backup snapshot
3. Explicit offline behavior for payments and AI
4. Mac launch assets for running BMM-POS on `127.0.0.1:8001`

## Decisions

### Runtime model

- The outage node runs as an always-on local standby on `127.0.0.1:8001`.
- Nginx continues to proxy `/pos/` to that local port.
- The local app reads a dedicated env file instead of trying to reuse cloud-only vars.

### Local data source

- The operational backup snapshot remains the portable backup artifact.
- The local runtime uses Postgres, not the snapshot file directly.
- A restore wrapper loads the latest snapshot into a local fallback database before first use or on demand.
- Startup can optionally trigger a restore with `OFFLINE_RESTORE_ON_START=1`.

### Offline payment behavior

- Allowed direct tenders in outage mode:
  - `cash`
  - `gift_card`
  - `crypto_blackbox`
- `split` stays available only for gift-card-plus-cash use. Card-backed split is rejected in offline mode.
- `card` payments are rejected in offline mode with a clear error message.
- `crypto_blackbox` is stored without a schema migration by persisting the operator reference in the existing `card_transaction_id` column.

### Offline AI behavior

- In outage mode, assistant endpoints use a local OpenAI-compatible endpoint instead of OpenRouter.
- Default local endpoint: `http://127.0.0.1:11434/v1`
- Default model: `llama3.2:latest`
- Vision/image search can use a separate `LOCAL_LLM_VISION_MODEL`. If no local vision model is configured, the feature fails clearly instead of appearing broken.

### UI behavior

- POS UIs should visibly indicate offline mode.
- Card actions are hidden/disabled in offline mode.
- A `Crypto / Blackbox` action is exposed in offline mode.
- Split payment hides the card leg when offline but still allows gift card plus cash.

## Files to add or change

### App runtime

- `app/config.py`
- `app/services/llm_gateway.py`
- `app/routers/assistant.py`
- `app/routers/storefront_assistant.py`
- `app/routers/pos.py`
- `app/routers/sales.py`
- `app/schemas/sale.py`

### POS UI

- `frontend/pos/index.html`
- `frontend/pos/register.html`

### Launch and restore

- `scripts/run_offline_pos.sh`
- `scripts/restore_offline_operational_backup.sh`
- `scripts/launchd/offline-pos.env.example`
- `scripts/launchd/com.bmmpos.offline-pos.plist.example`
- `docs/offline-pos-standby-setup.md`

## Verification target

- App boots locally with only the offline env file.
- `curl http://127.0.0.1:8001/health` succeeds.
- `GET /api/v1/pos/runtime` reports offline mode and local AI mode.
- Cash sale succeeds offline.
- Gift card sale succeeds offline.
- Card payment is blocked offline.
- Assistant chat routes through the local LLM path.
- Launchd assets are present and documented.

## Known follow-up items

- Continuous cloud-to-local sync is still separate from this patch. This implementation provides restore/startup tooling and the local outage runtime path.
- Any OpenRouter-dependent features outside the primary POS and assistant flows should be migrated separately if they are needed offline.
