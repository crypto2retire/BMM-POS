from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance, BalanceAdjustment
from app.models.rent import RentPayment
from app.schemas.vendor import (
    VendorCreate, VendorUpdate, VendorResponse, VendorBalanceResponse,
    BalanceAdjustRequest, BalanceAdjustmentResponse,
)
from app.routers.auth import get_current_user, require_role, get_password_hash
from app.routers.settings import role_allows_manage_vendors, role_feature_allowed, require_staff_feature

router = APIRouter(prefix="/vendors", tags=["vendors"])


class AssistantSettingsUpdate(BaseModel):
    assistant_name: Optional[str] = None
    assistant_enabled: Optional[bool] = None


async def _can_access_vendor_directory(db: AsyncSession, user: Vendor) -> bool:
    if user.role == "admin":
        return True
    if user.role != "cashier":
        return False
    for slug in (
        "role_manage_vendors",
        "role_process_sales",
        "role_manage_rent",
        "role_view_reports",
    ):
        if await role_feature_allowed(db, user, slug):
            return True
    return False


def _display_rent_balance_for_admin_list(
    rent_ledger: Decimal,
    monthly_rent: Decimal,
    current_month_rent_paid: bool,
) -> Decimal:
    """
    Match admin vendor hub / vendor-overview: when this month's rent is not paid,
    net monthly_rent from ledger so balance shows negative rent owed (e.g. 0 - 200 = -200).
    """
    rl = rent_ledger if rent_ledger is not None else Decimal("0.00")
    mr = monthly_rent if monthly_rent is not None else Decimal("0.00")
    if mr > 0 and not current_month_rent_paid:
        return (rl - mr).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return rl.quantize(Decimal("0.01"), ROUND_HALF_UP)


@router.get("/", response_model=List[VendorResponse])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if not await _can_access_vendor_directory(db, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to list vendors")
    result = await db.execute(select(Vendor).order_by(Vendor.name))
    vendors = result.scalars().all()

    # Fetch all balances in one query
    bal_result = await db.execute(
        select(VendorBalance.vendor_id, VendorBalance.balance, VendorBalance.rent_balance)
    )
    balance_map = {}
    rent_balance_map = {}
    for row in bal_result.all():
        balance_map[row.vendor_id] = (
            row.balance if row.balance is not None else Decimal("0.00")
        )
        rent_balance_map[row.vendor_id] = (
            row.rent_balance if row.rent_balance is not None else Decimal("0.00")
        )

    today = date.today()
    current_period = date(today.year, today.month, 1)
    rp_result = await db.execute(
        select(RentPayment.vendor_id, RentPayment.status).where(
            RentPayment.period_month == current_period
        )
    )
    paid_rent_vendor_ids = {
        row.vendor_id for row in rp_result.all() if row.status == "paid"
    }

    for v in vendors:
        sb = balance_map.get(v.id, Decimal("0.00"))
        rb_ledger = rent_balance_map.get(v.id, Decimal("0.00"))
        monthly = v.monthly_rent or Decimal("0.00")
        rent_paid = v.id in paid_rent_vendor_ids
        rb_disp = _display_rent_balance_for_admin_list(rb_ledger, monthly, rent_paid)
        v.sales_balance = sb
        v.rent_balance = rb_disp
        v.current_balance = (sb + rb_disp).quantize(Decimal("0.01"), ROUND_HALF_UP)

    return vendors

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

@router.get("/label-sizes")
async def list_label_sizes():
    from app.services.labels import LABEL_SIZES
    return [{"key": k, "name": v["name"], "width": v["w"], "height": v["h"]} for k, v in LABEL_SIZES.items()]


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role == "admin" or current_user.id == vendor_id:
        pass
    elif await role_allows_manage_vendors(db, current_user):
        pass
    else:
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    bal_result = await db.execute(
        select(VendorBalance).where(VendorBalance.vendor_id == vendor_id)
    )
    bal_row = bal_result.scalar_one_or_none()
    sb = (
        bal_row.balance if bal_row and bal_row.balance is not None else Decimal("0.00")
    )
    rb_ledger = (
        bal_row.rent_balance
        if bal_row and bal_row.rent_balance is not None
        else Decimal("0.00")
    )

    today = date.today()
    current_period = date(today.year, today.month, 1)
    rp_one = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor_id,
            RentPayment.period_month == current_period,
        )
    )
    rp_row = rp_one.scalar_one_or_none()
    rent_paid = rp_row is not None and rp_row.status == "paid"
    monthly = vendor.monthly_rent or Decimal("0.00")
    rb_disp = _display_rent_balance_for_admin_list(rb_ledger, monthly, rent_paid)

    vendor.sales_balance = sb
    vendor.rent_balance = rb_disp
    vendor.current_balance = (sb + rb_disp).quantize(Decimal("0.01"), ROUND_HALF_UP)

    return vendor

@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    vendor_update: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_vendors")),
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

@router.patch("/me/assistant-name")
async def update_assistant_name(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    import re
    name = (body.get("assistant_name") or "").strip()
    if not name:
        current_user.assistant_name = None
    else:
        if len(name) > 50:
            raise HTTPException(status_code=400, detail="Name must be 50 characters or less")
        if not re.match(r"^[a-zA-Z0-9 '\-\.!]+$", name):
            raise HTTPException(status_code=400, detail="Name can only contain letters, numbers, spaces, and basic punctuation")
        current_user.assistant_name = name
    await db.commit()
    return {"assistant_name": current_user.assistant_name}


@router.patch("/me/assistant-settings")
async def update_assistant_settings(
    body: AssistantSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    import re

    if body.assistant_name is not None:
        name = body.assistant_name.strip()
        if not name:
            current_user.assistant_name = None
        else:
            if len(name) > 50:
                raise HTTPException(status_code=400, detail="Name must be 50 characters or less")
            if not re.match(r"^[a-zA-Z0-9 '\\-\\.!]+$", name):
                raise HTTPException(status_code=400, detail="Name can only contain letters, numbers, spaces, and basic punctuation")
            current_user.assistant_name = name

    if body.assistant_enabled is not None:
        current_user.assistant_enabled = bool(body.assistant_enabled)

    await db.commit()
    return {
        "assistant_name": current_user.assistant_name,
        "assistant_enabled": getattr(current_user, "assistant_enabled", True),
    }

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

    pdf_size = body.get("pdf_label_size")
    if pdf_size is not None:
        from app.services.labels import LABEL_SIZES
        if pdf_size not in LABEL_SIZES:
            raise HTTPException(status_code=400, detail=f"Invalid label size. Options: {', '.join(LABEL_SIZES.keys())}")
        current_user.pdf_label_size = pdf_size

    await db.commit()
    return {
        "label_preference": current_user.label_preference,
        "pdf_label_size": current_user.pdf_label_size,
    }


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


@router.post("/{vendor_id}/archive")
async def archive_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    from app.models.item import Item
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor.status = "archived"
    vendor.is_active = False

    items_result = await db.execute(
        select(Item).where(Item.vendor_id == vendor_id, Item.status == "active")
    )
    items = items_result.scalars().all()
    items_deactivated = 0
    for item in items:
        item.status = "inactive"
        item.is_online = False
        items_deactivated += 1

    await db.commit()
    return {
        "detail": f"Vendor archived. {items_deactivated} item(s) deactivated.",
        "items_deactivated": items_deactivated,
    }


@router.post("/{vendor_id}/unarchive")
async def unarchive_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor.status = "active"
    vendor.is_active = True
    await db.commit()
    return {"detail": "Vendor restored to active. Items remain inactive — re-enable them as needed."}


@router.get("/{vendor_id}/balance", response_model=VendorBalanceResponse)
async def get_vendor_balance(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user)
):
    if current_user.id == vendor_id:
        pass
    elif current_user.role == "admin":
        pass
    elif (
        current_user.role == "cashier"
        and (
            await role_feature_allowed(db, current_user, "role_balance_adjustments")
            or await role_allows_manage_vendors(db, current_user)
        )
    ):
        pass
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(select(VendorBalance).where(VendorBalance.vendor_id == vendor_id))
    balance = result.scalar_one_or_none()
    if not balance:
        balance = VendorBalance(vendor_id=vendor_id)
        db.add(balance)
        await db.commit()
        await db.refresh(balance)
    return {
        "vendor_id": balance.vendor_id,
        "balance": balance.balance if balance.balance is not None else Decimal("0.00"),
        "rent_balance": balance.rent_balance if balance.rent_balance is not None else Decimal("0.00"),
        "combined_balance": (
            (balance.balance if balance.balance is not None else Decimal("0.00"))
            + (balance.rent_balance if balance.rent_balance is not None else Decimal("0.00"))
        ),
    }


@router.post("/{vendor_id}/balance/adjust", response_model=BalanceAdjustmentResponse)
async def adjust_vendor_balance(
    vendor_id: int,
    data: BalanceAdjustRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role == "admin":
        pass
    elif current_user.role != "cashier":
        raise HTTPException(status_code=403, detail="Not authorized")
    elif not await role_feature_allowed(db, current_user, "role_balance_adjustments"):
        raise HTTPException(
            status_code=403,
            detail="Balance adjustments are disabled for your role in Settings → User Roles.",
        )

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
    if current_user.id == vendor_id:
        pass
    elif current_user.role == "admin":
        pass
    elif current_user.role == "cashier" and (
        await role_feature_allowed(db, current_user, "role_balance_adjustments")
        or await role_feature_allowed(db, current_user, "role_manage_vendors")
    ):
        pass
    else:
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
