from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel


class CartItem(BaseModel):
    barcode: str
    quantity: int = 1


class SaleCreate(BaseModel):
    items: List[CartItem]
    payment_method: str
    cash_tendered: Optional[Decimal] = None
    card_transaction_id: Optional[str] = None
    receipt_email: Optional[str] = None


class SaleItemResponse(BaseModel):
    id: int
    item_id: int
    vendor_id: int
    item_name: str
    booth_number: Optional[str] = None
    sku: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class SaleResponse(BaseModel):
    id: int
    cashier_id: Optional[int] = None
    cashier_name: Optional[str] = None
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    payment_method: str
    cash_tendered: Optional[Decimal] = None
    change_given: Optional[Decimal] = None
    card_transaction_id: Optional[str] = None
    receipt_email: Optional[str] = None
    created_at: datetime
    line_items: List[SaleItemResponse] = []

    model_config = {"from_attributes": True}


class PoyntChargeRequest(BaseModel):
    amount: float
    sale_reference: str


class PoyntChargeResponse(BaseModel):
    success: bool
    reference_id: str
    message: str


class PoyntStatusResponse(BaseModel):
    status: str
    poynt_transaction_id: Optional[str] = None
