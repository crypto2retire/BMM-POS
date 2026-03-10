from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Date, ARRAY, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    booth_location: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True, default=list)

    vendor = relationship("Vendor", back_populates="items")
    sale_items = relationship("SaleItem", back_populates="item")

    @property
    def effective_price(self) -> Decimal:
        return self.sale_price if self.sale_price else self.price
