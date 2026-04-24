import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator, Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.models.reservation import Reservation
from app.routers.settings import get_tax_rate
from app.services.audit import log_audit

router = APIRouter(prefix="/storefront", tags=["shop"])

_rate_limit_store: dict = defaultdict(list)
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 10


def _has_real_sale_price_expr():
    return and_(
        Item.sale_price.isnot(None),
        Item.sale_price > 0,
        Item.sale_price < Item.price,
    )


def _check_rate_limit(request: Request, max_requests: int = _RATE_LIMIT_MAX):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if t > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    _rate_limit_store[client_ip].append(now)

class ShopItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    sale_price: Optional[float] = None
    category: Optional[str] = None
    vendor_name: str
    vendor_booth: Optional[str] = None
    quantity: int
    image_path: Optional[str] = None
    photo_urls: Optional[list] = None

    class Config:
        from_attributes = True

@router.get("/items")
async def get_shop_items(
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    vendor_id: Optional[int] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    on_sale: Optional[bool] = Query(None),
    sort: Optional[str] = Query("newest"),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    landing_slug: Optional[str] = Query(None),
):
    query = (
        select(
            Item.id,
            Item.name,
            Item.description,
            Item.price,
            Item.sale_price,
            Item.category,
            Item.quantity,
            Item.created_at,
            Item.image_path,
            Item.photo_urls,
            Vendor.name.label("vendor_name"),
            Vendor.booth_number.label("vendor_booth"),
        )
        .join(Vendor, Item.vendor_id == Vendor.id)
        .where(Item.status == "active")
        .where(Item.quantity > 0)
        .where(Vendor.is_active == True)
        .where(Item.is_online == True)
        .where(
            or_(
                Item.image_path.isnot(None),
                Item.photo_urls != [],
            )
        )
    )

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Item.name.ilike(pattern),
                Item.description.ilike(pattern),
                Item.sku.ilike(pattern),
                Item.category.ilike(pattern),
                Vendor.name.ilike(pattern),
            )
        )

    if category:
        query = query.where(Item.category == category)
    if vendor_id:
        query = query.where(Item.vendor_id == vendor_id)
    if min_price is not None:
        query = query.where(Item.price >= min_price)
    if max_price is not None:
        query = query.where(Item.price <= max_price)
    if on_sale:
        query = query.where(_has_real_sale_price_expr())

    if sort == "price_asc":
        query = query.order_by(Item.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Item.price.desc())
    elif sort == "name":
        query = query.order_by(Item.name.asc())
    elif sort == "oldest":
        query = query.order_by(Item.created_at.asc())
    else:
        query = query.order_by(Item.created_at.desc())

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for row in rows:
        photo_url = row.image_path
        if not photo_url and row.photo_urls:
            photo_url = row.photo_urls[0] if row.photo_urls else None
        items.append({
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "price": float(row.price),
            "sale_price": float(row.sale_price) if row.sale_price and row.sale_price < row.price else None,
            "category": row.category,
            "vendor_name": row.vendor_name,
            "booth_number": row.vendor_booth,
            "quantity": row.quantity,
            "image_path": row.image_path,
            "photo_url": photo_url,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "landing_slug": landing_slug,
    }

@router.get("/vendor-inventory/{vendor_id}")
async def get_vendor_inventory(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest"),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
):
    vendor_result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.is_active == True)
    )
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    query = (
        select(
            Item.id,
            Item.name,
            Item.description,
            Item.price,
            Item.sale_price,
            Item.category,
            Item.quantity,
            Item.created_at,
            Item.image_path,
            Item.photo_urls,
            Item.is_online,
        )
        .where(Item.vendor_id == vendor_id)
        .where(Item.status == "active")
        .where(Item.quantity > 0)
    )

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Item.name.ilike(pattern),
                Item.description.ilike(pattern),
                Item.category.ilike(pattern),
            )
        )
    if category:
        query = query.where(Item.category == category)

    if sort == "price_asc":
        query = query.order_by(Item.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Item.price.desc())
    elif sort == "name":
        query = query.order_by(Item.name.asc())
    else:
        query = query.order_by(Item.created_at.desc())

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for row in rows:
        photo_url = row.image_path
        if not photo_url and row.photo_urls:
            photo_url = row.photo_urls[0] if row.photo_urls else None
        items.append({
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "price": float(row.price),
            "sale_price": float(row.sale_price) if row.sale_price and row.sale_price < row.price else None,
            "category": row.category,
            "quantity": row.quantity,
            "image_path": row.image_path,
            "photo_url": photo_url,
            "is_online": bool(row.is_online),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "vendor_name": vendor.name,
        "booth_number": vendor.booth_number,
    }


@router.get("/tax-rate")
async def get_storefront_tax_rate(db: AsyncSession = Depends(get_db)):
    rate = await get_tax_rate(db)
    return {"tax_rate": rate}


@router.get("/categories")
async def get_categories(
    db: AsyncSession = Depends(get_db),
    vendor_id: Optional[int] = Query(None),
    format: Optional[str] = Query(None),
):
    query = (
        select(Item.category, func.count(Item.id))
        .where(Item.status == "active")
        .where(Item.quantity > 0)
        .where(Item.category.isnot(None))
    )
    if vendor_id:
        query = query.where(Item.vendor_id == vendor_id)
    else:
        query = query.where(Item.is_online == True)
    query = query.group_by(Item.category).order_by(Item.category)
    result = await db.execute(query)
    rows = result.all()
    if format == "simple":
        return [row[0] for row in rows]
    return [{"name": row[0], "count": row[1]} for row in rows]

CATEGORY_GROUPS = {
    "Handmade": ["Handmade items", "Candles", "Jewelry", "Cards", "Stickers", "Specialty Items", "Accessories"],
    "Vintage & Antique": ["Vintage", "Vintage Clothing", "Vintage Furniture"],
    "Upcycled & Resale": ["Upcycled Items", "BowenStreet Repeats", "Second hand clothes"],
    "Furniture & Home": ["Furniture", "Used furniture", "Decorations", "Outside"],
    "Art & Studio": ["Original Art", "Studio Class"],
}


_category_image_cache: dict = {"data": None, "ts": 0}
_CATEGORY_CACHE_TTL = 300


@router.get("/category-images")
async def get_category_images(
    db: AsyncSession = Depends(get_db),
):
    now = time.time()
    if _category_image_cache["data"] and (now - _category_image_cache["ts"]) < _CATEGORY_CACHE_TTL:
        return _category_image_cache["data"]

    results = {}
    for display_name, db_categories in CATEGORY_GROUPS.items():
        query = (
            select(Item.id, Item.name, Item.image_path, Item.photo_urls, Item.category)
            .join(Vendor, Item.vendor_id == Vendor.id)
            .where(Item.status == "active")
            .where(Item.quantity > 0)
            .where(Vendor.is_active == True)
            .where(Item.category.in_(db_categories))
            .where(Item.image_path.isnot(None))
            .where(Item.image_path != "")
            .order_by(func.random())
            .limit(1)
        )
        result = await db.execute(query)
        row = result.first()
        if row and row.image_path:
            image_url = row.image_path
            results[display_name] = {
                "item_id": row.id,
                "item_name": row.name,
                "category": row.category,
                "image_url": image_url,
            }
        else:
            results[display_name] = None

    _category_image_cache["data"] = results
    _category_image_cache["ts"] = now
    return results


@router.get("/vendors")
async def get_shop_vendors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Vendor.id,
            Vendor.name,
            Vendor.booth_number,
            func.count(Item.id).label("item_count"),
        )
        .outerjoin(Item, (Item.vendor_id == Vendor.id) & (Item.status == "active") & (Item.quantity > 0))
        .where(Vendor.is_active == True)
        .where(or_(Vendor.role == "vendor", Vendor.is_vendor == True))
        .group_by(Vendor.id, Vendor.name, Vendor.booth_number)
        .order_by(Vendor.name)
    )
    return [
        {"id": row.id, "name": row.name, "booth_number": row.booth_number, "item_count": row.item_count}
        for row in result.all()
    ]


class CreatePaymentRequest(BaseModel):
    item_id: int
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None

    @field_validator("customer_name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if len(v) < 1 or len(v) > 200:
            raise ValueError("Name must be 1-200 characters")
        return v

    @field_validator("customer_phone")
    @classmethod
    def validate_phone(cls, v):
        v = v.strip()
        if len(v) < 7 or len(v) > 50:
            raise ValueError("Phone must be 7-50 characters")
        return v

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 200 or "@" not in v:
            raise ValueError("Invalid email address")
        return v


class CreateCartPaymentRequest(BaseModel):
    item_ids: list[int]
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    idempotency_key: Optional[str] = Field(None, max_length=64)

    @field_validator("item_ids")
    @classmethod
    def validate_item_ids(cls, v):
        unique_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in v:
            item_id = int(raw_id)
            if item_id <= 0:
                raise ValueError("Item IDs must be positive integers")
            if item_id in seen:
                continue
            seen.add(item_id)
            unique_ids.append(item_id)
        if not unique_ids:
            raise ValueError("Please add at least one item to checkout")
        if len(unique_ids) > 25:
            raise ValueError("Cart checkout is limited to 25 items")
        return unique_ids

    @field_validator("customer_name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if len(v) < 2 or len(v) > 200:
            raise ValueError("Name must be 2-200 characters")
        return v

    @field_validator("customer_phone")
    @classmethod
    def validate_phone(cls, v):
        v = v.strip()
        if len(v) < 7 or len(v) > 50:
            raise ValueError("Phone must be 7-50 characters")
        return v

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 200 or "@" not in v:
            raise ValueError("Invalid email address")
        return v


def _reservation_total_for_item(item: Item, tax_rate: Decimal) -> Decimal:
    price = Decimal(str(item.sale_price or item.price))
    tax_amount = (price * tax_rate).quantize(Decimal("0.01"))
    return price + tax_amount


async def _load_checkout_items(db: AsyncSession, item_ids: list[int]) -> list[Item]:
    # Lock items to prevent concurrent online checkouts from overselling
    item_result = await db.execute(
        select(Item).where(Item.id.in_(item_ids), Item.status == "active").with_for_update()
    )
    found_items = item_result.scalars().all()
    found_map = {item.id: item for item in found_items}

    ordered_items: list[Item] = []
    for item_id in item_ids:
        item = found_map.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="One or more items are no longer available")
        effective_qty = item.quantity - item.reserved_quantity
        if effective_qty < 1:
            raise HTTPException(status_code=400, detail=f"{item.name} is out of stock")
        ordered_items.append(item)
    return ordered_items


@router.post("/create-payment")
async def create_payment(
    request: Request,
    req: CreatePaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    cart_req = CreateCartPaymentRequest(
        item_ids=[req.item_id],
        customer_name=req.customer_name,
        customer_phone=req.customer_phone,
        customer_email=req.customer_email,
    )
    return await create_cart_payment(request, cart_req, db)


@router.post("/create-cart-payment")
async def create_cart_payment(
    request: Request,
    req: CreateCartPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request)

    # Idempotency: return existing reservations if same key was used
    if req.idempotency_key:
        existing = await db.execute(
            select(Reservation).where(
                Reservation.idempotency_key == req.idempotency_key,
                Reservation.status == "pending"
            ).limit(1)
        )
        existing_res = existing.scalar_one_or_none()
        if existing_res:
            return {
                "reference_id": existing_res.checkout_group_id,
                "reservation_id": existing_res.public_id,
                "reservation_count": 1,
                "total": float(existing_res.amount_paid or 0),
                "payment_url": None,
                "message": "Existing reservation found. Complete payment to confirm.",
            }

    db_tax_rate = await get_tax_rate(db)
    tax_rate = Decimal(str(db_tax_rate)).quantize(Decimal("0.0001"))
    items = await _load_checkout_items(db, req.item_ids)
    checkout_group_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    reservations: list[Reservation] = []
    total = Decimal("0.00")
    for item in items:
        line_total = _reservation_total_for_item(item, tax_rate)
        total += line_total

        # Reserve inventory so POS can't sell it while payment is pending
        item.reserved_quantity += 1

        reservation = Reservation(
            item_id=item.id,
            checkout_group_id=checkout_group_id,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            customer_email=req.customer_email,
            amount_paid=line_total,
            status="pending",
            expires_at=expires_at,
            idempotency_key=req.idempotency_key,
        )
        db.add(reservation)
        reservations.append(reservation)

    await db.commit()

    await log_audit(
        db=db,
        vendor_id=None,
        action="create_cart_payment",
        entity_type="reservation",
        entity_id=checkout_group_id,
        details=f"Items: {len(items)}, Customer: {req.customer_name}, Total: ${float(total):.2f}",
        request=request,
    )

    for reservation in reservations:
        await db.refresh(reservation)

    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or "https"
    base_url = f"{scheme}://{host}"
    redirect_url = f"{base_url}/shop/index.html?payment=success&ref={checkout_group_id}"

    try:
        from app.services.square import create_payment_link
        price_cents = int(total * 100)
        item_count = len(items)
        item_name = (items[0].name or "Item")[:60]
        checkout_name = (
            f"Reserve: {item_name}" if item_count == 1
            else f"Reserve {item_count} items at Bowenstreet Market"
        )
        link_result = await create_payment_link(
            name=checkout_name,
            price_cents=price_cents,
            redirect_url=redirect_url,
        )
        payment_link_id = link_result.get("payment_link_id", "")
        for reservation in reservations:
            reservation.square_payment_id = payment_link_id
        await db.commit()

        return {
            "reference_id": checkout_group_id,
            "reservation_id": reservations[0].public_id,
            "reservation_count": item_count,
            "total": float(total),
            "payment_url": link_result["url"],
            "message": "Redirecting to secure checkout...",
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Square payment link error: {e}")
        return {
            "reference_id": checkout_group_id,
            "reservation_id": reservations[0].public_id,
            "reservation_count": len(reservations),
            "total": float(total),
            "message": "Reservations created. In-store payment required.",
        }


class ConfirmPaymentRequest(BaseModel):
    reference_id: Optional[str] = None
    reservation_id: Optional[str] = None


@router.post("/payment-confirmed")
async def payment_confirmed(
    request: Request,
    req: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request)
    reference_id = (req.reference_id or req.reservation_id or "").strip()
    if not reference_id:
        raise HTTPException(status_code=400, detail="Reservation reference is required")

    group_result = await db.execute(
        select(Reservation).where(Reservation.checkout_group_id == reference_id)
    )
    reservations = group_result.scalars().all()

    if not reservations:
        result = await db.execute(
            select(Reservation).where(Reservation.public_id == reference_id)
        )
        reservation = result.scalar_one_or_none()
        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")
        reservations = [reservation]

    # Check if already completed
    already_done = all(r.status == "completed" for r in reservations)
    if already_done:
        return {"message": "Payment already confirmed."}

    # Lock items and finalize
    item_ids = [r.item_id for r in reservations if r.item_id]
    if item_ids:
        await db.execute(select(Item).where(Item.id.in_(item_ids)).with_for_update())

    pending_count = 0
    for reservation in reservations:
        if reservation.status == "completed":
            continue
        reservation.status = "completed"
        if reservation.item:
            # Deduct actual inventory and release reservation hold
            reservation.item.quantity = max(0, reservation.item.quantity - 1)
            reservation.item.reserved_quantity = max(0, reservation.item.reserved_quantity - 1)
            if reservation.item.quantity <= 0:
                reservation.item.status = "sold"
        pending_count += 1

    await db.commit()

    await log_audit(
        db=db,
        vendor_id=None,
        action="payment_confirmed",
        entity_type="reservation",
        entity_id=reference_id,
        details=f"Confirmed {pending_count} reservations",
        request=request,
    )

    item_word = "item" if pending_count == 1 else "items"
    return {"message": f"Payment confirmed! {pending_count} {item_word} reserved."}


# ── Phase 3 SEO endpoints ──────────────────────────────────────────────
import re as _seo_re


def _seo_slugify(s: str) -> str:
    s = _seo_re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
    return _seo_re.sub(r"[-\s]+", "-", s) or "misc"


@router.get("/specialties")
async def get_storefront_specialties(db: AsyncSession = Depends(get_db)):
    """Aggregated list of specialties across all published showcases with vendor counts.
    Returns: [{slug, name, vendor_count}] sorted by vendor_count desc, then name asc.
    Used by the /vendors hub page and the Phase 3 specialty directory.
    """
    from app.models.booth_showcase import BoothShowcase

    result = await db.execute(
        select(BoothShowcase.landing_specialties)
        .where(BoothShowcase.is_published == True)
        .where(BoothShowcase.landing_page_enabled != False)
    )
    rows = result.all()

    # slug -> {"name": first-seen-casing, "count": int}
    bucket: dict = {}
    for (specs,) in rows:
        seen_this_row: set = set()
        for s in (specs or []):
            name = str(s or "").strip()
            if not name:
                continue
            slug = _seo_slugify(name)
            if slug in seen_this_row:
                continue
            seen_this_row.add(slug)
            if slug not in bucket:
                bucket[slug] = {"name": name[:60], "count": 0}
            bucket[slug]["count"] += 1

    out = [
        {"slug": slug, "name": v["name"], "vendor_count": v["count"]}
        for slug, v in bucket.items()
    ]
    out.sort(key=lambda x: (-x["vendor_count"], x["name"].lower()))
    return out


@router.get("/specialty/{slug}")
async def get_storefront_specialty(slug: str, db: AsyncSession = Depends(get_db)):
    """Vendors that list this specialty. Case-insensitive slug match across
    landing_specialties. Returns: {slug, name, vendor_count, vendors: [...]}.
    """
    from app.models.booth_showcase import BoothShowcase

    target = _seo_slugify(slug)
    if target == "misc" and slug.lower() != "misc":
        raise HTTPException(status_code=404, detail="Specialty not found")

    result = await db.execute(
        select(BoothShowcase, Vendor)
        .join(Vendor, Vendor.id == BoothShowcase.vendor_id)
        .where(BoothShowcase.is_published == True)
        .where(BoothShowcase.landing_page_enabled != False)
        .order_by(Vendor.name)
    )
    rows = result.all()

    display_name = None
    vendors_out = []
    for sc, vendor in rows:
        specs = sc.landing_specialties or []
        matched = False
        for s in specs:
            name = str(s or "").strip()
            if not name:
                continue
            if _seo_slugify(name) == target:
                matched = True
                if display_name is None:
                    display_name = name[:60]
                break
        if not matched:
            continue

        vendors_out.append({
            "vendor_id": sc.vendor_id,
            "vendor_name": vendor.name,
            "booth_number": vendor.booth_number,
            "landing_slug": sc.landing_slug,
            "title": sc.title,
            "tagline": sc.landing_tagline,
            "meta_desc": sc.landing_meta_desc,
            "cover_image_url": (sc.photo_urls or [None])[0] if sc.photo_urls else None,
            "specialties": list(specs),
            "updated_at": sc.updated_at.isoformat() if sc.updated_at else None,
        })

    if not vendors_out:
        raise HTTPException(status_code=404, detail="Specialty not found")

    return {
        "slug": target,
        "name": display_name or target.replace("-", " ").title(),
        "vendor_count": len(vendors_out),
        "vendors": vendors_out,
    }
