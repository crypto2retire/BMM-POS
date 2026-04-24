"""Password reset code model."""
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"
    __table_args__ = (
        Index("idx_reset_codes_email", "email"),
        Index("idx_reset_codes_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
