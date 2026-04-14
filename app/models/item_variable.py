from datetime import datetime
from sqlalchemy import String, Integer, TIMESTAMP, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ItemVariable(Base):
    """Defines a variable dimension on an item (e.g. 'Size', 'Color'). Max 2 per item."""
    __tablename__ = "item_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 or 1
    options: Mapped[str] = mapped_column(Text, nullable=False)  # comma-separated values e.g. "S,M,L,XL"
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)

    item = relationship("Item", back_populates="variables")
