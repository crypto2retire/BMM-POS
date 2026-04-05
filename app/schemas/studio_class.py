from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel


class StudioClassCreate(BaseModel):
    title: str
    description: Optional[str] = None
    instructor: str
    class_date: date
    start_time: time
    end_time: time
    capacity: int = 20
    price: Decimal
    category: Optional[str] = None
    location: str = "Studio"
    is_published: bool = True
    image_url: Optional[str] = None


class StudioClassUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instructor: Optional[str] = None
    class_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    capacity: Optional[int] = None
    price: Optional[Decimal] = None
    category: Optional[str] = None
    location: Optional[str] = None
    is_published: Optional[bool] = None
    is_cancelled: Optional[bool] = None
    image_url: Optional[str] = None


class StudioClassResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    instructor: str
    class_date: date
    start_time: time
    end_time: time
    capacity: int
    enrolled: int
    price: Decimal
    category: Optional[str] = None
    location: str
    is_published: bool
    is_cancelled: bool
    image_url: Optional[str] = None
    created_at: datetime
    spots_left: int = 0

    model_config = {"from_attributes": True}
