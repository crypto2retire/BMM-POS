# Infrastructure Reconstruction Checklist — 2026-04-04

This checklist maps the April 4 handoff onto the current local BMM-POS codebase.

## 1. Root Build Detection Cleanup

### Current state

- Root still contains:
  - `package.json`
  - `package-lock.json`
  - `package 2.json`
  - `package-lock 2.json`
- `.gitignore` still ignores `uv.lock`
- `.replit` exists at repo root

### Reconstruction work

- Move root Replit Node files out of the repo root into `replit/`
  - `package.json`
  - `package-lock.json`
- Decide whether `package 2.json` and `package-lock 2.json` are stale duplicates and remove or archive them
- Update `.gitignore` to stop ignoring `uv.lock`

### Verification

- Repo root should not contain a build-triggering `package.json`
- `uv.lock` should be trackable

## 2. Add `nixpacks.toml`

### Current state

- No `nixpacks.toml` exists in this repo

### Reconstruction work

- Create `nixpacks.toml` in repo root
- Force Python build/install path
- Match handoff intent:
  - Python 3.11
  - `pip install -r requirements.txt --break-system-packages`

### Verification

- File exists at repo root
- Railway build should no longer prefer Node

## 3. Add `railway.toml`

### Current state

- No `railway.toml` exists in this repo

### Reconstruction work

- Create `railway.toml` in repo root
- Include:
  - `preDeployCommand = "python scripts/migrate.py"`
  - `python -m gunicorn`
  - `uvicorn.workers.UvicornWorker`
  - 2 workers
  - `$PORT` binding
  - `/health` healthcheck
  - 120s timeout
  - restart-on-failure policy

### Verification

- File exists at repo root
- config matches handoff

## 4. Create `scripts/migrate.py`

### Current state

- No `scripts/migrate.py`
- `app/main.py` still performs heavy schema/index/backfill work during startup

### Reconstruction work

- Create `scripts/migrate.py`
- Move startup DDL / one-time data fixes out of `app/main.py`
- Include at minimum:
  - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` blocks currently in `app/main.py`
  - `CREATE INDEX IF NOT EXISTS ...` blocks currently in `app/main.py`
  - startup markers and one-time backfills currently embedded in `app/main.py`
  - storefront composite index:
    - `idx_items_online_active`

### Current heavy logic in `app/main.py`

- `ALTER TABLE vendors ...`
- `ALTER TABLE items ...`
- `ALTER TABLE sale_items ...`
- `ALTER TABLE sales ...`
- `ALTER TABLE reservations ...`
- booth/studio/poynt/eod column/index creation
- one-time startup markers:
  - import source backfill
  - consignment cleanup
  - vendor payout default
  - rent balance migration

### Verification

- `scripts/migrate.py` exists
- startup DDL logic removed from `app/main.py`

## 5. Trim `app/main.py`

### Current state

- `app/main.py` still contains large startup migration sections
- `lifespan()` currently runs schema create plus many DDL/backfill tasks

### Reconstruction work

- Keep only:
  - model registration
  - `Base.metadata.create_all`
  - DB connectivity check
  - vendor balance row backfill
  - seed-if-empty
- remove migration-style startup work and move it into `scripts/migrate.py`

### Verification

- `rg "ALTER TABLE|CREATE INDEX" app/main.py` should be minimal or empty
- startup path should be short and operational only

## 6. Create `app/services/spaces.py`

### Current state

- No `app/services/spaces.py`
- no Spaces helper exists in current tree

### Reconstruction work

- Create shared Spaces upload/delete helper
- Expected responsibilities from handoff:
  - upload bytes to DigitalOcean Spaces via `boto3`
  - delete object helper
  - graceful fallback to local disk if Spaces env vars are not set
  - return public CDN/origin URL

### Verification

- file exists
- imports `boto3`
- reads:
  - `DO_SPACES_KEY`
  - `DO_SPACES_SECRET`
  - `DO_SPACES_REGION`
  - `DO_SPACES_BUCKET`
  - `DO_SPACES_CDN_ENDPOINT`

## 7. Update `app/routers/items.py`

### Current state

Current image upload paths still write to local disk and DB blobs:

- `POST /items/{item_id}/photo`
  - writes to `frontend/static/images/items`
  - writes blob to `item_images`
  - sets `item.image_path = "/api/v1/items/{item_id}/image"`
- `POST /items/{item_id}/upload-image`
  - writes to `frontend/static/uploads/items`
  - writes blob to `item_images`
  - sets `item.image_path = "/api/v1/items/{item_id}/image"`

### Reconstruction work

- route both upload endpoints through `app/services/spaces.py`
- store public URL in `item.image_path`
- keep `/api/v1/items/{item_id}/image` as fallback for legacy blob-backed images
- preserve current behavior for existing DB-blob items

### Verification

- new uploads should not set `image_path` to the API route
- new uploads should return a stable public object-storage URL

## 8. Update `app/routers/booth_showcase.py`

### Current state

Current showcase uploads still write to local disk:

- `POST /mine/photo`
  - writes to local `UPLOAD_DIR`
  - appends `/static/uploads/booths/...`
- `DELETE /mine/photo`
  - deletes local file
- `POST /mine/video`
  - writes local video file
  - deletes old local video

### Reconstruction work

- move photo upload/delete to Spaces helper
- move video upload/delete to Spaces helper
- store public URLs instead of local static paths

### Verification

- new showcase media URLs should be object-storage URLs, not `/static/uploads/...`

## 9. Update `app/routers/studio.py`

### Current state

Current class image upload:

- `POST /classes/{class_id}/image`
  - writes local file to `STUDIO_UPLOAD_DIR`
  - writes blob to `StudioImage`
  - sets `c.image_url = "/api/v1/studio/classes/{class_id}/image"`

### Reconstruction work

- route class image upload/delete through Spaces helper
- store public URL in `image_url`
- keep legacy image endpoint as fallback if needed

### Verification

- new class images should not point to the API image route

## 10. Update `app/routers/pos.py`

### Current state

- POS item dict currently includes `photo_urls`
- handoff says `image_path` was added to `_item_to_pos_dict`

### Reconstruction work

- ensure POS search/result payload exposes `image_path`
- keep compatibility with legacy fallback

### Verification

- POS search payload should include `image_path`

## 11. Update `frontend/pos/index.html`

### Current state

- image search results still hardcode:
  - `const imgSrc = \`/api/v1/items/${item.id}/image\`;`

### Reconstruction work

- prefer `item.image_path`
- fallback to `/api/v1/items/${item.id}/image` only when `image_path` is missing

### Verification

- POS image results should use CDN/object URLs for new uploads
- legacy imports should still render

## 12. Index / Performance Verification

### Required index from handoff

```sql
CREATE INDEX IF NOT EXISTS idx_items_online_active
ON items(status, is_online, quantity)
WHERE status = 'active' AND is_online = true;
```

### Verification

- index creation should live in `scripts/migrate.py`, not `app/main.py`

## 13. Pending Local Label Fix To Reapply After Repo Recovery

File:
- `app/services/labels.py`

Current local-only changes already made:

- make `30347` Dymo layout barcode-first
- separate barcode text from barcode object
- increase quiet zones
- reduce text pressure on the small label
- tighten PDF fallback path for `1.5x1`

Do not lose this during repo recovery.
