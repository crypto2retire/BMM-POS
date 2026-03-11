from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    booth_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("200.00"))
    rent_due_day: Mapped[int] = mapped_column(Integer, default=1)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="vendor")
    payout_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zelle_handle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
    rent_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.10"))

    items = relationship("Item", back_populates="vendor")
    sales = relationship("Sale", back_populates="cashier", foreign_keys="[Sale.cashier_id]")
    rent_payments = relationship("RentPayment", back_populates="vendor")
    payouts = relationship("Payout", back_populates="vendor")

class VendorBalance(Base):
    __tablename__ = "vendor_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"))
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")
