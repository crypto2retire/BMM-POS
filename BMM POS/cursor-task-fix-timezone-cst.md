# Cursor Task: Pin All Times to CST (UTC-6) — No Daylight Saving

## Problem

The system uses `America/Chicago` which auto-switches between CST (UTC-6) and CDT (UTC-5). This causes receipt times and other displays to shift by an hour during daylight saving. The store wants everything permanently pinned to **CST (UTC-6)** year-round.

Additionally, receipt timestamps depend on the browser's local timezone via JavaScript's `toLocaleTimeString()`, so if someone opens POS from a different timezone the times are wrong.

---

## Strategy

1. **Backend**: Replace all `ZoneInfo("America/Chicago")` with a fixed UTC-6 offset
2. **Frontend**: Force CST display on all date/time formatting by specifying `timeZone: 'America/Chicago'` isn't good enough (it follows DST). Instead, the backend should return a pre-formatted CST timestamp string alongside the raw `created_at`, and the frontend should use that.

The cleanest approach: add a `created_at_cst` string field to the sale API response, formatted server-side in fixed CST.

---

## Step 1: Create a Shared CST Timezone Constant

### New file: `app/timezone.py`

```python
"""
Store timezone — fixed CST (UTC-6), no daylight saving adjustment.
Import this everywhere instead of using ZoneInfo("America/Chicago").
"""
from datetime import timezone, timedelta

STORE_TZ = timezone(timedelta(hours=-6), name="CST")
```

---

## Step 2: Update Backend Files to Use Fixed CST

### File: `app/routers/sales.py`

**Find** (near top):
```python
from zoneinfo import ZoneInfo

_STORE_TZ = ZoneInfo("America/Chicago")
```

**Replace with:**
```python
from app.timezone import STORE_TZ as _STORE_TZ
```

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

### File: `app/routers/reports.py`

**Find** (near top):
```python
from zoneinfo import ZoneInfo
```
and:
```python
STORE_TZ = ZoneInfo("America/Chicago")
```

**Replace with:**
```python
from app.timezone import STORE_TZ
```

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

### File: `app/routers/pos.py`

This file uses `ZoneInfo("America/Chicago")` inline in multiple places.

**Find** the import:
```python
from zoneinfo import ZoneInfo
```

**Add this import:**
```python
from app.timezone import STORE_TZ
```

Then **find and replace every instance** of:
```python
ZoneInfo("America/Chicago")
```
with:
```python
STORE_TZ
```

There should be about 4-5 occurrences in this file (in `_get_active_price`, EOD report, starting cash set/get, etc.).

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

### File: `app/routers/notifications.py`

**Find:**
```python
from zoneinfo import ZoneInfo
```
and inside `send_sale_digests`:
```python
CST = ZoneInfo("America/Chicago")
```

**Replace the import with:**
```python
from app.timezone import STORE_TZ
```

**Replace inside `send_sale_digests`:**
```python
CST = ZoneInfo("America/Chicago")
```
with:
```python
CST = STORE_TZ
```

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

### File: `app/services/email_templates.py`

**Find:**
```python
from zoneinfo import ZoneInfo
```
and:
```python
CST = ZoneInfo("America/Chicago")
```

**Replace with:**
```python
from app.timezone import STORE_TZ
CST = STORE_TZ
```

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

### File: `app/routers/admin.py`

**Find** (inside the weekly report function):
```python
from zoneinfo import ZoneInfo
cst = ZoneInfo("America/Chicago")
```

**Replace with:**
```python
from app.timezone import STORE_TZ
cst = STORE_TZ
```

Remove the `from zoneinfo import ZoneInfo` line if it's no longer used elsewhere in this file.

---

## Step 3: Add Pre-Formatted CST Timestamp to Sale API Response

### File: `app/schemas/sale.py`

**Add this field to `SaleResponse`** (after the `created_at: datetime` line):

```python
    created_at_display: Optional[str] = None
```

Also add `Optional` to the imports if not there:
```python
from typing import Optional, List
```

---

### File: `app/routers/pos.py`

Find the code that builds/returns the `SaleResponse` after creating a sale. There are likely multiple places where a sale response dict or object is constructed. In each place where `created_at` is included in the response, also add a `created_at_display` field.

**Add this helper function** near the top of the file (after imports):

```python
def _format_cst(dt):
    """Format a datetime as a display string in fixed CST."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    cst_dt = dt.astimezone(STORE_TZ)
    return cst_dt.strftime("%b %-d, %Y at %-I:%M %p") + " CST"
```

Then wherever a sale response is returned (look for `SaleResponse` or dict construction with `created_at`), add:

```python
created_at_display=_format_cst(sale.created_at),
```

**Also update the sale lookup/receipt endpoint** in `app/routers/sales.py` — add the same helper and include `created_at_display` in responses.

Add to `app/routers/sales.py` near the top:

```python
def _format_cst(dt):
    """Format a datetime as a display string in fixed CST."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    cst_dt = dt.astimezone(_STORE_TZ)
    return cst_dt.strftime("%b %-d, %Y at %-I:%M %p") + " CST"
```

And include `created_at_display` wherever sale responses are returned.

---

## Step 4: Update Frontend Receipt to Use Server-Formatted Time

### File: `frontend/pos/index.html`

**Find** (around line 2282):
```javascript
const now = new Date(sale.created_at || Date.now());
const dateStr = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
```

**Replace with:**
```javascript
let receiptDateTime;
if (sale.created_at_display) {
    receiptDateTime = sale.created_at_display;
} else {
    const now = new Date(sale.created_at || Date.now());
    const dateStr = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'Etc/GMT+6' });
    const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'Etc/GMT+6' });
    receiptDateTime = dateStr + ' at ' + timeStr + ' CST';
}
```

**Find** (around line 2370):
```html
<p>${dateStr} at ${timeStr}</p>
```

**Replace with:**
```html
<p>${receiptDateTime}</p>
```

**Do the same for the receipt lookup function** — find any other `toLocaleDateString`/`toLocaleTimeString` calls used for receipt display (around lines 2426-2427, 2877-2878, 3373, 3394-3395, 3516-3517) and add `timeZone: 'Etc/GMT+6'` to each options object as a fallback.

> **Note:** `Etc/GMT+6` is IANA for fixed UTC-6 (the sign is inverted from what you'd expect — `GMT+6` means UTC-6). This forces the browser to display in CST regardless of the user's system timezone.

---

## Step 5: Update POS Toast Notifications

### File: `frontend/pos/index.html`

**Find** (around line 2768):
```javascript
time: new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
```

**Replace with:**
```javascript
time: new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'Etc/GMT+6' })
```

---

## Step 6: Update Admin Dashboard Date Displays

### File: `frontend/admin/index.html`

Find date formatting like:
```javascript
var d = new Date(o.date || o.created_at);
var dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
```

Add `timeZone: 'Etc/GMT+6'` to the options:
```javascript
var dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'Etc/GMT+6' });
```

Do the same for any `toLocaleTimeString` calls in admin pages.

---

### File: `frontend/admin/rent.html`

Find:
```javascript
new Date(p.processed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
```

Add `timeZone: 'Etc/GMT+6'`:
```javascript
new Date(p.processed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'Etc/GMT+6' })
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `app/timezone.py` | **NEW** — shared fixed CST constant |
| `app/routers/sales.py` | Use `STORE_TZ` from `app.timezone`, add `_format_cst`, add `created_at_display` |
| `app/routers/reports.py` | Use `STORE_TZ` from `app.timezone` |
| `app/routers/pos.py` | Use `STORE_TZ` from `app.timezone`, add `_format_cst`, add `created_at_display` |
| `app/routers/notifications.py` | Use `STORE_TZ` from `app.timezone` |
| `app/routers/admin.py` | Use `STORE_TZ` from `app.timezone` |
| `app/services/email_templates.py` | Use `STORE_TZ` from `app.timezone` |
| `app/schemas/sale.py` | Add `created_at_display` field |
| `frontend/pos/index.html` | Use `created_at_display` for receipts, fallback with `Etc/GMT+6`, toast times |
| `frontend/admin/index.html` | Add `timeZone: 'Etc/GMT+6'` to date formatting |
| `frontend/admin/rent.html` | Add `timeZone: 'Etc/GMT+6'` to date formatting |

## Testing

1. Make a test sale — receipt should show correct CST time with "CST" label
2. Check the time matches your wall clock minus any DST offset (right now it's CDT/UTC-5, so CST will be 1 hour behind CDT)
3. View sales history — times should all show CST
4. Check admin dashboard recent sales — times should show CST
5. Check reports — hourly breakdown should use CST hours
6. Run `py_compile` on all changed Python files

## Important Note

Since you're pinning to CST year-round, during summer months (when CDT is active) the displayed times will be 1 hour behind wall clock time. This is intentional — it keeps times consistent year-round and matches your preference. If you ever want to switch to following daylight saving, just change `app/timezone.py` back to `ZoneInfo("America/Chicago")`.
