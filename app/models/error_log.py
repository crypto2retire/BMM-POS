from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ErrorLog(Base):
    __tablename__ = "error_logs"
    __table_args__ = (
        Index("idx_error_logs_status", "status"),
        Index("idx_error_logs_level", "level"),
        Index("idx_error_logs_source", "source"),
        Index("idx_error_logs_type", "error_type"),
        Index("idx_error_logs_occurred", "occurred_at"),
        Index("idx_error_logs_new", "status", "occurred_at", postgresql_where="status = 'new'"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="error")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    acknowledged_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vendors.id"), nullable=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    ack_user: Mapped[Optional["Vendor"]] = relationship("Vendor", foreign_keys=[acknowledged_by])
