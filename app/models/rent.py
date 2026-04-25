from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, TIMESTAMP, ForeignKey, Date, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class RentPayment(Base):
    __tablename__ = "rent_payments"
    __table_args__ = (
        Index("idx_rentpayments_vendor_period", "vendor_id", "period_month"),
        Index("idx_rentpayments_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="balance")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="paid")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reference_tag: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    square_payment_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )

    vendor: Mapped["Vendor"] = relationship("Vendor")
