# Cursor Task: Bulk Inventory Verification — Single File, All Vendors

## Overview

Replace the per-vendor upload (`POST /inventory-verify/upload/{vendor_id}`) with a new bulk endpoint that accepts one CSV containing ALL vendors' items (~26,000 rows). The CSV uses the **Consignor** column to identify which vendor each item belongs to. Match vendors by name to the database, then run the same verify/add logic per item.

Keep all existing endpoints (status, reset, archive, review queue, etc.) — they still work the same way. Just add the new bulk upload alongside the old one.

---

## Step 1: Add the Bulk Upload Endpoint

### File: `app/routers/inventory_verify.py`

**Add this new endpoint AFTER the existing `verify_vendor_inventory` endpoint (after line ~292) and BEFORE the `reset_vendor_verification` endpoint:**

```python
@router.post("/upload-bulk")
async def verify_bulk_inventory(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """
    Upload a single Ricochet CSV containing ALL vendors' items.
    Uses the 'Consignor' column to match items to vendors by name.
    - Items matching an existing barcode for the correct vendor → verified
    - Items matching a barcode for a DIFFERENT vendor → flagged as error
    - Items not in BMM-POS → created as pending_review under matched vendor
    - Items with no/unmatched Consignor → grouped in skipped
    """
    # Read CSV
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:  # 50MB limit for bulk
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    # Skip the first line if it's the Ricochet title row (not CSV headers)
    lines = text.split("\n")
    if lines and not lines[0].startswith("Product ID"):
        # First line is something like "Products 2026-04-01T..."
        text = "\n".join(lines[1:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    if "sku" not in headers_lower:
        raise HTTPException(status_code=400, detail="CSV must have a 'SKU' column")

    # Load ALL vendors — build name lookup (case-insensitive)
    vendor_result = await db.execute(select(Vendor))
    all_vendors = vendor_result.scalars().all()
    vendor_by_name = {}
    for v in all_vendors:
        if v.name:
            vendor_by_name[v.name.strip().lower()] = v
        # Also index by booth_number for fallback
        if v.booth_number:
            vendor_by_name[v.booth_number.strip().lower()] = v

    # Load ALL existing items by barcode (with vendor_id)
    existing_result = await db.execute(select(Item).where(Item.status.in_(["active", "pending_review"])))
    existing_by_barcode = {}
    for item in existing_result.scalars().all():
        if item.barcode:
            existing_by_barcode[item.barcode] = item

    # Load all barcodes and SKUs for duplicate checks
    all_barcodes = set(existing_by_barcode.keys())
    all_skus = set()
    sku_result = await db.execute(select(Item.sku))
    for (s,) in sku_result.all():
        if s:
            all_skus.add(s)

    # Track SKU sequences per vendor
    sku_seqs = {}

    async def get_next_sku(vid):
        if vid not in sku_seqs:
            seq_result = await db.execute(
                select(func.count(Item.id)).where(Item.vendor_id == vid)
            )
            sku_seqs[vid] = (seq_result.scalar() or 0) + 1
        while True:
            sku = f"BSM-{vid:04d}-{sku_seqs[vid]:06d}"
            if sku not in all_skus:
                all_skus.add(sku)
                sku_seqs[vid] += 1
                return sku
            sku_seqs[vid] += 1

    now = datetime.utcnow()
    verified_count = 0
    added_count = 0
    skipped = []
    errors = []
    vendor_stats = {}  # vendor_id -> {name, verified, added}
    unmatched_vendors = {}  # vendor_name -> count

    for row_num, row in enumerate(reader, start=2):
        clean_row = {k.strip().lower(): _clean(v) for k, v in row.items()}

        barcode_raw = (clean_row.get("sku") or "").strip().strip("'").strip()
        if not barcode_raw:
            skipped.append({"row": row_num, "reason": "Empty SKU"})
            continue

        name = clean_row.get("name") or ""
        if not name:
            skipped.append({"row": row_num, "barcode": barcode_raw, "reason": "Empty name"})
            continue

        # Match vendor by Consignor column
        consignor = (clean_row.get("consignor") or "").strip()
        if not consignor:
            skipped.append({"row": row_num, "barcode": barcode_raw, "name": name, "reason": "No vendor (Consignor empty)"})
            continue

        vendor = vendor_by_name.get(consignor.lower())
        if not vendor:
            # Try partial match — first + last name
            if consignor.lower() not in unmatched_vendors:
                unmatched_vendors[consignor.lower()] = {"name": consignor, "count": 0}
            unmatched_vendors[consignor.lower()]["count"] += 1
            skipped.append({"row": row_num, "barcode": barcode_raw, "name": name, "reason": f"Vendor not found: '{consignor}'"})
            continue

        vid = vendor.id
        if vid not in vendor_stats:
            vendor_stats[vid] = {"name": vendor.name, "verified": 0, "added": 0, "errors": 0}

        # Check if item exists by barcode
        if barcode_raw in existing_by_barcode:
            existing_item = existing_by_barcode[barcode_raw]
            if existing_item.vendor_id == vid:
                # Same vendor — verify it
                existing_item.verified_at = now
                # Update price if changed
                price_str = (clean_row.get("agreed price") or "").replace("$", "").replace(",", "")
                if price_str:
                    try:
                        new_price = Decimal(price_str)
                        if new_price > 0 and new_price != existing_item.price:
                            existing_item.price = new_price
                    except (InvalidOperation, ValueError):
                        pass
                # Update quantity
                try:
                    qty = int(clean_row.get("quantity") or "1")
                    if qty > 0:
                        existing_item.quantity = qty
                except ValueError:
                    pass
                verified_count += 1
                vendor_stats[vid]["verified"] += 1
            else:
                # Barcode exists for a different vendor
                errors.append({
                    "row": row_num,
                    "barcode": barcode_raw,
                    "name": name,
                    "consignor": consignor,
                    "error": f"Barcode belongs to vendor {existing_item.vendor_id}, not {vid}",
                })
                vendor_stats[vid]["errors"] += 1
                continue
        else:
            # New item — create as pending_review
            price_str = (clean_row.get("agreed price") or "0").replace("$", "").replace(",", "")
            try:
                price = Decimal(price_str)
                if price <= 0:
                    raise ValueError()
            except (InvalidOperation, ValueError):
                skipped.append({"row": row_num, "name": name, "reason": f"Invalid price: {price_str}"})
                continue

            try:
                qty = int(clean_row.get("quantity") or "1")
                if qty <= 0:
                    qty = 1
            except ValueError:
                qty = 1

            category = clean_row.get("category") or None
            description = clean_row.get("short description") or None

            tax_rate_str = (clean_row.get("tax rate") or "").replace("%", "").strip()
            is_tax_exempt = False
            if tax_rate_str:
                try:
                    is_tax_exempt = Decimal(tax_rate_str) == 0
                except (InvalidOperation, ValueError):
                    pass

            sku = await get_next_sku(vid)

            new_item = Item(
                vendor_id=vid,
                sku=sku,
                barcode=barcode_raw,
                name=name,
                price=price,
                quantity=qty,
                category=category,
                description=description,
                status="pending_review",
                is_tax_exempt=is_tax_exempt,
                is_consignment=False,
                consignment_rate=None,
                verified_at=now,
                import_source="ricochet",
            )
            db.add(new_item)
            all_barcodes.add(barcode_raw)
            added_count += 1
            vendor_stats[vid]["added"] += 1

        # Flush every 500 rows to avoid memory buildup
        if (row_num % 500) == 0:
            await db.flush()

    await db.commit()

    return {
        "total_rows_processed": row_num - 1 if 'row_num' in dir() else 0,
        "verified": verified_count,
        "added": added_count,
        "skipped": len(skipped),
        "errors": len(errors),
        "vendor_summary": sorted(vendor_stats.values(), key=lambda v: v["name"]),
        "unmatched_vendors": sorted(unmatched_vendors.values(), key=lambda v: -v["count"]),
        "skipped_details": skipped[:50],
        "error_details": errors[:50],
    }
```

---

## Step 2: Add a Reset-All Endpoint

### File: `app/routers/inventory_verify.py`

**Add after the existing `reset_vendor_verification` endpoint:**

```python
@router.post("/reset-all")
async def reset_all_verification(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Clear verified_at for ALL items (re-do full verification)."""
    result = await db.execute(
        update(Item)
        .where(Item.verified_at.isnot(None))
        .values(verified_at=None)
    )
    await db.commit()
    return {"detail": f"Verification reset for all items", "count": result.rowcount}
```

---

## Step 3: Increase File Size Limit

### File: `app/routers/inventory_verify.py`

**Find:**
```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
```

**Replace with:**
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
```

---

## Step 4: Update the Frontend Admin Verification Page

### File: `frontend/admin/inventory-verify.html`

If this file exists, update the upload UI to have a "Bulk Upload (All Vendors)" option that calls `POST /api/v1/inventory-verify/upload-bulk` instead of the per-vendor endpoint.

If there's no frontend page yet, no changes needed — the endpoint can be called via the admin panel or API directly.

**The key UI addition:** A single file upload button at the top of the verification page labeled "Upload Full Inventory" that:
1. Accepts one CSV file
2. POSTs to `/api/v1/inventory-verify/upload-bulk`
3. Shows progress/results: how many verified, added, skipped, plus the vendor summary and any unmatched vendor names

---

## Important Notes

- The CSV has a title row on line 1 (`Products 2026-04-01T...`) before the actual headers on line 2. The endpoint skips this automatically if the first line doesn't start with "Product ID".
- The **Consignor** column maps to vendor names in the database. ~2,043 items have empty Consignor and will be skipped.
- Vendor matching is case-insensitive. The response includes `unmatched_vendors` so you can see which Consignor names didn't match any vendor in the DB (these may need to be added or name-corrected).
- The endpoint flushes to the DB every 500 rows to manage memory with 26,000+ items.
- The per-vendor upload endpoint (`POST /upload/{vendor_id}`) is preserved for cases where you still want to verify a single vendor.
- **Do NOT remove the `_ricochet_filter()` usage in other endpoints** — the status, archive, and review endpoints still need it.

## Files Changed
- `app/routers/inventory_verify.py` — new `upload-bulk` and `reset-all` endpoints, increased file size limit

## Testing
1. Reset all verification: `POST /api/v1/inventory-verify/reset-all`
2. Upload the full CSV: `POST /api/v1/inventory-verify/upload-bulk` with the file
3. Check the response for verified/added/skipped counts and the vendor summary
4. Check `unmatched_vendors` in the response — these are Consignor names not found in the DB
5. Run `POST /api/v1/inventory-verify/status` to see per-vendor verification progress
6. Run `python3 -m py_compile app/routers/inventory_verify.py`
