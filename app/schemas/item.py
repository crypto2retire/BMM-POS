from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, model_validator

class ItemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: Decimal
    sale_price: Optional[Decimal] = None
    quantity: int = 1
    category: Optional[str] = None
    booth_location: Optional[str] = None
    tags: Optional[List[str]] = None

    @model_validator(mode='after')
    def check_sale_price(self):
        if self.sale_price is not None and self.sale_price >= self.price:
            raise ValueError('sale_price must be less than price')
        return self

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    quantity: Optional[int] = None
    category: Optional[str] = None
    booth_location: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[str]] = None

class ItemResponse(BaseModel):
    id: int
    vendor_id: int
    sku: str
    name: str
    description: Optional[str]
    price: Decimal
    sale_price: Optional[Decimal]
    quantity: int
    category: Optional[str]
    booth_location: Optional[str]
    is_active: bool
    created_at: datetime
    photo_url: Optional[str] = None
    tags: Optional[List[str]] = None

    class Config:
        from_attributes = True

class ItemSearchResult(BaseModel):
    id: int
    vendor_id: int
    sku: str
    name: str
    price: Decimal
    sale_price: Optional[Decimal]
    quantity: int
    category: Optional[str]
    booth_location: Optional[str]
    vendor_name: Optional[str] = None
    photo_url: Optional[str] = None

class BarcodeResponse(BaseModel):
    item: ItemResponse
    vendor_name: str
    vendor_booth: Optional[str]
