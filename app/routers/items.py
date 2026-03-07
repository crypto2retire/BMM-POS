import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.schemas.item import ItemCreate, ItemUpdate, ItemResponse
from app.routers.auth import get_current_user
from app.services.barcode import generate_sku
from app.services.labels import generate_label_pdf

router = APIRouter(prefix="/items", tags=["items"])


def item_to_response(item: Item) -> ItemResponse:
    booth_number = None
    if item.vendor:
        booth_number = item.vendor.booth_number
    resp = ItemResponse(
        id=item.id,
        vendor_id=item.vendor_id,
        sku=item.sku,
        barcode=item.barcode,
        name=item.name,
        description=item.description,
        category=item.category,
        price=item.price,
        quantity=item.quantity,
        photo_urls=item.photo_urls,
        is_online=item.is_online,
        is_tax_exempt=item.is_tax_exempt,
        sale_price=item.sale_price,
        sale_start=item.sale_start,
        sale_end=item.sale_end,
        status=item.status,
        created_at=item.created_at,
        booth_number=booth_number,
    )
    return resp


@router.get("/", response_model=List[ItemResponse])
async def list_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    query = select(Item).options(selectinload(Item.vendor))
    if current_user.role != "admin":
        query = query.where(Item.vendor_id == current_user.id)
    if status_filter:
        query = query.where(Item.status == status_filter)
    if category:
        query = query.where(Item.category == category)

    result = await db.execute(query)
    items = result.scalars().all()
    return [item_to_response(i) for i in items]


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    data: ItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role == "vendor":
        vendor_id = current_user.id
    else:
        if not data.vendor_id:
            raise HTTPException(status_code=400, detail="vendor_id is required for admin")
        vendor_id = data.vendor_id

    sku = await generate_sku(vendor_id, db)

    if data.barcode:
        barcode_val = data.barcode
        existing = await db.execute(select(Item).where(Item.barcode == barcode_val))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Barcode already exists")
    else:
        barcode_val = str(uuid.uuid4().int)[:12]
        while True:
            existing = await db.execute(select(Item).where(Item.barcode == barcode_val))
            if not existing.scalar_one_or_none():
                break
            barcode_val = str(uuid.uuid4().int)[:12]

    item = Item(
        vendor_id=vendor_id,
        sku=sku,
        barcode=barcode_val,
        name=data.name,
        description=data.description,
        category=data.category,
        price=data.price,
        quantity=data.quantity,
        photo_urls=data.photo_urls,
        is_online=data.is_online,
        is_tax_exempt=data.is_tax_exempt,
        sale_price=data.sale_price,
        sale_start=data.sale_start,
        sale_end=data.sale_end,
    )
    db.add(item)
    await db.commit()

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item.id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.get("/barcode/{barcode}", response_model=ItemResponse)
async def get_item_by_barcode(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.barcode == barcode)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item_to_response(item)


@router.get("/{item_id}/label")
async def get_item_label(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role != "admin" and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    pdf_bytes = generate_label_pdf(item)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="label_{item_id}.pdf"'},
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role != "admin" and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return item_to_response(item)


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: int,
    data: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role != "admin" and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor)).where(Item.id == item_id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role != "admin" and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    item.status = "removed"
    await db.commit()
