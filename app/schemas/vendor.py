from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


class VendorCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    monthly_rent: Decimal = Decimal("0")
    role: str = "vendor"
    payout_method: str = "zelle"
    zelle_handle: Optional[str] = None
    rent_due_day: int = 27

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    monthly_rent: Optional[Decimal] = None
    rent_due_day: Optional[int] = None
    role: Optional[str] = None
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class VendorResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    monthly_rent: Decimal
    rent_due_day: int
    role: str
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None
    status: str
    rent_flagged: bool = False
    created_at: datetime
    current_balance: Optional[Decimal] = None
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str
