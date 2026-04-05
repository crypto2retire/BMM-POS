# Task: Inventory Verification System — Part 1: Backend

Add backend support for a Ricochet-to-BMM-POS inventory verification workflow. Admins upload per-vendor CSV exports from Ricochet. The system matches items by barcode, marks verified items, and flags new items for review. **Only items imported from Ricochet are affected — BMM-POS native items are never touched.**

---

## Step 1: Add new columns to Item model

File: `app/models/item.py`

Add these fields after `label_printed` (around line 32):

```python
    verified_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    archive_expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    import_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
```

File: `app/schemas/item.py`

Add to `ItemResponse` class (around line 76, before `class Config`):

```python
    verified_at: Optional[datetime] = None
    archive_expires_at: Optional[datetime] = None
    import_source: Optional[str] = None
```

---

## Step 2: Auto-create columns on startup + backfill Ricochet items

File: `app/main.py`

Add inside the lifespan startup block, alongside the other `ALTER TABLE items` statements:

```python
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "verified_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "archive_expires_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "import_source VARCHAR(50)"
            ))
```

**IMPORTANT — backfill:** After the column creation statements, add a one-time backfill to tag all existing Ricochet-imported items. Items imported from Ricochet have barcodes that were set from the Ricochet SKU column and their SKUs start with `BSM-`. The key indicator: they were created by the bulk importer. Since we can't retroactively know that, we use this heuristic — items whose barcode is NOT NULL and whose barcode does NOT look like a randomly generated code are Ricochet imports. **The safest approach:** tag ALL existing items that have a barcode as Ricochet, since the original bulk import from Ricochet was the source of most inventory. Items created natively going forward will have `import_source` set to NULL.

```python
            # Backfill: tag existing items with barcodes as Ricochet imports (one-time)
            await session.execute(text(
                "UPDATE items SET import_source = 'ricochet' "
                "WHERE import_source IS NULL AND barcode IS NOT NULL"
            ))
```

---

## Step 3: Update bulk_import.py to tag Ricochet imports

File: `app/routers/bulk_import.py`

Find the `Item(` constructor call (around line 372) and add `import_source`:

Change:
```python
                item = Item(
                    vendor_id=vendor.id,
                    name=name[:200],
                    description=description,
                    price=price,
                    sale_price=sale_price,
                    quantity=qty,
                    category=category,
                    barcode=barcode,
                    sku=sku,
                    is_tax_exempt=is_tax_exempt,
                    is_consignment=consignment,
                    consignment_rate=consignment_rate,
                    status="active",
                    label_printed=True,
                )
```

To:
```python
                item = Item(
                    vendor_id=vendor.id,
                    name=name[:200],
                    description=description,
                    price=price,
                    sale_price=sale_price,
                    quantity=qty,
                    category=category,
                    barcode=barcode,
                    sku=sku,
                    is_tax_exempt=is_tax_exempt,
                    is_consignment=consignment,
                    consignment_rate=consignment_rate,
                    status="active",
                    label_printed=True,
                    import_source="ricochet" if is_ricochet else None,
                )
```

---

## Step 4: Create the inventory verification router

Create a new file: `app/routers/inventory_verify.py`

```python
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, delete
from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, require_role
from app.services.barcode import generate_sku, generate_short_barcode

router = APIRouter(prefix="/inventory-verify", tags=["inventory-verify"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# ── Helpers ─────────────────────────────────────────────────

def _clean(val):
    """Strip whitespace and quotes from CSV values."""
    if val is None:
        return ""
    return val.strip().strip('"').strip("'").strip()


def _ricochet_filter():
    """SQLAlchemy filter for Ricochet-imported items only."""
    return Item.import_source == "ricochet"


# ── Status (admin + cashier) ────────────────────────────────

@router.get("/status")
async def verification_status(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """Get verification progress per vendor. Only counts Ricochet-imported items."""
    result = await db.execute(
        select(
            Vendor.id,
            Vendor.name,
            Vendor.booth_number,
            func.count(Item.id).label("total_items"),
            func.count(Item.verified_at).label("verified_items"),
        )
        .outerjoin(Item, and_(
            Item.vendor_id == Vendor.id,
            Item.status == "active",
            _ricochet_filter(),
        ))
        .where(Vendor.role == "vendor", Vendor.status == "active")
        .group_by(Vendor.id, Vendor.name, Vendor.booth_number)
        .order_by(Vendor.name)
    )
    rows = result.all()

    vendors = []
    for r in rows:
        vendors.append({
            "id": r.id,
            "name": r.name,
            "booth_number": r.booth_number,
            "total_items": r.total_items,
            "verified_items": r.verified_items,
            "unverified_items": r.total_items - r.verified_items,
            "is_complete": r.verified_items == r.total_items and r.total_items > 0,
        })

    total = sum(v["total_items"] for v in vendors)
    verified = sum(v["verified_items"] for v in vendors)

    # Count pending review items
    review_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.status == "pending_review",
            _ricochet_filter(),
        )
    )
    pending_review = review_result.scalar() or 0

    return {
        "vendors": vendors,
        "summary": {
            "total_vendors": len(vendors),
            "completed_vendors": sum(1 for v in vendors if v["is_complete"]),
            "total_items": total,
            "verified_items": verified,
            "unverified_items": total - verified,
            "pending_review": pending_review,
        },
    }


# ── Upload CSV (admin only) ─────────────────────────────────

@router.post("/upload/{vendor_id}")
async def verify_vendor_inventory(
    vendor_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """
    Upload a Ricochet CSV for a specific vendor.
    - Items in CSV matching BMM-POS barcode → marked verified
    - Items in CSV NOT in BMM-POS → created as pending_review
    - Only Ricochet-imported items are considered for verification
    """
    # Validate vendor
    vendor_result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Read CSV
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}

    if "sku" not in headers_lower:
        raise HTTPException(status_code=400, detail="CSV must have a 'SKU' column")

    # Load existing Ricochet-imported items for this vendor (by barcode)
    existing_result = await db.execute(
        select(Item).where(
            Item.vendor_id == vendor_id,
            _ricochet_filter(),
        )
    )
    existing_items = {item.barcode: item for item in existing_result.scalars().all() if item.barcode}

    # Load all barcodes for duplicate check when creating new items
    all_barcodes = set()
    bc_result = await db.execute(select(Item.barcode))
    for (b,) in bc_result.all():
        if b:
            all_barcodes.add(b)

    all_skus = set()
    sku_result = await db.execute(select(Item.sku))
    for (s,) in sku_result.all():
        if s:
            all_skus.add(s)

    # Track SKU sequence for new items
    seq_result = await db.execute(
        select(func.count(Item.id)).where(Item.vendor_id == vendor_id)
    )
    sku_seq = (seq_result.scalar() or 0) + 1

    def next_sku():
        nonlocal sku_seq
        while True:
            sku = f"BSM-{vendor_id:04d}-{sku_seq:06d}"
            if sku not in all_skus:
                all_skus.add(sku)
                return sku
            sku_seq += 1

    now = datetime.utcnow()
    verified_count = 0
    added_count = 0
    skipped = []
    errors = []

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

        # Check if item exists in BMM-POS for this vendor
        if barcode_raw in existing_items:
            item = existing_items[barcode_raw]
            item.verified_at = now
            # Also update price if it changed in Ricochet
            price_str = (clean_row.get("agreed price") or "").replace("$", "").replace(",", "")
            if price_str:
                try:
                    new_price = Decimal(price_str)
                    if new_price > 0 and new_price != item.price:
                        item.price = new_price
                except (InvalidOperation, ValueError):
                    pass
            # Update quantity
            try:
                qty = int(clean_row.get("quantity") or "1")
                if qty > 0:
                    item.quantity = qty
            except ValueError:
                pass
            verified_count += 1
        else:
            # Item not in BMM-POS — create as pending_review
            if barcode_raw in all_barcodes:
                # Barcode exists but for a different vendor
                errors.append({
                    "row": row_num,
                    "barcode": barcode_raw,
                    "name": name,
                    "error": "Barcode already exists for another vendor",
                })
                continue

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

            # Tax exempt check
            tax_rate_str = (clean_row.get("tax rate") or "").replace("%", "").strip()
            is_tax_exempt = False
            if tax_rate_str:
                try:
                    is_tax_exempt = Decimal(tax_rate_str) == 0
                except (InvalidOperation, ValueError):
                    pass

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

            new_item = Item(
                vendor_id=vendor_id,
                sku=next_sku(),
                barcode=barcode_raw,
                name=name,
                price=price,
                quantity=qty,
                category=category,
                description=description,
                status="pending_review",
                is_tax_exempt=is_tax_exempt,
                is_consignment=is_consignment,
                consignment_rate=consignment_rate,
                verified_at=now,
                import_source="ricochet",
            )
            db.add(new_item)
            all_barcodes.add(barcode_raw)
            added_count += 1

    await db.commit()

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.name,
        "verified": verified_count,
        "added": added_count,
        "skipped": len(skipped),
        "errors": len(errors),
        "skipped_details": skipped[:20],
        "error_details": errors[:20],
    }


# ── Reset vendor verification (admin only) ──────────────────

@router.post("/reset/{vendor_id}")
async def reset_vendor_verification(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Clear verified_at for all Ricochet items of a vendor (re-do verification)."""
    await db.execute(
        update(Item)
        .where(
            Item.vendor_id == vendor_id,
            _ricochet_filter(),
        )
        .values(verified_at=None)
    )
    await db.commit()
    return {"detail": f"Verification reset for vendor {vendor_id}"}


# ── Archive unverified (admin only) ─────────────────────────

@router.post("/archive-unverified")
async def archive_unverified_items(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """
    Archive all RICOCHET-IMPORTED active items that have NOT been verified.
    Sets 30-day expiration. BMM-POS native items are never touched.
    """
    expires = datetime.utcnow() + timedelta(days=30)

    # Only archive Ricochet items that are active and unverified
    await db.execute(
        update(Item)
        .where(
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
        .values(
            status="pending_delete",
            archive_expires_at=expires,
        )
    )

    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.status == "pending_delete",
            Item.archive_expires_at == expires,
        )
    )
    count = count_result.scalar() or 0
    await db.commit()

    return {
        "archived": count,
        "expires_at": expires.isoformat(),
        "detail": f"Archived {count} unverified Ricochet items. They will be held for 30 days.",
    }


# ── Pending delete list (admin + cashier) ────────────────────

@router.get("/pending-delete")
async def list_pending_delete(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """List items pending deletion, grouped by vendor."""
    result = await db.execute(
        select(
            Vendor.id,
            Vendor.name,
            Vendor.booth_number,
            func.count(Item.id).label("count"),
            func.min(Item.archive_expires_at).label("earliest_expiry"),
        )
        .join(Item, Item.vendor_id == Vendor.id)
        .where(Item.status == "pending_delete")
        .group_by(Vendor.id, Vendor.name, Vendor.booth_number)
        .order_by(Vendor.name)
    )
    rows = result.all()

    vendors = []
    total = 0
    for r in rows:
        vendors.append({
            "vendor_id": r.id,
            "vendor_name": r.name,
            "booth_number": r.booth_number,
            "pending_count": r.count,
            "earliest_expiry": r.earliest_expiry.isoformat() if r.earliest_expiry else None,
        })
        total += r.count

    return {"vendors": vendors, "total_pending": total}


# ── Permanent delete (admin only) ────────────────────────────

@router.post("/permanent-delete")
async def permanently_delete_archived(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Permanently delete all items with status 'pending_delete'."""
    count_result = await db.execute(
        select(func.count(Item.id)).where(Item.status == "pending_delete")
    )
    count = count_result.scalar() or 0

    if count == 0:
        return {"deleted": 0, "detail": "No items pending deletion."}

    # Delete sale_items references first (if any exist)
    from app.models.sale import SaleItem
    await db.execute(
        delete(SaleItem).where(
            SaleItem.item_id.in_(
                select(Item.id).where(Item.status == "pending_delete")
            )
        )
    )

    # Delete the items
    await db.execute(
        delete(Item).where(Item.status == "pending_delete")
    )
    await db.commit()

    return {"deleted": count, "detail": f"Permanently deleted {count} items."}


# ── Restore vendor pending items (admin only) ────────────────

@router.post("/restore-vendor/{vendor_id}")
async def restore_vendor_pending(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Restore all pending_delete items for a vendor back to active."""
    result = await db.execute(
        select(func.count(Item.id)).where(
            Item.vendor_id == vendor_id,
            Item.status == "pending_delete",
        )
    )
    count = result.scalar() or 0

    await db.execute(
        update(Item)
        .where(Item.vendor_id == vendor_id, Item.status == "pending_delete")
        .values(status="active", archive_expires_at=None)
    )
    await db.commit()

    return {"restored": count, "detail": f"Restored {count} items to active."}


# ── Review Queue (admin + cashier) ───────────────────────────

@router.get("/review-queue")
async def get_review_queue(
    vendor_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """
    Get items in pending_review status. Cashiers and admins can view.
    Optional vendor_id filter.
    """
    base_query = select(Item).where(
        Item.status == "pending_review",
        _ricochet_filter(),
    )
    count_query = select(func.count(Item.id)).where(
        Item.status == "pending_review",
        _ricochet_filter(),
    )

    if vendor_id:
        base_query = base_query.where(Item.vendor_id == vendor_id)
        count_query = count_query.where(Item.vendor_id == vendor_id)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get items with vendor info
    result = await db.execute(
        base_query
        .order_by(Item.vendor_id, Item.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = result.scalars().all()

    # Get vendor names
    vendor_ids = list(set(i.vendor_id for i in items))
    vendor_map = {}
    if vendor_ids:
        v_result = await db.execute(
            select(Vendor.id, Vendor.name, Vendor.booth_number)
            .where(Vendor.id.in_(vendor_ids))
        )
        for v in v_result.all():
            vendor_map[v.id] = {"name": v.name, "booth_number": v.booth_number}

    # Count by vendor for summary
    summary_result = await db.execute(
        select(
            Item.vendor_id,
            func.count(Item.id).label("count"),
        )
        .where(Item.status == "pending_review", _ricochet_filter())
        .group_by(Item.vendor_id)
    )
    vendor_counts = {r.vendor_id: r.count for r in summary_result.all()}

    return {
        "items": [
            {
                "id": i.id,
                "vendor_id": i.vendor_id,
                "vendor_name": vendor_map.get(i.vendor_id, {}).get("name", "Unknown"),
                "booth_number": vendor_map.get(i.vendor_id, {}).get("booth_number"),
                "sku": i.sku,
                "barcode": i.barcode,
                "name": i.name,
                "price": float(i.price),
                "quantity": i.quantity,
                "category": i.category,
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "vendor_counts": {
            str(vid): {
                "count": cnt,
                "name": vendor_map.get(vid, {}).get("name", "Unknown"),
            }
            for vid, cnt in vendor_counts.items()
        },
    }


@router.post("/review/approve")
async def approve_review_items(
    item_ids: list[int] = [],
    approve_all_vendor: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """
    Approve pending_review items → set status to active.
    Either pass specific item_ids in body, or approve_all_vendor query param.
    """
    if approve_all_vendor:
        count_result = await db.execute(
            select(func.count(Item.id)).where(
                Item.vendor_id == approve_all_vendor,
                Item.status == "pending_review",
                _ricochet_filter(),
            )
        )
        count = count_result.scalar() or 0
        await db.execute(
            update(Item)
            .where(
                Item.vendor_id == approve_all_vendor,
                Item.status == "pending_review",
                _ricochet_filter(),
            )
            .values(status="active")
        )
        await db.commit()
        return {"approved": count, "detail": f"Approved {count} items for vendor."}

    if not item_ids:
        raise HTTPException(status_code=400, detail="No item IDs provided")

    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.id.in_(item_ids),
            Item.status == "pending_review",
        )
    )
    count = count_result.scalar() or 0

    await db.execute(
        update(Item)
        .where(Item.id.in_(item_ids), Item.status == "pending_review")
        .values(status="active")
    )
    await db.commit()

    return {"approved": count, "detail": f"Approved {count} items."}


@router.post("/review/reject")
async def reject_review_items(
    item_ids: list[int] = [],
    reject_all_vendor: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """
    Reject pending_review items → hard delete them.
    These are items from the CSV that don't belong in the system.
    """
    if reject_all_vendor:
        count_result = await db.execute(
            select(func.count(Item.id)).where(
                Item.vendor_id == reject_all_vendor,
                Item.status == "pending_review",
                _ricochet_filter(),
            )
        )
        count = count_result.scalar() or 0
        await db.execute(
            delete(Item).where(
                Item.vendor_id == reject_all_vendor,
                Item.status == "pending_review",
                _ricochet_filter(),
            )
        )
        await db.commit()
        return {"rejected": count, "detail": f"Rejected and deleted {count} items."}

    if not item_ids:
        raise HTTPException(status_code=400, detail="No item IDs provided")

    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.id.in_(item_ids),
            Item.status == "pending_review",
        )
    )
    count = count_result.scalar() or 0

    await db.execute(
        delete(Item).where(Item.id.in_(item_ids), Item.status == "pending_review")
    )
    await db.commit()

    return {"rejected": count, "detail": f"Rejected and deleted {count} items."}
```

---

## Step 5: Register the router

File: `app/main.py`

Add the import near the other router imports:

```python
from app.routers.inventory_verify import router as inventory_verify_router
```

And register it alongside the other routers:

```python
app.include_router(inventory_verify_router, prefix="/api/v1")
```

---

## Summary of API endpoints

| Method | Endpoint | Roles | Purpose |
|--------|----------|-------|---------|
| GET | `/api/v1/inventory-verify/status` | admin, cashier | Verification progress per vendor (Ricochet items only) |
| POST | `/api/v1/inventory-verify/upload/{vendor_id}` | admin | Upload CSV, verify existing + add new as pending_review |
| POST | `/api/v1/inventory-verify/reset/{vendor_id}` | admin | Re-do a vendor's verification |
| POST | `/api/v1/inventory-verify/archive-unverified` | admin | Archive unverified Ricochet items (30-day hold) |
| GET | `/api/v1/inventory-verify/pending-delete` | admin, cashier | List pending-delete items by vendor |
| POST | `/api/v1/inventory-verify/permanent-delete` | admin | Hard delete all pending items |
| POST | `/api/v1/inventory-verify/restore-vendor/{vendor_id}` | admin | Restore a vendor's archived items |
| GET | `/api/v1/inventory-verify/review-queue` | admin, cashier | List items needing review (filterable by vendor) |
| POST | `/api/v1/inventory-verify/review/approve` | admin, cashier | Approve pending items → active |
| POST | `/api/v1/inventory-verify/review/reject` | admin, cashier | Reject pending items → delete |

### Key behavior notes:
- **Ricochet-only:** All verification and archiving ONLY touches items where `import_source = 'ricochet'`. BMM-POS native items are never affected.
- **New CSV items → pending_review:** Items found in the CSV but not in BMM-POS are created with `status='pending_review'` so they can be reviewed before going active.
- **Cashier access:** Cashiers can view status, review queue, and pending-delete list. They can approve or reject review items. Only admins can upload CSVs, archive, or permanently delete.

Commit and push when done. Do NOT create the frontend page yet — that's a separate task file.
