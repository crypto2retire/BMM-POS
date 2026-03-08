from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.vendor import Vendor
from app.schemas.vendor import VendorCreate, VendorUpdate, VendorResponse
from app.routers.auth import get_current_user, require_admin, require_cashier_or_admin, hash_password

router = APIRouter(prefix="/vendors", tags=["vendors"])


def vendor_to_response(vendor: Vendor) -> VendorResponse:
    balance = None
    if vendor.balance:
        balance = vendor.balance.balance
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        email=vendor.email,
        phone=vendor.phone,
        booth_number=vendor.booth_number,
        monthly_rent=vendor.monthly_rent,
        rent_due_day=vendor.rent_due_day,
        role=vendor.role,
        payout_method=vendor.payout_method,
        zelle_handle=vendor.zelle_handle,
        status=vendor.status,
        rent_flagged=vendor.rent_flagged,
        created_at=vendor.created_at,
        current_balance=balance,
    )


@router.get("/", response_model=List[VendorResponse])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_cashier_or_admin),
):
    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.balance))
    )
    vendors = result.scalars().all()
    return [vendor_to_response(v) for v in vendors]


@router.post("/", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    data: VendorCreate,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_admin),
):
    existing = await db.execute(select(Vendor).where(Vendor.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    vendor = Vendor(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        phone=data.phone,
        booth_number=data.booth_number,
        monthly_rent=data.monthly_rent,
        rent_due_day=data.rent_due_day,
        role=data.role,
        payout_method=data.payout_method,
        zelle_handle=data.zelle_handle,
    )
    db.add(vendor)
    await db.commit()

    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.balance)).where(Vendor.id == vendor.id)
    )
    vendor = result.scalar_one()
    return vendor_to_response(vendor)


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.balance)).where(Vendor.id == vendor_id)
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor_to_response(vendor)


@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    data: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.balance)).where(Vendor.id == vendor_id)
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    restricted_fields = {"role", "status", "monthly_rent", "rent_due_day", "booth_number"}

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if current_user.role != "admin" and field in restricted_fields:
            continue
        if field == "password":
            vendor.password_hash = hash_password(value)
        else:
            setattr(vendor, field, value)

    await db.commit()
    await db.refresh(vendor)

    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.balance)).where(Vendor.id == vendor_id)
    )
    vendor = result.scalar_one()
    return vendor_to_response(vendor)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_admin),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    vendor.status = "suspended"
    await db.commit()
