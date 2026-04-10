from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Integer, String, Text, Numeric, ForeignKey, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SecurityDepositLog(Base):
    __tablename__ = "security_deposit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # received, deduction, refund, applied_to_rent
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    performed_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()", nullable=False
    )

    vendor: Mapped["Vendor"] = relationship(  # noqa: F821
        "Vendor", foreign_keys=[vendor_id]
    )
    admin: Mapped["Vendor"] = relationship(  # noqa: F821
        "Vendor", foreign_keys=[performed_by]
    )
