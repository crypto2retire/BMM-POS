from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ItemVariant(Base):
    """A specific combination of variable values, with its own price/qty/barcode/photo."""
    __tablename__ = "item_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    variable_1_value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    variable_2_value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)

    item = relationship("Item", back_populates="variants")

    __table_args__ = (
        UniqueConstraint("item_id", "variable_1_value", "variable_2_value", name="uq_item_variant_values"),
    )
