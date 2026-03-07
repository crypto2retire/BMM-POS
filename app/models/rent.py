from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, TIMESTAMP, ForeignKey, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class RentPayment(Base):
    __tablename__ = "rent_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="balance")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="paid")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )

    vendor: Mapped["Vendor"] = relationship("Vendor")
