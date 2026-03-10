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
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    booth_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="vendor")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("200.00"))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.10"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    items = relationship("Item", back_populates="vendor")
    sales = relationship("Sale", back_populates="cashier", foreign_keys="[Sale.cashier_id]")
    rent_payments = relationship("RentPayment", back_populates="vendor")
    payouts = relationship("Payout", back_populates="vendor")

class VendorBalance(Base):
    __tablename__ = "vendor_balances"

    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id"), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    total_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_payouts: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
