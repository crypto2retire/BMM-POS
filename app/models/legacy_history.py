from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, Numeric, Integer, TIMESTAMP, ForeignKey, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LegacyFinancialHistory(Base):
    __tablename__ = "legacy_financial_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False, default="ricochet")
    reference_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="summary")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    period_month: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    import_batch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )

    vendor: Mapped["Vendor"] = relationship("Vendor")
