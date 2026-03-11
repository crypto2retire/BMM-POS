from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator

class VendorCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    booth_number: Optional[str] = None
    role: str = "vendor"
    is_vendor: bool = False
    monthly_rent: Decimal = Decimal("200.00")
    commission_rate: Decimal = Decimal("0.10")
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v not in ('vendor', 'cashier', 'admin'):
            raise ValueError('role must be vendor, cashier, or admin')
        return v

class VendorUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_vendor: Optional[bool] = None
    monthly_rent: Optional[Decimal] = None
    commission_rate: Optional[Decimal] = None
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None
    status: Optional[str] = None
    rent_flagged: Optional[bool] = None

class VendorResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    role: str
    is_active: bool
    is_vendor: bool = False
    monthly_rent: Decimal
    commission_rate: Decimal
    status: Optional[str] = "active"
    rent_flagged: Optional[bool] = False
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class VendorBalanceResponse(BaseModel):
    vendor_id: int
    balance: Decimal

    class Config:
        from_attributes = True
