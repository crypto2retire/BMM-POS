from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, model_validator


class ItemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Decimal
    quantity: int = 1
    photo_urls: Optional[List[str]] = None
    is_online: bool = False
    is_tax_exempt: bool = False
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    barcode: Optional[str] = None
    vendor_id: Optional[int] = None
    label_style: str = "standard"


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[Decimal] = None
    quantity: Optional[int] = None
    photo_urls: Optional[List[str]] = None
    is_online: Optional[bool] = None
    is_tax_exempt: Optional[bool] = None
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    status: Optional[str] = None
    label_style: Optional[str] = None


class ItemResponse(BaseModel):
    id: int
    vendor_id: int
    sku: str
    barcode: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Decimal
    quantity: int
    photo_urls: Optional[List[str]] = None
    is_online: bool
    is_tax_exempt: bool
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    status: str
    label_style: str = "standard"
    image_path: Optional[str] = None
    created_at: datetime
    active_price: Optional[Decimal] = None
    booth_number: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_active_price(self) -> "ItemResponse":
        today = date.today()
        if (
            self.sale_price is not None
            and self.sale_start is not None
            and self.sale_end is not None
            and self.sale_start <= today <= self.sale_end
        ):
            self.active_price = self.sale_price
        else:
            self.active_price = self.price
        return self
