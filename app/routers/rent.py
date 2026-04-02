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


def _has_vendor_booth_access(user: Vendor) -> bool:
    return user.role == "vendor" or bool(getattr(user, "is_vendor", False))


@router.get("/rent-status")
async def rent_status(
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
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
    current_payment = existing.scalar_one_or_none()

    history_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id == vendor.id)
        .order_by(RentPayment.period_month.desc())
        .limit(12)
    )
    history = history_result.scalars().all()

    return {
        "monthly_rent": float(vendor.monthly_rent or 0),
        "current_month": today.strftime("%B %Y"),
        "paid_this_month": current_payment is not None and current_payment.status == "paid",
        "pending_this_month": current_payment is not None and current_payment.status == "pending",
        "history": [
            {
                "period": p.period_month.strftime("%B %Y"),
                "amount": float(p.amount),
                "method": p.method,
                "status": p.status,
                "date": p.processed_at.strftime("%m/%d/%Y") if p.processed_at else None,
            }
            for p in history
        ],
    }


class RentConfirmRequest(BaseModel):
    square_payment_id: Optional[str] = None


@router.post("/pay-rent")
async def pay_rent(
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
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
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Rent payment could not be initiated. Please try again or contact the office.",
        )


@router.post("/rent-confirmed")
async def rent_confirmed(
    body: RentConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
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
