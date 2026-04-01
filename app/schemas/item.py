from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, model_validator

class ItemCreate(BaseModel):
    vendor_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: Decimal
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    quantity: int = 1
    category: Optional[str] = None
    barcode: Optional[str] = None
    photo_urls: Optional[List[str]] = None
    is_online: Optional[bool] = False
    is_tax_exempt: Optional[bool] = False
    is_consignment: Optional[bool] = False
    consignment_rate: Optional[Decimal] = None
    label_style: Optional[str] = "standard"

    @model_validator(mode='after')
    def check_sale_price(self):
        if self.sale_price is not None and self.sale_price >= self.price:
            raise ValueError('sale_price must be less than price')
        if self.is_consignment and self.consignment_rate is None:
            raise ValueError('consignment_rate is required when is_consignment is true')
        if self.consignment_rate is not None:
            if self.consignment_rate < Decimal('0') or self.consignment_rate > Decimal('1'):
                raise ValueError('consignment_rate must be between 0 and 1')
        if not self.is_consignment:
            self.consignment_rate = None
        return self

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    quantity: Optional[int] = None
    category: Optional[str] = None
    status: Optional[str] = None
    is_online: Optional[bool] = None
    is_tax_exempt: Optional[bool] = None
    is_consignment: Optional[bool] = None
    consignment_rate: Optional[Decimal] = None
    label_style: Optional[str] = None

class ItemResponse(BaseModel):
    id: int
    vendor_id: int
    sku: str
    barcode: Optional[str] = None
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Decimal
    quantity: int
    photo_urls: Optional[List[str]] = None
    is_online: Optional[bool] = False
    is_tax_exempt: Optional[bool] = False
    is_consignment: Optional[bool] = False
    consignment_rate: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    status: Optional[str] = "active"
    label_style: Optional[str] = "standard"
    image_path: Optional[str] = None
    created_at: datetime
    booth_number: Optional[str] = None
    label_printed: Optional[bool] = False
    verified_at: Optional[datetime] = None
    archive_expires_at: Optional[datetime] = None
    import_source: Optional[str] = None

    class Config:
        from_attributes = True

class ItemSearchResult(BaseModel):
    id: int
    vendor_id: int
    sku: str
    name: str
    price: Decimal
    sale_price: Optional[Decimal] = None
    quantity: int
    category: Optional[str] = None
    booth_number: Optional[str] = None
    vendor_name: Optional[str] = None
    photo_url: Optional[str] = None
    image_path: Optional[str] = None

class BarcodeResponse(BaseModel):
    item: ItemResponse
    vendor_name: str
    vendor_booth: Optional[str] = None
