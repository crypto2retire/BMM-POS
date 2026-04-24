from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, TIMESTAMP, ForeignKey, Date, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (
        Index("idx_payouts_vendor_period", "vendor_id", "period_month"),
        Index("idx_payouts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    gross_sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    rent_deducted: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    net_payout: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    payout_method: Mapped[Optional[str]] = mapped_column(String(20))
    zelle_handle: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    paid_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )

    vendor: Mapped["Vendor"] = relationship("Vendor")
