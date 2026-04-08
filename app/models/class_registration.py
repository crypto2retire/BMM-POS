from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, TIMESTAMP, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid as _uuid


class ClassRegistration(Base):
    __tablename__ = "class_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey("studio_classes.id", ondelete="CASCADE"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    num_spots: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(_uuid.uuid4()))
    square_payment_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pending_expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)

    studio_class = relationship("StudioClass", backref="registrations", lazy="selectin")
