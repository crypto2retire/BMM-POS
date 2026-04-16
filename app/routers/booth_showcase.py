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
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor
from app.models.booth_showcase import BoothShowcase
from app.routers.auth import get_current_user
from app.services import spaces as spaces_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/booth-showcase", tags=["booth-showcase"])

UPLOAD_DIR = "frontend/static/uploads/booths"
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1600
MAX_PHOTOS = 8
PHOTO_STALE_DAYS = 60
STATIC_ROOT = Path("frontend/static")


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
            valid_templates = ("classic", "modern", "boutique", "minimal")
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
        valid_templates = ("classic", "modern", "boutique", "minimal")
        sc.landing_template = data.landing_template if data.landing_template in valid_templates else "classic"
    if data.landing_theme is not None:
        sc.landing_theme = data.landing_theme

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
        valid_templates = ("classic", "modern", "boutique", "minimal")
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
                BoothShowcase.landing_page_enabled == True,
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
