from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.rent import RentPayment
from app.models.legacy_history import LegacyFinancialHistory
from app.routers.auth import get_current_user
from app.services.rent_payments import apply_rent_payment

router = APIRouter(prefix="/vendor", tags=["vendor-rent"])


def _serialize_legacy_entry(entry: LegacyFinancialHistory) -> dict:
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "source_system": entry.source_system,
        "reference_kind": entry.reference_kind,
        "amount": float(entry.amount or 0),
        "entry_date": entry.entry_date.isoformat() if entry.entry_date else None,
        "period_month": entry.period_month.isoformat() if entry.period_month else None,
        "description": entry.description,
        "source_name": entry.source_name,
        "source_email": entry.source_email,
        "source_reference": entry.source_reference,
        "import_batch": entry.import_batch,
        "imported_at": entry.imported_at.isoformat() if entry.imported_at else None,
    }


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

    legacy_result = await db.execute(
        select(LegacyFinancialHistory)
        .where(
            LegacyFinancialHistory.vendor_id == vendor.id,
            LegacyFinancialHistory.entry_type == "rent",
        )
        .order_by(
            LegacyFinancialHistory.entry_date.desc().nullslast(),
            LegacyFinancialHistory.imported_at.desc(),
        )
        .limit(24)
    )
    legacy_history = legacy_result.scalars().all()

    balance_result = await db.execute(
        select(VendorBalance).where(VendorBalance.vendor_id == vendor.id)
    )
    balance = balance_result.scalar_one_or_none()
    rent_credit = float(balance.rent_balance or 0) if balance and balance.rent_balance is not None else 0.0

    return {
        "monthly_rent": float(vendor.monthly_rent or 0),
        "current_month": today.strftime("%B %Y"),
        "paid_this_month": current_payment is not None and current_payment.status == "paid",
        "pending_this_month": current_payment is not None and current_payment.status == "pending",
        "rent_credit": rent_credit,
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
        "legacy_history": [_serialize_legacy_entry(entry) for entry in legacy_history],
    }


class RentConfirmRequest(BaseModel):
    square_payment_id: Optional[str] = None
    amount: Optional[Decimal] = None
    period: Optional[str] = None


class VendorRentRequest(BaseModel):
    amount: Optional[Decimal] = None
    period: Optional[str] = None


@router.post("/pay-rent")
async def pay_rent(
    body: VendorRentRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    configured_rent = Decimal(str(vendor.monthly_rent or 0))
    if configured_rent <= 0:
        raise HTTPException(status_code=400, detail="No rent amount configured for this vendor.")

    try:
        amount = Decimal(str(body.amount if body.amount is not None else configured_rent))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount.")

    if body.period:
        try:
            parts = body.period.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    price_cents = round(float(amount) * 100)
    month_label = period.strftime("%B %Y")
    redirect_url = (
        f"https://www.bowenstreetmm.com/vendor/dashboard.html"
        f"?rent_paid=success&vendor_id={vendor.id}"
        f"&rent_amount={float(amount):.2f}&rent_period={period.isoformat()}"
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
    try:
        amount = Decimal(str(body.amount if body.amount is not None else vendor.monthly_rent))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount.")

    if body.period:
        try:
            parts = body.period.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    allocation = await apply_rent_payment(
        db=db,
        vendor=vendor,
        amount=amount,
        requested_period=period,
        method="square",
        notes=body.square_payment_id or "Square online payment",
    )
    await db.commit()

    applied_periods = allocation["applied_periods"]
    credit_remainder = allocation["credit_remainder"]
    if applied_periods and credit_remainder > 0:
        message = (
            f"Rent payment recorded. Applied to {', '.join(p.strftime('%B %Y') for p in applied_periods)}. "
            f"Remaining credit ${float(credit_remainder):.2f} stays on your rent account."
        )
    elif applied_periods:
        message = (
            f"Rent payment recorded for {', '.join(p.strftime('%B %Y') for p in applied_periods)}."
        )
    else:
        message = (
            f"Rent payment recorded. The full amount remains as rent credit until a full month is covered."
        )

    return {
        "success": True,
        "message": message,
        "applied_periods": [p.isoformat() for p in applied_periods],
        "credit_remainder": float(credit_remainder),
    }
