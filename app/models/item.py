from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Date, ARRAY, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    barcode: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    photo_urls: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    sale_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sale_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
    label_style: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_consignment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consignment_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)

    vendor = relationship("Vendor", back_populates="items")
    sale_items = relationship("SaleItem", back_populates="item")

    @property
    def effective_price(self) -> Decimal:
        return self.sale_price if self.sale_price else self.price
