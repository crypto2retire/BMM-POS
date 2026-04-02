from datetime import date, datetime, timedelta, timezone
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.models.vendor import Vendor, VendorBalance
from app.schemas.sale import SaleCreate, SaleResponse, SaleItemResponse
from app.routers.auth import get_current_user, require_cashier_or_admin
from app.config import settings
from app.routers.settings import get_tax_rate
from app.timezone import STORE_TZ as _STORE_TZ

router = APIRouter(prefix="/sales", tags=["sales"])


def _format_cst(dt):
    """Format a datetime as a display string in store local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    local_dt = dt.astimezone(_STORE_TZ)
    tz_abbr = local_dt.strftime("%Z")  # "CST" or "CDT" depending on time of year
    return local_dt.strftime("%b %-d, %Y at %-I:%M %p") + f" {tz_abbr}"


def get_active_price(item: Item) -> Decimal:
    today = datetime.now(_STORE_TZ).date()
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        return Decimal(str(item.sale_price))
    return Decimal(str(item.price))


def sale_to_response(sale: Sale) -> SaleResponse:
    cashier_name = None
    if sale.cashier:
        cashier_name = sale.cashier.name

    line_items = []
    for si in sale.items:
        booth = si.vendor.booth_number if si.vendor else None
        sku = si.item.sku if si.item else ""
        item_name = si.item.name if si.item else "Unknown"
        line_items.append(
            SaleItemResponse(
                id=si.id,
                item_id=si.item_id,
                vendor_id=si.vendor_id,
                item_name=item_name,
                booth_number=booth,
                sku=sku,
                quantity=si.quantity,
                unit_price=si.unit_price,
                line_total=si.line_total,
                is_consignment=si.is_consignment,
                consignment_rate=si.consignment_rate,
                consignment_amount=si.consignment_amount,
                discount_type=getattr(si, 'discount_type', None),
                discount_value=getattr(si, 'discount_value', None),
                discount_amount=getattr(si, 'discount_amount', None),
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
        is_voided=sale.is_voided,
        voided_at=sale.voided_at,
        voided_by=sale.voided_by,
        voided_by_name=sale.voided_by_user.name if hasattr(sale, 'voided_by_user') and sale.voided_by_user else None,
        void_reason=sale.void_reason,
        discount_type=getattr(sale, 'discount_type', None),
        discount_value=getattr(sale, 'discount_value', None),
        discount_amount=getattr(sale, 'discount_amount', None),
        created_at=sale.created_at,
        created_at_display=_format_cst(sale.created_at),
        line_items=line_items,
    )


@router.post("/", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
async def create_sale(
    data: SaleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
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
        unit_price = get_active_price(item)
        line_total = (unit_price * cart_item.quantity).quantize(Decimal("0.01"), ROUND_HALF_UP)
        resolved_lines.append((item, cart_item.quantity, unit_price, line_total))

    subtotal = sum(line[3] for line in resolved_lines).quantize(Decimal("0.01"), ROUND_HALF_UP)
    db_tax_rate = await get_tax_rate(db)
    tax_rate = Decimal(str(db_tax_rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    tax_amount = (subtotal * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    total = (subtotal + tax_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

    change_given = None
    if data.payment_method == "cash":
        if data.cash_tendered is None:
            raise HTTPException(status_code=400, detail="cash_tendered is required for cash payments")
        cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if cash_tendered < total:
            raise HTTPException(
                status_code=400,
                detail=f"Cash tendered ${cash_tendered} is less than total ${total}",
            )
        change_given = (cash_tendered - total).quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        cash_tendered = None

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
        # Safety: no consignment — vendors receive 100% of line total (ignore stale DB flags)
        sale_item = SaleItem(
            sale_id=sale.id,
            item_id=item.id,
            vendor_id=item.vendor_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total,
            is_consignment=False,
            consignment_rate=None,
            consignment_amount=None,
        )
        db.add(sale_item)

        new_qty = item.quantity - qty
        item.quantity = new_qty
        if new_qty <= 0:
            item.status = "sold"

        vendor_credit = line_total

        vendor_totals[item.vendor_id] = vendor_totals.get(item.vendor_id, Decimal("0")) + vendor_credit

    for vendor_id, amount in vendor_totals.items():
        result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == vendor_id)
        )
        balance_row = result.scalar_one_or_none()
        if balance_row:
            balance_row.balance = (Decimal(str(balance_row.balance)) + amount).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        else:
            db.add(VendorBalance(vendor_id=vendor_id, balance=amount))

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
    return sale_to_response(sale)


@router.get("/", response_model=List[SaleResponse])
async def list_sales(
    vendor_id: Optional[int] = Query(None),
    limit: Optional[int] = Query(200, ge=1, le=500),
    search_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    def _parse_date(s, label="date"):
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid {label} format. Use YYYY-MM-DD.")

    def _apply_date_filters(q):
        if date_from and date_to:
            d1 = _parse_date(date_from, "date_from")
            d2 = _parse_date(date_to, "date_to")
            if d2 < d1:
                d1, d2 = d2, d1
            start_utc = datetime(d1.year, d1.month, d1.day, tzinfo=_STORE_TZ).astimezone(timezone.utc)
            end_utc = datetime(d2.year, d2.month, d2.day, tzinfo=_STORE_TZ).astimezone(timezone.utc) + timedelta(days=1)
            q = q.where(Sale.created_at >= start_utc, Sale.created_at < end_utc)
        elif date_from:
            d1 = _parse_date(date_from, "date_from")
            start_utc = datetime(d1.year, d1.month, d1.day, tzinfo=_STORE_TZ).astimezone(timezone.utc)
            q = q.where(Sale.created_at >= start_utc)
        elif date_to:
            d2 = _parse_date(date_to, "date_to")
            end_utc = datetime(d2.year, d2.month, d2.day, tzinfo=_STORE_TZ).astimezone(timezone.utc) + timedelta(days=1)
            q = q.where(Sale.created_at < end_utc)
        elif search_date:
            d = _parse_date(search_date, "search_date")
            start_utc = datetime(d.year, d.month, d.day, tzinfo=_STORE_TZ).astimezone(timezone.utc)
            end_utc = start_utc + timedelta(days=1)
            q = q.where(Sale.created_at >= start_utc, Sale.created_at < end_utc)
        return q

    if current_user.role in ("admin", "cashier"):
        q = (
            select(Sale)
            .options(
                selectinload(Sale.cashier),
                selectinload(Sale.items).selectinload(SaleItem.item).selectinload(Item.vendor),
                selectinload(Sale.items).selectinload(SaleItem.vendor),
            )
            .order_by(Sale.created_at.desc())
        )
        if vendor_id:
            q = q.join(SaleItem, SaleItem.sale_id == Sale.id).where(SaleItem.vendor_id == vendor_id).distinct()
        q = _apply_date_filters(q)
        q = q.limit(limit)
        result = await db.execute(q)
        sales = result.scalars().all()
    else:
        vq = (
            select(Sale)
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .where(SaleItem.vendor_id == current_user.id)
            .options(
                selectinload(Sale.cashier),
                selectinload(Sale.items).selectinload(SaleItem.item).selectinload(Item.vendor),
                selectinload(Sale.items).selectinload(SaleItem.vendor),
            )
            .order_by(Sale.created_at.desc())
            .distinct()
        )
        vq = _apply_date_filters(vq)
        result = await db.execute(vq)
        sales = result.scalars().all()

    return [sale_to_response(s) for s in sales]


@router.get("/summary/today")
async def sales_summary_today(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    today = datetime.now(_STORE_TZ).date()
    start_local = datetime(today.year, today.month, today.day, tzinfo=_STORE_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    result = await db.execute(
        select(
            func.count(Sale.id).label("sale_count"),
            func.coalesce(func.sum(Sale.total), 0).label("total_revenue"),
            func.coalesce(func.sum(Sale.tax_amount), 0).label("total_tax"),
        ).where(
            Sale.created_at >= start_utc,
            Sale.created_at < end_utc,
        )
    )
    row = result.one()
    return {
        "date": str(today),
        "sale_count": row.sale_count,
        "total_revenue": float(row.total_revenue),
        "total_tax": float(row.total_tax),
    }


@router.get("/{sale_id}", response_model=SaleResponse)
async def get_sale(
    sale_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
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
    sale = result.scalar_one_or_none()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if current_user.role not in ("admin", "cashier"):
        vendor_ids = {si.vendor_id for si in sale.items}
        if current_user.id not in vendor_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    return sale_to_response(sale)
