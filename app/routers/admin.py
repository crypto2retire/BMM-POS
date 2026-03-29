import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.rent import RentPayment
from app.models.payout import Payout
from app.routers.auth import get_current_user, require_admin, require_cashier_or_admin
from app.services.email import send_email_safe
from app.services.email_templates import (
    payout_with_rent_email,
    rent_shortfall_email,
    rent_overdue_15day_email,
    rent_overdue_27day_email,
)

logger = logging.getLogger(__name__)

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


@router.get("/payout-preview")
async def payout_preview(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_admin),
):
    today = date.today()
    period = date(today.year, today.month, 1)
    period_label = period.strftime("%B %Y")

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    existing_payout = await db.execute(
        select(Payout).where(Payout.period_month == period).limit(1)
    )
    already_processed = existing_payout.scalar_one_or_none() is not None

    rows = []
    for v in vendors:
        bal_result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == v.id)
        )
        bal = bal_result.scalar_one_or_none()
        gross = float(bal.balance) if bal else 0.0
        rent = float(v.monthly_rent or 0)

        rent_paid_result = await db.execute(
            select(RentPayment).where(
                RentPayment.vendor_id == v.id,
                RentPayment.period_month == period,
            )
        )
        rent_already_paid = rent_paid_result.scalar_one_or_none() is not None

        if rent_already_paid:
            rent_to_deduct = 0.0
        else:
            rent_to_deduct = rent

        if gross >= rent_to_deduct:
            net = round(gross - rent_to_deduct, 2)
            shortfall = 0.0
        else:
            net = 0.0
            shortfall = round(rent_to_deduct - gross, 2)

        rows.append({
            "vendor_id": v.id,
            "name": v.name,
            "booth_number": v.booth_number or "—",
            "email": v.email or "",
            "gross_sales": round(gross, 2),
            "monthly_rent": rent,
            "rent_already_paid": rent_already_paid,
            "rent_to_deduct": round(rent_to_deduct, 2),
            "net_payout": net,
            "shortfall": shortfall,
            "payout_method": v.payout_method or "—",
        })

    return {
        "period": period_label,
        "period_date": period.isoformat(),
        "already_processed": already_processed,
        "vendors": rows,
        "totals": {
            "gross_sales": round(sum(r["gross_sales"] for r in rows), 2),
            "rent_deducted": round(sum(r["rent_to_deduct"] for r in rows), 2),
            "net_payouts": round(sum(r["net_payout"] for r in rows), 2),
            "shortfalls": round(sum(r["shortfall"] for r in rows), 2),
        },
    }


@router.post("/process-payouts")
async def process_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_admin),
):
    today = date.today()
    period = date(today.year, today.month, 1)
    period_label = period.strftime("%B %Y")

    existing_payout = await db.execute(
        select(Payout).where(Payout.period_month == period).limit(1)
    )
    if existing_payout.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Payouts for {period_label} have already been processed.")

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    processed = 0
    shortfall_count = 0
    total_net = Decimal("0")

    for v in vendors:
        bal_result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == v.id)
        )
        bal = bal_result.scalar_one_or_none()
        gross = Decimal(str(bal.balance)) if bal and bal.balance else Decimal("0")
        rent = Decimal(str(v.monthly_rent or 0))

        rent_paid_result = await db.execute(
            select(RentPayment).where(
                RentPayment.vendor_id == v.id,
                RentPayment.period_month == period,
            )
        )
        rent_already_paid = rent_paid_result.scalar_one_or_none() is not None

        rent_to_deduct = Decimal("0") if rent_already_paid else rent

        if gross >= rent_to_deduct:
            net = (gross - rent_to_deduct).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            net = Decimal("0")

        shortfall = Decimal("0")
        if gross < rent_to_deduct:
            shortfall = (rent_to_deduct - gross).quantize(Decimal("0.01"), ROUND_HALF_UP)
            shortfall_count += 1

        payout = Payout(
            vendor_id=v.id,
            period_month=period,
            gross_sales=gross.quantize(Decimal("0.01"), ROUND_HALF_UP),
            rent_deducted=min(gross, rent_to_deduct).quantize(Decimal("0.01"), ROUND_HALF_UP),
            net_payout=net,
            payout_method=v.payout_method,
            zelle_handle=v.zelle_handle if hasattr(v, 'zelle_handle') else None,
            status="pending",
            notes=f"Processed by {current_user.name}",
        )
        db.add(payout)

        if not rent_already_paid and rent > 0:
            rent_amount_paid = min(gross, rent_to_deduct)
            if rent_amount_paid > 0:
                rent_payment = RentPayment(
                    vendor_id=v.id,
                    amount=rent_amount_paid,
                    period_month=period,
                    method="balance",
                    status="paid",
                    notes=f"Deducted from sales by {current_user.name}",
                )
                db.add(rent_payment)

        if bal:
            bal.balance = Decimal("0")

        total_net += net
        processed += 1

        if v.email:
            try:
                if shortfall > 0:
                    subj, html, plain = rent_shortfall_email(
                        vendor_name=v.name or "Vendor",
                        gross_sales=float(gross),
                        rent_amount=float(rent),
                        shortfall=float(shortfall),
                        booth=v.booth_number or "—",
                        period=period_label,
                    )
                    await send_email_safe(v.email, subj, html, plain)
                elif net > 0:
                    subj, html, plain = payout_with_rent_email(
                        vendor_name=v.name or "Vendor",
                        gross_sales=float(gross),
                        rent_deducted=float(min(gross, rent_to_deduct)),
                        net_payout=float(net),
                        period=period_label,
                        method=v.payout_method or "TBD",
                    )
                    await send_email_safe(v.email, subj, html, plain)
            except Exception as e:
                logger.warning(f"Failed to send payout email to {v.email}: {e}")

    await db.commit()

    return {
        "success": True,
        "message": f"Payouts processed for {period_label}.",
        "processed": processed,
        "shortfalls": shortfall_count,
        "total_net_payouts": float(total_net),
    }


@router.post("/send-rent-reminders")
async def send_rent_reminders(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_admin),
):
    today = date.today()
    current_period = date(today.year, today.month, 1)

    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.status == "active",
            Vendor.monthly_rent > 0,
        ).order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    sent_15 = 0
    sent_27 = 0
    skipped = 0

    for v in vendors:
        if not v.email:
            skipped += 1
            continue

        latest_result = await db.execute(
            select(RentPayment)
            .where(RentPayment.vendor_id == v.id)
            .order_by(RentPayment.period_month.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()

        if latest and latest.period_month >= current_period:
            continue

        if latest:
            days_overdue = (today - latest.period_month).days
        else:
            days_overdue = 999

        rent_amount = float(v.monthly_rent or 0)
        booth = v.booth_number or "—"
        period_label = current_period.strftime("%B %Y")

        if days_overdue >= 27:
            subj, html, plain = rent_overdue_27day_email(
                vendor_name=v.name or "Vendor",
                amount=rent_amount,
                booth=booth,
                period=period_label,
            )
            await send_email_safe(v.email, subj, html, plain)
            sent_27 += 1
        elif days_overdue >= 15:
            subj, html, plain = rent_overdue_15day_email(
                vendor_name=v.name or "Vendor",
                amount=rent_amount,
                booth=booth,
                period=period_label,
            )
            await send_email_safe(v.email, subj, html, plain)
            sent_15 += 1

    return {
        "success": True,
        "message": f"Rent reminders sent: {sent_15} at 15 days, {sent_27} at 27 days.",
        "sent_15_day": sent_15,
        "sent_27_day": sent_27,
        "skipped_no_email": skipped,
    }
