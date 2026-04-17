from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, Text, Boolean, TIMESTAMP, ForeignKey, ARRAY, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class BoothShowcase(Base):
    __tablename__ = "booth_showcases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_urls: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_photo_update: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()", nullable=False)

    landing_page_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    landing_slug: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    landing_about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_contact_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    landing_contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    landing_website: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_facebook: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_instagram: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_tiktok: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_twitter: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_etsy: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    landing_meta_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    landing_meta_desc: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    landing_faq: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    show_facebook_feed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    show_instagram_feed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    landing_template: Mapped[Optional[str]] = mapped_column(String(50), default="classic", server_default="classic")
    landing_theme: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ── Phase 1: hero variants + section deck + differentiation signals ──
    # hero_style → one of: classic | split | editorial | collage | story | carousel | portrait
    landing_hero_style: Mapped[str] = mapped_column(String(30), default="classic", server_default="classic")
    # layout → ordered list of section keys e.g. ["hero","about","specialties","featured","gallery","faq","contact"]
    landing_layout: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # vendor-specific keyword surface (powers unique H2s, alt text, JSON-LD, internal links)
    landing_specialties: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    landing_era: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    landing_materials: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    # structured story prompts → { origin, specialty, process, values, whats_new }
    landing_story_blocks: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    landing_tagline: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    landing_year_started: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    vendor = relationship("Vendor", backref="booth_showcase", lazy="selectin")
