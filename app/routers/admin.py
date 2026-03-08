from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor
from app.models.rent import RentPayment
from app.routers.auth import get_current_user, require_admin, require_cashier_or_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _rent_status(today: date, last_payment: Optional[RentPayment]) -> str:
    if last_payment is None:
        return "overdue"
    period = last_payment.period_month
    current_period = date(today.year, today.month, 1)
    if period >= current_period:
        return "current"
    days_since = (today - period).days
    if days_since >= 30:
        return "overdue"
    return "due"


@router.get("/rent-status")
async def rent_status(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_cashier_or_admin),
):
    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    today = date.today()
    vendor_ids = [v.id for v in vendors]

    payments_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id.in_(vendor_ids))
        .order_by(RentPayment.vendor_id, RentPayment.period_month.desc())
    )
    all_payments = payments_result.scalars().all()

    latest_by_vendor: dict[int, RentPayment] = {}
    for p in all_payments:
        if p.vendor_id not in latest_by_vendor:
            latest_by_vendor[p.vendor_id] = p

    rows = []
    total_collected_this_month = 0.0
    current_period = date(today.year, today.month, 1)

    for v in vendors:
        last = latest_by_vendor.get(v.id)
        status = _rent_status(today, last)
        if last and last.period_month >= current_period:
            total_collected_this_month += float(last.amount or 0)
        rows.append({
            "id": v.id,
            "name": v.name,
            "booth_number": v.booth_number or "—",
            "monthly_rent": float(v.monthly_rent or 0),
            "last_payment_date": last.processed_at.date().isoformat() if last else None,
            "last_payment_amount": float(last.amount) if last else None,
            "status": status,
            "rent_flagged": v.rent_flagged,
        })

    return {
        "vendors": rows,
        "total_collected_this_month": round(total_collected_this_month, 2),
        "month_label": today.strftime("%B %Y"),
    }


@router.post("/vendors/{vendor_id}/flag")
async def toggle_vendor_flag(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_admin),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    vendor.rent_flagged = not vendor.rent_flagged
    await db.commit()

    return {
        "id": vendor.id,
        "name": vendor.name,
        "rent_flagged": vendor.rent_flagged,
    }
