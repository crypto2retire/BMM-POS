from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance, BalanceAdjustment
from app.schemas.vendor import (
    VendorCreate, VendorUpdate, VendorResponse, VendorBalanceResponse,
    BalanceAdjustRequest, BalanceAdjustmentResponse,
)
from app.routers.auth import get_current_user, require_role, get_password_hash

router = APIRouter(prefix="/vendors", tags=["vendors"])

@router.get("/", response_model=List[VendorResponse])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    result = await db.execute(select(Vendor).order_by(Vendor.name))
    return result.scalars().all()

@router.post("/", response_model=VendorResponse, status_code=201)
async def create_vendor(
    vendor: VendorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    existing = await db.execute(select(Vendor).where(Vendor.email == vendor.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    db_vendor = Vendor(
        name=vendor.name,
        email=vendor.email,
        phone=vendor.phone,
        password_hash=get_password_hash(vendor.password),
        booth_number=vendor.booth_number,
        role=vendor.role,
        is_vendor=vendor.is_vendor,
        monthly_rent=vendor.monthly_rent,
        commission_rate=vendor.commission_rate,
    )
    db.add(db_vendor)
    await db.commit()
    await db.refresh(db_vendor)
    return db_vendor

@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user)
):
    if current_user.role != "admin" and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor

@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    vendor_update: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    update_data = vendor_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(vendor, key, value)

    await db.commit()
    await db.refresh(vendor)
    return vendor

@router.patch("/me/label-preference")
async def update_label_preference(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    pref = body.get("label_preference", "standard")
    if pref not in ("standard", "dymo"):
        raise HTTPException(status_code=400, detail="Must be 'standard' or 'dymo'")
    current_user.label_preference = pref
    await db.commit()
    return {"label_preference": pref}


@router.post("/{vendor_id}/reset-password")
async def reset_vendor_password(
    vendor_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    new_password = body.get("new_password")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor.password_hash = get_password_hash(new_password)
    await db.commit()
    return {"detail": "Password reset successfully"}

@router.post("/me/change-password")
async def change_own_password(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user)
):
    import bcrypt
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if not bcrypt.checkpw(current_password.encode('utf-8'), current_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = get_password_hash(new_password)
    await db.commit()
    return {"detail": "Password changed successfully"}

@router.delete("/{vendor_id}")
async def delete_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    vendor.is_active = False
    await db.commit()
    return {"detail": "Vendor deactivated"}

@router.get("/{vendor_id}/balance", response_model=VendorBalanceResponse)
async def get_vendor_balance(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user)
):
    if current_user.role not in ("admin", "cashier") and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(select(VendorBalance).where(VendorBalance.vendor_id == vendor_id))
    balance = result.scalar_one_or_none()
    if not balance:
        balance = VendorBalance(vendor_id=vendor_id)
        db.add(balance)
        await db.commit()
        await db.refresh(balance)
    return balance


@router.post("/{vendor_id}/balance/adjust", response_model=BalanceAdjustmentResponse)
async def adjust_vendor_balance(
    vendor_id: int,
    data: BalanceAdjustRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    result = await db.execute(
        select(VendorBalance)
        .where(VendorBalance.vendor_id == vendor_id)
        .with_for_update()
    )
    balance_row = result.scalar_one_or_none()
    if not balance_row:
        balance_row = VendorBalance(vendor_id=vendor_id, balance=Decimal("0.00"))
        db.add(balance_row)
        await db.flush()
        await db.execute(
            select(VendorBalance)
            .where(VendorBalance.vendor_id == vendor_id)
            .with_for_update()
        )

    balance_before = Decimal(str(balance_row.balance))
    adj_amount = Decimal(str(data.amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    if adj_amount > Decimal("99999999.99"):
        raise HTTPException(status_code=400, detail="Amount exceeds maximum allowed")

    if data.adjustment_type == "credit":
        balance_after = (balance_before + adj_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        balance_after = (balance_before - adj_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

    balance_row.balance = balance_after
    balance_row.last_updated = datetime.utcnow()

    adjustment = BalanceAdjustment(
        vendor_id=vendor_id,
        adjusted_by=current_user.id,
        amount=adj_amount,
        adjustment_type=data.adjustment_type,
        reason=data.reason,
        balance_before=balance_before,
        balance_after=balance_after,
    )
    db.add(adjustment)
    await db.commit()
    await db.refresh(adjustment)

    return BalanceAdjustmentResponse(
        id=adjustment.id,
        vendor_id=adjustment.vendor_id,
        adjusted_by=adjustment.adjusted_by,
        admin_name=current_user.name,
        amount=adjustment.amount,
        adjustment_type=adjustment.adjustment_type,
        reason=adjustment.reason,
        balance_before=adjustment.balance_before,
        balance_after=adjustment.balance_after,
        created_at=adjustment.created_at,
    )


@router.get("/{vendor_id}/balance/history", response_model=List[BalanceAdjustmentResponse])
async def get_balance_history(
    vendor_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(
        select(BalanceAdjustment)
        .options(selectinload(BalanceAdjustment.admin))
        .where(BalanceAdjustment.vendor_id == vendor_id)
        .order_by(BalanceAdjustment.created_at.desc())
        .limit(limit)
    )
    adjustments = result.scalars().all()

    return [
        BalanceAdjustmentResponse(
            id=a.id,
            vendor_id=a.vendor_id,
            adjusted_by=a.adjusted_by,
            admin_name=a.admin.name if a.admin else None,
            amount=a.amount,
            adjustment_type=a.adjustment_type,
            reason=a.reason,
            balance_before=a.balance_before,
            balance_after=a.balance_after,
            created_at=a.created_at,
        )
        for a in adjustments
    ]
