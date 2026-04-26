from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.security_deposit import SecurityDepositLog
from app.models.rent import RentPayment
from app.routers.auth import get_current_user, require_role

router = APIRouter(prefix="/vendors", tags=["security-deposits"])

VALID_ACTIONS = ("received", "deduction", "refund", "applied_to_rent")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


class DepositActionRequest(BaseModel):
    action: str
    amount: Decimal
    reason: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        if v not in VALID_ACTIONS:
            raise ValueError(f"action must be one of: {', '.join(VALID_ACTIONS)}")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        if v > Decimal("99999999.99"):
            raise ValueError("amount exceeds maximum allowed")
        return v


class DepositLogResponse(BaseModel):
    id: int
    vendor_id: int
    action: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    reason: Optional[str] = None
    performed_by: int
    admin_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/{vendor_id}/deposit", response_model=DepositLogResponse)
async def record_deposit_action(
    vendor_id: int,
    payload: DepositActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id).with_for_update()
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    amount = _money(payload.amount)
    balance_before = _money(vendor.security_deposit_balance)
    action = payload.action

    if action == "received":
        balance_after = balance_before + amount
    elif action == "deduction":
        if amount > balance_before:
            raise HTTPException(
                status_code=400,
                detail=f"Deduction ${amount} exceeds current balance ${balance_before}",
            )
        if not payload.reason:
            raise HTTPException(status_code=400, detail="Reason is required for deductions")
        balance_after = balance_before - amount
    elif action == "refund":
        if amount > balance_before:
            raise HTTPException(
                status_code=400,
                detail=f"Refund ${amount} exceeds current balance ${balance_before}",
            )
        balance_after = balance_before - amount
    elif action == "applied_to_rent":
        if amount > balance_before:
            raise HTTPException(
                status_code=400,
                detail=f"Amount ${amount} exceeds current deposit balance ${balance_before}",
            )
        monthly_rent = _money(vendor.monthly_rent)
        if monthly_rent <= 0:
            raise HTTPException(
                status_code=400, detail="Vendor has no monthly rent configured"
            )
        balance_after = balance_before - amount

        # Credit the vendor's rent balance
        bal_result = await db.execute(
            select(VendorBalance)
            .where(VendorBalance.vendor_id == vendor_id)
            .limit(1)
            .with_for_update()
        )
        vb = bal_result.scalar_one_or_none()
        if vb:
            vb.rent_balance = _money(vb.rent_balance) + amount
        else:
            db.add(VendorBalance(
                vendor_id=vendor_id,
                balance=Decimal("0.00"),
                rent_balance=amount,
            ))

        # Also record a rent payment for the current month
        today = date.today()
        current_period = date(today.year, today.month, 1)
        db.add(RentPayment(
            vendor_id=vendor_id,
            amount=amount,
            period_month=current_period,
            method="deposit",
            status="paid",
            notes=f"Applied from security deposit. {payload.reason or ''}".strip(),
        ))
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    balance_after = _money(balance_after)
    vendor.security_deposit_balance = balance_after

    log_entry = SecurityDepositLog(
        vendor_id=vendor_id,
        action=action,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        reason=payload.reason,
        performed_by=current_user.id,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)

    return DepositLogResponse(
        id=log_entry.id,
        vendor_id=log_entry.vendor_id,
        action=log_entry.action,
        amount=log_entry.amount,
        balance_before=log_entry.balance_before,
        balance_after=log_entry.balance_after,
        reason=log_entry.reason,
        performed_by=log_entry.performed_by,
        admin_name=current_user.name,
        created_at=log_entry.created_at,
    )


@router.get("/{vendor_id}/deposit/history", response_model=List[DepositLogResponse])
async def get_deposit_history(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vendor not found")

    logs_result = await db.execute(
        select(SecurityDepositLog)
        .where(SecurityDepositLog.vendor_id == vendor_id)
        .order_by(SecurityDepositLog.created_at.desc())
    )
    logs = logs_result.scalars().all()

    # Build admin name lookup
    admin_ids = {log.performed_by for log in logs}
    if admin_ids:
        admins_result = await db.execute(
            select(Vendor.id, Vendor.name).where(Vendor.id.in_(admin_ids))
        )
        admin_names = {row[0]: row[1] for row in admins_result.all()}
    else:
        admin_names = {}

    return [
        DepositLogResponse(
            id=log.id,
            vendor_id=log.vendor_id,
            action=log.action,
            amount=log.amount,
            balance_before=log.balance_before,
            balance_after=log.balance_after,
            reason=log.reason,
            performed_by=log.performed_by,
            admin_name=admin_names.get(log.performed_by),
            created_at=log.created_at,
        )
        for log in logs
    ]
