import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.models.reservation import Reservation
from app.routers.settings import get_tax_rate

router = APIRouter(prefix="/storefront", tags=["shop"])

_rate_limit_store: dict = defaultdict(list)
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 10


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
        query = query.where(Item.sale_price.isnot(None))

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
            "sale_price": float(row.sale_price) if row.sale_price else None,
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
            "sale_price": float(row.sale_price) if row.sale_price else None,
            "category": row.category,
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
    query = query.group_by(Item.category).order_by(Item.category)
    result = await db.execute(query)
    rows = result.all()
    if format == "simple":
        return [row[0] for row in rows]
    return [{"name": row[0], "count": row[1]} for row in rows]

CATEGORY_GROUPS = {
    "Handmade": ["Handmade items", "Candles", "Jewelry", "Cards", "Stickers", "Specialty Items", "Accesories"],
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


@router.post("/create-payment")
async def create_payment(
    request: Request,
    req: CreatePaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request)
    item_result = await db.execute(
        select(Item).where(Item.id == req.item_id, Item.status == "active")
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or no longer available")

    if item.quantity < 1:
        raise HTTPException(status_code=400, detail="Item is out of stock")

    price = Decimal(str(item.sale_price or item.price))
    db_tax_rate = await get_tax_rate(db)
    tax_rate = Decimal(str(db_tax_rate)).quantize(Decimal("0.0001"))
    tax_amount = (price * tax_rate).quantize(Decimal("0.01"))
    total = price + tax_amount

    reservation = Reservation(
        item_id=req.item_id,
        customer_name=req.customer_name,
        customer_phone=req.customer_phone,
        customer_email=req.customer_email,
        amount_paid=total,
        status="pending",
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)

    return {
        "reservation_id": reservation.public_id,
        "total": float(total),
        "message": "Reservation created. In-store payment required.",
    }


class ConfirmPaymentRequest(BaseModel):
    reservation_id: str


@router.post("/payment-confirmed")
async def payment_confirmed(
    request: Request,
    req: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request)
    result = await db.execute(
        select(Reservation).where(Reservation.public_id == req.reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status == "completed":
        return {"message": "Payment already confirmed."}

    if reservation.status == "pending":
        reservation.status = "pending"
    await db.commit()

    return {"message": "Payment confirmed! Your item has been reserved."}
