from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, TIMESTAMP, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PoyntPayment(Base):
    __tablename__ = "poynt_payments"
    __table_args__ = (
        Index("idx_poynt_status", "status"),
        Index("idx_poynt_sale_id", "sale_id"),
        Index("idx_poynt_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    poynt_transaction_id: Mapped[Optional[str]] = mapped_column(String(200))
    sale_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
