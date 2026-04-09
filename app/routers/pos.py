import asyncio
import math
import secrets
import uuid
import base64
import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func, cast, Date, case
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.store_setting import StoreSetting
from app.routers.settings import require_staff_feature, role_feature_allowed
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.eod_report import EodReport
from app.models.item_image import ItemImage
from app.models.sale import Sale, SaleItem
from app.models.gift_card import GiftCard, GiftCardTransaction
from app.models.poynt_payment import PoyntPayment
from app.models.studio_class import StudioClass
from app.schemas.sale import (
    SaleCreate, SaleResponse, SaleItemResponse, VoidSaleRequest,
    PoyntChargeRequest, PoyntChargeResponse, PoyntStatusResponse,
)
from app.schemas.gift_card import (
    GiftCardActivate, GiftCardLoad, GiftCardRedeem,
    GiftCardResponse, GiftCardDetailResponse, GiftCardTransactionResponse,
)
from app.services import poynt
from app.services.llm_gateway import ai_runtime_mode, chat_completion
from app.services.rent_payments import apply_rent_payment, stamp_rent_notes
from app.config import settings
from app.routers.notifications import bg_notify_product_sold, bg_notify_order_confirmation
from app.routers.settings import get_tax_rate
from app.timezone import STORE_TZ

router = APIRouter(prefix="/pos", tags=["pos"])
logger = logging.getLogger(__name__)

ONLINE_PAYMENT_METHODS = ("cash", "card", "split", "gift_card", "crypto_blackbox")


def _offline_mode_enabled() -> bool:
    return bool(settings.offline_mode)


def _allowed_runtime_payment_methods() -> list[str]:
    if _offline_mode_enabled():
        methods = settings.resolved_offline_payment_methods or ["cash", "gift_card", "split", "crypto_blackbox"]
        return methods
    return list(ONLINE_PAYMENT_METHODS)


def _split_uses_card(data: SaleCreate) -> bool:
    return bool(data.card_transaction_id)


def _resolve_external_payment_reference(data: SaleCreate) -> Optional[str]:
    explicit_ref = (data.external_payment_reference or "").strip()
    if explicit_ref:
        return explicit_ref
    if data.payment_method == "crypto_blackbox":
        return f"BLACKBOX-{int(datetime.now(tz=STORE_TZ).timestamp())}"
    return data.card_transaction_id


def _starting_cash_key(for_date: date) -> str:
    return "starting_cash_" + for_date.isoformat()


def _starting_cash_verified_key(for_date: date) -> str:
    return "starting_cash_verified_" + for_date.isoformat()


async def _get_store_setting_row(db: AsyncSession, key: str) -> Optional[StoreSetting]:
    result = await db.execute(select(StoreSetting).where(StoreSetting.key == key))
    return result.scalar_one_or_none()


async def _get_starting_cash_amount(db: AsyncSession, for_date: date) -> Decimal:
    setting = await _get_store_setting_row(db, _starting_cash_key(for_date))
    if setting and setting.value:
        try:
            return Decimal(setting.value).quantize(Decimal("0.01"), ROUND_HALF_UP)
        except Exception:
            pass
    return Decimal("150.00")


async def _get_starting_cash_verification(db: AsyncSession, for_date: date) -> Optional[dict]:
    setting = await _get_store_setting_row(db, _starting_cash_verified_key(for_date))
    if not setting or not setting.value:
        return None
    try:
        data = json.loads(setting.value)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _format_cst(dt):
    """Format a datetime as a display string in store local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz
        dt = dt.replace(tzinfo=_tz.utc)
    local_dt = dt.astimezone(STORE_TZ)
    tz_abbr = local_dt.strftime("%Z")  # "CST" or "CDT" depending on time of year
    return local_dt.strftime("%b %-d, %Y at %-I:%M %p") + f" {tz_abbr}"


def _get_active_price(item: Item) -> Decimal:
    today = datetime.now(STORE_TZ).date()
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
        "vendor_name": item.vendor.name if item.vendor else None,
        "booth_number": item.vendor.booth_number if item.vendor else None,
        "is_tax_exempt": item.is_tax_exempt,
        "is_consignment": item.is_consignment,
        "consignment_rate": float(item.consignment_rate) if item.consignment_rate is not None else None,
        "quantity": item.quantity,
        "photo_urls": item.photo_urls,
        "image_path": item.image_path,
    }


def _is_tax_exempt_sale_item(item: Item) -> bool:
    if bool(item.is_tax_exempt):
        return True
    return (item.category or "").strip().lower() == "studio class"


@router.get("/runtime")
async def pos_runtime(
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    return {
        "offline_mode": _offline_mode_enabled(),
        "ai_mode": ai_runtime_mode(),
        "local_ai_enabled": bool(settings.local_ai_enabled),
        "allowed_payment_methods": _allowed_runtime_payment_methods(),
        "split_allows_card": not _offline_mode_enabled(),
        "split_allows_cash": True,
        "split_allows_gift_card": True,
        "crypto_payment_label": "Crypto / Blackbox",
        "offline_snapshot_path": settings.offline_snapshot_path if _offline_mode_enabled() else None,
    }


@router.get("/search")
async def pos_search(
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(20, ge=1, le=40, description="Maximum number of matches to return"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    raw_query = (q or "").strip()
    if not raw_query:
        return []

    tokens = [token for token in raw_query.split() if token]
    exact_barcode = func.upper(Item.barcode) == raw_query.upper()
    exact_sku = func.upper(func.coalesce(Item.sku, "")) == raw_query.upper()
    prefix_name = Item.name.ilike(f"{raw_query}%")
    prefix_sku = Item.sku.ilike(f"{raw_query}%")

    token_filters = []
    for token in tokens:
        token_term = f"%{token}%"
        token_filters.append(
            or_(
                Item.name.ilike(token_term),
                Item.sku.ilike(token_term),
                Item.barcode.ilike(token_term),
            )
        )

    search_filter = and_(*token_filters) if token_filters else or_(
        Item.name.ilike(f"%{raw_query}%"),
        Item.sku.ilike(f"%{raw_query}%"),
        Item.barcode.ilike(f"%{raw_query}%"),
    )

    query = (
        select(Item)
        .options(selectinload(Item.vendor))
        .where(
            Item.status == "active",
            search_filter,
        )
        .order_by(
            case((exact_barcode, 0), (exact_sku, 1), (prefix_name, 2), (prefix_sku, 3), else_=4),
            Item.name.asc(),
        )
        .limit(limit)
    )
    result = await db.execute(query)
    items = result.scalars().all()
    return [_item_to_pos_dict(i) for i in items]


@router.get("/barcode/{barcode}")
async def pos_barcode_lookup(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    vendor_id = body.get("vendor_id")
    name = body.get("name", "").strip()
    price = body.get("price")
    quantity = body.get("quantity", 1)
    is_tax_exempt = body.get("is_tax_exempt", False)
    # Consignment fields left as defaults — vendor-level rate is applied at sale time
    is_consignment = False
    consignment_rate = None

    if not vendor_id or not name or not price:
        raise HTTPException(status_code=400, detail="vendor_id, name, and price are required")

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if vendor.status != "active":
        raise HTTPException(status_code=400, detail="Manual items can only be created for active vendors")
    if vendor.role != "vendor" and not bool(getattr(vendor, "is_vendor", False)):
        raise HTTPException(status_code=400, detail="Manual items can only be created for vendor accounts")

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
        is_consignment=False,
        consignment_rate=None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item, attribute_names=["id", "vendor"])

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item.id)
    )
    item = result.scalar_one()

    return _item_to_pos_dict(item)


@router.post("/class-fee-item")
async def pos_class_fee_item(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    class_id = body.get("class_id")
    spots = int(body.get("num_spots") or 1)

    if not class_id:
        raise HTTPException(status_code=400, detail="class_id is required")
    if spots < 1 or spots > 10:
        raise HTTPException(status_code=400, detail="Class signup must be for 1-10 spots")

    result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    studio_class = result.scalar_one_or_none()
    if not studio_class:
        raise HTTPException(status_code=404, detail="Class not found")
    if not studio_class.is_published or studio_class.is_cancelled:
        raise HTTPException(status_code=400, detail="Class is not available for signup")
    if studio_class.class_date < date.today():
        raise HTTPException(status_code=400, detail="This class has already passed")

    enrolled = int(studio_class.enrolled or 0)
    capacity = int(studio_class.capacity or 0)
    spots_left = max(0, capacity - enrolled)
    if spots > spots_left:
        raise HTTPException(status_code=400, detail=f"Only {spots_left} spot(s) remaining")

    owner_id = studio_class.created_by or current_user.id
    owner_result = await db.execute(select(Vendor).where(Vendor.id == owner_id))
    owner = owner_result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=400, detail="Class host account was not found")
    if owner.status != "active":
        raise HTTPException(status_code=400, detail="Class host account is not active")

    barcode = f"CLASS-{uuid.uuid4().hex[:10].upper()}"
    total_price = (Decimal(str(studio_class.price)) * Decimal(str(spots))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    item = Item(
        vendor_id=owner.id,
        name=f"Class Signup: {studio_class.title} ({spots} spot{'s' if spots != 1 else ''})",
        barcode=barcode,
        sku=barcode,
        price=total_price,
        quantity=1,
        category="Studio Class",
        status="active",
        is_tax_exempt=True,
        is_consignment=False,
        consignment_rate=None,
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
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    if not data.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    if data.payment_method not in ONLINE_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail="payment_method must be cash, card, split, gift_card, or crypto_blackbox",
        )

    if _offline_mode_enabled():
        if data.payment_method == "card":
            raise HTTPException(
                status_code=400,
                detail="Card processing is disabled in offline mode. Use cash, gift card, or Crypto / Blackbox.",
            )
        if data.payment_method == "split" and _split_uses_card(data):
            raise HTTPException(
                status_code=400,
                detail="Offline split payments can use gift card plus cash only. Card legs are disabled.",
            )
        if data.payment_method not in _allowed_runtime_payment_methods():
            raise HTTPException(
                status_code=400,
                detail="That payment method is not enabled in offline mode.",
            )

    if data.payment_method == "card":
        if not data.card_transaction_id:
            raise HTTPException(
                status_code=400,
                detail="Card transaction ID is required for card payments. Confirm payment on the terminal first.",
            )

    if data.payment_method == "crypto_blackbox":
        data.card_transaction_id = _resolve_external_payment_reference(data)

    if data.payment_method in ("gift_card", "split") and data.gift_card_barcode:
        if not await role_feature_allowed(db, current_user, "role_manage_gift_cards"):
            raise HTTPException(
                status_code=403,
                detail="Gift card payments are disabled for your role in Settings → User Roles.",
            )

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

        # Per-item discount
        item_discount_type = cart_item.discount_type
        item_discount_value = Decimal(str(cart_item.discount_value)) if cart_item.discount_value else Decimal("0")
        item_discount_amount = Decimal("0")

        if item_discount_type == 'dollar':
            item_discount_amount = min(item_discount_value, line_total)
        elif item_discount_type == 'percent':
            item_discount_amount = (line_total * item_discount_value / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
            item_discount_amount = min(item_discount_amount, line_total)

        line_total_after_discount = (line_total - item_discount_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
        resolved_lines.append((item, cart_item, unit_price, line_total, line_total_after_discount, item_discount_type, item_discount_value, item_discount_amount))

    subtotal = sum(ltad for _, _, _, _, ltad, _, _, _ in resolved_lines).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Cart-wide discount
    cart_discount_amount = Decimal("0")
    if data.cart_discount_type == 'dollar' and data.cart_discount_value:
        cart_discount_amount = min(Decimal(str(data.cart_discount_value)), subtotal)
    elif data.cart_discount_type == 'percent' and data.cart_discount_value:
        cart_discount_amount = (subtotal * Decimal(str(data.cart_discount_value)) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        cart_discount_amount = min(cart_discount_amount, subtotal)

    subtotal_after_discount = subtotal - cart_discount_amount

    db_tax_rate = await get_tax_rate(db)
    tax_rate = Decimal(str(db_tax_rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    taxable_subtotal = sum(
        ltad for item, _, _, _, ltad, _, _, _ in resolved_lines if not _is_tax_exempt_sale_item(item)
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)
    # Proportionally reduce taxable amount by cart discount
    if subtotal > 0 and cart_discount_amount > 0:
        taxable_subtotal = (taxable_subtotal * (subtotal_after_discount / subtotal)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax_amount = (taxable_subtotal * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    total = (subtotal_after_discount + tax_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

    change_given = None
    cash_tendered = None
    gc_amount_applied = None

    if data.payment_method == "split":
        remainder = total
        if data.gift_card_barcode and data.gift_card_amount:
            gc_pre_check = await db.execute(
                select(GiftCard).where(GiftCard.barcode == data.gift_card_barcode)
            )
            gc_pre = gc_pre_check.scalar_one_or_none()
            if not gc_pre or not gc_pre.is_active:
                raise HTTPException(status_code=400, detail="Gift card not found or inactive")
            gc_avail = Decimal(str(gc_pre.balance))
            gc_amount_applied = min(
                Decimal(str(data.gift_card_amount)).quantize(Decimal("0.01"), ROUND_HALF_UP),
                gc_avail,
                remainder,
            )
            remainder = (remainder - gc_amount_applied).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if data.cash_tendered is not None:
            cash_tendered = Decimal(str(data.cash_tendered)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if data.card_transaction_id:
                cash_portion = min(cash_tendered, remainder)
                change_given = max(
                    (cash_tendered - cash_portion).quantize(Decimal("0.01"), ROUND_HALF_UP),
                    Decimal("0.00"),
                )
            else:
                if cash_tendered < remainder:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cash tendered ${cash_tendered} is less than remaining ${remainder}",
                    )
                change_given = max(
                    (cash_tendered - remainder).quantize(Decimal("0.01"), ROUND_HALF_UP),
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
    elif data.payment_method == "crypto_blackbox":
        cash_tendered = None
        change_given = None

    sale = Sale(
        cashier_id=current_user.id,
        subtotal=subtotal_after_discount,
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
        discount_type=data.cart_discount_type,
        discount_value=Decimal(str(data.cart_discount_value)) if data.cart_discount_value else None,
        discount_amount=cart_discount_amount if cart_discount_amount > 0 else None,
    )
    db.add(sale)
    await db.flush()

    vendor_totals: dict[int, Decimal] = {}
    for item, cart_item, unit_price, line_total, line_total_after_discount, i_disc_type, i_disc_val, i_disc_amt in resolved_lines:
        qty = cart_item.quantity
        # Consignment: check vendor's consignment_rate for store's cut
        vendor_consign_rate = Decimal("0")
        if item.vendor and getattr(item.vendor, "consignment_rate", None):
            vendor_consign_rate = Decimal(str(item.vendor.consignment_rate))

        is_consignment = vendor_consign_rate > 0
        consignment_amount = None
        if is_consignment:
            consignment_amount = (line_total_after_discount * vendor_consign_rate).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

        sale_item = SaleItem(
            sale_id=sale.id,
            item_id=item.id,
            vendor_id=item.vendor_id,
            quantity=qty,
            unit_price=unit_price,
            line_total=line_total_after_discount,
            is_consignment=is_consignment,
            consignment_rate=vendor_consign_rate if is_consignment else None,
            consignment_amount=consignment_amount,
            discount_type=i_disc_type if i_disc_amt > 0 else None,
            discount_value=i_disc_val if i_disc_amt > 0 else None,
            discount_amount=i_disc_amt if i_disc_amt > 0 else None,
        )
        db.add(sale_item)

        new_qty = item.quantity - qty
        item.quantity = new_qty
        if new_qty <= 0:
            item.status = "sold"

        # Vendor receives sale amount minus store's consignment cut
        vendor_credit = line_total_after_discount
        if consignment_amount:
            vendor_credit = (line_total_after_discount - consignment_amount).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

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
                discount_type=si.discount_type,
                discount_value=si.discount_value,
                discount_amount=si.discount_amount,
            )
        )

    if sale.created_at:
        _sat = sale.created_at
        if _sat.tzinfo is None:
            _sat = _sat.replace(tzinfo=timezone.utc)
        sold_at_str = _sat.astimezone(STORE_TZ).strftime("%-m/%-d/%Y %-I:%M %p")
    else:
        sold_at_str = ""
    for si in sale.items:
        if si.item and si.vendor and si.vendor.email:
            try:
                asyncio.ensure_future(bg_notify_product_sold(
                    vendor_id=si.vendor.id,
                    vendor_name=si.vendor.name or "Vendor",
                    vendor_email=si.vendor.email,
                    item_name=si.item.name,
                    item_sku=si.item.sku or "",
                    sale_price=float(si.line_total),
                    sale_id=sale.id,
                    sold_at=sold_at_str,
                ))
            except Exception as e:
                logger.exception("Failed to queue product sold notification")

    if sale.receipt_email:
        try:
            email_items = [{"name": si.item.name if si.item else "Unknown",
                            "price": float(si.unit_price)} for si in sale.items]
            asyncio.ensure_future(bg_notify_order_confirmation(
                receipt_email=sale.receipt_email,
                customer_name="",
                sale_id=sale.id,
                items=email_items,
                subtotal=float(sale.subtotal),
                tax=float(sale.tax_amount),
                total=float(sale.total),
                payment_method=sale.payment_method,
            ))
        except Exception as e:
            logger.exception("Failed to queue order confirmation")

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
        discount_type=sale.discount_type,
        discount_value=sale.discount_value,
        discount_amount=sale.discount_amount,
        created_at=sale.created_at,
        created_at_display=_format_cst(sale.created_at),
        line_items=line_items,
    )


@router.post("/sale/{sale_id}/void", response_model=SaleResponse)
async def void_sale(
    sale_id: int,
    data: VoidSaleRequest = VoidSaleRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_void_sales")),
):
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
                discount_type=si.discount_type,
                discount_value=si.discount_value,
                discount_amount=si.discount_amount,
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
        external_payment_reference=sale.card_transaction_id if sale.payment_method == "crypto_blackbox" else None,
        gift_card_amount=sale.gift_card_amount,
        gift_card_barcode=sale.gift_card_barcode,
        receipt_email=sale.receipt_email,
        is_voided=sale.is_voided,
        voided_at=sale.voided_at,
        voided_by=sale.voided_by,
        voided_by_name=sale.voided_by_user.name if sale.voided_by_user else None,
        void_reason=sale.void_reason,
        discount_type=sale.discount_type,
        discount_value=sale.discount_value,
        discount_amount=sale.discount_amount,
        created_at=sale.created_at,
        created_at_display=_format_cst(sale.created_at),
        line_items=line_items,
    )


@router.post("/poynt/charge", response_model=PoyntChargeResponse)
async def poynt_charge(
    request: Request,
    data: PoyntChargeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    if _offline_mode_enabled():
        raise HTTPException(
            status_code=400,
            detail="Terminal card processing is disabled in offline mode.",
        )

    amount_cents = math.ceil(data.amount * 100)
    reference_id = f"BMM-{uuid.uuid4().hex[:12]}"

    # Create pending payment record
    payment = PoyntPayment(
        reference_id=reference_id,
        amount_cents=amount_cents,
        status="pending",
    )
    db.add(payment)
    await db.commit()

    try:
        await poynt.send_payment_to_terminal(
            amount_cents=amount_cents,
            currency="USD",
            order_ref=reference_id,
        )
    except Exception as e:
        payment.status = "error"
        await db.commit()
        raise

    return PoyntChargeResponse(reference_id=reference_id)


@router.get("/poynt/status/{reference_id}", response_model=PoyntStatusResponse)
async def poynt_status(
    reference_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    result = await db.execute(
        select(PoyntPayment).where(PoyntPayment.reference_id == reference_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        # Fall back to polling Poynt API directly
        api_result = await poynt.check_terminal_payment(reference_id)
        return PoyntStatusResponse(
            status=api_result["status"].lower(),
            poynt_transaction_id=api_result.get("transaction_id"),
            amount_cents=api_result.get("amount_cents"),
        )

    return PoyntStatusResponse(
        status=payment.status,
        poynt_transaction_id=payment.poynt_transaction_id,
        amount_cents=payment.amount_cents,
    )


@router.post("/poynt/callback", status_code=status.HTTP_200_OK)
async def poynt_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Callback from Poynt terminal — updates payment status."""
    try:
        payload = await request.json()
    except Exception:
        logger.warning(
            "Ignoring non-JSON Poynt callback with content-type %r",
            request.headers.get("content-type"),
        )
        return {"status": "ok"}

    reference_id = None
    txn_status = "pending"
    txn_id = None

    # Extract reference_id from various payload locations
    if "referenceId" in payload:
        reference_id = payload["referenceId"]
    elif "notes" in payload:
        reference_id = payload["notes"]
    elif "transactions" in payload:
        for txn in payload.get("transactions", []):
            for ref in txn.get("references", []):
                if ref.get("id", "").startswith("BMM-"):
                    reference_id = ref["id"]
                    break

    # Extract status
    raw_status = payload.get("status", "")
    if isinstance(payload.get("transactions"), list) and payload["transactions"]:
        raw_status = payload["transactions"][0].get("status", raw_status)
        txn_id = str(payload["transactions"][0].get("id", ""))

    if raw_status.upper() in ("APPROVED", "CAPTURED", "AUTHORIZED"):
        txn_status = "approved"
    elif raw_status.upper() in ("DECLINED", "VOIDED", "REFUNDED", "FAILED"):
        txn_status = "declined"

    verified_status = "pending"
    verified_txn_id = txn_id
    try:
        if txn_id:
            verification = await poynt.verify_transaction(txn_id)
            if verification.get("valid"):
                verified_status = "approved"
                verified_txn_id = verification.get("transaction_id") or verified_txn_id
            elif str(verification.get("status", "")).upper() in ("DECLINED", "VOIDED", "REFUNDED", "FAILED"):
                verified_status = "declined"
        elif reference_id:
            verification = await poynt.check_terminal_payment(reference_id)
            verified_txn_id = verification.get("transaction_id") or verified_txn_id
            if str(verification.get("status", "")).upper() == "APPROVED":
                verified_status = "approved"
            elif str(verification.get("status", "")).upper() == "DECLINED":
                verified_status = "declined"
    except Exception:
        logger.exception("Poynt callback verification failed for reference_id=%s", reference_id)

    if reference_id:
        result = await db.execute(
            select(PoyntPayment).where(PoyntPayment.reference_id == reference_id)
        )
        payment = result.scalar_one_or_none()
        if payment and payment.status == "pending" and verified_status in {"approved", "declined"}:
            payment.status = verified_status
            if verified_txn_id:
                payment.poynt_transaction_id = verified_txn_id
            await db.commit()

    return {"status": "ok"}


@router.get("/end-of-day")
async def end_of_day_report(
    report_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    store_tz = STORE_TZ

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

    starting_balance = await _get_starting_cash_amount(db, target_date)
    expected_cash_in_drawer = (starting_balance + total_cash).quantize(Decimal("0.01"), ROUND_HALF_UP)

    submitted_report_result = await db.execute(
        select(EodReport).where(EodReport.report_date == target_date)
    )
    submitted_report = submitted_report_result.scalar_one_or_none()
    submitted_info = None
    if submitted_report:
        submitted_info = {
            "id": submitted_report.id,
            "submitted_by_name": submitted_report.submitted_by_name,
            "submitted_at": submitted_report.submitted_at.isoformat() if submitted_report.submitted_at else None,
        }

    return {
        "date": target_date.isoformat(),
        "total_revenue": float(total_revenue),
        "total_tax": float(total_tax),
        "total_transactions": total_transactions,
        "items_sold": items_sold,
        "starting_balance": float(starting_balance),
        "expected_cash_in_drawer": float(expected_cash_in_drawer),
        "voided": {"count": voided_count, "total": float(voided_total)},
        "cash": {"total": float(total_cash), "count": cash_count},
        "card": {"total": float(total_card), "count": card_count},
        "split": {"total": float(total_split), "count": split_count},
        "gift_card": {"total": float(total_gift_card), "count": gift_card_count},
        "submitted_report": submitted_info,
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


@router.post("/set-starting-cash")
async def set_starting_cash(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    body = await request.json()
    amount = body.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount is required")
    try:
        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")
    if amount_dec < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")

    store_tz = STORE_TZ
    today = datetime.now(store_tz).date()
    key = _starting_cash_key(today)

    setting = await _get_store_setting_row(db, key)
    if setting:
        setting.value = str(amount_dec)
    else:
        setting = StoreSetting(key=key, value=str(amount_dec), description=f"Starting cash for {today.isoformat()}")
        db.add(setting)
    await db.commit()
    return {"starting_balance": float(amount_dec), "date": today.isoformat()}


@router.get("/starting-cash")
async def get_starting_cash(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    store_tz = STORE_TZ
    today = datetime.now(store_tz).date()
    amount = await _get_starting_cash_amount(db, today)
    return {"starting_balance": float(amount), "date": today.isoformat()}


@router.get("/starting-cash/status")
async def get_starting_cash_status(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    today = datetime.now(STORE_TZ).date()
    amount = await _get_starting_cash_amount(db, today)
    verification = await _get_starting_cash_verification(db, today)
    return {
        "date": today.isoformat(),
        "starting_balance": float(amount),
        "verified": bool(verification),
        "verified_at": verification.get("verified_at") if verification else None,
        "verified_by": verification.get("verified_by") if verification else None,
        "verified_by_name": verification.get("verified_by_name") if verification else None,
        "verified_amount": float(Decimal(str(verification.get("amount")))) if verification and verification.get("amount") is not None else None,
        "default_expected_amount": 150.0,
    }


@router.post("/starting-cash/verify")
async def verify_starting_cash(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    body = await request.json()
    amount = body.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount is required")
    try:
        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")
    if amount_dec < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")

    today = datetime.now(STORE_TZ).date()
    amount_key = _starting_cash_key(today)
    verify_key = _starting_cash_verified_key(today)

    amount_setting = await _get_store_setting_row(db, amount_key)
    if amount_setting:
        amount_setting.value = str(amount_dec)
    else:
        db.add(
            StoreSetting(
                key=amount_key,
                value=str(amount_dec),
                description=f"Starting cash for {today.isoformat()}",
            )
        )

    verified_payload = {
        "amount": str(amount_dec),
        "verified_by": current_user.id,
        "verified_by_name": current_user.name,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    verify_setting = await _get_store_setting_row(db, verify_key)
    if verify_setting:
        verify_setting.value = json.dumps(verified_payload)
    else:
        db.add(
            StoreSetting(
                key=verify_key,
                value=json.dumps(verified_payload),
                description=f"Opening drawer verified for {today.isoformat()}",
            )
        )

    await db.commit()
    return {
        "date": today.isoformat(),
        "starting_balance": float(amount_dec),
        "verified": True,
        "verified_by": current_user.id,
        "verified_by_name": current_user.name,
        "verified_at": verified_payload["verified_at"],
        "detail": f"Opening drawer verified at ${amount_dec:.2f}.",
    }


@router.post("/end-of-day/submit")
async def submit_eod_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    body = await request.json()
    required = ["report_date", "starting_balance", "counted_cash", "expected_cash",
                "variance", "deposit", "total_revenue", "total_tax",
                "total_transactions", "items_sold"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    try:
        report_date = date.fromisoformat(body["report_date"])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    existing = await db.execute(
        select(EodReport).where(EodReport.report_date == report_date)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"An End of Day report for {report_date.isoformat()} has already been submitted.")

    denom = body.get("denomination_counts")
    if denom is not None and not isinstance(denom, dict):
        raise HTTPException(status_code=400, detail="denomination_counts must be an object")

    report = EodReport(
        report_date=report_date,
        submitted_by=current_user.id,
        submitted_by_name=current_user.name,
        starting_balance=Decimal(str(body["starting_balance"])),
        counted_cash=Decimal(str(body["counted_cash"])),
        expected_cash=Decimal(str(body["expected_cash"])),
        variance=Decimal(str(body["variance"])),
        deposit=Decimal(str(body["deposit"])),
        total_revenue=Decimal(str(body["total_revenue"])),
        total_tax=Decimal(str(body["total_tax"])),
        total_transactions=int(body["total_transactions"]),
        items_sold=int(body["items_sold"]),
        cash_total=Decimal(str(body.get("cash_total", 0))),
        cash_count=int(body.get("cash_count", 0)),
        card_total=Decimal(str(body.get("card_total", 0))),
        card_count=int(body.get("card_count", 0)),
        gift_card_total=Decimal(str(body.get("gift_card_total", 0))),
        gift_card_count=int(body.get("gift_card_count", 0)),
        voided_count=int(body.get("voided_count", 0)),
        voided_total=Decimal(str(body.get("voided_total", 0))),
        cashier_breakdown=body.get("cashier_breakdown"),
        notes=body.get("notes"),
        denomination_counts=denom,
    )
    db.add(report)

    # Cash left in drawer after deposit → next calendar day's starting drawer (store opening)
    next_date = report_date + timedelta(days=1)
    counted_dec = Decimal(str(body["counted_cash"]))
    deposit_dec = Decimal(str(body["deposit"]))
    next_starting = (counted_dec - deposit_dec).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if next_starting < 0:
        next_starting = Decimal("0.00")
    key_next = "starting_cash_" + next_date.isoformat()
    next_setting_result = await db.execute(select(StoreSetting).where(StoreSetting.key == key_next))
    next_setting = next_setting_result.scalar_one_or_none()
    if next_setting:
        next_setting.value = str(next_starting)
    else:
        db.add(
            StoreSetting(
                key=key_next,
                value=str(next_starting),
                description=f"Starting cash for {next_date.isoformat()} (set at EOD close)",
            )
        )

    await db.commit()
    await db.refresh(report)
    return {
        "id": report.id,
        "detail": f"End of Day report for {report_date.isoformat()} submitted successfully.",
        "report_url": f"/admin/eod-reports.html?report_id={report.id}",
        "next_day": next_date.isoformat(),
        "next_day_starting_cash": float(next_starting),
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
    }


@router.get("/end-of-day/reports")
async def list_eod_reports(
    limit: int = Query(30, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    count_result = await db.execute(select(func.count(EodReport.id)))
    total = count_result.scalar()

    result = await db.execute(
        select(EodReport)
        .order_by(EodReport.report_date.desc())
        .limit(limit)
        .offset(offset)
    )
    reports = result.scalars().all()

    return {
        "total": total,
        "reports": [
            {
                "id": r.id,
                "report_date": r.report_date.isoformat(),
                "submitted_by_name": r.submitted_by_name,
                "total_revenue": float(r.total_revenue),
                "total_transactions": r.total_transactions,
                "cash_total": float(r.cash_total),
                "card_total": float(r.card_total),
                "gift_card_total": float(r.gift_card_total),
                "variance": float(r.variance),
                "deposit": float(r.deposit),
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in reports
        ],
    }


@router.get("/end-of-day/reports/{report_id}")
async def get_eod_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    result = await db.execute(select(EodReport).where(EodReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "id": report.id,
        "report_date": report.report_date.isoformat(),
        "submitted_by": report.submitted_by,
        "submitted_by_name": report.submitted_by_name,
        "starting_balance": float(report.starting_balance),
        "counted_cash": float(report.counted_cash),
        "expected_cash": float(report.expected_cash),
        "variance": float(report.variance),
        "deposit": float(report.deposit),
        "total_revenue": float(report.total_revenue),
        "total_tax": float(report.total_tax),
        "total_transactions": report.total_transactions,
        "items_sold": report.items_sold,
        "cash_total": float(report.cash_total),
        "cash_count": report.cash_count,
        "card_total": float(report.card_total),
        "card_count": report.card_count,
        "gift_card_total": float(report.gift_card_total),
        "gift_card_count": report.gift_card_count,
        "voided_count": report.voided_count,
        "voided_total": float(report.voided_total),
        "cashier_breakdown": report.cashier_breakdown,
        "notes": report.notes,
        "denomination_counts": report.denomination_counts,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
    }


@router.post("/image-search")
async def image_search(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_process_sales")),
):
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 5MB")

    mime = file.content_type or "image/jpeg"
    img_b64 = base64.b64encode(contents).decode("utf-8")

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
        body = await chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            max_tokens=500,
            referer="https://bowenstreetmarket.com",
            title="Bowenstreet Market POS",
            prefer_vision=True,
            require_local_vision=_offline_mode_enabled(),
        )
        raw_text = body["choices"][0]["message"].get("content", "")
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        import json as json_lib
        ai_result = json_lib.loads(cleaned)

    except HTTPException:
        raise
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
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


@router.get("/gift-cards/{barcode}/balance")
async def get_gift_card_balance(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
    result = await db.execute(
        select(GiftCard).where(GiftCard.barcode == barcode)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Gift card not found")
    return {
        "barcode": card.barcode,
        "balance": float(card.balance),
        "status": "active" if card.is_active else "inactive",
        "is_active": bool(card.is_active),
    }


@router.get("/gift-cards/{barcode}", response_model=GiftCardResponse)
async def check_gift_card_balance(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_gift_cards")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    from app.models.rent import RentPayment
    from datetime import date as dt_date

    vendor_id = body.get("vendor_id")
    method = body.get("method", "cash")
    amount_override = body.get("amount")
    notes = str(body.get("notes", "") or "")[:200]

    if not vendor_id or not isinstance(vendor_id, int):
        raise HTTPException(status_code=400, detail="Valid vendor_id required")
    if method not in ("cash", "check", "card"):
        raise HTTPException(status_code=400, detail="Method must be cash, check, or card")

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    amount = Decimal(str(amount_override if amount_override is not None else (vendor.monthly_rent or 0))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="No rent amount configured for this vendor")

    today = dt_date.today()
    period = dt_date(today.year, today.month, 1)

    if method == "card":
        try:
            from app.services.square import create_payment_link
            price_cents = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
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

    reference_tag = secrets.token_hex(4)
    base_notes = f"POS {method} payment received by {current_user.name}. {notes}".strip()
    allocation = await apply_rent_payment(
        db=db,
        vendor=vendor,
        amount=amount,
        requested_period=period,
        method=method,
        notes=base_notes,
        reference_tag=reference_tag,
    )
    applied_periods = allocation["applied_periods"]
    credit_remainder = allocation["credit_remainder"]
    period_summary = ", ".join(p.strftime("%b %Y") for p in applied_periods[:4])
    if len(applied_periods) > 4:
        period_summary += f", +{len(applied_periods) - 4} more"
    if not period_summary:
        period_summary = "rent credit only"

    receipt_notes = base_notes
    if applied_periods:
        receipt_notes = f"{receipt_notes} Applied to {period_summary}."
    if credit_remainder > 0:
        receipt_notes = f"{receipt_notes} Remaining rent credit ${float(credit_remainder):.2f}."

    db.add(RentPayment(
        vendor_id=vendor.id,
        amount=amount,
        period_month=period,
        method=method,
        status="received",
        notes=stamp_rent_notes(receipt_notes, reference_tag),
    ))
    await db.commit()

    return {
        "success": True,
        "method": method,
        "message": (
            f"{method.capitalize()} rent payment of ${amount:.2f} recorded for {vendor.name}. "
            f"Applied to {period_summary}."
        ),
        "applied_periods": [p.isoformat() for p in applied_periods],
        "credit_remainder": float(credit_remainder),
        "rent_balance_after": float(allocation["rent_balance_after"]),
    }
