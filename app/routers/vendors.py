from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance, BalanceAdjustment
from app.models.rent import RentPayment
from app.models.sale import SaleItem, Sale
from app.schemas.vendor import (
    VendorCreate, VendorUpdate, VendorResponse, VendorBalanceResponse,
    BalanceAdjustRequest, BalanceAdjustmentResponse,
)
from app.routers.auth import (
    MIN_PASSWORD_LENGTH,
    _validate_password_strength,
    bump_auth_version,
    get_current_user,
    require_role,
    get_password_hash,
)
from app.routers.settings import role_allows_manage_vendors, role_feature_allowed, require_staff_feature
from app.services.audit import log_audit

router = APIRouter(prefix="/vendors", tags=["vendors"])


class AssistantSettingsUpdate(BaseModel):
    assistant_name: Optional[str] = None
    assistant_enabled: Optional[bool] = None


import re as _re

_VENDOR_NAME_RE = _re.compile(r"^[a-zA-Z0-9 '&\-\.!]{1,120}$")


def _validate_vendor_name(name: str) -> str:
    """Validate and sanitize vendor name. Returns error message or empty string."""
    if not name or not name.strip():
        return "Vendor name is required"
    name = name.strip()
    if len(name) > 120:
        return "Vendor name must be 120 characters or less"
    if not _VENDOR_NAME_RE.match(name):
        return "Vendor name can only contain letters, numbers, spaces, and basic punctuation (& ' - . !)"
    return ""


def _normalize_vendor_account_payload(data: dict) -> dict:
    role = data.get("role")
    if role == "vendor":
        data["is_vendor"] = True
        return data

    if role in ("admin", "cashier"):
        data["is_vendor"] = False
        data["booth_number"] = None
        data["monthly_rent"] = Decimal("0.00")
        data["zelle_handle"] = None
        return data

    return data


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


def _hydrate_vendor_balance_fields(
    vendor: Vendor,
    sales_balance: Decimal,
    rent_ledger: Decimal,
    current_month_rent_paid: bool,
    current_month_sales: Decimal = None,
):
    """Populate the display fields: total_sales, rent_due, net_payout.

    Business rules:
    - total_sales = current month sales from sale_items (what vendor earned this month)
    - rent_due = Vendor.monthly_rent + landing_page_fee
    - net_payout = what the vendor will actually receive:
      * If rent already paid this month: full sales_balance
      * If vendor has prepaid rent credit (rent_ledger > 0): full sales_balance
      * Otherwise: sales_balance - rent_due (capped at $0)
    - carry_over = VendorBalance.rent_balance (positive = prepaid credit)
    - sales_balance is the running VendorBalance.balance (used for net_payout calc)
    """
    monthly = vendor.monthly_rent or Decimal("0.00")
    landing_fee = vendor.landing_page_fee or Decimal("0.00")
    effective_rent = monthly + landing_fee
    sb = sales_balance if sales_balance is not None else Decimal("0.00")
    rl = rent_ledger if rent_ledger is not None else Decimal("0.00")

    # Show current month sales to the vendor, not lifetime balance
    if current_month_sales is not None:
        vendor.total_sales = current_month_sales.quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        vendor.total_sales = sb.quantize(Decimal("0.01"), ROUND_HALF_UP)
    vendor.rent_due = effective_rent.quantize(Decimal("0.01"), ROUND_HALF_UP)
    vendor.carry_over = rl.quantize(Decimal("0.01"), ROUND_HALF_UP)
    vendor.rent_paid_this_month = current_month_rent_paid

    if effective_rent > 0 and not current_month_rent_paid and rl <= 0:
        # Rent is due and no prepaid credit — deduct rent from payout
        vendor.net_payout = max(Decimal("0.00"), sb - effective_rent).quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        # Rent already paid or vendor has prepaid credit — full payout
        vendor.net_payout = sb.quantize(Decimal("0.01"), ROUND_HALF_UP)


@router.get("/", response_model=List[VendorResponse])
async def list_vendors(
    search: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if not await _can_access_vendor_directory(db, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to list vendors")
    query = select(Vendor).order_by(Vendor.name).limit(limit)
    if search:
        term = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Vendor.name).like(term),
                func.lower(Vendor.email).like(term),
                func.lower(Vendor.phone).like(term),
                func.lower(Vendor.booth_number).like(term),
            )
        )
    result = await db.execute(query)
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

    # Fetch current month sales per vendor (for display)
    month_sales_result = await db.execute(
        select(
            SaleItem.vendor_id,
            func.COALESCE(func.SUM(
                SaleItem.line_total - func.COALESCE(SaleItem.consignment_amount, 0)
            ), 0)
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.is_voided == False,
            Sale.created_at >= current_period,
            Sale.created_at < date(today.year, today.month + 1, 1) if today.month < 12
                else date(today.year + 1, 1, 1),
        )
        .group_by(SaleItem.vendor_id)
    )
    month_sales_map = {}
    for row in month_sales_result.all():
        month_sales_map[row[0]] = Decimal(str(row[1]))

    for v in vendors:
        sb = balance_map.get(v.id, Decimal("0.00"))
        rb_ledger = rent_balance_map.get(v.id, Decimal("0.00"))
        rent_paid = v.id in paid_rent_vendor_ids
        ms = month_sales_map.get(v.id, Decimal("0.00"))
        _hydrate_vendor_balance_fields(v, sb, rb_ledger, rent_paid, current_month_sales=ms)

    # Fetch all landing page data in one query
    from app.models.booth_showcase import BoothShowcase
    lp_result = await db.execute(
        select(BoothShowcase.vendor_id, BoothShowcase.landing_page_enabled, BoothShowcase.landing_slug)
    )
    lp_map = {row.vendor_id: row for row in lp_result.all()}

    for v in vendors:
        lp = lp_map.get(v.id)
        v.landing_page_enabled = lp.landing_page_enabled if lp else False
        v.landing_slug = lp.landing_slug if lp else None

    return vendors

@router.post("/", response_model=VendorResponse, status_code=201)
async def create_vendor(
    request: Request,
    vendor: VendorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    name_error = _validate_vendor_name(vendor.name)
    if name_error:
        raise HTTPException(status_code=400, detail=name_error)

    existing = await db.execute(select(Vendor).where(Vendor.email == vendor.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    normalized = _normalize_vendor_account_payload(vendor.model_dump())

    db_vendor = Vendor(
        name=normalized["name"],
        email=normalized["email"],
        phone=normalized.get("phone"),
        password_hash=get_password_hash(vendor.password),
        booth_number=normalized.get("booth_number"),
        role=normalized["role"],
        is_vendor=normalized.get("is_vendor", False),
        monthly_rent=normalized.get("monthly_rent", Decimal("0.00")),
        commission_rate=normalized.get("commission_rate", Decimal("0")),
        consignment_rate=normalized.get("consignment_rate", Decimal("0.0000")),
        payout_method=normalized.get("payout_method"),
        zelle_handle=normalized.get("zelle_handle"),
        auto_payout_enabled=normalized.get("auto_payout_enabled", True),
        security_deposit_amount=normalized.get("security_deposit_amount", Decimal("0.00")),
    )
    db.add(db_vendor)
    await db.commit()
    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="create_vendor",
        entity_type="vendor",
        entity_id=str(db_vendor.id),
        details=f"Email: {db_vendor.email}, Role: {db_vendor.role}",
        request=request,
    )
    await db.refresh(db_vendor)
    return db_vendor

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
        select(VendorBalance).where(VendorBalance.vendor_id == vendor_id).limit(1)
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
    rp_result = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor_id,
            RentPayment.period_month == current_period,
            RentPayment.status == "paid",
        ).limit(1)
    )
    rp_row = rp_result.first()
    rent_paid = rp_row is not None

    # Current month sales for display
    next_month = date(today.year, today.month + 1, 1) if today.month < 12 else date(today.year + 1, 1, 1)
    ms_result = await db.execute(
        select(
            func.COALESCE(func.SUM(
                SaleItem.line_total - func.COALESCE(SaleItem.consignment_amount, 0)
            ), 0)
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.is_voided == False,
            SaleItem.vendor_id == vendor_id,
            Sale.created_at >= current_period,
            Sale.created_at < next_month,
        )
    )
    ms_row = ms_result.one()
    current_month_sales = Decimal(str(ms_row[0]))

    _hydrate_vendor_balance_fields(vendor, sb, rb_ledger, rent_paid, current_month_sales=current_month_sales)

    # Attach landing page data
    from app.models.booth_showcase import BoothShowcase
    lp_result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor_id).limit(1)
    )
    lp = lp_result.scalar_one_or_none()
    vendor.landing_page_enabled = lp.landing_page_enabled if lp else False
    vendor.landing_slug = lp.landing_slug if lp else None

    return vendor

@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    request: Request,
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

    # Validate name if being updated
    if "name" in update_data:
        name_error = _validate_vendor_name(update_data["name"])
        if name_error:
            raise HTTPException(status_code=400, detail=name_error)

    update_data = _normalize_vendor_account_payload(update_data)
    for key, value in update_data.items():
        setattr(vendor, key, value)

    await db.commit()
    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="update_vendor",
        entity_type="vendor",
        entity_id=str(vendor_id),
        request=request,
    )
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

@router.post("/{vendor_id}/reset-password")
async def reset_vendor_password(
    request: Request,
    vendor_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_vendors"))
):
    new_password = body.get("new_password")
    if not new_password:
        raise HTTPException(status_code=400, detail="Password is required")
    pw_err = _validate_password_strength(new_password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if current_user.role != "admin" and vendor.role != "vendor":
        raise HTTPException(
            status_code=403,
            detail="Cashiers can only reset vendor passwords.",
        )

    vendor.password_hash = get_password_hash(new_password)
    vendor.password_changed = True
    bump_auth_version(vendor)
    await db.commit()
    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="reset_password",
        entity_type="vendor",
        entity_id=str(vendor_id),
        details=f"Password reset for vendor {vendor.email}",
        request=request,
    )
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
    if not new_password:
        raise HTTPException(status_code=400, detail="New password is required")
    pw_err = _validate_password_strength(new_password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)
    if not bcrypt.checkpw(current_password.encode('utf-8'), current_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = get_password_hash(new_password)
    current_user.password_changed = True
    bump_auth_version(current_user)
    await db.commit()
    return {"detail": "Password changed successfully"}

@router.delete("/{vendor_id}")
async def delete_vendor(
    request: Request,
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
    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="deactivate_vendor",
        entity_type="vendor",
        entity_id=str(vendor_id),
        details=f"Deactivated vendor {vendor.email}",
        request=request,
    )
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

    result = await db.execute(select(VendorBalance).where(VendorBalance.vendor_id == vendor_id).limit(1))
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
    request: Request,
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
        .limit(1)
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
            .limit(1)
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
    balance_row.last_updated = datetime.now(timezone.utc)

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

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="balance_adjustment",
        entity_type="vendor_balance",
        entity_id=str(vendor_id),
        details=f"{data.adjustment_type} ${float(adj_amount):.2f} — reason: {data.reason} — balance {float(balance_before):.2f} → {float(balance_after):.2f}",
        request=request,
    )

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
