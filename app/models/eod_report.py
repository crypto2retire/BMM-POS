from sqlalchemy import Column, Integer, String, Numeric, DateTime, Date, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class EodReport(Base):
    __tablename__ = "eod_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(Date, nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    submitted_by_name = Column(String(200), nullable=True)

    starting_balance = Column(Numeric(10, 2), nullable=False)
    counted_cash = Column(Numeric(10, 2), nullable=False)
    expected_cash = Column(Numeric(10, 2), nullable=False)
    variance = Column(Numeric(10, 2), nullable=False)
    deposit = Column(Numeric(10, 2), nullable=False)

    total_revenue = Column(Numeric(10, 2), nullable=False, default=0)
    total_tax = Column(Numeric(10, 2), nullable=False, default=0)
    total_transactions = Column(Integer, nullable=False, default=0)
    items_sold = Column(Integer, nullable=False, default=0)

    cash_total = Column(Numeric(10, 2), nullable=False, default=0)
    cash_count = Column(Integer, nullable=False, default=0)
    card_total = Column(Numeric(10, 2), nullable=False, default=0)
    card_count = Column(Integer, nullable=False, default=0)
    gift_card_total = Column(Numeric(10, 2), nullable=False, default=0)
    gift_card_count = Column(Integer, nullable=False, default=0)

    voided_count = Column(Integer, nullable=False, default=0)
    voided_total = Column(Numeric(10, 2), nullable=False, default=0)

    cashier_breakdown = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    # Bill/coin counts from POS drawer count (e.g. {"100": 1, "0.01": 50})
    denomination_counts = Column(JSON, nullable=True)

    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
