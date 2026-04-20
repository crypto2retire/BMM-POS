import io
import os
import json
import uuid
import logging
from datetime import datetime
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from PIL import Image
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models.vendor import Vendor
from app.models.booth_showcase import BoothShowcase
from app.routers.auth import get_current_user
from app.services import spaces as spaces_svc
from app.services import similarity as similarity_svc
from app.services import og_image as og_svc
from app.services.gsc_ping import schedule_gsc_ping

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/booth-showcase", tags=["booth-showcase"])

UPLOAD_DIR = "frontend/static/uploads/booths"
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1600
MAX_PHOTOS = 8
PHOTO_STALE_DAYS = 60
CONTENT_STALE_DAYS = 60  # freshness threshold for landing content
STATIC_ROOT = Path("frontend/static")

# In-process OG cache: {(slug, hash): bytes} — bounded to ~64 entries.
_OG_CACHE: dict[tuple[str, str], bytes] = {}
_OG_CACHE_ORDER: list[tuple[str, str]] = []
_OG_CACHE_MAX = 64


def _og_cache_get(key: tuple[str, str]) -> Optional[bytes]:
    return _OG_CACHE.get(key)


def _og_cache_put(key: tuple[str, str], value: bytes) -> None:
    if key in _OG_CACHE:
        return
    _OG_CACHE[key] = value
    _OG_CACHE_ORDER.append(key)
    while len(_OG_CACHE_ORDER) > _OG_CACHE_MAX:
        old = _OG_CACHE_ORDER.pop(0)
        _OG_CACHE.pop(old, None)


def _has_vendor_booth_access(user: Vendor) -> bool:
    return user.role == "vendor" or bool(getattr(user, "is_vendor", False))


async def require_vendor_booth_user(
    current_user: Vendor = Depends(get_current_user),
) -> Vendor:
    if not _has_vendor_booth_access(current_user):
        raise HTTPException(status_code=403, detail="Vendor booth access required.")
    return current_user


class ShowcaseResponse(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    booth_number: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    photo_urls: Optional[list] = None
    video_url: Optional[str] = None
    is_published: bool = False
    last_photo_update: Optional[str] = None
    photos_stale: bool = False
    item_count: int = 0

    class Config:
        from_attributes = True


class ShowcaseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_published: Optional[bool] = None
    landing_about: Optional[str] = None
    landing_contact_email: Optional[str] = None
    landing_contact_phone: Optional[str] = None
    landing_website: Optional[str] = None
    landing_facebook: Optional[str] = None
    landing_instagram: Optional[str] = None
    landing_tiktok: Optional[str] = None
    landing_twitter: Optional[str] = None
    landing_etsy: Optional[str] = None
    landing_meta_title: Optional[str] = None
    landing_meta_desc: Optional[str] = None
    landing_faq: Optional[str] = None
    show_facebook_feed: Optional[bool] = None
    show_instagram_feed: Optional[bool] = None
    landing_template: Optional[str] = None
    landing_theme: Optional[dict] = None
    # ── Phase 1 ──
    landing_hero_style: Optional[str] = None
    landing_layout: Optional[dict] = None
    landing_specialties: Optional[list] = None
    landing_era: Optional[list] = None
    landing_materials: Optional[list] = None
    landing_story_blocks: Optional[dict] = None
    landing_tagline: Optional[str] = None
    landing_year_started: Optional[int] = None


class AIDesignRequest(BaseModel):
    message: str
    current_theme: Optional[dict] = None
    current_template: Optional[str] = None


@router.post("/mine/ai-design")
async def ai_design_endpoint(
    data: AIDesignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    """LLM generates/updates landing theme + template from vendor conversation."""
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()

    from app.models.item import Item
    items_result = await db.execute(
        select(Item.name, Item.category).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        ).limit(20)
    )
    items = items_result.fetchall()
    item_summary = ", ".join([f"{r.name} ({r.category})" if r.category else r.name for r in items]) if items else "various items"

    vendor_name = current_user.name
    booth = current_user.booth_number or "their booth"
    existing_title = sc.title if sc else None

    current_theme_json = json.dumps(data.current_theme) if data.current_theme else "none"
    current_template_str = data.current_template or "classic"

    system_prompt = (
        "You are a landing page design consultant for Bowenstreet Market, "
        "a vintage and handcrafted marketplace in Oshkosh, Wisconsin. "
        "You help vendors design their vendor page with colors, fonts, and layout templates.\n\n"
        "AVAILABLE TEMPLATES:\n"
        "- classic: Serif headings, full-width hero, grid items. Traditional market feel.\n"
        "- modern: Sans-serif throughout, split hero (text left/image right), card items with shadows.\n"
        "- boutique: Script/cursive headings, soft pastels, centered layout, elegant feel.\n"
        "- minimal: Ultra-clean, no hero image (text + colors only), masonry items, lots of whitespace.\n\n"
        "AVAILABLE HEADING FONTS: EB Garamond, Playfair Display, Lora, Roboto, Inter, Poppins, Montserrat, Great Vibes, Dancing Script, Pacifico\n"
        "AVAILABLE BODY FONTS: Roboto, Inter, Poppins, Montserrat, EB Garamond, Playfair Display, Lora\n"
        "HEADING WEIGHTS: 300, 400, 500, 600, 700\n"
        "BODY WEIGHTS: 300, 400, 500\n\n"
        "RESPONSE FORMAT: Always respond with a JSON object containing:\n"
        '{\n'
        '  "reply": "A friendly message to the vendor about the design choices (2-3 sentences)",\n'
        '  "landing_theme": {\n'
        '    "colors": {\n'
        '      "primary": "#hexcolor",\n'
        '      "secondary": "#hexcolor",\n'
        '      "background": "#hexcolor",\n'
        '      "text": "#hexcolor",\n'
        '      "accent": "#hexcolor",\n'
        '      "card_background": "#hexcolor"\n'
        '    },\n'
        '    "fonts": {\n'
        '      "heading": "Font Name",\n'
        '      "heading_weight": "500",\n'
        '      "heading_style": "normal or italic",\n'
        '      "body": "Font Name",\n'
        '      "body_weight": "300"\n'
        '    }\n'
        '  },\n'
        '  "landing_template": "classic|modern|boutique|minimal"\n'
        '}\n\n'
        "DESIGN GUIDELINES:\n"
        "- If no theme exists yet, generate a complete design based on the vendor's message\n"
        "- If a theme exists, refine it based on the vendor's request\n"
        "- Keep contrast high: text on background must be readable\n"
        "- Dark backgrounds need light text (#F5F5F0 or similar)\n"
        "- Light backgrounds need dark text (#1A1A1C or similar)\n"
        "- Primary color is the accent/brand color (buttons, links, highlights)\n"
        "- Secondary color is used for headings, borders, and secondary elements\n"
        "- Card background should differ slightly from page background\n"
        "- Match font choices to template: classic/boutique use serif/script, modern/minimal use sans-serif\n"
        "- For boutique template, always use Great Vibes or Dancing Script for headings\n"
        "- For minimal template, keep fonts lightweight (300-400 weight)\n\n"
        "VENDOR CONTEXT:\n"
        f"Name: {vendor_name}. Booth: {booth}. Items: {item_summary}. "
        f"Current title: {existing_title or 'none'}. "
        f"Current template: {current_template_str}. Current theme: {current_theme_json}."
    )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant is not configured")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": data.message},
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 800,
                    "messages": messages,
                },
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(status_code=504, detail="AI assistant timed out")

    if not resp.is_success:
        raise HTTPException(status_code=502, detail="AI assistant unavailable")

    body = resp.json()
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="AI returned empty response")

    # Parse the JSON response
    try:
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        # Handle json prefix
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

        design_result = json.loads(cleaned)
        landing_theme = design_result.get("landing_theme")
        landing_template = design_result.get("landing_template")
        reply = design_result.get("reply", "Here's your design!")

        if landing_template and isinstance(landing_template, str):
            valid_templates = ("classic", "modern", "boutique", "minimal", "editorial-warm", "editorial-modern")
            landing_template = landing_template if landing_template in valid_templates else "classic"
        else:
            landing_template = "classic"

        # Validate theme structure
        if not isinstance(landing_theme, dict):
            landing_theme = None

        if landing_theme:
            colors = landing_theme.get("colors", {})
            fonts = landing_theme.get("fonts", {})
            landing_theme = {
                "colors": {
                    "primary": str(colors.get("primary", "#C9A96E")),
                    "secondary": str(colors.get("secondary", "#38383B")),
                    "background": str(colors.get("background", "#1A1A1C")),
                    "text": str(colors.get("text", "#F5F5F0")),
                    "accent": str(colors.get("accent", colors.get("primary", "#C9A96E"))),
                    "card_background": str(colors.get("card_background", "#2A2A2C")),
                },
                "fonts": {
                    "heading": str(fonts.get("heading", "EB Garamond")),
                    "heading_weight": str(fonts.get("heading_weight", "500")),
                    "heading_style": str(fonts.get("heading_style", "normal")),
                    "body": str(fonts.get("body", "Roboto")),
                    "body_weight": str(fonts.get("body_weight", "300")),
                },
            }

        # Save to database
        if not sc:
            sc = BoothShowcase(vendor_id=current_user.id)
            db.add(sc)
            await db.flush()

        if landing_theme:
            sc.landing_theme = landing_theme
        sc.landing_template = landing_template
        sc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(sc)

        from app.models.item import Item
        count_result = await db.execute(
            select(func.count()).select_from(Item).where(
                Item.vendor_id == current_user.id, Item.status == "active"
            )
        )
        item_count = count_result.scalar() or 0

        return {
            "reply": reply,
            "landing_template": sc.landing_template,
            "landing_theme": sc.landing_theme,
            "showcase": _to_response(sc, item_count),
        }

    except json.JSONDecodeError:
        # If LLM didn't return valid JSON, return raw text
        return {"reply": text, "landing_template": None, "landing_theme": None, "showcase": None}


class LandingSlugUpdate(BaseModel):
    slug: str


class PublicShowcaseResponse(BaseModel):
    id: int
    vendor_name: str
    booth_number: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    photo_urls: Optional[list] = None
    video_url: Optional[str] = None
    item_count: int = 0


def _is_stale(last_update: Optional[datetime]) -> bool:
    if not last_update:
        return False
    now = datetime.now(timezone.utc)
    if last_update.tzinfo is None:
        last_update = last_update.replace(tzinfo=timezone.utc)
    return (now - last_update).days >= PHOTO_STALE_DAYS


def _content_staleness(updated_at: Optional[datetime]) -> dict:
    """Return {is_stale: bool, days_since_update: int|None, threshold_days: int}."""
    if not updated_at:
        return {"is_stale": False, "days_since_update": None, "threshold_days": CONTENT_STALE_DAYS}
    now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days = (now - updated_at).days
    return {
        "is_stale": days >= CONTENT_STALE_DAYS,
        "days_since_update": days,
        "threshold_days": CONTENT_STALE_DAYS,
    }


def _public_media_exists(url: Optional[str]) -> bool:
    if not url:
        return False
    if url.startswith("http://") or url.startswith("https://"):
        return True
    if url.startswith("/api/v1/items/"):
        return True
    if url.startswith("/static/"):
        return (STATIC_ROOT / url.removeprefix("/static/")).exists()
    return False


def _valid_public_photo_urls(photo_urls: Optional[list]) -> list[str]:
    return [url for url in (photo_urls or []) if _public_media_exists(url)]


async def _fallback_item_image_url(db: AsyncSession, vendor_id: int) -> Optional[str]:
    from app.models.item import Item

    result = await db.execute(
        select(Item).where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
        ).order_by(Item.created_at.desc()).limit(20)
    )
    items = result.scalars().all()
    for item in items:
        if item.image_path and _public_media_exists(item.image_path):
            return item.image_path
        for url in item.photo_urls or []:
            if _public_media_exists(url):
                return url
    return None


async def _public_showcase_payload(db: AsyncSession, sc: BoothShowcase, item_count: int = 0) -> dict:
    valid_photo_urls = _valid_public_photo_urls(sc.photo_urls)
    cover_image_url = valid_photo_urls[0] if valid_photo_urls else await _fallback_item_image_url(db, sc.vendor_id)
    if not valid_photo_urls and cover_image_url:
        valid_photo_urls = [cover_image_url]

    return {
        "id": sc.id,
        "vendor_id": sc.vendor_id,
        "vendor_name": sc.vendor.name if sc.vendor else "",
        "booth_number": sc.vendor.booth_number if sc.vendor else None,
        "title": sc.title,
        "description": sc.description,
        "photo_urls": valid_photo_urls or None,
        "cover_image_url": cover_image_url,
        "video_url": sc.video_url,
        "item_count": item_count,
        "landing_slug": sc.landing_slug if sc.landing_page_enabled else None,
        "landing_specialties": list(sc.landing_specialties or []),
        "landing_tagline": sc.landing_tagline,
        "landing_meta_desc": sc.landing_meta_desc,
        "updated_at": sc.updated_at.isoformat() if sc.updated_at else None,
        "content_freshness": _content_staleness(sc.updated_at),
    }


def _to_response(sc: BoothShowcase, item_count: int = 0) -> dict:
    return {
        "id": sc.id,
        "vendor_id": sc.vendor_id,
        "vendor_name": sc.vendor.name if sc.vendor else "",
        "booth_number": sc.vendor.booth_number if sc.vendor else None,
        "title": sc.title,
        "description": sc.description,
        "photo_urls": sc.photo_urls,
        "video_url": sc.video_url,
        "is_published": sc.is_published,
        "last_photo_update": sc.last_photo_update.isoformat() if sc.last_photo_update else None,
        "photos_stale": _is_stale(sc.last_photo_update),
        "item_count": item_count,
        "landing_page_enabled": sc.landing_page_enabled,
        "landing_slug": sc.landing_slug,
        "landing_about": sc.landing_about,
        "landing_contact_email": sc.landing_contact_email,
        "landing_contact_phone": sc.landing_contact_phone,
        "landing_website": sc.landing_website,
        "landing_facebook": sc.landing_facebook,
        "landing_instagram": sc.landing_instagram,
        "landing_tiktok": sc.landing_tiktok,
        "landing_twitter": sc.landing_twitter,
        "landing_etsy": sc.landing_etsy,
        "landing_meta_title": sc.landing_meta_title,
        "landing_meta_desc": sc.landing_meta_desc,
        "landing_faq": sc.landing_faq,
        "show_facebook_feed": sc.show_facebook_feed,
        "show_instagram_feed": sc.show_instagram_feed,
        "landing_template": sc.landing_template or "classic",
        "landing_theme": sc.landing_theme,
        "landing_hero_style": sc.landing_hero_style or "classic",
        "landing_layout": sc.landing_layout,
        "landing_specialties": sc.landing_specialties or [],
        "landing_era": sc.landing_era or [],
        "landing_materials": sc.landing_materials or [],
        "landing_story_blocks": sc.landing_story_blocks or {},
        "landing_tagline": sc.landing_tagline,
        "landing_year_started": sc.landing_year_started,
        "content_freshness": _content_staleness(sc.updated_at),
    }


@router.get("/mine")
async def get_my_showcase(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    if not sc:
        return {
            "id": None,
            "vendor_id": current_user.id,
            "vendor_name": current_user.name,
            "booth_number": current_user.booth_number,
            "title": None,
            "description": None,
            "photo_urls": None,
            "video_url": None,
            "is_published": False,
            "last_photo_update": None,
            "photos_stale": False,
            "item_count": item_count,
            "landing_page_enabled": False,
            "landing_slug": None,
            "landing_about": None,
            "landing_contact_email": None,
            "landing_contact_phone": None,
            "landing_website": None,
            "landing_facebook": None,
            "landing_instagram": None,
            "landing_tiktok": None,
            "landing_twitter": None,
            "landing_etsy": None,
            "landing_meta_title": None,
            "landing_meta_desc": None,
            "landing_template": "classic",
            "landing_theme": None,
        }

    return _to_response(sc, item_count)


async def _summarize_story_blocks_to_about(
    story_blocks: dict | None,
    vendor_name: str,
    booth: str,
) -> Optional[str]:
    """Best-effort: turn filled story blocks into a 1-2 sentence 'about' summary.

    Returns the summary text or None on any failure. Never raises.
    The About paragraph is retired from the UI, but the backend still stores
    landing_about for use by the public page renderer (meta tags, snippets, etc.).
    """
    try:
        if not story_blocks:
            return None
        # Keep only the non-empty block values in a stable order.
        order = ("origin", "specialty", "process", "values", "whats_new")
        filled = [(k, str(story_blocks.get(k, "")).strip()) for k in order]
        filled = [(k, v) for k, v in filled if v]
        if not filled:
            return None

        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return None

        blocks_text = "\n\n".join(f"[{k}] {v}" for k, v in filled)
        system_prompt = (
            "You are a copywriter for Bowenstreet Market, a vintage and handcrafted "
            "goods marketplace in Oshkosh, Wisconsin. Write warmly, specifically, and "
            "without hashtags or emojis."
        )
        user_prompt = (
            f"Vendor: {vendor_name}. Booth: {booth}.\n\n"
            f"Here are the vendor's story blocks:\n\n{blocks_text}\n\n"
            f"Write a 1-2 sentence summary (max ~280 characters) that captures the "
            f"essence of this vendor — what they sell and what makes them distinctive. "
            f"This summary is used for SEO meta descriptions and search snippets, so "
            f"be concrete and natural. Return ONLY the summary text, no quotes or labels."
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 200,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
        if not resp.is_success:
            return None
        body = resp.json()
        text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            return None
        # Hard cap to stay within the 5000 char column and reasonable meta length.
        return text[:500]
    except Exception as e:  # pragma: no cover
        logger.info("landing_about auto-summarize skipped: %s", e)
        return None


@router.put("/mine")
async def update_my_showcase(
    data: ShowcaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()

    if not sc:
        sc = BoothShowcase(vendor_id=current_user.id)
        db.add(sc)
        await db.flush()

    if data.title is not None:
        sc.title = data.title.strip()[:200] if data.title.strip() else None
    if data.description is not None:
        sc.description = data.description.strip() if data.description.strip() else None

    if data.is_published is not None:
        if data.is_published:
            if not sc.photo_urls or len(sc.photo_urls) == 0:
                raise HTTPException(status_code=400, detail="Add at least one photo before publishing your booth showcase")
            if not sc.description or not sc.description.strip():
                raise HTTPException(status_code=400, detail="Add a description before publishing your booth showcase")
        sc.is_published = data.is_published

    if data.landing_about is not None:
        sc.landing_about = data.landing_about.strip()[:5000] if data.landing_about.strip() else None
    if data.landing_contact_email is not None:
        sc.landing_contact_email = data.landing_contact_email.strip()[:200] if data.landing_contact_email.strip() else None
    if data.landing_contact_phone is not None:
        sc.landing_contact_phone = data.landing_contact_phone.strip()[:50] if data.landing_contact_phone.strip() else None
    if data.landing_website is not None:
        sc.landing_website = data.landing_website.strip()[:300] if data.landing_website.strip() else None
    if data.landing_facebook is not None:
        sc.landing_facebook = data.landing_facebook.strip()[:300] if data.landing_facebook.strip() else None
    if data.landing_instagram is not None:
        sc.landing_instagram = data.landing_instagram.strip()[:300] if data.landing_instagram.strip() else None
    if data.landing_tiktok is not None:
        sc.landing_tiktok = data.landing_tiktok.strip()[:300] if data.landing_tiktok.strip() else None
    if data.landing_twitter is not None:
        sc.landing_twitter = data.landing_twitter.strip()[:300] if data.landing_twitter.strip() else None
    if data.landing_etsy is not None:
        sc.landing_etsy = data.landing_etsy.strip()[:300] if data.landing_etsy.strip() else None
    if data.landing_meta_title is not None:
        sc.landing_meta_title = data.landing_meta_title.strip()[:200] if data.landing_meta_title.strip() else None
    if data.landing_meta_desc is not None:
        sc.landing_meta_desc = data.landing_meta_desc.strip()[:500] if data.landing_meta_desc.strip() else None
    if data.landing_faq is not None:
        sc.landing_faq = data.landing_faq.strip()[:8000] if data.landing_faq.strip() else None
    if data.show_facebook_feed is not None:
        sc.show_facebook_feed = data.show_facebook_feed
    if data.show_instagram_feed is not None:
        sc.show_instagram_feed = data.show_instagram_feed

    if data.landing_template is not None:
        valid_templates = ("classic", "modern", "boutique", "minimal", "editorial-warm", "editorial-modern")
        sc.landing_template = data.landing_template if data.landing_template in valid_templates else "classic"
    if data.landing_theme is not None:
        sc.landing_theme = data.landing_theme

    # ── Phase 1 fields ──
    if data.landing_hero_style is not None:
        valid_heroes = ("classic", "split", "editorial", "collage", "story", "carousel", "portrait")
        sc.landing_hero_style = data.landing_hero_style if data.landing_hero_style in valid_heroes else "classic"
    if data.landing_layout is not None:
        existing_layout = sc.landing_layout or {}
        sc.landing_layout = {**existing_layout, **data.landing_layout}
    if data.landing_specialties is not None:
        # clip to 8 entries, 60 chars each
        sc.landing_specialties = [str(s).strip()[:60] for s in data.landing_specialties if str(s).strip()][:8]
    if data.landing_era is not None:
        sc.landing_era = [str(s).strip()[:40] for s in data.landing_era if str(s).strip()][:8]
    if data.landing_materials is not None:
        sc.landing_materials = [str(s).strip()[:40] for s in data.landing_materials if str(s).strip()][:12]
    if data.landing_story_blocks is not None:
        allowed_keys = ("origin", "specialty", "process", "values", "whats_new")
        sc.landing_story_blocks = {
            k: str(v).strip()[:1200]
            for k, v in (data.landing_story_blocks or {}).items()
            if k in allowed_keys and v
        }
    if data.landing_tagline is not None:
        sc.landing_tagline = data.landing_tagline.strip()[:200] if data.landing_tagline.strip() else None
    if data.landing_year_started is not None:
        try:
            y = int(data.landing_year_started)
            sc.landing_year_started = y if 1800 <= y <= 2100 else None
        except (TypeError, ValueError):
            sc.landing_year_started = None

    # ── Best-effort: auto-summarize story blocks → landing_about ──
    # The About paragraph was retired from the UI, but landing_about still
    # powers meta descriptions and search snippets. Only runs when story
    # blocks were touched in this save; failures are swallowed so a flaky
    # AI call never blocks the save.
    about_is_custom = bool((sc.landing_layout or {}).get("about_is_custom", False))
    if data.landing_story_blocks is not None and not about_is_custom:
        summary = await _summarize_story_blocks_to_about(
            sc.landing_story_blocks or {},
            vendor_name=current_user.name,
            booth=current_user.booth_number or "their booth",
        )
        if summary:
            sc.landing_about = summary
        elif not (sc.landing_story_blocks or {}):
            # All story blocks cleared → wipe the derived summary too
            sc.landing_about = None

    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    # Fire-and-forget GSC ping when the landing page is live
    try:
        if sc.landing_page_enabled and sc.landing_slug:
            schedule_gsc_ping(sc.landing_slug, "URL_UPDATED")
    except Exception as e:  # pragma: no cover
        logger.info("gsc ping skipped: %s", e)

    return _to_response(sc, item_count)


@router.post("/mine/photo")
async def upload_showcase_photo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=current_user.id)
        db.add(sc)
        await db.flush()

    current_photos = sc.photo_urls or []
    if len(current_photos) >= MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_PHOTOS} photos allowed")

    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use JPG, PNG, GIF, or WebP")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    try:
        img = Image.open(io.BytesIO(contents))
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        contents = buf.getvalue()
        ext = ".jpg"
    except Exception:
        pass

    filename = f"booth_{current_user.id}_{uuid.uuid4().hex[:10]}.jpg"
    spaces_key = f"booths/{filename}"
    cdn_url = spaces_svc.upload_bytes(contents, spaces_key, "image/jpeg")
    if cdn_url:
        photo_url = cdn_url
    else:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(contents)
        photo_url = f"/static/uploads/booths/{filename}"
    sc.photo_urls = current_photos + [photo_url]
    sc.last_photo_update = datetime.now(timezone.utc)
    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    return _to_response(sc, item_count)


@router.post("/mine/logo")
async def upload_showcase_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    """Upload a square logo. Stored at theme.branding.logo_url."""
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=current_user.id)
        db.add(sc)
        await db.flush()

    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    ext = os.path.splitext(file.filename or "logo.png")[1].lower() or ".png"
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use JPG, PNG, GIF, or WebP")

    contents = await file.read()
    if len(contents) > 2_000_000:
        raise HTTPException(status_code=400, detail="Logo must be under 2MB")

    preserve_png = ext == ".png"
    out_ext = ".png" if preserve_png else ".jpg"
    content_type = "image/png" if preserve_png else "image/jpeg"
    try:
        img = Image.open(io.BytesIO(contents))
        if preserve_png:
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        if side > 600:
            img = img.resize((600, 600), Image.LANCZOS)
        buf = io.BytesIO()
        if preserve_png:
            img.save(buf, "PNG", optimize=True)
        else:
            img.save(buf, "JPEG", quality=88)
        contents = buf.getvalue()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not process image: {e}")

    filename = f"logo_{current_user.id}_{uuid.uuid4().hex[:10]}{out_ext}"
    spaces_key = f"booths/logos/{filename}"
    cdn_url = spaces_svc.upload_bytes(contents, spaces_key, content_type)
    if cdn_url:
        logo_url = cdn_url
    else:
        logo_dir = os.path.join(UPLOAD_DIR, "logos")
        os.makedirs(logo_dir, exist_ok=True)
        filepath = os.path.join(logo_dir, filename)
        with open(filepath, "wb") as f:
            f.write(contents)
        logo_url = f"/static/uploads/booths/logos/{filename}"

    theme = sc.landing_theme or {}
    branding = theme.get("branding") or {}
    branding["logo_url"] = logo_url
    theme["branding"] = branding
    sc.landing_theme = theme
    sc.updated_at = datetime.now(timezone.utc)
    flag_modified(sc, "landing_theme")
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0
    return _to_response(sc, item_count)


@router.delete("/mine/logo")
async def delete_showcase_logo(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Showcase not found")
    theme = sc.landing_theme or {}
    branding = theme.get("branding") or {}
    if "logo_url" in branding:
        del branding["logo_url"]
        theme["branding"] = branding
        sc.landing_theme = theme
        flag_modified(sc, "landing_theme")
        sc.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0
    return _to_response(sc, item_count)


@router.delete("/mine/photo")
async def delete_showcase_photo(
    photo_url: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Showcase not found")

    current_photos = sc.photo_urls or []
    if photo_url not in current_photos:
        raise HTTPException(status_code=404, detail="Photo not found")

    sc.photo_urls = [p for p in current_photos if p != photo_url]
    if not sc.photo_urls:
        sc.photo_urls = None
        sc.is_published = False
    sc.updated_at = datetime.now(timezone.utc)

    if photo_url.startswith("http"):
        spaces_svc.delete_object(photo_url)
    else:
        basename = os.path.basename(photo_url)
        filepath = os.path.join(UPLOAD_DIR, basename)
        if os.path.exists(filepath):
            os.remove(filepath)

    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    return _to_response(sc, item_count)


@router.post("/mine/video")
async def upload_showcase_video(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=current_user.id)
        db.add(sc)
        await db.flush()

    allowed = {".mp4", ".mov", ".webm"}
    ext = os.path.splitext(file.filename or "video.mp4")[1].lower() or ".mp4"
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported video type. Use MP4, MOV, or WebM")

    contents = await file.read()
    if len(contents) > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail="Video must be under 50MB")

    if sc.video_url:
        if sc.video_url.startswith("http"):
            spaces_svc.delete_object(sc.video_url)
        else:
            old_basename = os.path.basename(sc.video_url)
            old_path = os.path.join(UPLOAD_DIR, old_basename)
            if os.path.exists(old_path):
                os.remove(old_path)

    filename = f"booth_vid_{current_user.id}_{uuid.uuid4().hex[:10]}{ext}"
    spaces_key = f"booths/{filename}"
    cdn_url = spaces_svc.upload_bytes(contents, spaces_key, "video/mp4")
    if cdn_url:
        sc.video_url = cdn_url
    else:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(contents)
        sc.video_url = f"/static/uploads/booths/{filename}"
    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    return _to_response(sc, item_count)


@router.delete("/mine/video")
async def delete_showcase_video(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc or not sc.video_url:
        raise HTTPException(status_code=404, detail="No video to remove")

    if sc.video_url.startswith("http"):
        spaces_svc.delete_object(sc.video_url)
    else:
        basename = os.path.basename(sc.video_url)
        filepath = os.path.join(UPLOAD_DIR, basename)
        if os.path.exists(filepath):
            os.remove(filepath)

    sc.video_url = None
    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    return _to_response(sc, item_count)


@router.post("/mine/ai-description")
async def generate_ai_description(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()

    from app.models.item import Item
    items_result = await db.execute(
        select(Item.name, Item.category).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        ).limit(20)
    )
    items = items_result.fetchall()
    item_summary = ", ".join([f"{r.name} ({r.category})" if r.category else r.name for r in items]) if items else "various items"

    vendor_name = current_user.name
    booth = current_user.booth_number or "their booth"
    existing_title = sc.title if sc else None

    prompt = (
        f"Write an inviting, warm booth description for a vendor at Bowenstreet Market, "
        f"a vintage and handcrafted marketplace in Oshkosh, Wisconsin. "
        f"Vendor name: {vendor_name}. Booth: {booth}. "
    )
    if existing_title:
        prompt += f"Booth name: {existing_title}. "
    prompt += (
        f"They sell: {item_summary}. "
        f"Write 2-3 short paragraphs (around 80-120 words total) that would make customers "
        f"want to visit this booth. Be genuine and specific to what they sell. "
        f"Do NOT use hashtags or emojis. Write in a warm, welcoming tone."
    )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant is not configured")

    messages = [
        {"role": "system", "content": "You are a helpful copywriter for Bowenstreet Market, a vintage and handcrafted goods marketplace."},
        {"role": "user", "content": prompt},
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 300,
                    "messages": messages,
                },
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(status_code=504, detail="AI assistant timed out")

    if not resp.is_success:
        raise HTTPException(status_code=502, detail="AI assistant unavailable")

    body = resp.json()
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="AI returned empty response")

    return {"description": text}


@router.get("/public")
async def list_public_showcases(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.is_published == True).order_by(BoothShowcase.updated_at.desc())
    )
    showcases = result.scalars().all()

    from app.models.item import Item
    response = []
    for sc in showcases:
        count_result = await db.execute(
            select(func.count()).select_from(Item).where(
                Item.vendor_id == sc.vendor_id, Item.status == "active"
            )
        )
        item_count = count_result.scalar() or 0
        response.append(await _public_showcase_payload(db, sc, item_count))

    return response


@router.get("/public/{showcase_id}")
async def get_public_showcase(
    showcase_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BoothShowcase).where(
            BoothShowcase.id == showcase_id,
            BoothShowcase.is_published == True,
        )
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Showcase not found")

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == sc.vendor_id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    payload = await _public_showcase_payload(db, sc, item_count)
    payload.pop("landing_slug", None)
    return payload


@router.get("/stale-check")
async def check_stale_photos(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc or not sc.last_photo_update:
        return {"stale": False, "has_showcase": sc is not None, "days_since_update": None}

    days = (datetime.now(timezone.utc) - (sc.last_photo_update.replace(tzinfo=timezone.utc) if sc.last_photo_update.tzinfo is None else sc.last_photo_update)).days
    return {
        "stale": days >= PHOTO_STALE_DAYS,
        "has_showcase": True,
        "days_since_update": days,
    }


import re

SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9\-]{1,98}[a-z0-9]$')
RESERVED_SLUGS = {"admin", "pos", "vendor", "shop", "api", "static", "login", "signup", "settings", "booths", "classes"}


@router.put("/mine/landing-slug")
async def update_landing_slug(
    data: LandingSlugUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    slug = data.slug.strip().lower()
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')

    if not slug or not SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=400, detail="URL must be 3-100 characters, lowercase letters, numbers, and hyphens only")
    if slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="This URL is reserved. Please choose a different one.")

    existing = await db.execute(
        select(BoothShowcase).where(
            BoothShowcase.landing_slug == slug,
            BoothShowcase.vendor_id != current_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This URL is already taken. Please choose a different one.")

    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=current_user.id)
        db.add(sc)
        await db.flush()

    sc.landing_slug = slug
    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0
    return _to_response(sc, item_count)


@router.get("/landing/vendor/{vendor_id}")
async def get_landing_page_by_vendor_id(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Admin endpoint: get a vendor's landing page data by vendor ID."""
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier only")

    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor_id)
    )
    sc = result.scalar_one_or_none()

    vendor_result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id)
    )
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if not sc:
        return {
            "vendor_id": vendor_id,
            "vendor_name": vendor.name,
            "booth_number": vendor.booth_number,
            "landing_page_enabled": False,
            "landing_slug": None,
            "landing_template": "classic",
            "landing_theme": None,
            "is_published": False,
        }

    from app.models.item import Item
    count_result = await db.execute(
        select(func.count()).select_from(Item).where(
            Item.vendor_id == sc.vendor_id, Item.status == "active"
        )
    )
    item_count = count_result.scalar() or 0

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.name,
        "booth_number": vendor.booth_number,
        "landing_page_enabled": sc.landing_page_enabled,
        "landing_slug": sc.landing_slug,
        "landing_template": sc.landing_template or "classic",
        "landing_theme": sc.landing_theme,
        "is_published": sc.is_published,
        **_to_response(sc, item_count),
    }


@router.put("/admin/booth-showcase/{vendor_id}")
async def admin_update_showcase(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
    landing_template: Optional[str] = Body(None),
    landing_theme: Optional[dict] = Body(None),
    toggle_landing_page: Optional[bool] = Body(None),
):
    """Admin endpoint: update a vendor's showcase settings."""
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier only")

    vendor_result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id)
    )
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor_id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=vendor_id)
        db.add(sc)
        await db.flush()

    result_data = {}

    if landing_template is not None:
        valid_templates = ("classic", "modern", "boutique", "minimal", "editorial-warm", "editorial-modern")
        sc.landing_template = landing_template if landing_template in valid_templates else "classic"
        result_data["landing_template"] = sc.landing_template

    if landing_theme is not None:
        sc.landing_theme = landing_theme
        result_data["landing_theme"] = sc.landing_theme

    if toggle_landing_page:
        enabling = not sc.landing_page_enabled
        sc.landing_page_enabled = enabling
        LANDING_PAGE_FEE = Decimal("10.00")
        vendor.landing_page_fee = LANDING_PAGE_FEE if enabling else Decimal("0.00")
        result_data["landing_page_enabled"] = sc.landing_page_enabled
        result_data["landing_page_fee"] = float(vendor.landing_page_fee)

    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)
    await db.refresh(vendor)

    try:
        if sc.landing_page_enabled and sc.landing_slug:
            schedule_gsc_ping(sc.landing_slug, "URL_UPDATED")
    except Exception as e:  # pragma: no cover
        logger.info("gsc ping skipped: %s", e)

    return result_data


@router.post("/admin/landing-page/{vendor_id}")
async def admin_toggle_landing_page(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier only")

    # Load vendor
    vendor_result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id)
    )
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Load or create showcase
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor_id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=vendor_id)
        db.add(sc)
        await db.flush()

    # Toggle
    enabling = not sc.landing_page_enabled
    sc.landing_page_enabled = enabling
    sc.updated_at = datetime.now(timezone.utc)

    # Manage $10/month fee
    LANDING_PAGE_FEE = Decimal("10.00")
    if enabling:
        vendor.landing_page_fee = LANDING_PAGE_FEE
    else:
        vendor.landing_page_fee = Decimal("0.00")

    await db.commit()
    await db.refresh(sc)
    await db.refresh(vendor)

    # GSC ping on publish; deletion ping on unpublish
    try:
        if sc.landing_slug:
            schedule_gsc_ping(
                sc.landing_slug,
                "URL_UPDATED" if sc.landing_page_enabled else "URL_DELETED",
            )
    except Exception as e:  # pragma: no cover
        logger.info("gsc ping skipped: %s", e)

    effective_rent = (vendor.monthly_rent or Decimal("0")) + (vendor.landing_page_fee or Decimal("0"))

    return {
        "landing_page_enabled": sc.landing_page_enabled,
        "vendor_id": vendor_id,
        "landing_page_fee": float(vendor.landing_page_fee),
        "base_monthly_rent": float(vendor.monthly_rent or 0),
        "effective_monthly_rent": float(effective_rent),
    }


@router.put("/admin/landing-slug/{vendor_id}")
async def admin_update_landing_slug(
    vendor_id: int,
    data: LandingSlugUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier only")

    vendor_result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id)
    )
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor_id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        sc = BoothShowcase(vendor_id=vendor_id)
        db.add(sc)
        await db.flush()

    slug = data.slug.strip().lower()
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')

    if not slug or not SLUG_PATTERN.match(slug):
        raise HTTPException(status_code=400, detail="URL must be 3-100 characters, lowercase letters, numbers, and hyphens only")
    if slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="This URL is reserved. Please choose a different one.")

    existing = await db.execute(
        select(BoothShowcase).where(
            BoothShowcase.landing_slug == slug,
            BoothShowcase.vendor_id != vendor_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This URL is already taken. Please choose a different one.")

    sc.landing_slug = slug
    sc.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    return {
        "landing_slug": sc.landing_slug,
        "vendor_id": vendor_id,
        "landing_page_enabled": sc.landing_page_enabled,
    }


@router.get("/landing/{slug}")
async def get_landing_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(BoothShowcase).where(
                BoothShowcase.landing_slug == slug,
                BoothShowcase.landing_page_enabled != False,
            )
        )
        sc = result.scalar_one_or_none()
        if not sc:
            raise HTTPException(status_code=404, detail="Page not found")

        from app.models.item import Item
        count_result = await db.execute(
            select(func.count()).select_from(Item).where(
                Item.vendor_id == sc.vendor_id, Item.status == "active"
            )
        )
        item_count = count_result.scalar() or 0

        items_result = await db.execute(
            select(Item).where(
                Item.vendor_id == sc.vendor_id, Item.status == "active"
            ).order_by(Item.created_at.desc()).limit(12)
        )
        items = items_result.scalars().all()
        item_list = []
        for item in items:
            img = item.image_path or (item.photo_urls[0] if item.photo_urls else None)
            item_list.append({
                "id": item.id,
                "name": item.name,
                "price": float(item.price) if item.price else 0,
                "image_url": img,
                "category": item.category,
            })

        from app.models.store_setting import StoreSetting
        settings_result = await db.execute(
            select(StoreSetting).where(
                StoreSetting.key.in_([
                    "webstore_facebook_url", "webstore_facebook_on",
                    "webstore_instagram_url", "webstore_instagram_on",
                    "webstore_tiktok_url", "webstore_tiktok_on",
                    "store_name",
                ])
            )
        )
        settings = {s.key: s.value for s in settings_result.scalars().all()}

        market_socials = {}
        if settings.get("webstore_facebook_on") == "true" and settings.get("webstore_facebook_url"):
            market_socials["facebook"] = settings["webstore_facebook_url"]
        if settings.get("webstore_instagram_on") == "true" and settings.get("webstore_instagram_url"):
            market_socials["instagram"] = settings["webstore_instagram_url"]
        if settings.get("webstore_tiktok_on") == "true" and settings.get("webstore_tiktok_url"):
            market_socials["tiktok"] = settings["webstore_tiktok_url"]

        valid_photo_urls = _valid_public_photo_urls(sc.photo_urls)
        if not valid_photo_urls:
            fallback_cover = await _fallback_item_image_url(db, sc.vendor_id)
            valid_photo_urls = [fallback_cover] if fallback_cover else []

        payload = {
            "id": sc.id,
            "vendor_id": sc.vendor_id,
            "vendor_name": sc.vendor.name if sc.vendor else "",
            "booth_number": sc.vendor.booth_number if sc.vendor else None,
            "title": sc.title,
            "description": sc.description,
            "landing_about": sc.landing_about,
            "photo_urls": valid_photo_urls or None,
            "video_url": sc.video_url,
            "item_count": item_count,
            "items": item_list,
            "landing_contact_email": sc.landing_contact_email,
            "landing_contact_phone": sc.landing_contact_phone,
            "landing_website": sc.landing_website,
            "landing_facebook": sc.landing_facebook,
            "landing_instagram": sc.landing_instagram,
            "landing_tiktok": sc.landing_tiktok,
            "landing_twitter": sc.landing_twitter,
            "landing_etsy": sc.landing_etsy,
            "landing_meta_title": sc.landing_meta_title,
            "landing_meta_desc": sc.landing_meta_desc,
            "landing_faq": sc.landing_faq,
            "show_facebook_feed": sc.show_facebook_feed,
            "show_instagram_feed": sc.show_instagram_feed,
            "market_socials": market_socials,
            "market_name": settings.get("store_name", "Bowenstreet Market Mall"),
            "landing_template": sc.landing_template or "classic",
            "landing_theme": sc.landing_theme,
            "landing_hero_style": sc.landing_hero_style or "classic",
            "landing_layout": sc.landing_layout,
            "landing_specialties": sc.landing_specialties or [],
            "landing_era": sc.landing_era or [],
            "landing_materials": sc.landing_materials or [],
            "landing_story_blocks": sc.landing_story_blocks or {},
            "landing_tagline": sc.landing_tagline,
            "landing_year_started": sc.landing_year_started,
            "updated_at": sc.updated_at.isoformat() if sc.updated_at else None,
            "content_freshness": _content_staleness(sc.updated_at),
        }
        return JSONResponse(
            content=payload,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Landing page error for slug '{slug}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Landing page error: {str(e)}")


@router.post("/mine/ai-landing-about")
async def ai_generate_landing_about(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()

    from app.models.item import Item
    items_result = await db.execute(
        select(Item.name, Item.category).where(
            Item.vendor_id == current_user.id, Item.status == "active"
        ).limit(30)
    )
    items = items_result.fetchall()
    item_summary = ", ".join([f"{r.name} ({r.category})" if r.category else r.name for r in items]) if items else "various items"

    vendor_name = current_user.name
    booth = current_user.booth_number or "their booth"
    existing_title = sc.title if sc else None
    existing_desc = sc.description if sc else None

    prompt = (
        f"Write a compelling, detailed 'About' section for a vendor's landing page at Bowenstreet Market, "
        f"a vintage and handcrafted marketplace at 2837 Bowen St, Oshkosh, Wisconsin 54901. "
        f"Vendor name: {vendor_name}. Booth: {booth}. "
    )
    if existing_title:
        prompt += f"Booth name: {existing_title}. "
    if existing_desc:
        prompt += f"Short booth description: {existing_desc}. "
    prompt += (
        f"They sell: {item_summary}. "
        f"Write 3-4 paragraphs (200-300 words) that tell the vendor's story, highlight what makes them special, "
        f"and invite customers to visit or shop. Include what types of items they carry, why customers love them, "
        f"and the experience of visiting their booth. Be warm, genuine, and specific. "
        f"Do NOT use hashtags or emojis. Do NOT include the address or market name in the text — those are shown separately."
    )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant is not configured")

    messages = [
        {"role": "system", "content": "You are a skilled copywriter helping small vendors build their online presence at Bowenstreet Market."},
        {"role": "user", "content": prompt},
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "max_tokens": 600,
                    "messages": messages,
                },
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(status_code=504, detail="AI assistant timed out")

    if not resp.is_success:
        raise HTTPException(status_code=502, detail="AI assistant unavailable")

    body = resp.json()
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="AI returned empty response")

    return {"about": text}


# ───────────────────────────────────────────────────────────────
# Phase 4: Uniqueness guard, Freshness, OG image
# ───────────────────────────────────────────────────────────────


async def _load_peer_story_corpora(
    db: AsyncSession, exclude_vendor_id: int
) -> list[tuple[str, str]]:
    """Load (vendor_name, corpus_text) pairs for all OTHER vendors with
    enabled landing pages. Cap to ~200 to keep request fast.
    """
    q = (
        select(BoothShowcase)
        .where(
            BoothShowcase.vendor_id != exclude_vendor_id,
            BoothShowcase.landing_page_enabled != False,
        )
        .limit(200)
    )
    result = await db.execute(q)
    scs = result.scalars().all()
    pairs: list[tuple[str, str]] = []
    for s in scs:
        vname = s.vendor.name if s.vendor else f"Vendor #{s.vendor_id}"
        corpus = similarity_svc.vendor_corpus(
            s.landing_tagline,
            s.landing_meta_desc,
            s.landing_about,
            s.landing_story_blocks,
        )
        if corpus.strip():
            pairs.append((vname, corpus))
    return pairs


@router.get("/mine/uniqueness")
async def get_my_uniqueness_score(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    """Compute a 0-100 uniqueness score for the current vendor's landing
    copy vs. every other vendor's published landing copy.
    Higher = more original.
    """
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        return {
            "score": 0,
            "top_similarity": 0.0,
            "similar_to": [],
            "word_count": 0,
            "message": "Set up your landing page to get a uniqueness score.",
        }

    target_text = similarity_svc.vendor_corpus(
        sc.landing_tagline,
        sc.landing_meta_desc,
        sc.landing_about,
        sc.landing_story_blocks,
    )
    peers = await _load_peer_story_corpora(db, exclude_vendor_id=current_user.id)
    return similarity_svc.uniqueness_score(target_text, peers)


class UniquenessPreviewRequest(BaseModel):
    landing_tagline: Optional[str] = None
    landing_meta_desc: Optional[str] = None
    landing_about: Optional[str] = None
    landing_story_blocks: Optional[dict] = None


@router.post("/mine/uniqueness/preview")
async def preview_uniqueness_score(
    data: UniquenessPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    """Score a proposed draft (without saving) against peer corpora.
    Lets the vendor iterate in-editor before committing.
    """
    target_text = similarity_svc.vendor_corpus(
        data.landing_tagline,
        data.landing_meta_desc,
        data.landing_about,
        data.landing_story_blocks,
    )
    peers = await _load_peer_story_corpora(db, exclude_vendor_id=current_user.id)
    return similarity_svc.uniqueness_score(target_text, peers)


@router.get("/mine/freshness")
async def get_my_freshness(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_booth_user),
):
    """Return content- and photo-freshness indicators for the vendor's
    own landing page. Drives the admin "refresh recommended" banner.
    """
    result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == current_user.id)
    )
    sc = result.scalar_one_or_none()
    if not sc:
        return {
            "content": _content_staleness(None),
            "photos": {
                "is_stale": False,
                "days_since_update": None,
                "threshold_days": PHOTO_STALE_DAYS,
                "last_photo_update": None,
            },
            "has_showcase": False,
            "suggestions": [],
        }

    content = _content_staleness(sc.updated_at)
    photo_days = None
    if sc.last_photo_update:
        last = sc.last_photo_update
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        photo_days = (datetime.now(timezone.utc) - last).days
    photos = {
        "is_stale": _is_stale(sc.last_photo_update),
        "days_since_update": photo_days,
        "threshold_days": PHOTO_STALE_DAYS,
        "last_photo_update": sc.last_photo_update.isoformat() if sc.last_photo_update else None,
    }

    suggestions: list[str] = []
    if content["is_stale"]:
        suggestions.append(
            "Refresh your story — small edits signal to Google that this page is alive."
        )
    if photos["is_stale"]:
        suggestions.append(
            "Add a new photo of recent work, booth setup, or current inventory."
        )
    if not (sc.landing_story_blocks or {}).get("whats_new"):
        suggestions.append(
            "Fill in \"What's New\" to highlight this season's arrivals or projects."
        )
    if not sc.landing_tagline:
        suggestions.append(
            "Add a tagline — one crisp sentence that captures what makes you different."
        )

    return {
        "content": content,
        "photos": photos,
        "has_showcase": True,
        "landing_page_enabled": sc.landing_page_enabled,
        "landing_slug": sc.landing_slug,
        "suggestions": suggestions,
    }


@router.get("/og/{slug}.png")
async def get_og_image(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve a 1200x630 OG image for a vendor landing page.

    Served as JPEG (despite the .png extension for URL stability) — most
    social platforms accept either. Cached in-process until redeploy.
    """
    if not slug or "." in slug or "/" in slug:
        raise HTTPException(status_code=404, detail="Not found")

    result = await db.execute(
        select(BoothShowcase).where(
            BoothShowcase.landing_slug == slug,
            BoothShowcase.landing_page_enabled != False,
        )
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Landing page not found")

    vendor_name = sc.vendor.name if sc.vendor else "Vendor"
    tagline = sc.landing_tagline
    specialties = list(sc.landing_specialties or [])

    # Choose cover: first valid photo or first item image
    valid_photos = _valid_public_photo_urls(sc.photo_urls)
    cover_url = valid_photos[0] if valid_photos else await _fallback_item_image_url(db, sc.vendor_id)

    # Cache key factors in anything that affects the rendered output
    cache_hash = og_svc.content_hash(
        vendor_name,
        tagline,
        "|".join(specialties[:3]),
        cover_url,
        (sc.updated_at.isoformat() if sc.updated_at else ""),
    )
    key = (slug, cache_hash)
    cached = _og_cache_get(key)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    try:
        img_bytes = og_svc.render_og_image(
            vendor_name=vendor_name,
            tagline=tagline,
            specialties=specialties,
            cover_url=cover_url,
            theme=sc.landing_theme,
            static_root=STATIC_ROOT,
        )
    except Exception as e:
        logger.error("og_image render failed for %s: %s", slug, e, exc_info=True)
        raise HTTPException(status_code=500, detail="OG image generation failed")

    _og_cache_put(key, img_bytes)
    return Response(
        content=img_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# =========================================================================
# Related vendors (cross-vendor discovery rail)
# =========================================================================

class RelatedVendorOut(BaseModel):
    slug: str
    name: str
    booth_number: Optional[str] = None
    cover_image_url: Optional[str] = None
    shared_tag_count: int = 0


@router.get("/related/{slug}", response_model=list[RelatedVendorOut])
async def get_related_vendors(
    slug: str,
    limit: int = 4,
    db: AsyncSession = Depends(get_db),
):
    """
    Return up to `limit` published vendors who share specialty tags with the given vendor.
    Ranking: vendors with more overlapping tags come first. Falls back to random
    published vendors if the target vendor has no tags or no overlaps exist.

    Used by the "You might also like" rail on the public landing page.
    """
    limit = max(1, min(limit, 8))

    # Load source vendor's specialties
    stmt_src = select(BoothShowcase).where(BoothShowcase.landing_slug == slug)
    res_src = await db.execute(stmt_src)
    source = res_src.scalar_one_or_none()
    if not source or not source.landing_page_enabled:
        raise HTTPException(status_code=404, detail="Vendor not found")

    source_tags = list(source.landing_specialties or [])

    # Load all other published vendors
    stmt_all = (
        select(BoothShowcase, Vendor)
        .join(Vendor, Vendor.id == BoothShowcase.vendor_id)
        .where(
            BoothShowcase.landing_page_enabled == True,  # noqa: E712
            BoothShowcase.landing_slug != slug,
            Vendor.is_active == True,  # noqa: E712
        )
    )
    res_all = await db.execute(stmt_all)
    rows = res_all.all()

    def _score(sc: BoothShowcase) -> int:
        tags = set(sc.landing_specialties or [])
        return len(tags.intersection(source_tags))

    # Rank: by shared-tag count desc, then by recency (most recently updated first)
    ranked = sorted(
        rows,
        key=lambda r: (_score(r[0]), r[0].updated_at or r[0].created_at),
        reverse=True,
    )

    # If source has tags and we have overlaps, prefer those. Otherwise fall back
    # to the full ranked list (by recency) so the rail is never empty.
    if source_tags and any(_score(r[0]) > 0 for r in ranked):
        ranked = [r for r in ranked if _score(r[0]) > 0] + [r for r in ranked if _score(r[0]) == 0]

    picked = ranked[:limit]

    out: list[RelatedVendorOut] = []
    for sc, v in picked:
        valid_photos = _valid_public_photo_urls(sc.photo_urls)
        cover = valid_photos[0] if valid_photos else None
        if not cover:
            cover = await _fallback_item_image_url(db, sc.vendor_id)
        out.append(RelatedVendorOut(
            slug=sc.landing_slug or "",
            name=v.name,
            booth_number=v.booth_number,
            cover_image_url=cover,
            shared_tag_count=_score(sc),
        ))
    return out
