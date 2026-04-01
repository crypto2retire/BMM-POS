# Cursor Task: Set Up Railway Cron Jobs for Sale Digest Emails

## Overview

The `POST /api/v1/notifications/send-sale-digests?period=daily|weekly|monthly` endpoint exists and works, but it requires admin JWT auth. We need:

1. A cron-safe auth method (shared secret via env var) so Railway cron jobs can call it without logging in
2. A small cron script in the repo
3. Railway cron service configuration

---

## Step 1: Add Cron Secret Auth to the Digest Endpoint

### File: `app/routers/notifications.py`

**A) Add these imports at the top** (skip any already present):

```python
import os
from fastapi import Header
from typing import Optional
```

**B) Replace the `send_sale_digests` endpoint signature and its first few lines** — change from requiring `_admin: Vendor = Depends(require_admin)` to accepting either admin JWT OR a cron secret header:

Find this:
```python
@router.post("/send-sale-digests")
async def send_sale_digests(
    period: str = "daily",
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
```

Replace with:
```python
@router.post("/send-sale-digests")
async def send_sale_digests(
    period: str = "daily",
    db: AsyncSession = Depends(get_db),
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    # Auth: accept either a valid cron secret OR admin JWT
    cron_secret = os.getenv("CRON_SECRET")
    if x_cron_secret and cron_secret and x_cron_secret == cron_secret:
        pass  # Cron auth OK
    elif authorization:
        # Fall back to normal admin JWT check
        from app.routers.auth import require_admin as _require_admin_fn
        # Manual JWT validation — extract token and verify
        from app.routers.auth import get_current_user
        from fastapi import Request
        token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
        try:
            from jose import jwt as jose_jwt
            from app.routers.auth import SECRET_KEY, ALGORITHM
            payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            role = payload.get("role")
            if role != "admin":
                raise HTTPException(status_code=403, detail="Admin only")
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        raise HTTPException(status_code=401, detail="Auth required: send X-Cron-Secret header or admin Bearer token")
```

> **Why this approach:** The existing admin JWT flow still works for manual testing from the browser/Postman, but Railway cron jobs just send the `X-Cron-Secret` header — no login step needed.

---

## Step 2: Create the Cron Script

### New file: `cron_digest.py` (in the project root)

```python
"""
Lightweight cron script for Railway.
Called with: python cron_digest.py <period>
Where period is: daily, weekly, or monthly

Requires env vars:
  CRON_SECRET  — shared secret matching the one in the app
  APP_URL      — base URL of the running app (e.g. https://bmm-pos-production.up.railway.app)
"""
import os
import sys
import urllib.request
import urllib.error
import json

def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if period not in ("daily", "weekly", "monthly"):
        print(f"Invalid period: {period}")
        sys.exit(1)

    app_url = os.environ.get("APP_URL", "").rstrip("/")
    cron_secret = os.environ.get("CRON_SECRET", "")

    if not app_url:
        print("ERROR: APP_URL env var not set")
        sys.exit(1)
    if not cron_secret:
        print("ERROR: CRON_SECRET env var not set")
        sys.exit(1)

    url = f"{app_url}/api/v1/notifications/send-sale-digests?period={period}"
    print(f"Calling {url} ...")

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Cron-Secret": cron_secret,
            "Content-Type": "application/json",
        },
        data=b"",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            print(f"OK: {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

> **No extra dependencies** — uses only Python stdlib so it runs without installing anything.

---

## Step 3: Railway Setup Instructions (Manual Steps for Kevin)

After deploying the code changes above:

### A) Set Environment Variables in Railway

In your BMM-POS Railway service, add these env vars:

| Variable | Value |
|----------|-------|
| `CRON_SECRET` | Generate a random string (e.g. `openssl rand -hex 32` in terminal) |
| `APP_URL` | Your Railway app URL (e.g. `https://bmm-pos-production.up.railway.app`) |

### B) Create 3 Railway Cron Services

In your Railway project, create 3 new **Cron Job** services. Each one uses the same repo/Docker setup but with a different schedule and command:

**1. Daily Sale Digest**
- **Name:** `bmm-digest-daily`
- **Schedule:** `0 1 * * *` (1:00 AM UTC = 7:00 PM CST)
- **Command:** `python cron_digest.py daily`
- **Env vars:** Same `CRON_SECRET` and `APP_URL` as the main service

**2. Weekly Sale Digest**
- **Name:** `bmm-digest-weekly`
- **Schedule:** `0 14 * * 1` (2:00 PM UTC Monday = 8:00 AM CST Monday)
- **Command:** `python cron_digest.py weekly`
- **Env vars:** Same `CRON_SECRET` and `APP_URL` as the main service

**3. Monthly Sale Digest**
- **Name:** `bmm-digest-monthly`
- **Schedule:** `0 14 1 * *` (2:00 PM UTC on 1st = 8:00 AM CST on 1st)
- **Command:** `python cron_digest.py monthly`
- **Env vars:** Same `CRON_SECRET` and `APP_URL` as the main service

> **UTC conversion (fixed CST = UTC-6, no daylight saving):** 7pm CST = 1:00 AM UTC next day. 8am CST = 2:00 PM UTC. These never change — the system is pinned to CST year-round.

---

## Files Changed
- `app/routers/notifications.py` — dual auth (cron secret + admin JWT) on digest endpoint
- `cron_digest.py` — new file, lightweight cron script

## Files NOT Changed
- Everything else stays the same

## Testing
1. Deploy the code
2. Set `CRON_SECRET` env var in Railway (same value for main service and cron services)
3. Set `APP_URL` env var in Railway
4. Test manually from terminal: `CRON_SECRET=yoursecret APP_URL=https://your-app.up.railway.app python cron_digest.py daily`
5. Verify a digest email is sent (or "No vendors with daily preference" if no one has daily set)
6. Verify the old admin JWT method still works too
