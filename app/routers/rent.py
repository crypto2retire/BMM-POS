from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor
from app.models.rent import RentPayment
from app.routers.auth import get_current_user

router = APIRouter(prefix="/vendor", tags=["vendor-rent"])


class RentConfirmRequest(BaseModel):
    square_payment_id: Optional[str] = None


@router.post("/pay-rent")
async def pay_rent(
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if current_vendor.role not in ("vendor", "admin"):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    rent_amount = float(vendor.monthly_rent or 0)
    if rent_amount <= 0:
        raise HTTPException(status_code=400, detail="No rent amount configured for this vendor.")

    price_cents = round(rent_amount * 100)
    today = date.today()
    month_label = today.strftime("%B %Y")
    redirect_url = (
        f"https://www.bowenstreetmm.com/vendor/dashboard.html"
        f"?rent_paid=success&vendor_id={vendor.id}"
    )

    try:
        from app.services.square import create_payment_link
        result = await create_payment_link(
            name=f"Rent payment - {vendor.name} - {month_label}",
            price_cents=price_cents,
            redirect_url=redirect_url,
        )
        return {"payment_url": result["url"]}
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/rent-confirmed")
async def rent_confirmed(
    body: RentConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if current_vendor.role not in ("vendor", "admin"):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    today = date.today()
    period = date(today.year, today.month, 1)

    existing = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.period_month == period,
        )
    )
    if existing.scalar_one_or_none():
        return {"success": True, "message": "Rent for this month already recorded."}

    payment = RentPayment(
        vendor_id=vendor.id,
        amount=vendor.monthly_rent,
        period_month=period,
        method="square",
        status="paid",
        notes=body.square_payment_id or "Square online payment",
    )
    db.add(payment)
    await db.commit()

    return {
        "success": True,
        "message": f"Rent payment of ${float(vendor.monthly_rent):.2f} recorded for {period.strftime('%B %Y')}.",
    }
