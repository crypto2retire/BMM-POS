from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cashier_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vendors.id"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0550"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    cash_tendered: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    change_given: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    card_transaction_id: Mapped[Optional[str]] = mapped_column(String(255))
    gift_card_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    gift_card_barcode: Mapped[Optional[str]] = mapped_column(String(100))
    receipt_email: Mapped[Optional[str]] = mapped_column(String(255))
    is_voided: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voided_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    voided_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    cashier: Mapped[Optional["Vendor"]] = relationship("Vendor", foreign_keys=[cashier_id])
    voided_by_user: Mapped[Optional["Vendor"]] = relationship("Vendor", foreign_keys=[voided_by])
    items: Mapped[List["SaleItem"]] = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(Integer, ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), nullable=False)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_consignment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consignment_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    consignment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    sale: Mapped["Sale"] = relationship("Sale", back_populates="items")
    item: Mapped["Item"] = relationship("Item")
    vendor: Mapped["Vendor"] = relationship("Vendor", foreign_keys=[vendor_id])
