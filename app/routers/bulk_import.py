import csv
import io
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.routers.auth import get_current_user, get_password_hash
from app.services.barcode import generate_sku, generate_short_barcode

from sqlalchemy import text

router = APIRouter(prefix="/bulk-import", tags=["bulk-import"])

MAX_FILE_SIZE = 25 * 1024 * 1024


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

    sku_counters = {}
    sku_count_result = await db.execute(
        select(Item.vendor_id, func.count(Item.id)).group_by(Item.vendor_id)
    )
    for vid, cnt in sku_count_result.all():
        sku_counters[vid] = cnt

    existing_skus = set()
    sku_result = await db.execute(select(Item.sku))
    for (s,) in sku_result.all():
        if s:
            existing_skus.add(s)

    existing_barcodes = set()
    bc_result = await db.execute(select(Item.barcode))
    for (b,) in bc_result.all():
        if b:
            existing_barcodes.add(b)

    def next_sku(vendor_id):
        seq = sku_counters.get(vendor_id, 0) + 1
        while True:
            sku = f"BSM-{vendor_id:04d}-{seq:06d}"
            if sku not in existing_skus:
                existing_skus.add(sku)
                sku_counters[vendor_id] = seq
                return sku
            seq += 1

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
            import random, string
            _bc_chars = string.digits + string.ascii_uppercase
            barcode = "".join(random.choices(_bc_chars, k=6))
            while barcode in existing_barcodes:
                barcode = "".join(random.choices(_bc_chars, k=6))
        existing_barcodes.add(barcode)

        try:
            async with db.begin_nested():
                sku = clean_row.get("sku") or next_sku(vendor.id)

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

            created.append({
                "row": row_num,
                "name": name,
                "price": float(price),
                "vendor": vendor.name,
                "booth": vendor.booth_number,
                "barcode": barcode,
            })
        except Exception as e:
            errors.append({"row": row_num, "name": name, "error": "Import failed for this row"})

    if created:
        await db.commit()

    return {
        "summary": f"Created {len(created)} items, skipped {len(skipped)}, errors {len(errors)}",
        "created_count": len(created),
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


@router.post("/fix-barcodes")
async def fix_barcodes_from_ricochet(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    csv_rows = []
    for row in reader:
        sku_raw = row.get("SKU", "").strip().strip("'").strip()
        name = row.get("Name", "").strip()
        consignor = row.get("Consignor", "").strip()
        price_str = row.get("Agreed Price", "").strip().replace("$", "").replace(",", "")
        if not sku_raw or not name:
            continue
        try:
            price = float(Decimal(price_str)) if price_str else 0.0
        except (InvalidOperation, ValueError):
            continue
        csv_rows.append({
            "sku6": sku_raw,
            "name": name,
            "consignor": consignor.lower(),
            "price": price,
        })

    vendor_map = {}
    vresult = await db.execute(text("SELECT id, lower(name) as lname FROM vendors WHERE role='vendor'"))
    for row in vresult.all():
        vendor_map[row.lname] = row.id

    items_result = await db.execute(
        text("SELECT id, vendor_id, lower(name) as lname, price::float as price, barcode FROM items WHERE status='active'")
    )
    db_items = items_result.all()

    db_lookup = {}
    for it in db_items:
        key = (it.vendor_id, it.lname.strip(), round(it.price, 2))
        if key not in db_lookup:
            db_lookup[key] = []
        db_lookup[key].append(it)

    updated = 0
    not_found = 0
    already_correct = 0
    errors_list = []

    used_ids = set()
    update_pairs = []

    for csv_row in csv_rows:
        vendor_id = vendor_map.get(csv_row["consignor"])
        if not vendor_id:
            not_found += 1
            continue

        key = (vendor_id, csv_row["name"].lower().strip(), round(csv_row["price"], 2))
        matches = db_lookup.get(key, [])

        if not matches:
            not_found += 1
            continue

        target = None
        for m in matches:
            if m.id not in used_ids:
                target = m
                break
        if not target:
            not_found += 1
            continue

        used_ids.add(target.id)
        new_bc = csv_row["sku6"].upper()

        if target.barcode == new_bc:
            already_correct += 1
            continue

        update_pairs.append((target.id, new_bc))

    BATCH = 500
    for i in range(0, len(update_pairs), BATCH):
        chunk = update_pairs[i:i + BATCH]
        cases = []
        ids = []
        params = {}
        for j, (item_id, bc) in enumerate(chunk):
            cases.append(f"WHEN id = :id{j} THEN :bc{j}")
            params[f"id{j}"] = item_id
            params[f"bc{j}"] = bc
            ids.append(f":id{j}")
        sql = text(
            f"UPDATE items SET barcode = CASE {' '.join(cases)} END "
            f"WHERE id IN ({', '.join(ids)})"
        )
        try:
            result = await db.execute(sql, params)
            updated += result.rowcount
        except Exception as e:
            errors_list.append(str(e)[:200])

    if updated > 0:
        await db.commit()

    return {
        "summary": f"Updated {updated} barcodes, {already_correct} already correct, {not_found} not matched, {len(errors_list)} errors",
        "updated": updated,
        "already_correct": already_correct,
        "not_found": not_found,
        "errors": errors_list[:20],
    }


@router.post("/batch-items")
async def batch_import_items(
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
        raise HTTPException(status_code=400, detail="File too large")

    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    vendor_map = {}
    vresult = await db.execute(text("SELECT id, lower(name) as lname FROM vendors WHERE role='vendor'"))
    for row in vresult.all():
        vendor_map[row.lname] = row.id

    created = 0
    skipped = 0
    errors = []
    batch_params = []

    for row_num, row in enumerate(reader, start=2):
        clean = {k.strip().lower(): _clean(v) for k, v in row.items()}
        name = clean.get("name")
        if not name:
            continue

        price_str = clean.get("price", "0")
        try:
            price = Decimal(price_str.replace("$", "").replace(",", ""))
            if price <= 0:
                continue
        except (InvalidOperation, ValueError):
            continue

        vref = clean.get("vendor_name") or clean.get("vendor") or ""
        vendor_id = vendor_map.get(vref.lower())
        if not vendor_id:
            errors.append({"row": row_num, "name": name, "error": f"Vendor not found: {vref}"})
            continue

        import random as _rnd, string as _stg
        barcode = clean.get("barcode") or "".join(_rnd.choices(_stg.digits + _stg.ascii_uppercase, k=6))
        sku = clean.get("sku") or f"BSM-{vendor_id:04d}-{row_num:06d}"

        try:
            qty = int(clean.get("quantity") or "1")
        except ValueError:
            qty = 1

        is_consignment = clean.get("consignment", "").lower() in ("true", "yes", "1", "y")
        is_tax_exempt = clean.get("tax_exempt", "").lower() in ("true", "yes", "1", "y")

        cr = None
        if is_consignment and clean.get("consignment_rate"):
            try:
                crv = Decimal(clean["consignment_rate"].replace("%", ""))
                cr = crv / 100 if crv > 1 else crv
            except (InvalidOperation, ValueError):
                pass

        sp = None
        if clean.get("sale_price"):
            try:
                spv = Decimal(clean["sale_price"].replace("$", "").replace(",", ""))
                if spv < price:
                    sp = spv
            except (InvalidOperation, ValueError):
                pass

        batch_params.append({
            "vid": vendor_id, "name": name[:200],
            "desc": clean.get("description"), "price": float(price),
            "sp": float(sp) if sp else None, "qty": qty,
            "cat": clean.get("category"), "bc": barcode, "sku": sku,
            "tax": is_tax_exempt, "cons": is_consignment,
            "cr": float(cr) if cr else None,
        })

    if batch_params:
        BATCH_SIZE = 100
        for i in range(0, len(batch_params), BATCH_SIZE):
            chunk = batch_params[i:i + BATCH_SIZE]
            values_parts = []
            bind_params = {}
            for j, p in enumerate(chunk):
                prefix = f"p{j}_"
                values_parts.append(
                    f"(:{prefix}vid, :{prefix}name, :{prefix}desc, :{prefix}price, "
                    f":{prefix}sp, :{prefix}qty, :{prefix}cat, :{prefix}bc, :{prefix}sku, "
                    f":{prefix}tax, :{prefix}cons, :{prefix}cr, 'active')"
                )
                for k, v in p.items():
                    bind_params[f"{prefix}{k}"] = v
            sql = text(
                "INSERT INTO items (vendor_id, name, description, price, sale_price, "
                "quantity, category, barcode, sku, is_tax_exempt, is_consignment, "
                "consignment_rate, status) VALUES " + ", ".join(values_parts) +
                " ON CONFLICT DO NOTHING"
            )
            try:
                result = await db.execute(sql, bind_params)
                created += result.rowcount
                skipped += len(chunk) - result.rowcount
            except Exception as e:
                errors.append({"row": i, "name": "batch", "error": str(e)[:200]})
        await db.commit()

    return {
        "summary": f"Inserted {created} items, skipped {skipped} duplicates, {len(errors)} errors",
        "created_count": created,
        "skipped_count": skipped,
        "errors": errors[:20],
    }
