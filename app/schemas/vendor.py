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
    notes: Optional[str] = None

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
    label_preference: Optional[str] = None
    notes: Optional[str] = None

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
    label_preference: Optional[str] = "standard"
    pdf_label_size: Optional[str] = "2.25x1.25"
    assistant_name: Optional[str] = None
    notes: Optional[str] = None
    theme_preference: Optional[str] = "dark"
    font_size_preference: Optional[str] = "medium"
    created_at: datetime
    current_balance: Optional[Decimal] = Decimal("0.00")

    class Config:
        from_attributes = True

class VendorBalanceResponse(BaseModel):
    vendor_id: int
    balance: Decimal

    class Config:
        from_attributes = True


class BalanceAdjustRequest(BaseModel):
    amount: Decimal
    adjustment_type: str
    reason: str

    @field_validator('adjustment_type')
    @classmethod
    def validate_type(cls, v):
        if v not in ('credit', 'debit'):
            raise ValueError('adjustment_type must be credit or debit')
        return v

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('amount must be greater than 0')
        if v > Decimal("99999999.99"):
            raise ValueError('amount exceeds maximum allowed')
        return v

    @field_validator('reason')
    @classmethod
    def validate_reason(cls, v):
        if not v or not v.strip():
            raise ValueError('reason is required')
        return v.strip()


class BalanceAdjustmentResponse(BaseModel):
    id: int
    vendor_id: int
    adjusted_by: int
    admin_name: Optional[str] = None
    amount: Decimal
    adjustment_type: str
    reason: str
    balance_before: Decimal
    balance_after: Decimal
    created_at: datetime

    class Config:
        from_attributes = True
