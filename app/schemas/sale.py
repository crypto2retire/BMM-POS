from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel


class CartItem(BaseModel):
    barcode: str
    quantity: int = 1
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None


class SaleCreate(BaseModel):
    items: List[CartItem]
    payment_method: str
    cash_tendered: Optional[Decimal] = None
    card_transaction_id: Optional[str] = None
    external_payment_reference: Optional[str] = None
    receipt_email: Optional[str] = None
    gift_card_barcode: Optional[str] = None
    gift_card_amount: Optional[Decimal] = None
    cart_discount_type: Optional[str] = None
    cart_discount_value: Optional[float] = None


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
    is_consignment: bool = False
    consignment_rate: Optional[Decimal] = None
    consignment_amount: Optional[Decimal] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    unit_cost: Optional[Decimal] = None

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
    external_payment_reference: Optional[str] = None
    gift_card_amount: Optional[Decimal] = None
    gift_card_barcode: Optional[str] = None
    receipt_email: Optional[str] = None
    is_voided: bool = False
    voided_at: Optional[datetime] = None
    voided_by: Optional[int] = None
    voided_by_name: Optional[str] = None
    void_reason: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    created_at: datetime
    created_at_display: Optional[str] = None
    line_items: List[SaleItemResponse] = []

    model_config = {"from_attributes": True}


class VendorSoldItemSummary(BaseModel):
    item_id: int
    item_name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    quantity_on_hand: int = 0
    qty_sold: int
    gross_sales: Decimal
    sale_count: int
    last_sold_at: Optional[datetime] = None
    last_sold_at_display: Optional[str] = None
    image_path: Optional[str] = None
    total_cost: Optional[Decimal] = None
    profit: Optional[Decimal] = None


class VendorSoldItemsResponse(BaseModel):
    period: str
    period_label: str
    total_items: int
    items: List[VendorSoldItemSummary]


class VoidSaleRequest(BaseModel):
    reason: Optional[str] = None


class PoyntChargeRequest(BaseModel):
    amount: float
    sale_reference: str = ""


class PoyntChargeResponse(BaseModel):
    success: bool = True
    reference_id: str
    message: str = "Payment sent to terminal"


class PoyntStatusResponse(BaseModel):
    status: str
    poynt_transaction_id: Optional[str] = None
    amount_cents: Optional[int] = None
