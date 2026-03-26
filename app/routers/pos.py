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
from app.models.gift_card import GiftCard, GiftCardTransaction
from app.schemas.sale import (
    SaleCreate, SaleResponse, SaleItemResponse, VoidSaleRequest,
    PoyntChargeRequest, PoyntChargeResponse, PoyntStatusResponse,
)
from app.schemas.gift_card import (
    GiftCardActivate, GiftCardLoad, GiftCardRedeem,
    GiftCardResponse, GiftCardDetailResponse, GiftCardTransactionResponse,
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
        .where(func.upper(Item.barcode) == barcode.upper(), Item.status == "active")
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

    if data.payment_method not in ("cash", "card", "split", "gift_card"):
        raise HTTPException(status_code=400, detail="payment_method must be cash, card, split, or gift_card")

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
    gc_amount_applied = None

    if data.payment_method == "split" and data.gift_card_barcode and data.gift_card_amount:
        gc_amount_applied = Decimal(str(data.gift_card_amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        remainder = (total - gc_amount_applied).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if remainder < Decimal("0"):
            gc_amount_applied = total
            remainder = Decimal("0.00")
        if data.cash_tendered is not None:
            cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            change_given = max(
                (cash_tendered - remainder).quantize(Decimal("0.01"), ROUND_HALF_UP),
                Decimal("0.00"),
            )
            if cash_tendered < remainder:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cash tendered ${cash_tendered} is less than remaining ${remainder}",
                )
    elif data.payment_method == "split":
        if data.cash_tendered is not None:
            cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            cash_portion = min(cash_tendered, total)
            change_given = max(
                (cash_tendered - cash_portion).quantize(Decimal("0.01"), ROUND_HALF_UP),
                Decimal("0.00"),
            )
    elif data.payment_method == "cash":
        if data.cash_tendered is None:
            raise HTTPException(status_code=400, detail="cash_tendered is required for cash payments")
        cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if cash_tendered < total:
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
        gift_card_amount=gc_amount_applied if gc_amount_applied else (total if data.payment_method == "gift_card" and data.gift_card_barcode else None),
        gift_card_barcode=data.gift_card_barcode if (gc_amount_applied or data.payment_method == "gift_card") else None,
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

    if data.payment_method in ("gift_card", "split") and data.gift_card_barcode:
        gc_result = await db.execute(
            select(GiftCard).where(GiftCard.barcode == data.gift_card_barcode).with_for_update()
        )
        gc = gc_result.scalar_one_or_none()
        if not gc:
            raise HTTPException(status_code=404, detail="Gift card not found")
        if not gc.is_active:
            raise HTTPException(status_code=400, detail="Gift card is deactivated")
        gc_balance = Decimal(str(gc.balance))
        if data.payment_method == "gift_card":
            deduct_amount = total
            if total > gc_balance:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient gift card balance: ${gc_balance:.2f} available, ${total:.2f} needed"
                )
        else:
            deduct_amount = min(gc_amount_applied or total, gc_balance)
        new_gc_balance = (gc_balance - deduct_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
        gc.balance = new_gc_balance
        gc.last_used_at = datetime.utcnow()
        db.add(GiftCardTransaction(
            gift_card_id=gc.id,
            amount=deduct_amount,
            transaction_type="redeem",
            sale_id=sale.id,
            cashier_id=current_user.id,
            balance_after=new_gc_balance,
            notes=f"Sale #{sale.id}" + (" (split)" if data.payment_method == "split" else ""),
        ))

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
        gift_card_amount=sale.gift_card_amount,
        gift_card_barcode=sale.gift_card_barcode,
        receipt_email=sale.receipt_email,
        created_at=sale.created_at,
        line_items=line_items,
    )


@router.post("/sale/{sale_id}/void", response_model=SaleResponse)
async def void_sale(
    sale_id: int,
    data: VoidSaleRequest = VoidSaleRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Not authorized to void sales")

    lock_result = await db.execute(
        select(Sale).where(Sale.id == sale_id).with_for_update()
    )
    sale_locked = lock_result.scalar_one_or_none()
    if not sale_locked:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale_locked.is_voided:
        raise HTTPException(status_code=400, detail="Sale is already voided")

    result = await db.execute(
        select(Sale)
        .options(
            selectinload(Sale.cashier),
            selectinload(Sale.voided_by_user),
            selectinload(Sale.items).selectinload(SaleItem.item).selectinload(Item.vendor),
            selectinload(Sale.items).selectinload(SaleItem.vendor),
        )
        .where(Sale.id == sale_id)
    )
    sale = result.scalar_one()

    sale.is_voided = True
    sale.voided_at = datetime.utcnow()
    sale.voided_by = current_user.id
    sale.void_reason = data.reason

    vendor_credits = {}
    for si in sale.items:
        item = si.item
        if item:
            item.quantity = item.quantity + si.quantity
            if item.status == "sold":
                item.status = "active"

        vendor_credit = si.line_total
        if si.consignment_amount is not None:
            vendor_credit = (si.line_total - si.consignment_amount).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        vendor_credits[si.vendor_id] = (
            vendor_credits.get(si.vendor_id, Decimal("0")) + vendor_credit
        )

    for vendor_id, amount in vendor_credits.items():
        vb_result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == vendor_id)
        )
        balance_row = vb_result.scalar_one_or_none()
        if balance_row:
            balance_row.balance = (
                Decimal(str(balance_row.balance)) - amount
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    if sale.gift_card_barcode and sale.payment_method in ("gift_card", "split"):
        gc_amount = Decimal(str(sale.gift_card_amount or sale.total))
        gc_result = await db.execute(
            select(GiftCard).where(GiftCard.barcode == sale.gift_card_barcode).with_for_update()
        )
        gc = gc_result.scalar_one_or_none()
        if gc:
            new_balance = (Decimal(str(gc.balance)) + gc_amount).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            gc.balance = new_balance
            db.add(GiftCardTransaction(
                gift_card_id=gc.id,
                amount=gc_amount,
                transaction_type="refund",
                sale_id=sale.id,
                cashier_id=current_user.id,
                balance_after=new_balance,
                notes=f"Void sale #{sale.id}",
            ))

    await db.commit()

    result = await db.execute(
        select(Sale)
        .options(
            selectinload(Sale.cashier),
            selectinload(Sale.voided_by_user),
            selectinload(Sale.items).selectinload(SaleItem.item).selectinload(Item.vendor),
            selectinload(Sale.items).selectinload(SaleItem.vendor),
        )
        .where(Sale.id == sale.id)
    )
    sale = result.scalar_one()

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
        cashier_name=sale.cashier.name if sale.cashier else None,
        subtotal=sale.subtotal,
        tax_rate=sale.tax_rate,
        tax_amount=sale.tax_amount,
        total=sale.total,
        payment_method=sale.payment_method,
        cash_tendered=sale.cash_tendered,
        change_given=sale.change_given,
        card_transaction_id=sale.card_transaction_id,
        gift_card_amount=sale.gift_card_amount,
        gift_card_barcode=sale.gift_card_barcode,
        receipt_email=sale.receipt_email,
        is_voided=sale.is_voided,
        voided_at=sale.voided_at,
        voided_by=sale.voided_by,
        voided_by_name=sale.voided_by_user.name if sale.voided_by_user else None,
        void_reason=sale.void_reason,
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
    total_gift_card = Decimal("0")
    total_tax = Decimal("0")
    total_revenue = Decimal("0")
    cash_count = 0
    card_count = 0
    split_count = 0
    gift_card_count = 0
    cashier_breakdown = {}

    voided_count = 0
    voided_total = Decimal("0")
    for sale in sales:
        if sale.is_voided:
            voided_count += 1
            voided_total += sale.total
            continue

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
            gc_part = sale.gift_card_amount or Decimal("0")
            remaining = sale.total - gc_part
            if sale.cash_tendered is not None:
                split_cash = min(sale.cash_tendered, remaining)
                sale_cash = split_cash
                sale_card = max(remaining - split_cash, Decimal("0"))
            else:
                sale_card = remaining
            total_gift_card += gc_part
            split_count += 1
        elif sale.payment_method == "gift_card":
            total_gift_card += sale.total
            gift_card_count += 1

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
                "gift_card_total": Decimal("0"),
                "total": Decimal("0"),
            }
        cb = cashier_breakdown[cashier_id]
        cb["transactions"] += 1
        cb["total"] += sale.total
        cb["cash_total"] += sale_cash
        cb["card_total"] += sale_card
        if sale.payment_method == "gift_card":
            cb["gift_card_total"] = cb.get("gift_card_total", Decimal("0")) + sale.total

    total_transactions = cash_count + card_count + split_count + gift_card_count
    items_sold = sum(
        si.quantity for sale in sales if not sale.is_voided for si in sale.items
    )

    return {
        "date": target_date.isoformat(),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_transactions": total_transactions,
        "items_sold": items_sold,
        "voided": {"count": voided_count, "total": float(voided_total)},
        "cash": {"total": float(total_cash), "count": cash_count},
        "card": {"total": float(total_card), "count": card_count},
        "split": {"total": float(total_split), "count": split_count},
        "gift_card": {"total": float(total_gift_card), "count": gift_card_count},
        "cashier_breakdown": [
            {
                "cashier_id": cid,
                "name": info["name"],
                "transactions": info["transactions"],
                "cash_total": float(info["cash_total"]),
                "card_total": float(info["card_total"]),
                "gift_card_total": float(info.get("gift_card_total", Decimal("0"))),
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


@router.post("/gift-cards/activate", response_model=GiftCardResponse)
async def activate_gift_card(
    data: GiftCardActivate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    if data.initial_balance < Decimal("0"):
        raise HTTPException(status_code=400, detail="Balance cannot be negative")

    existing = await db.execute(
        select(GiftCard).where(GiftCard.barcode == data.barcode)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This barcode is already registered as a gift card")

    card = GiftCard(
        barcode=data.barcode,
        balance=data.initial_balance,
        is_active=True,
        notes=data.notes,
    )
    db.add(card)
    await db.flush()

    if data.initial_balance > 0:
        txn = GiftCardTransaction(
            gift_card_id=card.id,
            amount=data.initial_balance,
            transaction_type="load",
            cashier_id=current_user.id,
            balance_after=data.initial_balance,
            notes="Initial activation",
        )
        db.add(txn)

    await db.commit()
    await db.refresh(card)
    return card


@router.get("/gift-cards/{barcode}", response_model=GiftCardResponse)
async def check_gift_card_balance(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(
        select(GiftCard).where(GiftCard.barcode == barcode)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Gift card not found")
    return card


@router.post("/gift-cards/{barcode}/load", response_model=GiftCardResponse)
async def load_gift_card(
    barcode: str,
    data: GiftCardLoad,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Load amount must be positive")

    result = await db.execute(
        select(GiftCard).where(GiftCard.barcode == barcode).with_for_update()
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Gift card not found")
    if not card.is_active:
        raise HTTPException(status_code=400, detail="Gift card is deactivated")

    load_amount = Decimal(str(data.amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    new_balance = (Decimal(str(card.balance)) + load_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
    card.balance = new_balance
    card.last_used_at = datetime.utcnow()

    txn = GiftCardTransaction(
        gift_card_id=card.id,
        amount=load_amount,
        transaction_type="load",
        cashier_id=current_user.id,
        balance_after=new_balance,
        notes=data.notes,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(card)
    return card


@router.post("/gift-cards/{barcode}/redeem", response_model=GiftCardResponse)
async def redeem_gift_card(
    barcode: str,
    data: GiftCardRedeem,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Redeem amount must be positive")

    result = await db.execute(
        select(GiftCard).where(GiftCard.barcode == barcode).with_for_update()
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Gift card not found")
    if not card.is_active:
        raise HTTPException(status_code=400, detail="Gift card is deactivated")

    redeem_amount = Decimal(str(data.amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    current_balance = Decimal(str(card.balance))
    if redeem_amount > current_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient gift card balance: ${current_balance:.2f} available, ${redeem_amount:.2f} requested"
        )

    new_balance = (current_balance - redeem_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
    card.balance = new_balance
    card.last_used_at = datetime.utcnow()

    txn = GiftCardTransaction(
        gift_card_id=card.id,
        amount=redeem_amount,
        transaction_type="redeem",
        cashier_id=current_user.id,
        balance_after=new_balance,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(card)
    return card


@router.get("/gift-cards/{barcode}/history")
async def gift_card_history(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(
        select(GiftCard).where(GiftCard.barcode == barcode)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Gift card not found")

    txn_result = await db.execute(
        select(GiftCardTransaction)
        .options(selectinload(GiftCardTransaction.cashier))
        .where(GiftCardTransaction.gift_card_id == card.id)
        .order_by(GiftCardTransaction.created_at.desc())
    )
    txns = txn_result.scalars().all()

    return {
        "card": {
            "id": card.id,
            "barcode": card.barcode,
            "balance": float(card.balance),
            "is_active": card.is_active,
            "issued_at": card.issued_at.isoformat() if card.issued_at else None,
            "last_used_at": card.last_used_at.isoformat() if card.last_used_at else None,
        },
        "transactions": [
            {
                "id": t.id,
                "amount": float(t.amount),
                "type": t.transaction_type,
                "sale_id": t.sale_id,
                "cashier_name": t.cashier.name if t.cashier else None,
                "balance_after": float(t.balance_after),
                "notes": t.notes,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ],
    }


@router.get("/rent/vendors")
async def rent_vendor_list(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    from app.models.rent import RentPayment
    from datetime import date as dt_date
    today = dt_date.today()
    period = dt_date(today.year, today.month, 1)

    result = await db.execute(
        select(Vendor)
        .where(Vendor.role == "vendor", Vendor.monthly_rent > 0)
        .order_by(Vendor.name)
    )
    vendors = result.scalars().all()

    paid_result = await db.execute(
        select(RentPayment.vendor_id).where(
            RentPayment.period_month == period,
            RentPayment.status == "paid",
        )
    )
    paid_ids = {r[0] for r in paid_result.all()}

    return [
        {
            "id": v.id,
            "name": v.name,
            "booth_number": v.booth_number,
            "monthly_rent": float(v.monthly_rent),
            "paid_this_month": v.id in paid_ids,
        }
        for v in vendors
    ]


@router.post("/rent/pay")
async def pos_rent_payment(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Cashier or admin access required")

    from app.models.rent import RentPayment
    from datetime import date as dt_date

    vendor_id = body.get("vendor_id")
    method = body.get("method", "cash")
    amount_override = body.get("amount")
    notes = str(body.get("notes", "") or "")[:200]

    if not vendor_id or not isinstance(vendor_id, int):
        raise HTTPException(status_code=400, detail="Valid vendor_id required")
    if method not in ("cash", "card"):
        raise HTTPException(status_code=400, detail="Method must be cash or card")

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    amount = float(amount_override) if amount_override else float(vendor.monthly_rent or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="No rent amount configured for this vendor")

    today = dt_date.today()
    period = dt_date(today.year, today.month, 1)

    existing = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.period_month == period,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Rent for {period.strftime('%B %Y')} already recorded for {vendor.name}"
        )

    if method == "card":
        try:
            from app.services.square import create_payment_link
            price_cents = round(amount * 100)
            result_link = await create_payment_link(
                name=f"Rent - {vendor.name} - {today.strftime('%B %Y')}",
                price_cents=price_cents,
                redirect_url=f"https://www.bowenstreetmm.com/pos/index.html?rent_paid=success&vendor_id={vendor.id}",
            )
            payment = RentPayment(
                vendor_id=vendor.id,
                amount=amount,
                period_month=period,
                method="square",
                status="pending",
                notes=f"POS card payment initiated by {current_user.name}. {notes}".strip(),
            )
            db.add(payment)
            await db.commit()
            return {
                "success": True,
                "method": "card",
                "payment_url": result_link["url"],
                "message": f"Card payment link created for {vendor.name}. Complete payment at the link.",
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Card payment failed: {str(exc)[:100]}")

    payment = RentPayment(
        vendor_id=vendor.id,
        amount=amount,
        period_month=period,
        method="cash",
        status="paid",
        notes=f"POS cash payment received by {current_user.name}. {notes}".strip(),
    )
    db.add(payment)
    await db.commit()

    return {
        "success": True,
        "method": "cash",
        "message": f"Cash rent payment of ${amount:.2f} recorded for {vendor.name} ({period.strftime('%B %Y')})",
    }
