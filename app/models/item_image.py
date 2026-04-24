from datetime import datetime
from sqlalchemy import Integer, String, LargeBinary, TIMESTAMP, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ItemImage(Base):
    __tablename__ = "item_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    # Deprecated: image_data is no longer stored in DB. Images are stored on disk/DO Spaces.
    # Kept for backward compatibility; will be removed in future migration.
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str] = mapped_column(String(50), default="image/jpeg", nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
