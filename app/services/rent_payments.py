from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rent import RentPayment
from app.models.vendor import Vendor, VendorBalance


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _next_month(period: date) -> date:
    if period.month == 12:
        return date(period.year + 1, 1, 1)
    return date(period.year, period.month + 1, 1)


async def apply_rent_payment(
    db: AsyncSession,
    vendor: Vendor,
    amount: Decimal,
    requested_period: date,
    method: str,
    notes: str | None = None,
) -> dict:
    amount = _money(amount)
    monthly_rent = _money(vendor.monthly_rent)

    if amount <= 0:
        raise ValueError("Invalid amount.")
    if monthly_rent <= 0:
        raise ValueError("No rent amount configured for this vendor.")

    paid_result = await db.execute(
        select(RentPayment.period_month).where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.status == "paid",
        )
    )
    paid_periods = {row[0] for row in paid_result.all()}

    balance_result = await db.execute(
        select(VendorBalance).where(VendorBalance.vendor_id == vendor.id).with_for_update()
    )
    balance_row = balance_result.scalar_one_or_none()
    if balance_row:
        balance_row.rent_balance = _money(balance_row.rent_balance) + amount
    else:
        balance_row = VendorBalance(
            vendor_id=vendor.id,
            balance=Decimal("0.00"),
            rent_balance=amount,
        )
        db.add(balance_row)

    remaining = amount
    applied_periods: list[date] = []
    period = requested_period
    guard = 0
    while remaining >= monthly_rent and guard < 240:
        if period not in paid_periods:
            payment = RentPayment(
                vendor_id=vendor.id,
                amount=monthly_rent,
                period_month=period,
                method=method,
                status="paid",
                notes=notes,
            )
            db.add(payment)
            applied_periods.append(period)
            paid_periods.add(period)
            remaining -= monthly_rent
            remaining = _money(remaining)
        period = _next_month(period)
        guard += 1

    return {
        "amount": amount,
        "monthly_rent": monthly_rent,
        "applied_periods": applied_periods,
        "credit_remainder": remaining,
        "rent_balance_after": _money(balance_row.rent_balance),
    }
