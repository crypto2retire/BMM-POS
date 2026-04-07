from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


class ClassRegistrationCreate(BaseModel):
    class_id: int
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    num_spots: int = 1
    notes: Optional[str] = None

    @field_validator("customer_name")
    @classmethod
    def validate_customer_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 1 or len(value) > 200:
            raise ValueError("Name must be 1-200 characters")
        return value

    @field_validator("customer_phone")
    @classmethod
    def validate_customer_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 30:
            raise ValueError("Phone number must be 30 characters or fewer")
        return value

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 2000:
            raise ValueError("Notes must be 2000 characters or fewer")
        return value


class ClassRegistrationResponse(BaseModel):
    id: int
    class_id: int
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    num_spots: int
    notes: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
