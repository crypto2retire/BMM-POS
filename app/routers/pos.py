import math
import os
import base64
import io
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, cast, Date
from sqlalchemy.orm import selectinload
import httpx
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.item_image import ItemImage
from app.models.sale import Sale, SaleItem
from app.schemas.sale import (
    SaleCreate, SaleResponse, SaleItemResponse,
    PoyntChargeRequest, PoyntChargeResponse, PoyntStatusResponse,
)
from app.services import poynt
from app.config import settings
from app.routers.settings import get_tax_rate

router = APIRouter(prefix="/pos", tags=["pos"])


def _get_active_price(item: Item) -> Decimal:
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        return Decimal(str(item.sale_price))
    return Decimal(str(item.price))


def _item_to_pos_dict(item: Item) -> dict:
    active_price = _get_active_price(item)
    return {
        "id": item.id,
        "name": item.name,
        "barcode": item.barcode,
        "sku": item.sku,
        "price": float(item.price),
        "active_price": float(active_price),
        "sale_price": float(item.sale_price) if item.sale_price is not None else None,
        "sale_start": item.sale_start.isoformat() if item.sale_start else None,
        "sale_end": item.sale_end.isoformat() if item.sale_end else None,
        "category": item.category,
        "vendor_id": item.vendor_id,
        "booth_number": item.vendor.booth_number if item.vendor else None,
        "is_tax_exempt": item.is_tax_exempt,
        "is_consignment": item.is_consignment,
        "consignment_rate": float(item.consignment_rate) if item.consignment_rate is not None else None,
        "quantity": item.quantity,
        "photo_urls": item.photo_urls,
    }


@router.get("/search")
async def pos_search(
    q: str = Query(..., min_length=1, description="Search term"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    term = f"%{q}%"
    query = (
        select(Item)
        .options(selectinload(Item.vendor))
        .where(
            Item.status == "active",
            or_(
                Item.name.ilike(term),
                Item.barcode == q,
                Item.sku.ilike(term),
            ),
        )
        .limit(20)
    )
    result = await db.execute(query)
    items = result.scalars().all()
    return [_item_to_pos_dict(i) for i in items]


@router.get("/barcode/{barcode}")
async def pos_barcode_lookup(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    result = await db.execute(
        select(Item)
        .options(selectinload(Item.vendor))
        .where(Item.barcode == barcode, Item.status == "active")
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or not available")
    return _item_to_pos_dict(item)


@router.post("/manual-item")
async def pos_manual_item(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    vendor_id = body.get("vendor_id")
    name = body.get("name", "").strip()
    price = body.get("price")
    quantity = body.get("quantity", 1)
    is_tax_exempt = body.get("is_tax_exempt", False)
    is_consignment = body.get("is_consignment", False)
    consignment_rate = body.get("consignment_rate")

    if not vendor_id or not name or not price:
        raise HTTPException(status_code=400, detail="vendor_id, name, and price are required")

    if is_consignment and consignment_rate is None:
        raise HTTPException(status_code=400, detail="consignment_rate is required for consignment items")
    if consignment_rate is not None and (consignment_rate < 0 or consignment_rate > 1):
        raise HTTPException(status_code=400, detail="consignment_rate must be between 0 and 1")
    if not is_consignment:
        consignment_rate = None

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    import uuid
    barcode = f"MAN-{uuid.uuid4().hex[:8].upper()}"

    item = Item(
        vendor_id=vendor_id,
        name=name,
        barcode=barcode,
        sku=barcode,
        price=Decimal(str(price)),
        quantity=quantity,
        category="Manual Entry",
        status="active",
        is_tax_exempt=is_tax_exempt,
        is_consignment=is_consignment,
        consignment_rate=Decimal(str(consignment_rate)) if consignment_rate is not None else None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item, attribute_names=["id", "vendor"])

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item.id)
    )
    item = result.scalar_one()

    return _item_to_pos_dict(item)


@router.post("/sale", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
async def pos_create_sale(
    data: SaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    if not data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    if data.payment_method not in ("cash", "card", "split"):
        raise HTTPException(status_code=400, detail="payment_method must be cash, card, or split")

    resolved_lines = []
    for cart_item in data.items:
        result = await db.execute(
            select(Item).options(selectinload(Item.vendor)).where(Item.barcode == cart_item.barcode)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item with barcode {cart_item.barcode!r} not found")
        if item.status != "active":
            raise HTTPException(status_code=400, detail=f"Item {item.name!r} is not available for sale")
        if item.quantity < cart_item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {item.name!r}: have {item.quantity}, requested {cart_item.quantity}",
            )
        unit_price = _get_active_price(item)
        line_total = (unit_price * cart_item.quantity).quantize(Decimal("0.01"), ROUND_HALF_UP)
        resolved_lines.append((item, cart_item.quantity, unit_price, line_total))

    subtotal = sum(lt for _, _, _, lt in resolved_lines).quantize(Decimal("0.01"), ROUND_HALF_UP)

    db_tax_rate = await get_tax_rate(db)
    tax_rate = Decimal(str(db_tax_rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    taxable_subtotal = sum(
        lt for item, _, _, lt in resolved_lines if not item.is_tax_exempt
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax_amount = (taxable_subtotal * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    total = (subtotal + tax_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

    change_given = None
    cash_tendered = None
    if data.payment_method in ("cash", "split"):
        if data.cash_tendered is None:
            raise HTTPException(status_code=400, detail="cash_tendered is required for cash payments")
        cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if data.payment_method == "cash" and cash_tendered < total:
            raise HTTPException(
                status_code=400,
                detail=f"Cash tendered ${cash_tendered} is less than total ${total}",
            )
        change_given = max(
            (cash_tendered - total).quantize(Decimal("0.01"), ROUND_HALF_UP),
            Decimal("0.00"),
        )

    sale = Sale(
        cashier_id=current_user.id,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        payment_method=data.payment_method,
        cash_tendered=cash_tendered,
        change_given=change_given,
        card_transaction_id=data.card_transaction_id,
        receipt_email=data.receipt_email,
    )
    db.add(sale)
    await db.flush()

    vendor_totals: dict[int, Decimal] = {}
    for item, qty, unit_price, line_total in resolved_lines:
        consignment_amt = None
        c_rate = None
        if item.is_consignment and item.consignment_rate is not None:
            c_rate = Decimal(str(item.consignment_rate))
            consignment_amt = (line_total * c_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

        sale_item = SaleItem(
            sale_id=sale.id,
            item_id=item.id,
            vendor_id=item.vendor_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
            is_consignment=item.is_consignment,
            consignment_rate=c_rate,
            consignment_amount=consignment_amt,
        )
        db.add(sale_item)

        new_qty = item.quantity - qty
        item.quantity = new_qty
        if new_qty <= 0:
            item.status = "sold"

        vendor_credit = line_total
        if consignment_amt is not None:
            vendor_credit = (line_total - consignment_amt).quantize(Decimal("0.01"), ROUND_HALF_UP)

        vendor_totals[item.vendor_id] = (
            vendor_totals.get(item.vendor_id, Decimal("0")) + vendor_credit
        )

    for vendor_id, amount in vendor_totals.items():
        result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == vendor_id)
        )
        balance_row = result.scalar_one_or_none()
        if balance_row:
            balance_row.balance = (
                Decimal(str(balance_row.balance)) + amount
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            db.add(VendorBalance(vendor_id=vendor_id, balance=amount))

    await db.commit()

    result = await db.execute(
        select(Sale)
        .options(
            selectinload(Sale.cashier),
            selectinload(Sale.items).selectinload(SaleItem.item).selectinload(Item.vendor),
            selectinload(Sale.items).selectinload(SaleItem.vendor),
        )
        .where(Sale.id == sale.id)
    )
    sale = result.scalar_one()

    cashier_name = sale.cashier.name if sale.cashier else None
    line_items = []
    for si in sale.items:
        line_items.append(
            SaleItemResponse(
                id=si.id,
                item_id=si.item_id,
                vendor_id=si.vendor_id,
                item_name=si.item.name if si.item else "Unknown",
                booth_number=si.vendor.booth_number if si.vendor else None,
                sku=si.item.sku if si.item else "",
                quantity=si.quantity,
                unit_price=si.unit_price,
                line_total=si.line_total,
                is_consignment=si.is_consignment,
                consignment_rate=si.consignment_rate,
                consignment_amount=si.consignment_amount,
            )
        )

    return SaleResponse(
        id=sale.id,
        cashier_id=sale.cashier_id,
        cashier_name=cashier_name,
        subtotal=sale.subtotal,
        tax_rate=sale.tax_rate,
        tax_amount=sale.tax_amount,
        total=sale.total,
        payment_method=sale.payment_method,
        cash_tendered=sale.cash_tendered,
        change_given=sale.change_given,
        card_transaction_id=sale.card_transaction_id,
        receipt_email=sale.receipt_email,
        created_at=sale.created_at,
        line_items=line_items,
    )


@router.post("/payment-callback", status_code=status.HTTP_200_OK)
async def payment_callback(current_user: Vendor = Depends(get_current_user)):
    return {"status": "ok"}


@router.post("/poynt/charge", response_model=PoyntChargeResponse)
async def poynt_charge(
    data: PoyntChargeRequest,
    current_user: Vendor = Depends(get_current_user),
):
    amount_cents = math.ceil(data.amount * 100)
    order_id = await poynt.create_terminal_order(
        amount_cents=amount_cents,
        currency="USD",
        order_ref=data.order_ref,
    )
    return PoyntChargeResponse(poynt_order_id=order_id)


@router.get("/poynt/status/{poynt_order_id}", response_model=PoyntStatusResponse)
async def poynt_status(
    poynt_order_id: str,
    current_user: Vendor = Depends(get_current_user),
):
    result = await poynt.get_transaction_for_order(poynt_order_id)
    return PoyntStatusResponse(
        status=result["status"],
        transaction_id=result.get("transaction_id"),
    )


@router.get("/end-of-day")
async def end_of_day_report(
    report_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    store_tz = ZoneInfo("America/Chicago")

    if report_date:
        try:
            target_date = date.fromisoformat(report_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        target_date = datetime.now(store_tz).date()

    start_local = datetime(target_date.year, target_date.month, target_date.day, tzinfo=store_tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    result = await db.execute(
        select(Sale)
        .options(selectinload(Sale.cashier), selectinload(Sale.items))
        .where(Sale.created_at >= start_utc, Sale.created_at < end_utc)
        .order_by(Sale.created_at)
    )
    sales = result.scalars().all()

    total_cash = Decimal("0")
    total_card = Decimal("0")
    total_split = Decimal("0")
    total_tax = Decimal("0")
    total_revenue = Decimal("0")
    cash_count = 0
    card_count = 0
    split_count = 0
    cashier_breakdown = {}

    for sale in sales:
        total_revenue += sale.total
        total_tax += sale.tax_amount

        sale_cash = Decimal("0")
        sale_card = Decimal("0")

        if sale.payment_method == "cash":
            sale_cash = sale.total
            cash_count += 1
        elif sale.payment_method == "card":
            sale_card = sale.total
            card_count += 1
        elif sale.payment_method == "split":
            split_cash = min(sale.cash_tendered or Decimal("0"), sale.total)
            sale_cash = split_cash
            sale_card = sale.total - split_cash
            split_count += 1

        total_cash += sale_cash
        total_card += sale_card
        total_split += (sale_cash + sale_card) if sale.payment_method == "split" else Decimal("0")

        cashier_name = sale.cashier.name if sale.cashier else "Unknown"
        cashier_id = sale.cashier_id or 0
        if cashier_id not in cashier_breakdown:
            cashier_breakdown[cashier_id] = {
                "name": cashier_name,
                "transactions": 0,
                "cash_total": Decimal("0"),
                "card_total": Decimal("0"),
                "total": Decimal("0"),
            }
        cb = cashier_breakdown[cashier_id]
        cb["transactions"] += 1
        cb["total"] += sale.total
        cb["cash_total"] += sale_cash
        cb["card_total"] += sale_card

    total_transactions = cash_count + card_count + split_count
    items_sold = sum(
        si.quantity for sale in sales for si in sale.items
    )

    return {
        "date": target_date.isoformat(),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_transactions": total_transactions,
        "items_sold": items_sold,
        "cash": {"total": float(total_cash), "count": cash_count},
        "card": {"total": float(total_card), "count": card_count},
        "split": {"total": float(total_split), "count": split_count},
        "cashier_breakdown": [
            {
                "cashier_id": cid,
                "name": info["name"],
                "transactions": info["transactions"],
                "cash_total": float(info["cash_total"]),
                "card_total": float(info["card_total"]),
                "total": float(info["total"]),
            }
            for cid, info in cashier_breakdown.items()
        ],
    }


@router.post("/image-search")
async def image_search(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 5MB")

    mime = file.content_type or "image/jpeg"
    img_b64 = base64.b64encode(contents).decode("utf-8")

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant not configured")

    result = await db.execute(
        select(Item.id)
        .join(ItemImage, ItemImage.item_id == Item.id)
        .where(Item.status == "active")
    )
    items_with_images = [r[0] for r in result.all()]

    if not items_with_images:
        return {"matches": [], "description": "No items with images in inventory."}

    result = await db.execute(
        select(Item)
        .options(selectinload(Item.vendor))
        .where(Item.id.in_(items_with_images))
    )
    inventory_items = result.scalars().all()

    inventory_text = "\n".join([
        f"- ID:{it.id} | {it.name} | Category: {it.category or 'N/A'} | ${float(it.price):.2f} | Booth: {it.vendor.booth_number if it.vendor else 'N/A'}"
        for it in inventory_items
    ])

    prompt = f"""You are helping a cashier identify an item a customer brought to the register that has no tag.
Look at this photo and describe the item briefly, then check this inventory list of items that have photos on file.
Return ONLY a JSON object with:
- "description": a short description of what you see in the photo (1-2 sentences)
- "matches": an array of item IDs from the list that could be this item, ranked by likelihood (most likely first). Maximum 8 matches. Only include plausible matches based on name/category.

If nothing matches, return an empty matches array.

INVENTORY:
{inventory_text}

Respond with ONLY valid JSON, no markdown.
"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 500,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ]},
                    ],
                },
            )

        if not resp.is_success:
            raise HTTPException(status_code=502, detail="AI service unavailable")

        body = resp.json()
        raw_text = body["choices"][0]["message"].get("content", "")
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        import json as json_lib
        ai_result = json_lib.loads(cleaned)

    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(status_code=504, detail="AI service timed out")
    except (KeyError, IndexError, ValueError):
        return {"matches": [], "description": "Could not identify the item. Try a clearer photo."}

    matched_ids = ai_result.get("matches", [])
    description = ai_result.get("description", "")

    if matched_ids:
        result = await db.execute(
            select(Item)
            .options(selectinload(Item.vendor))
            .where(Item.id.in_(matched_ids), Item.status == "active")
        )
        matched_items = result.scalars().all()
        items_by_id = {it.id: it for it in matched_items}
        ordered_matches = []
        for mid in matched_ids:
            if mid in items_by_id:
                ordered_matches.append(_item_to_pos_dict(items_by_id[mid]))
    else:
        ordered_matches = []

    return {"matches": ordered_matches, "description": description}
