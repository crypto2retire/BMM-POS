import csv
import io
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.routers.auth import get_current_user, get_password_hash
from app.services.barcode import generate_sku

router = APIRouter(prefix="/bulk-import", tags=["bulk-import"])

MAX_FILE_SIZE = 5 * 1024 * 1024


def _clean(val):
    if val is None:
        return None
    v = val.strip()
    return v if v else None


@router.post("/vendors")
async def bulk_import_vendors(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    required = ["name"]
    for r in required:
        if r not in headers_lower:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required column: {r}. Found: {', '.join(headers_lower.keys())}",
            )

    created = []
    skipped = []
    errors = []

    for row_num, row in enumerate(reader, start=2):
        clean_row = {k.strip().lower(): _clean(v) for k, v in row.items()}
        name = clean_row.get("name")
        if not name:
            skipped.append({"row": row_num, "reason": "Empty name"})
            continue

        email = clean_row.get("email")
        if not email:
            slug = name.lower().replace(" ", ".").replace("'", "")[:40]
            email = f"{slug}@bowenstreetmarket.com"

        existing = await db.execute(
            select(Vendor).where(Vendor.email == email.lower())
        )
        if existing.scalar_one_or_none():
            skipped.append({"row": row_num, "name": name, "reason": f"Email {email} already exists"})
            continue

        try:
            rent_val = Decimal(clean_row["monthly_rent"]) if clean_row.get("monthly_rent") else Decimal("200.00")
        except (InvalidOperation, ValueError):
            rent_val = Decimal("200.00")

        try:
            comm_val = Decimal(clean_row["commission_rate"]) if clean_row.get("commission_rate") else Decimal("0.10")
            if comm_val > 1:
                comm_val = comm_val / 100
        except (InvalidOperation, ValueError):
            comm_val = Decimal("0.10")

        password = clean_row.get("password") or secrets.token_urlsafe(12)

        try:
            async with db.begin_nested():
                vendor = Vendor(
                    name=name,
                    email=email.lower(),
                    phone=clean_row.get("phone"),
                    booth_number=clean_row.get("booth_number") or clean_row.get("booth"),
                    monthly_rent=rent_val,
                    commission_rate=comm_val,
                    password_hash=get_password_hash(password),
                    role="vendor",
                    is_active=True,
                    is_vendor=True,
                    payout_method=clean_row.get("payout_method"),
                    zelle_handle=clean_row.get("zelle_handle") or clean_row.get("zelle"),
                )
                db.add(vendor)
                await db.flush()

                balance_check = await db.execute(
                    select(VendorBalance).where(VendorBalance.vendor_id == vendor.id)
                )
                if not balance_check.scalar_one_or_none():
                    db.add(VendorBalance(vendor_id=vendor.id, balance=Decimal("0.00")))

            created.append({"row": row_num, "name": name, "email": email, "booth": vendor.booth_number, "id": vendor.id})
        except Exception as e:
            errors.append({"row": row_num, "name": name, "error": "Import failed for this row"})

    if created:
        await db.commit()

    return {
        "summary": f"Created {len(created)} vendors, skipped {len(skipped)}, errors {len(errors)}",
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/inventory")
async def bulk_import_inventory(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    required = ["name", "price"]
    for r in required:
        if r not in headers_lower:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required column: {r}. Found: {', '.join(headers_lower.keys())}",
            )

    vendors_cache = {}
    result = await db.execute(select(Vendor).where(Vendor.role == "vendor"))
    for v in result.scalars().all():
        vendors_cache[v.name.lower()] = v
        if v.booth_number:
            vendors_cache[v.booth_number.lower()] = v
        vendors_cache[str(v.id)] = v

    created = []
    skipped = []
    errors = []

    for row_num, row in enumerate(reader, start=2):
        clean_row = {k.strip().lower(): _clean(v) for k, v in row.items()}
        name = clean_row.get("name")
        if not name:
            skipped.append({"row": row_num, "reason": "Empty name"})
            continue

        try:
            price = Decimal(clean_row.get("price", "0").replace("$", "").replace(",", ""))
            if price <= 0:
                raise ValueError("Price must be positive")
        except (InvalidOperation, ValueError) as e:
            errors.append({"row": row_num, "name": name, "error": f"Invalid price: {clean_row.get('price')}"})
            continue

        vendor_ref = clean_row.get("vendor") or clean_row.get("vendor_name") or clean_row.get("booth") or clean_row.get("booth_number") or clean_row.get("vendor_id")
        vendor = None
        if vendor_ref:
            vendor = vendors_cache.get(vendor_ref.lower()) or vendors_cache.get(vendor_ref)

        if not vendor:
            errors.append({"row": row_num, "name": name, "error": f"Vendor not found: '{vendor_ref}'. Import vendors first."})
            continue

        try:
            qty = int(clean_row.get("quantity") or clean_row.get("qty") or "1")
        except ValueError:
            qty = 1

        category = clean_row.get("category")
        description = clean_row.get("description")
        barcode = clean_row.get("barcode")

        is_tax_exempt = clean_row.get("tax_exempt", "").lower() in ("true", "yes", "1", "y")

        if not barcode:
            barcode = str(uuid.uuid4().int)[:12]
            existing = await db.execute(select(Item).where(Item.barcode == barcode))
            while existing.scalar_one_or_none():
                barcode = str(uuid.uuid4().int)[:12]
                existing = await db.execute(select(Item).where(Item.barcode == barcode))

        try:
            async with db.begin_nested():
                sku = await generate_sku(vendor.id, db)

                sale_price = None
                if clean_row.get("sale_price"):
                    try:
                        sp = Decimal(clean_row["sale_price"].replace("$", "").replace(",", ""))
                        if sp < price:
                            sale_price = sp
                    except (InvalidOperation, ValueError):
                        pass

                consignment = clean_row.get("consignment", "").lower() in ("true", "yes", "1", "y")
                consignment_rate = None
                if consignment and clean_row.get("consignment_rate"):
                    try:
                        cr = Decimal(clean_row["consignment_rate"].replace("%", ""))
                        consignment_rate = cr / 100 if cr > 1 else cr
                    except (InvalidOperation, ValueError):
                        consignment_rate = None

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
                )
                db.add(item)
                await db.flush()

            created.append({
                "row": row_num,
                "name": name,
                "price": float(price),
                "vendor": vendor.name,
                "booth": vendor.booth_number,
                "barcode": barcode,
                "id": item.id,
            })
        except Exception as e:
            errors.append({"row": row_num, "name": name, "error": "Import failed for this row"})

    if created:
        await db.commit()

    return {
        "summary": f"Created {len(created)} items, skipped {len(skipped)}, errors {len(errors)}",
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/clear-test-data")
async def clear_test_data(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.models.sale import Sale, SaleItem

    sale_count_result = await db.execute(select(Sale))
    if sale_count_result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="Cannot clear data: sales records exist. This is a safety check to prevent accidental data loss.",
        )

    from sqlalchemy import delete
    from app.models.gift_card import GiftCard, GiftCardTransaction

    await db.execute(delete(GiftCardTransaction))
    await db.execute(delete(GiftCard))

    result = await db.execute(
        select(Item).where(Item.vendor_id.in_(
            select(Vendor.id).where(Vendor.role == "vendor")
        ))
    )
    items = result.scalars().all()
    item_count = len(items)
    for item in items:
        await db.delete(item)

    result = await db.execute(
        select(Vendor).where(Vendor.role == "vendor")
    )
    vendors = result.scalars().all()
    vendor_count = len(vendors)
    for vendor in vendors:
        bal = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == vendor.id)
        )
        b = bal.scalar_one_or_none()
        if b:
            await db.delete(b)
        await db.delete(vendor)

    await db.commit()

    return {
        "message": f"Cleared {vendor_count} vendors and {item_count} items (test data only, no sales affected)",
    }
