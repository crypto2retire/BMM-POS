from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Date, ARRAY, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    barcode: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    photo_urls: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_tax_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    sale_start: Mapped[Optional[date]] = mapped_column(Date)
    sale_end: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    label_style: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="items")
