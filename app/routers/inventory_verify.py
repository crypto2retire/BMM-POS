import csv
import io
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, delete, text as sql_text
from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, require_role
from app.routers.settings import require_staff_feature
from app.services.barcode import generate_sku, generate_short_barcode

router = APIRouter(prefix="/inventory-verify", tags=["inventory-verify"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

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
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
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
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        if "SKU" in line and "Product ID" in line:
            header_idx = i
            break
    if header_idx > 0:
        text = "\n".join(lines[header_idx:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    if "sku" not in headers_lower:
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have a 'SKU' column. Found: {', '.join(reader.fieldnames[:10])}"
        )

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

            # Consignment — ignored from Ricochet CSV (was junk data)
            is_consignment = False
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


@router.post("/upload-bulk")
async def verify_bulk_inventory(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """
    Upload a single Ricochet CSV containing ALL vendors' items.
    Uses the 'Consignor' column to match items to vendors by name.
    """
    logger = logging.getLogger(__name__)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        if "SKU" in line and "Product ID" in line:
            header_idx = i
            break
    if header_idx > 0:
        text = "\n".join(lines[header_idx:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    if "sku" not in headers_lower:
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have a 'SKU' column. Found: {', '.join(reader.fieldnames[:10])}"
        )

    logger.info("Bulk verify: CSV parsed, loading vendor data...")

    vendor_result = await db.execute(select(Vendor.id, Vendor.name, Vendor.booth_number))
    vendor_by_name = {}
    for row in vendor_result.all():
        if row.name:
            vendor_by_name[row.name.strip().lower()] = {"id": row.id, "name": row.name}
        if row.booth_number:
            vendor_by_name[row.booth_number.strip().lower()] = {"id": row.id, "name": row.name}

    logger.info("Bulk verify: %s vendor name mappings loaded", len(vendor_by_name))

    item_rows = await db.execute(
        sql_text(
            "SELECT id, barcode, vendor_id FROM items WHERE barcode IS NOT NULL AND status IN ('active', 'pending_review')"
        )
    )
    existing_by_barcode = {}
    for r in item_rows.all():
        existing_by_barcode[r[1]] = {"id": r[0], "vendor_id": r[2]}

    logger.info("Bulk verify: %s existing barcodes loaded", len(existing_by_barcode))

    sku_rows = await db.execute(sql_text("SELECT sku FROM items WHERE sku IS NOT NULL"))
    all_skus = {r[0] for r in sku_rows.all() if r[0]}

    sku_seqs = {}

    def next_sku_sync(vid):
        if vid not in sku_seqs:
            prefix = f"BSM-{vid:04d}-"
            max_seq = 0
            for s in all_skus:
                if s.startswith(prefix):
                    try:
                        seq_num = int(s[len(prefix) :])
                        if seq_num > max_seq:
                            max_seq = seq_num
                    except ValueError:
                        pass
            sku_seqs[vid] = max_seq + 1
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
    vendor_stats = {}
    unmatched_vendors = {}
    rows_processed = 0

    verify_ids = []
    verify_updates = []
    new_items = []
    BATCH_SIZE = 500

    async def flush_batch():
        nonlocal verify_ids, verify_updates, new_items
        if verify_ids:
            await db.execute(update(Item).where(Item.id.in_(verify_ids)).values(verified_at=now))
        for item_id, new_price, new_qty in verify_updates:
            vals = {}
            if new_price is not None:
                vals["price"] = new_price
            if new_qty is not None:
                vals["quantity"] = new_qty
            if vals:
                await db.execute(update(Item).where(Item.id == item_id).values(**vals))
        pending_new = list(new_items)
        for item in new_items:
            db.add(item)
        await db.flush()
        for item in pending_new:
            if item.barcode is not None:
                existing_by_barcode[item.barcode] = {"id": item.id, "vendor_id": item.vendor_id}
        verify_ids = []
        verify_updates = []
        new_items = []

    logger.info("Bulk verify: starting row processing...")

    try:
        for row_num, row in enumerate(reader, start=2):
            rows_processed += 1
            clean_row = {k.strip().lower(): _clean(v) for k, v in row.items()}

            barcode_raw = (clean_row.get("sku") or "").strip().strip("'").strip()
            if not barcode_raw:
                skipped.append({"row": row_num, "reason": "Empty SKU"})
                continue

            name = clean_row.get("name") or ""
            if not name:
                skipped.append({"row": row_num, "barcode": barcode_raw, "reason": "Empty name"})
                continue

            consignor = (clean_row.get("consignor") or "").strip()
            if not consignor:
                skipped.append({"row": row_num, "barcode": barcode_raw, "name": name, "reason": "No vendor (Consignor empty)"})
                continue

            vendor_info = vendor_by_name.get(consignor.lower())
            if not vendor_info:
                if consignor.lower() not in unmatched_vendors:
                    unmatched_vendors[consignor.lower()] = {"name": consignor, "count": 0}
                unmatched_vendors[consignor.lower()]["count"] += 1
                skipped.append({"row": row_num, "barcode": barcode_raw, "name": name, "reason": f"Vendor not found: '{consignor}'"})
                continue

            vid = vendor_info["id"]
            vname = vendor_info["name"]
            if vid not in vendor_stats:
                vendor_stats[vid] = {"name": vname, "verified": 0, "added": 0, "errors": 0}

            if barcode_raw in existing_by_barcode:
                existing = existing_by_barcode[barcode_raw]
                if existing["id"] is None:
                    skipped.append({"row": row_num, "barcode": barcode_raw, "name": name, "reason": "Duplicate barcode in CSV (pending insert)"})
                    continue
                if existing["vendor_id"] == vid:
                    item_id = existing["id"]
                    verify_ids.append(item_id)

                    new_price = None
                    new_qty = None
                    price_str = (clean_row.get("agreed price") or "").replace("$", "").replace(",", "")
                    if price_str:
                        try:
                            new_price = Decimal(price_str)
                            if new_price <= 0:
                                new_price = None
                        except (InvalidOperation, ValueError):
                            new_price = None
                    try:
                        q = int(clean_row.get("quantity") or "1")
                        if q > 0:
                            new_qty = q
                    except ValueError:
                        pass
                    if new_price is not None or new_qty is not None:
                        verify_updates.append((item_id, new_price, new_qty))

                    verified_count += 1
                    vendor_stats[vid]["verified"] += 1
                else:
                    errors.append({
                        "row": row_num,
                        "barcode": barcode_raw,
                        "name": name,
                        "consignor": consignor,
                        "error": f"Barcode belongs to vendor {existing['vendor_id']}, not {vid}",
                    })
                    vendor_stats[vid]["errors"] += 1
                    continue
            else:
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

                sku = next_sku_sync(vid)

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
                new_items.append(new_item)
                existing_by_barcode[barcode_raw] = {"id": None, "vendor_id": vid}
                added_count += 1
                vendor_stats[vid]["added"] += 1

            if rows_processed % BATCH_SIZE == 0:
                await flush_batch()
                logger.info("Bulk verify: processed %s rows...", rows_processed)

        await flush_batch()
        await db.commit()
        logger.info(
            "Bulk verify: DONE — %s verified, %s added, %s skipped, %s errors",
            verified_count,
            added_count,
            len(skipped),
            len(errors),
        )

    except Exception as e:
        logger.error("Bulk verify FAILED at row %s: %s: %s", rows_processed, type(e).__name__, e)
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Processing failed at row {rows_processed}: {str(e)}") from e

    return {
        "total_rows_processed": rows_processed,
        "verified": verified_count,
        "added": added_count,
        "skipped": len(skipped),
        "errors": len(errors),
        "vendor_summary": sorted(vendor_stats.values(), key=lambda v: v["name"]),
        "unmatched_vendors": sorted(unmatched_vendors.values(), key=lambda v: -v["count"]),
        "skipped_details": skipped[:50],
        "error_details": errors[:50],
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
    return {"detail": "Verification reset for all items", "count": result.rowcount}


@router.get("/unverified/{vendor_id}")
async def list_unverified_items(
    vendor_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
):
    """List active Ricochet items for a vendor that have NOT been verified."""
    # Get vendor name
    vendor_result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Count total
    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
    )
    total = count_result.scalar() or 0

    # Get items
    result = await db.execute(
        select(Item)
        .where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
        .order_by(Item.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = result.scalars().all()

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.name,
        "items": [
            {
                "id": i.id,
                "sku": i.sku,
                "barcode": i.barcode,
                "name": i.name,
                "price": float(i.price),
                "quantity": i.quantity,
                "category": i.category,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 1,
    }


@router.post("/archive-vendor/{vendor_id}")
async def archive_vendor_unverified(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Archive unverified Ricochet items for a single vendor. 30-day hold."""
    expires = datetime.utcnow() + timedelta(days=30)

    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
    )
    count = count_result.scalar() or 0

    if count == 0:
        return {"archived": 0, "detail": "No unverified items for this vendor."}

    await db.execute(
        update(Item)
        .where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
        .values(
            status="pending_delete",
            archive_expires_at=expires,
        )
    )
    await db.commit()

    return {
        "archived": count,
        "expires_at": expires.isoformat(),
        "detail": f"Archived {count} unverified items. Held for 30 days.",
    }


@router.post("/verify-item/{item_id}")
async def manually_verify_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
):
    """Manually mark a single item as verified (keep it active)."""
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.verified_at = datetime.utcnow()
    await db.commit()

    return {"detail": f"Item '{item.name}' marked as verified."}


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
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
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
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
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
    item_ids: list[int] = Body(default=[]),
    approve_all_vendor: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
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
    item_ids: list[int] = Body(default=[]),
    reject_all_vendor: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_inventory_verify")),
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
