from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor

router = APIRouter(prefix="/storefront", tags=["shop"])

class ShopItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: float
    sale_price: Optional[float]
    category: Optional[str]
    booth_location: Optional[str]
    vendor_name: str
    vendor_booth: Optional[str]
    quantity: int
    photo_url: Optional[str] = None

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
            Item.booth_location,
            Item.quantity,
            Item.created_at,
            Item.photo_url,
            Vendor.name.label("vendor_name"),
            Vendor.booth_number.label("vendor_booth"),
        )
        .join(Vendor, Item.vendor_id == Vendor.id)
        .where(Item.is_active == True)
        .where(Item.quantity > 0)
        .where(Vendor.is_active == True)
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

    # Sorting
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

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Paginate
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for row in rows:
        items.append({
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "price": float(row.price),
            "sale_price": float(row.sale_price) if row.sale_price else None,
            "category": row.category,
            "booth_location": row.booth_location,
            "vendor_name": row.vendor_name,
            "vendor_booth": row.vendor_booth,
            "quantity": row.quantity,
            "photo_url": row.photo_url,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }

@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Item.category, func.count(Item.id))
        .where(Item.is_active == True)
        .where(Item.quantity > 0)
        .where(Item.category.isnot(None))
        .group_by(Item.category)
        .order_by(Item.category)
    )
    return [{"name": row[0], "count": row[1]} for row in result.all()]

@router.get("/vendors")
async def get_shop_vendors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Vendor.id,
            Vendor.name,
            Vendor.booth_number,
            func.count(Item.id).label("item_count"),
        )
        .outerjoin(Item, (Item.vendor_id == Vendor.id) & (Item.is_active == True) & (Item.quantity > 0))
        .where(Vendor.is_active == True)
        .where(or_(Vendor.role == "vendor", Vendor.is_vendor == True))
        .group_by(Vendor.id, Vendor.name, Vendor.booth_number)
        .order_by(Vendor.name)
    )
    return [
        {"id": row.id, "name": row.name, "booth_number": row.booth_number, "item_count": row.item_count}
        for row in result.all()
    ]
