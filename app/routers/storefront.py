from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.item import Item
from app.models.reservation import Reservation

router = APIRouter(prefix="/storefront", tags=["storefront"])


class ReserveRequest(BaseModel):
    item_id: int
    customer_name: str
    customer_phone: str


class CreatePaymentRequest(BaseModel):
    item_id: int
    customer_name: str
    customer_phone: str


class ConfirmPaymentRequest(BaseModel):
    reservation_id: int
    square_payment_id: Optional[str] = None


@router.get("/items")
async def storefront_items(
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Item)
        .options(selectinload(Item.vendor))
        .where(Item.status == "active", Item.is_online.is_(True))
        .order_by(Item.name)
    )
    if search:
        q = q.where(Item.name.ilike(f"%{search}%"))

    rows = await db.execute(q)
    items = rows.scalars().all()

    today = date.today()
    result = []
    for item in items:
        sale_active = (
            item.sale_price is not None
            and item.sale_start is not None
            and item.sale_end is not None
            and item.sale_start <= today <= item.sale_end
        )
        result.append({
            "id": item.id,
            "name": item.name,
            "price": float(item.price),
            "sale_price": float(item.sale_price) if sale_active else None,
            "sale_start": str(item.sale_start) if item.sale_start else None,
            "sale_end": str(item.sale_end) if item.sale_end else None,
            "description": item.description,
            "vendor_name": item.vendor.name if item.vendor else "Bowenstreet Market",
            "booth_number": item.vendor.booth_number if item.vendor else None,
        })
    return result


@router.post("/create-payment")
async def create_payment(
    body: CreatePaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Item).where(Item.id == body.item_id, Item.status == "active")
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or no longer available.")

    today = date.today()
    sale_active = (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    )
    display_price = float(item.sale_price) if sale_active else float(item.price)
    price_cents = round(display_price * 100)

    reservation = Reservation(
        item_id=body.item_id,
        customer_name=body.customer_name,
        customer_phone=body.customer_phone,
        amount_paid=display_price,
        status="pending",
    )
    db.add(reservation)
    await db.flush()
    reservation_id = reservation.id

    redirect_url = f"https://www.bowenstreetmm.com/shop/index.html?payment=success&ref={reservation_id}"

    try:
        from app.services.square import create_payment_link
        result = await create_payment_link(
            name=item.name,
            price_cents=price_cents,
            redirect_url=redirect_url,
        )
        reservation.square_payment_id = result.get("payment_link_id", "")
        await db.commit()
        return {"payment_url": result["url"], "reservation_id": reservation_id}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/payment-confirmed")
async def payment_confirmed(
    body: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Reservation).where(
            Reservation.id == body.reservation_id,
            Reservation.status == "pending",
        )
    )
    reservation = row.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or already confirmed.")

    item_row = await db.execute(
        select(Item).where(Item.id == reservation.item_id)
    )
    item = item_row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    if item.status not in ("active", "reserved"):
        raise HTTPException(status_code=409, detail="Item is no longer available.")

    item.status = "reserved"
    reservation.status = "confirmed"
    if body.square_payment_id:
        reservation.square_payment_id = body.square_payment_id

    await db.commit()

    return {
        "success": True,
        "message": (
            f"Payment confirmed. '{item.name}' has been reserved for {reservation.customer_name}. "
            "Please stop in to complete your purchase — we'll hold it for 48 hours."
        ),
        "item_name": item.name,
        "customer_name": reservation.customer_name,
    }


@router.post("/reserve")
async def reserve_item(
    body: ReserveRequest,
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Item).where(Item.id == body.item_id, Item.status == "active")
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=404,
            detail="Item not found or no longer available for reservation.",
        )

    item.status = "reserved"
    await db.commit()

    return {
        "success": True,
        "message": (
            f"'{item.name}' has been reserved for {body.customer_name}. "
            "Please stop in to complete your purchase — we'll hold it for 48 hours."
        ),
        "item_id": item.id,
        "item_name": item.name,
        "customer_name": body.customer_name,
        "customer_phone": body.customer_phone,
    }
