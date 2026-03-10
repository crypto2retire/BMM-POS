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

class VendorResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    booth_number: Optional[str]
    role: str
    is_active: bool
    is_vendor: bool = False
    monthly_rent: Decimal
    commission_rate: Decimal
    created_at: datetime

    class Config:
        from_attributes = True

class VendorBalanceResponse(BaseModel):
    vendor_id: int
    balance: Decimal
    total_sales: Decimal
    total_commission: Decimal
    total_payouts: Decimal

    class Config:
        from_attributes = True
