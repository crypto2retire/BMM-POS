from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    booth_number: Mapped[Optional[str]] = mapped_column(String(20))
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    rent_due_day: Mapped[int] = mapped_column(Integer, nullable=False, default=27)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="vendor")
    payout_method: Mapped[Optional[str]] = mapped_column(String(20), default="zelle")
    zelle_handle: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    rent_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    balance: Mapped[Optional["VendorBalance"]] = relationship("VendorBalance", back_populates="vendor", uselist=False)
    items: Mapped[list["Item"]] = relationship("Item", back_populates="vendor")


class VendorBalance(Base):
    __tablename__ = "vendor_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), unique=True, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    last_updated: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="balance")
