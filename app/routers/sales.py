from datetime import date, datetime, timedelta, timezone
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.models.vendor import Vendor, VendorBalance
from app.schemas.sale import (
    SaleCreate,
    SaleResponse,
    SaleItemResponse,
    VendorSoldItemSummary,
    VendorSoldItemsResponse,
)
from app.routers.auth import get_current_user
from app.config import settings
from app.routers.settings import get_tax_rate, require_staff_feature, role_feature_allowed
from app.services.audit import log_audit
from app.timezone import STORE_TZ as _STORE_TZ

router = APIRouter(prefix="/sales", tags=["sales"])


def _offline_mode_enabled() -> bool:
    return bool(settings.offline_mode)


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


def _current_period_window(period: str):
    today = datetime.now(_STORE_TZ).date()
    if period == "day":
        start_local = datetime(today.year, today.month, today.day, tzinfo=_STORE_TZ)
        end_local = start_local + timedelta(days=1)
        label = today.strftime("%b %-d, %Y")
    elif period == "week":
        week_start = today - timedelta(days=today.weekday())
        start_local = datetime(week_start.year, week_start.month, week_start.day, tzinfo=_STORE_TZ)
        end_local = start_local + timedelta(days=7)
        week_end = end_local.date() - timedelta(days=1)
        label = f"{week_start.strftime('%b %-d')} - {week_end.strftime('%b %-d, %Y')}"
    elif period == "month":
        start_local = datetime(today.year, today.month, 1, tzinfo=_STORE_TZ)
        if today.month == 12:
            end_local = datetime(today.year + 1, 1, 1, tzinfo=_STORE_TZ)
        else:
            end_local = datetime(today.year, today.month + 1, 1, tzinfo=_STORE_TZ)
        label = today.strftime("%B %Y")
    elif period == "year":
        start_local = datetime(today.year, 1, 1, tzinfo=_STORE_TZ)
        end_local = datetime(today.year + 1, 1, 1, tzinfo=_STORE_TZ)
        label = today.strftime("%Y")
    else:
        raise HTTPException(status_code=400, detail="period must be one of: day, week, month, year")

    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), label


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
        external_payment_reference=sale.card_transaction_id if sale.payment_method == "crypto_blackbox" else None,
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
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    if not data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    if data.payment_method not in ("cash", "card", "split", "crypto_blackbox"):
        raise HTTPException(status_code=400, detail="payment_method must be cash, card, split, or crypto_blackbox")
    if _offline_mode_enabled() and data.payment_method == "card":
        raise HTTPException(
            status_code=400,
            detail="Card processing is disabled in offline mode. Use cash or Crypto / Blackbox.",
        )
    if _offline_mode_enabled() and data.payment_method == "split" and data.card_transaction_id:
        raise HTTPException(
            status_code=400,
            detail="Offline split payments cannot include a card leg.",
        )

    # Lock all cart items first to prevent race conditions / overselling
    cart_barcodes = [cart_item.barcode for cart_item in data.items]
    locked_result = await db.execute(
        select(Item).where(Item.barcode.in_(cart_barcodes)).with_for_update()
    )
    locked_items = {item.barcode: item for item in locked_result.scalars().all()}

    resolved_lines = []
    for cart_item in data.items:
        item = locked_items.get(cart_item.barcode)
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
    if data.payment_method == "crypto_blackbox" and not data.card_transaction_id:
        data.card_transaction_id = data.external_payment_reference or f"BLACKBOX-{datetime.now(_STORE_TZ).strftime('%Y%m%d%H%M%S')}"

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
            select(VendorBalance).where(VendorBalance.vendor_id == vendor_id).limit(1)
        )
        balance_row = result.scalar_one_or_none()
        if balance_row:
            balance_row.balance = (Decimal(str(balance_row.balance)) + amount).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        else:
            db.add(VendorBalance(vendor_id=vendor_id, balance=amount))

    await db.commit()

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="create_sale",
        entity_type="sale",
        entity_id=str(sale.id),
        details=f"Payment: {data.payment_method}, Total: ${float(total):.2f}, Items: {len(data.items)}",
    )

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
    offset: int = Query(0, ge=0),
    search_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if not await role_feature_allowed(db, current_user, "role_view_sales"):
        raise HTTPException(
            status_code=403,
            detail="Sales history is disabled for your role in Settings → User Roles.",
        )

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
        q = q.offset(offset)
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
        vq = vq.offset(offset)
        result = await db.execute(vq)
        sales = result.scalars().all()

    return [sale_to_response(s) for s in sales]


@router.get("/summary/today")
async def sales_summary_today(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_sales")),
):
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


@router.get("/vendor-sold-items", response_model=VendorSoldItemsResponse)
async def vendor_sold_items(
    period: str = Query("month"),
    limit: int = Query(100, ge=1, le=250),
    vendor_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if not await role_feature_allowed(db, current_user, "role_view_sales"):
        raise HTTPException(
            status_code=403,
            detail="Sales history is disabled for your role in Settings → User Roles.",
        )

    if current_user.role not in ("vendor", "admin", "cashier"):
        raise HTTPException(status_code=403, detail="Vendor sales access is not available for this account")
    if current_user.role in ("admin", "cashier") and not current_user.is_vendor:
        raise HTTPException(status_code=403, detail="Vendor sales access is not available for this account")

    target_vendor_id = current_user.id
    if vendor_id is not None:
        if current_user.role in ("admin", "cashier"):
            if vendor_id != current_user.id and not await role_feature_allowed(db, current_user, "role_manage_vendors"):
                raise HTTPException(status_code=403, detail="Access denied")
            target_vendor_id = vendor_id
        else:
            if vendor_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")
            target_vendor_id = vendor_id

    start_utc, end_utc, period_label = _current_period_window(period)
    result = await db.execute(
        select(
            SaleItem.item_id.label("item_id"),
            Item.name.label("item_name"),
            Item.sku.label("sku"),
            Item.category.label("category"),
            Item.status.label("status"),
            Item.quantity.label("quantity_on_hand"),
            Item.image_path.label("image_path"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("qty_sold"),
            func.coalesce(func.sum(SaleItem.line_total), 0).label("gross_sales"),
            func.coalesce(func.sum(SaleItem.unit_cost * SaleItem.quantity), 0).label("total_cost"),
            func.count(func.distinct(Sale.id)).label("sale_count"),
            func.max(Sale.created_at).label("last_sold_at"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Item, Item.id == SaleItem.item_id)
        .where(
            SaleItem.vendor_id == target_vendor_id,
            Sale.is_voided.is_(False),
            Sale.created_at >= start_utc,
            Sale.created_at < end_utc,
        )
        .group_by(
            SaleItem.item_id,
            Item.name,
            Item.sku,
            Item.category,
            Item.status,
            Item.quantity,
            Item.image_path,
        )
        .order_by(func.max(Sale.created_at).desc(), func.sum(SaleItem.quantity).desc())
        .limit(limit)
    )
    rows = result.all()
    items = [
        VendorSoldItemSummary(
            item_id=row.item_id,
            item_name=row.item_name,
            sku=row.sku,
            category=row.category,
            status=row.status,
            quantity_on_hand=int(row.quantity_on_hand or 0),
            qty_sold=int(row.qty_sold or 0),
            gross_sales=Decimal(str(row.gross_sales or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP),
            sale_count=int(row.sale_count or 0),
            last_sold_at=row.last_sold_at,
            last_sold_at_display=_format_cst(row.last_sold_at),
            image_path=row.image_path,
            total_cost=Decimal(str(row.total_cost or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP) if row.total_cost else None,
            profit=(Decimal(str(row.gross_sales or 0)) - Decimal(str(row.total_cost or 0))).quantize(Decimal("0.01"), ROUND_HALF_UP) if row.total_cost else None,
        )
        for row in rows
    ]
    return VendorSoldItemsResponse(
        period=period,
        period_label=period_label,
        total_items=len(items),
        items=items,
    )


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

    if not await role_feature_allowed(db, current_user, "role_view_sales"):
        raise HTTPException(
            status_code=403,
            detail="Sales history is disabled for your role in Settings → User Roles.",
        )

    if current_user.role not in ("admin", "cashier"):
        vendor_ids = {si.vendor_id for si in sale.items}
        if current_user.id not in vendor_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    return sale_to_response(sale)
