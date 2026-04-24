from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Text, text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("idx_vendors_status", "status"),
        Index("idx_vendors_role", "role"),
        Index("idx_vendors_booth", "booth_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    booth_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    landing_page_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), server_default=text("0.00"))
    rent_due_day: Mapped[int] = mapped_column(Integer, default=1)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="vendor")
    payout_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="check")
    auto_payout_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=text("true"))
    zelle_handle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
    rent_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    password_changed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    consignment_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0000"), server_default="0.0000")
    label_preference: Mapped[str] = mapped_column(String(20), default="dymo", nullable=False)
    pdf_label_size: Mapped[str] = mapped_column(String(30), default="2.25x1.25", nullable=False)
    assistant_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    assistant_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=text("true"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    theme_preference: Mapped[str] = mapped_column(String(10), default="dark", nullable=False, server_default="dark")
    font_size_preference: Mapped[str] = mapped_column(String(10), default="medium", nullable=False, server_default="medium")
    sale_notify_preference: Mapped[str] = mapped_column(String(10), default="instant", nullable=False, server_default="instant")
    security_deposit_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False, server_default="0.00")
    security_deposit_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False, server_default="0.00")

    items = relationship("Item", back_populates="vendor")
    sales = relationship("Sale", back_populates="cashier", foreign_keys="[Sale.cashier_id]")
    rent_payments = relationship("RentPayment", back_populates="vendor")
    payouts = relationship("Payout", back_populates="vendor")

class VendorBalance(Base):
    __tablename__ = "vendor_balances"
    __table_args__ = (
        Index("idx_vb_vendor", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"))
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))  # sales balance
    rent_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))  # prepaid rent credit (negative = owes rent)
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")


class BalanceAdjustment(Base):
    __tablename__ = "balance_adjustments"
    __table_args__ = (
        Index("idx_ba_vendor", "vendor_id"),
        Index("idx_ba_admin", "adjusted_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    adjusted_by: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)

    vendor: Mapped["Vendor"] = relationship("Vendor", foreign_keys=[vendor_id])
    admin: Mapped["Vendor"] = relationship("Vendor", foreign_keys=[adjusted_by])
