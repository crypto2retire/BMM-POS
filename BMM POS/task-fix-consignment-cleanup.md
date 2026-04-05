# Task: Clear Consignment on All Items & Stop Importing It

## Background
Ricochet CSV exports have a "consignor %" column that marked nearly all items as consignment with 100% going to the store. This was junk data from Ricochet's vendor lock-in. Only ONE vendor (Lisa) actually has consignment items (70/30 split). Kevin will manually re-set Lisa's items after this fix.

## What This Task Does
1. **Database migration:** Clear `is_consignment` and `consignment_rate` on ALL items
2. **Stop importing consignment from CSVs:** Remove consignor % parsing from all import/verify code
3. **Keep the consignment feature in the system** — it's still used for Lisa and possibly future vendors. Just stop auto-setting it from imports.

---

## Step 1: Database Migration in `app/main.py`

In the `lifespan` function, find the section where auto-migrations run (where the other `ALTER TABLE` and `UPDATE` statements are). Add this NEW migration block:

```python
            # ── Clear consignment flags on all items (Ricochet junk data) ──
            await conn.execute(text("""
                UPDATE items
                SET is_consignment = false,
                    consignment_rate = NULL
                WHERE is_consignment = true
            """))
```

Add this AFTER the existing migration statements but BEFORE the `await conn.commit()` (or the end of the connection block). This runs once on startup and is idempotent — running it again just does nothing.

---

## Step 2: Stop Importing Consignment from Ricochet CSVs

### File: `app/routers/inventory_verify.py`

Find this block (around lines 257-266):

```python
            # Consignment
            consignment_pct = (clean_row.get("consignor %") or "").strip()
            is_consignment = bool(consignment_pct and consignment_pct != "0")
            consignment_rate = None
            if is_consignment and consignment_pct:
                try:
                    cr = Decimal(consignment_pct.replace("%", ""))
                    consignment_rate = cr / 100 if cr > 1 else cr
                except (InvalidOperation, ValueError):
                    consignment_rate = None
```

**Replace with:**

```python
            # Consignment — ignored from Ricochet CSV (was junk data)
            is_consignment = False
            consignment_rate = None
```

### File: `app/routers/bulk_import.py`

There are THREE places that parse consignment. Replace all three:

**Place 1** — Ricochet import (around lines 289-297). Find:

```python
            consignment_pct_str = (clean_row.get("consignor %") or "").strip()
            consignment = bool(consignment_pct_str and consignment_pct_str != "0")
            consignment_rate = None
            if consignment and consignment_pct_str:
                try:
                    cr = Decimal(consignment_pct_str.replace("%", ""))
                    consignment_rate = cr / 100 if cr > 1 else cr
                except (InvalidOperation, ValueError):
                    consignment_rate = None
```

**Replace with:**

```python
            # Consignment — ignored from Ricochet CSV (was junk data)
            consignment = False
            consignment_rate = None
```

**Place 2** — Generic/non-Ricochet import (around lines 341-348). Find:

```python
            consignment = clean_row.get("consignment", "").lower() in ("true", "yes", "1", "y")
            consignment_rate = None
            if consignment and clean_row.get("consignment_rate"):
                try:
                    cr = Decimal(clean_row["consignment_rate"].replace("%", ""))
                    consignment_rate = cr / 100 if cr > 1 else cr
                except (InvalidOperation, ValueError):
                    consignment_rate = None
```

**Replace with:**

```python
            # Consignment — not set from CSV imports
            consignment = False
            consignment_rate = None
```

**Place 3** — Batch import function (around lines 688-716). Find the Ricochet branch:

```python
            consignment_pct_str = (clean.get("consignor %") or "").strip()
            is_consignment = bool(consignment_pct_str and consignment_pct_str != "0")
            cr = None
            if is_consignment and consignment_pct_str:
                try:
                    crv = Decimal(consignment_pct_str.replace("%", ""))
                    cr = float(crv / 100 if crv > 1 else crv)
                except (InvalidOperation, ValueError):
                    pass
```

**Replace with:**

```python
            # Consignment — ignored from Ricochet CSV (was junk data)
            is_consignment = False
            cr = None
```

And find the non-Ricochet branch (around lines 709-717):

```python
            is_consignment = clean.get("consignment", "").lower() in ("true", "yes", "1", "y")
            is_tax_exempt = clean.get("tax_exempt", "").lower() in ("true", "yes", "1", "y")
            cr = None
            if is_consignment and clean.get("consignment_rate"):
                try:
                    crv = Decimal(clean["consignment_rate"].replace("%", ""))
                    cr = float(crv / 100 if crv > 1 else crv)
                except (InvalidOperation, ValueError):
                    pass
```

**Replace with:**

```python
            # Consignment — not set from CSV imports
            is_consignment = False
            is_tax_exempt = clean.get("tax_exempt", "").lower() in ("true", "yes", "1", "y")
            cr = None
```

**IMPORTANT:** Keep the `is_tax_exempt` line — only remove the consignment parsing.

---

## Step 3: No Frontend Changes Needed

The consignment feature stays in the system (POS, item forms, sales). We're only:
- Clearing the junk data on existing items
- Stopping the CSV import from setting consignment

Kevin will manually re-set Lisa's consignment items through the admin interface after this deploys.

---

## Testing
1. Deploy and let the startup migration run
2. Check that items no longer show as consignment: `SELECT COUNT(*) FROM items WHERE is_consignment = true;` — should return 0
3. Upload a Ricochet CSV for any vendor — new items should NOT be marked consignment
4. Verify the POS still works for regular (non-consignment) sales
5. Verify you can still manually set an item as consignment through the item edit form (the feature should still exist)

## Files Changed
- `app/main.py` (startup migration)
- `app/routers/inventory_verify.py` (1 block)
- `app/routers/bulk_import.py` (3 blocks)
