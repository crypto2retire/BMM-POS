# BMM-POS Recovery Plan — 2026-04-04

## Current State

- Local working tree still contains the full app source tree.
- Local git metadata is damaged.
- `origin/main` is also damaged and currently contains only:
  - `frontend/admin/index.html`
  - `frontend/admin/vendors.html`
- The following infrastructure/performance files described in the April 4 handoff are not present in this working tree:
  - `railway.toml`
  - `nixpacks.toml`
  - `scripts/migrate.py`
  - `app/services/spaces.py`
- `app/main.py` still contains heavy startup migration logic and one-time data fixes.
- `.gitignore` still ignores `uv.lock`.
- Root `package.json` and `package-lock.json` still exist.

## Verified Missing Handoff Changes

The April 4 handoff described these missing changes:

1. Force Railway/Nixpacks to build Python instead of Node.
2. Move startup migrations out of `app/main.py` and into `scripts/migrate.py`.
3. Add `railway.toml` pre-deploy/startup config.
4. Add `app/services/spaces.py` and move new image uploads to DigitalOcean Spaces.
5. Stop ignoring `uv.lock`.
6. Add storefront composite index:
   - `idx_items_online_active`

These are not recoverable from GitHub or another local clone on this Mac.
The only artifacts currently available are:

- `Downloads/bmm-pos-handoff-summary.pdf`
- Codex session logs under `.codex/sessions`

## Do Not Do While Store Is Open

- Do not push to `main`.
- Do not run repo recovery that rewrites the Git index and immediately deploys.
- Do not recreate and push missing Railway/Spaces changes blindly.

## After-Hours Recovery Sequence

### Phase 1: Snapshot and Git Recovery

1. Create a filesystem backup of the current repo directory before touching git.
2. Record current local file inventory counts for `app/`, `frontend/`, and `scripts/`.
3. Repair git by rebuilding the index from the local working tree, not from GitHub.
4. Restore a healthy repository state with the full project tree committed.
5. Push only after confirming the recovered commit still contains the full app.

### Phase 2: Immediate Post-Recovery Verification

1. Verify GitHub tree contains the expected project directories.
2. Verify key app files still exist:
   - `app/main.py`
   - `app/routers/pos.py`
   - `app/routers/items.py`
   - `frontend/pos/index.html`
   - `frontend/vendor/items.html`
3. Verify Railway is not auto-deploying a broken intermediate state.

### Phase 3: Reconstruct Missing Infra Changes

Recreate and test these in order:

1. `nixpacks.toml`
   - force Python build
   - stop Node-first detection
2. `railway.toml`
   - preDeploy migration command
   - `python -m gunicorn`
   - 2 workers
   - `/health` check
3. `scripts/migrate.py`
   - move schema/index/backfill work out of startup
4. trim `app/main.py`
   - keep `create_all`
   - keep DB connectivity check
   - keep vendor balance backfill
   - keep seed-if-empty
   - remove large startup migration batches
5. `app/services/spaces.py`
   - shared upload/delete helper
6. image upload routes
   - `items.py`
   - `booth_showcase.py`
   - `studio.py`
   - `pos.py`
   - `frontend/pos/index.html`
7. `.gitignore`
   - stop ignoring `uv.lock`
8. root packaging cleanup
   - move Replit `package.json` files out of repo root if still needed

### Phase 4: Reapply Pending Local Fixes

Once repo recovery is complete, reapply and push the current local label fix:

- `app/services/labels.py`
  - make `30347` barcode-first
  - separate barcode text from barcode object
  - increase quiet zones
  - reduce text pressure on the small label

## Pre-Push Verification Checklist

- `git ls-files | wc -l` shows a sane file count, not `2`
- `git ls-tree -r --name-only HEAD | wc -l` shows a sane file count
- `python3 -m compileall app`
- spot-check:
  - POS opens
  - vendor items page opens
  - admin dashboard opens
  - labels still generate
  - `/health` still responds

## High-Risk Items

- Do not rely on current GitHub as a source of truth.
- Do not assume the April 4 handoff changes exist anywhere except the PDF and session logs.
- DigitalOcean keys from the handoff should be treated as compromised and rotated before any fresh Spaces deployment.
