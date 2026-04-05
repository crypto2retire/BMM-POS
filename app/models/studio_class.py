from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Integer, Boolean, TIMESTAMP, Date, Time, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class StudioClass(Base):
    __tablename__ = "studio_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instructor: Mapped[str] = mapped_column(String(120), nullable=False)
    class_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    enrolled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="Studio", nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vendors.id"), nullable=True)
