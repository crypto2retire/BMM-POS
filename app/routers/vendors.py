from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.schemas.vendor import VendorCreate, VendorUpdate, VendorResponse, VendorBalanceResponse
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
