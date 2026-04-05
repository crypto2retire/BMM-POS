# PRIORITY 1: Remove All Consignment Data — Vendors Must Get Paid

## Problem

ALL items in the database are marked `is_consignment = true` with `consignment_rate = 1.0` (100% to store, 0% to vendor). This means vendors get $0 when their items sell. This is caused by the original Ricochet import and the Edit Item UI still allows setting consignment. A previous startup migration was supposed to clean this up but either failed silently or items were re-saved with consignment via the UI.

**None of the 120 vendors are consignment. All vendors get 100% of their sales.** The consignment feature should be completely hidden from the UI and forced to false on all saves.

---

## Step 1: Force-Clean Database on Startup (Bulletproof)

### File: `app/main.py`

The existing cleanup at line ~278 may have run inside a transaction that rolled back. Make it standalone and add logging so we can confirm it ran.

**Find the existing consignment cleanup block:**
```python
            # ── Clear consignment flags on all items (Ricochet junk data) ──
            await session.execute(text("""
                UPDATE items
                SET is_consignment = false,
                    consignment_rate = NULL
                WHERE is_consignment = true
            """))
```

**Replace with a standalone block that runs in its own try/except and its own session, AFTER the main migration commit. Add it right after the existing `await session.commit()` and before the final `except`:**

Actually, to be absolutely sure, add a brand new standalone block AFTER the entire migration try/except. Find the line:

```python
    except Exception as e:
        print(f"BMM-POS: column migration FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
```

**Add this NEW block immediately after it (before the "Verify connectivity" section):**

```python
    # ── PRIORITY: Force-clear ALL consignment flags ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                UPDATE items
                SET is_consignment = false,
                    consignment_rate = NULL
                WHERE is_consignment = true OR consignment_rate IS NOT NULL
            """))
            await session.commit()
            count = result.rowcount
            if count > 0:
                print(f"BMM-POS: CLEARED consignment flags on {count} items", file=sys.stderr, flush=True)
            else:
                print("BMM-POS: consignment check OK — no items flagged", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: CRITICAL — consignment cleanup failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
```

You can also remove the old consignment cleanup from inside the migration block (the one at line ~278) since this new one replaces it.

---

## Step 2: Force consignment = false on ALL Item Creates and Updates

### File: `app/routers/items.py`

**A) In the `create_item` function (the POST endpoint), find:**
```python
        is_consignment=data.is_consignment or False,
        consignment_rate=data.consignment_rate,
```

**Replace with:**
```python
        is_consignment=False,
        consignment_rate=None,
```

**B) In the `update_item` function (the PUT endpoint), add these two lines right BEFORE `for field, value in update_data.items():`:**

```python
    update_data.pop("is_consignment", None)
    update_data.pop("consignment_rate", None)
    update_data["is_consignment"] = False
    update_data["consignment_rate"] = None
```

This ensures that no matter what the UI sends, items are NEVER saved as consignment.

---

### File: `app/routers/pos.py`

**Find in the quick-add item endpoint (around line 151):**
```python
    is_consignment = body.get("is_consignment", False)
    consignment_rate = body.get("consignment_rate")
```
and the validation below it:
```python
    if is_consignment and consignment_rate is None:
        raise HTTPException(status_code=400, detail="consignment_rate is required for consignment items")
    if consignment_rate is not None and (consignment_rate < 0 or consignment_rate > 1):
        raise HTTPException(status_code=400, detail="consignment_rate must be between 0 and 1")
    if not is_consignment:
        consignment_rate = None
```

**Replace ALL of those lines with:**
```python
    is_consignment = False
    consignment_rate = None
```

---

### File: `app/routers/bulk_import.py`

Already patched to set `consignment = False` and `consignment_rate = None`. Verify these lines are present:
- Around line 290: `consignment = False` and `consignment_rate = None`
- Around line 336: `consignment = False` and `consignment_rate = None`
- Around line 678: `is_consignment = False`
- Around line 693: `is_consignment = False`

No changes needed if already correct.

---

### File: `app/routers/inventory_verify.py`

Already patched (line ~258): `is_consignment = False` and `consignment_rate = None`. Verify, no changes needed.

---

## Step 3: Hide Consignment from ALL Frontend UIs

### File: `frontend/vendor/items.html`

Search for any consignment checkbox, consignment rate input, or related UI elements in the Edit Item modal and the Add Item form. **Hide or remove them entirely.**

Look for elements like:
- A checkbox with label "Consignment"
- An input for "Consignment Rate (%)"
- Any text mentioning "Percentage the store keeps on each sale"

**Option A (safest):** Wrap the consignment UI elements in a `<div style="display:none">` so the HTML is still there but invisible.

**Option B (cleaner):** Delete the consignment HTML elements entirely.

Use Option A for safety. Find the consignment checkbox and rate input section and wrap them:

The screenshot shows these elements at the bottom of the Edit Item modal:
- A "Consignment" checkbox
- A "Consignment Rate (%)" number input with value 100.00

Find those elements and wrap them in `<div style="display:none !important">...</div>`, or set `style="display:none !important"` on each individual element and its label.

---

### File: `frontend/admin/vendors.html`

If there's any consignment UI in admin vendor management, hide it too. Search for "consignment" in this file.

---

### File: `frontend/pos/index.html`

If the POS quick-add form has consignment fields, hide those too. Search for "consignment" in this file.

---

## Step 4: Force consignment_amount = 0 in Sale Processing

This is the critical part — when a sale is processed, the consignment logic determines how much the vendor gets credited.

### File: `app/routers/pos.py`

**Find** (around line 352):
```python
        if item.is_consignment and item.consignment_rate is not None:
            c_rate = Decimal(str(item.consignment_rate))
```

This block calculates `consignment_amount` (the store's cut) and subtracts it from the vendor credit. Since all items should now be `is_consignment = false`, this block won't execute. But as a safety net, add a guard BEFORE this block:

```python
        # Safety: force no consignment regardless of DB state
        c_rate = Decimal("0")
        consignment_amount = Decimal("0")
```

And make sure the vendor balance credit uses the full `line_total` without any consignment deduction. Look for where `vendor_credit` or balance update is calculated and verify the vendor gets `line_total` (not `line_total - consignment_amount`).

**Also check** `app/routers/sales.py` around line 175 for the same pattern:
```python
        if item.is_consignment and item.consignment_rate is not None:
            c_rate = Decimal(str(item.consignment_rate))
```

Apply the same safety guard.

---

## Testing

1. Deploy and check Railway logs for: `BMM-POS: CLEARED consignment flags on X items`
2. Open any item in the vendor items page — consignment checkbox and rate should be hidden
3. Edit and save any item — verify `is_consignment` stays `false` in the database
4. Make a test sale — verify the vendor's balance is credited the FULL sale amount (not reduced by consignment)
5. Check the admin panel for any remaining consignment UI

## Files Changed
- `app/main.py` — standalone consignment cleanup with logging
- `app/routers/items.py` — force consignment=false on create and update
- `app/routers/pos.py` — force consignment=false on quick-add, safety guard on sale processing
- `app/routers/sales.py` — safety guard on sale processing
- `frontend/vendor/items.html` — hide consignment UI
- Any other frontend files with consignment UI
