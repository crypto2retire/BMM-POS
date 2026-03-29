from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
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
        select(Vendor).where(
            Vendor.status == "active",
            Vendor.monthly_rent > 0,
        ).order_by(Vendor.name)
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


@router.get("/vendors/{vendor_id}/rent-history")
async def vendor_rent_history(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_cashier_or_admin),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    payments_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id == vendor_id)
        .order_by(RentPayment.period_month.desc())
    )
    payments = payments_result.scalars().all()

    today = date.today()
    latest = payments[0] if payments else None
    status = _rent_status(today, latest)

    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.name,
            "email": vendor.email,
            "phone": vendor.phone,
            "booth_number": vendor.booth_number or "—",
            "monthly_rent": float(vendor.monthly_rent or 0),
            "status": vendor.status,
            "role": vendor.role,
            "rent_flagged": vendor.rent_flagged,
            "rent_status": status,
        },
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "period_month": p.period_month.strftime("%B %Y"),
                "method": p.method,
                "status": p.status,
                "notes": p.notes,
                "processed_at": p.processed_at.isoformat() if p.processed_at else None,
            }
            for p in payments
        ],
    }


@router.post("/vendors/{vendor_id}/record-rent")
async def record_rent_payment(
    vendor_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_admin),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    method = body.get("method", "cash")
    if method not in ("cash", "check", "square", "zelle", "other"):
        raise HTTPException(status_code=400, detail="Invalid payment method.")

    amount = body.get("amount")
    if amount is not None:
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid amount.")
    else:
        amount = vendor.monthly_rent

    period_str = body.get("period")
    if period_str:
        try:
            parts = period_str.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    notes = body.get("notes", "")

    existing = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor_id,
            RentPayment.period_month == period,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Rent for {period.strftime('%B %Y')} is already recorded.",
        )

    payment = RentPayment(
        vendor_id=vendor_id,
        amount=amount,
        period_month=period,
        method=method,
        status="paid",
        notes=notes or f"Recorded by admin ({current_user.name})",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return {
        "success": True,
        "message": f"Rent payment of ${float(amount):.2f} recorded for {vendor.name} — {period.strftime('%B %Y')}.",
        "payment": {
            "id": payment.id,
            "amount": float(payment.amount),
            "period_month": payment.period_month.strftime("%B %Y"),
            "method": payment.method,
            "status": payment.status,
        },
    }
