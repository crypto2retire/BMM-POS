from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class GiftCard(Base):
    __tablename__ = "gift_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    transactions: Mapped[List["GiftCardTransaction"]] = relationship(
        "GiftCardTransaction", back_populates="gift_card", cascade="all, delete-orphan",
        order_by="GiftCardTransaction.created_at.desc()"
    )


class GiftCardTransaction(Base):
    __tablename__ = "gift_card_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gift_card_id: Mapped[int] = mapped_column(Integer, ForeignKey("gift_cards.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sale_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sales.id"), nullable=True)
    cashier_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=True)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)

    gift_card: Mapped["GiftCard"] = relationship("GiftCard", back_populates="transactions")
    cashier: Mapped[Optional["Vendor"]] = relationship("Vendor", foreign_keys=[cashier_id])
