import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, Numeric, Integer, TIMESTAMP, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("idx_reservations_item", "item_id"),
        Index("idx_reservations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=_new_uuid, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("items.id"), nullable=True)
    checkout_group_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(200))
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50))
    customer_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    square_payment_id: Mapped[Optional[str]] = mapped_column(String(200))
    amount_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    item: Mapped[Optional["Item"]] = relationship("Item")
