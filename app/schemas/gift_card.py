from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel


class GiftCardActivate(BaseModel):
    barcode: str
    initial_balance: Decimal
    notes: Optional[str] = None


class GiftCardLoad(BaseModel):
    amount: Decimal
    notes: Optional[str] = None


class GiftCardRedeem(BaseModel):
    amount: Decimal


class GiftCardTransactionResponse(BaseModel):
    id: int
    amount: Decimal
    transaction_type: str
    sale_id: Optional[int] = None
    cashier_name: Optional[str] = None
    balance_after: Decimal
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GiftCardResponse(BaseModel):
    id: int
    barcode: str
    balance: Decimal
    is_active: bool
    notes: Optional[str] = None
    issued_at: datetime
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GiftCardDetailResponse(GiftCardResponse):
    transactions: List[GiftCardTransactionResponse] = []
