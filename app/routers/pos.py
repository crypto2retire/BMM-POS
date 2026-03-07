import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.sale import Sale, SaleItem
from app.schemas.sale import (
    SaleCreate, SaleResponse, SaleItemResponse,
    PoyntChargeRequest, PoyntChargeResponse, PoyntStatusResponse,
)
from app.services import poynt
from app.config import settings

router = APIRouter(prefix="/pos", tags=["pos"])


def _get_active_price(item: Item) -> Decimal:
    today = date.today()
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        return Decimal(str(item.sale_price))
    return Decimal(str(item.price))


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

    tax_rate = Decimal(str(settings.tax_rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
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
        sale_item = SaleItem(
            sale_id=sale.id,
            item_id=item.id,
            vendor_id=item.vendor_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
        )
        db.add(sale_item)

        new_qty = item.quantity - qty
        item.quantity = new_qty
        if new_qty <= 0:
            item.status = "sold"

        vendor_totals[item.vendor_id] = (
            vendor_totals.get(item.vendor_id, Decimal("0")) + line_total
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
