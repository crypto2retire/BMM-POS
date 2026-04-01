# Cursor Task: Fix Timezone to Follow Wall Clock (America/Chicago)

## Problem

`app/timezone.py` is set to fixed UTC-6, but the store wants times to match the wall clock in Oshkosh, WI — which means `America/Chicago` (CST in winter, CDT in summer). Receipts and displays need to show the correct local time year-round.

---

## Step 1: Fix the Timezone Constant

### File: `app/timezone.py`

**Replace the entire file contents with:**

```python
"""
Store timezone — America/Chicago (CST/CDT).
Follows wall clock time in Oshkosh, WI.
Import this everywhere instead of using ZoneInfo("America/Chicago") directly.
"""
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Chicago")
```

---

## Step 2: Fix the Display Label in `_format_cst`

### File: `app/routers/pos.py`

**Find:**
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

**Replace with:**
```python
def _format_cst(dt):
    """Format a datetime as a display string in store local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    local_dt = dt.astimezone(STORE_TZ)
    tz_abbr = local_dt.strftime("%Z")  # "CST" or "CDT" depending on time of year
    return local_dt.strftime("%b %-d, %Y at %-I:%M %p") + f" {tz_abbr}"
```

### File: `app/routers/sales.py`

If this file also has a `_format_cst` function, apply the same change — replace the hardcoded `" CST"` with `f" {tz_abbr}"` using `local_dt.strftime("%Z")`.

---

## Step 3: Update Frontend Fallback

### File: `frontend/pos/index.html`

Anywhere the JavaScript fallback uses `timeZone: 'Etc/GMT+6'`, change it to `timeZone: 'America/Chicago'`. Search for all instances of `Etc/GMT+6` and replace with `America/Chicago`.

If there are no instances of `Etc/GMT+6` yet (the earlier task may not have been deployed), then find the receipt display code (around line 2282):

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
    const dateStr = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Chicago' });
    const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' });
    receiptDateTime = dateStr + ' at ' + timeStr;
}
```

Then find (around line 2370):
```html
<p>${dateStr} at ${timeStr}</p>
```

**Replace with:**
```html
<p>${receiptDateTime}</p>
```

Also apply `timeZone: 'America/Chicago'` to any other `toLocaleDateString` / `toLocaleTimeString` calls used for receipt display elsewhere in this file (around lines 2426-2427, 2877-2878, 3373, 3394-3395, 3516-3517).

---

## Step 4: Fix the Cron Digest Timezone

### File: `app/routers/notifications.py`

Find inside `send_sale_digests`:
```python
CST = ZoneInfo("America/Chicago")
```

If this line still uses `ZoneInfo` directly, replace with:
```python
from app.timezone import STORE_TZ
CST = STORE_TZ
```

Or if it already imports from `app.timezone`, no change needed — updating `timezone.py` in Step 1 handles it.

---

## Files Changed

| File | Change |
|------|--------|
| `app/timezone.py` | Switch from fixed UTC-6 to `ZoneInfo("America/Chicago")` |
| `app/routers/pos.py` | Dynamic timezone label (CST/CDT) in `_format_cst` |
| `app/routers/sales.py` | Same `_format_cst` fix if present |
| `frontend/pos/index.html` | Use `created_at_display` for receipts, fallback with `America/Chicago` timezone |

## Testing

1. Make a test sale — receipt time should match your wall clock
2. The timezone label should show "CDT" right now (April, daylight saving active)
3. Check sale history — times should also match
4. Run `python3 -m py_compile app/timezone.py app/routers/pos.py`
