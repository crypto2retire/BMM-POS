from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class ClassRegistrationCreate(BaseModel):
    class_id: int
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    num_spots: int = 1
    notes: Optional[str] = None


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
