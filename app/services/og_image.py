"""OG (Open Graph) image generator for vendor landing pages.

Composites a 1200×630 JPG from:
  - cover photo (blurred, darkened, full-bleed background)
  - vendor name (large)
  - tagline or first specialty (medium)
  - market footer ("Bowenstreet Market — Oshkosh, WI")

Falls back gracefully when fonts or cover photo aren't available.
Results are cached to a local in-process dict keyed by (slug, content-hash)
and also buffered in-memory — since Railway containers are ephemeral and
we don't have a shared cache layer, we keep this simple.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

OG_WIDTH = 1200
OG_HEIGHT = 630
OG_PADDING = 60

# Candidate font paths — in order of preference. Pillow ships no default
# truetype font, so we probe common system locations.
_FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/local/lib/python3.13/site-packages/cv2/qt/fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]
_FONT_CANDIDATES_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/local/lib/python3.13/site-packages/cv2/qt/fonts/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]


def _load_font(paths: list[str], size: int) -> ImageFont.ImageFont:
    for p in paths:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    # Fallback: PIL's built-in bitmap font (no size control, tiny, but
    # prevents crashes on misconfigured systems).
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _fetch_cover_image(url: Optional[str], static_root: Path) -> Optional[Image.Image]:
    if not url:
        return None
    try:
        if url.startswith(("http://", "https://")):
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                r = client.get(url)
                if r.status_code != 200:
                    return None
                img = Image.open(io.BytesIO(r.content))
        elif url.startswith("/static/"):
            p = static_root / url.removeprefix("/static/")
            if not p.exists():
                return None
            img = Image.open(p)
        else:
            return None
        return img.convert("RGB")
    except Exception as e:
        logger.info("og_image: cover fetch failed for %s: %s", url, e)
        return None


def _wrap_text(draw: ImageDraw.ImageDraw, text: str,
               font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Greedy word-wrap that respects pixel width."""
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = current + " " + w
        width = draw.textlength(candidate, font=font)
        if width <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def _gradient_background(size: tuple[int, int], top: tuple[int, int, int],
                         bottom: tuple[int, int, int]) -> Image.Image:
    """Vertical gradient fallback when no cover photo."""
    img = Image.new("RGB", size, top)
    px = img.load()
    w, h = size
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _theme_colors(theme: Optional[dict]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Extract top/bottom gradient colors from landing_theme, with fallback."""
    default_top = (30, 41, 59)      # slate-800
    default_bot = (15, 23, 42)       # slate-900
    if not theme:
        return default_top, default_bot
    try:
        c = theme.get("colors", {}) if isinstance(theme, dict) else {}
        prim = c.get("primary") or c.get("background")
        sec = c.get("secondary") or c.get("accent")
        return _hex_to_rgb(prim, default_top), _hex_to_rgb(sec, default_bot)
    except Exception:
        return default_top, default_bot


def _hex_to_rgb(value: Optional[str], fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not value or not isinstance(value, str):
        return fallback
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        return fallback
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        return fallback


def render_og_image(
    *,
    vendor_name: str,
    tagline: Optional[str] = None,
    specialties: Optional[list[str]] = None,
    cover_url: Optional[str] = None,
    theme: Optional[dict] = None,
    static_root: Path = Path("frontend/static"),
    market_label: str = "Bowenstreet Market · Oshkosh, WI",
) -> bytes:
    """Generate OG image bytes (JPEG, ~1200x630)."""
    # ── Base canvas ──
    cover = _fetch_cover_image(cover_url, static_root)
    if cover:
        # Cover-fit crop to 1200x630
        cw, ch = cover.size
        target_ratio = OG_WIDTH / OG_HEIGHT
        src_ratio = cw / ch
        if src_ratio > target_ratio:
            # wider → crop sides
            new_w = int(ch * target_ratio)
            left = (cw - new_w) // 2
            cover = cover.crop((left, 0, left + new_w, ch))
        else:
            new_h = int(cw / target_ratio)
            top = (ch - new_h) // 2
            cover = cover.crop((0, top, cw, top + new_h))
        canvas = cover.resize((OG_WIDTH, OG_HEIGHT), Image.LANCZOS)
        # Darken + blur slightly for readability
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=2))
        overlay = Image.new("RGB", canvas.size, (0, 0, 0))
        canvas = Image.blend(canvas, overlay, alpha=0.45)
    else:
        top_c, bot_c = _theme_colors(theme)
        canvas = _gradient_background((OG_WIDTH, OG_HEIGHT), top_c, bot_c)

    draw = ImageDraw.Draw(canvas)

    # Corner accent bar
    draw.rectangle([(0, 0), (OG_WIDTH, 6)], fill=(245, 158, 11))  # amber-500

    # ── Text layout ──
    name_font = _load_font(_FONT_CANDIDATES_BOLD, 80)
    tagline_font = _load_font(_FONT_CANDIDATES_REG, 38)
    footer_font = _load_font(_FONT_CANDIDATES_BOLD, 28)

    max_text_width = OG_WIDTH - (OG_PADDING * 2)

    # Vendor name (up to 2 lines)
    name = (vendor_name or "Vendor").strip()
    name_lines = _wrap_text(draw, name, name_font, max_text_width)[:2]

    # Tagline: prefer explicit tagline, else first specialty
    subtitle = (tagline or "").strip()
    if not subtitle and specialties:
        first = next((s for s in specialties if s and s.strip()), None)
        if first:
            subtitle = first.strip()
    sub_lines = _wrap_text(draw, subtitle, tagline_font, max_text_width)[:2] if subtitle else []

    # Measure total block height
    line_spacing_name = 10
    line_spacing_sub = 6
    total_h = 0
    for i, ln in enumerate(name_lines):
        bbox = draw.textbbox((0, 0), ln, font=name_font)
        total_h += (bbox[3] - bbox[1])
        if i < len(name_lines) - 1:
            total_h += line_spacing_name
    if sub_lines:
        total_h += 28  # gap
        for i, ln in enumerate(sub_lines):
            bbox = draw.textbbox((0, 0), ln, font=tagline_font)
            total_h += (bbox[3] - bbox[1])
            if i < len(sub_lines) - 1:
                total_h += line_spacing_sub

    # Vertically center the block, but bias slightly upward to leave room for footer
    y = max(OG_PADDING, (OG_HEIGHT - total_h) // 2 - 40)

    # Draw name
    for ln in name_lines:
        # soft shadow for legibility
        draw.text((OG_PADDING + 2, y + 2), ln, font=name_font, fill=(0, 0, 0))
        draw.text((OG_PADDING, y), ln, font=name_font, fill=(255, 255, 255))
        bbox = draw.textbbox((0, 0), ln, font=name_font)
        y += (bbox[3] - bbox[1]) + line_spacing_name

    # Draw subtitle
    if sub_lines:
        y += 18
        for ln in sub_lines:
            draw.text((OG_PADDING + 1, y + 1), ln, font=tagline_font, fill=(0, 0, 0))
            draw.text((OG_PADDING, y), ln, font=tagline_font, fill=(245, 211, 139))
            bbox = draw.textbbox((0, 0), ln, font=tagline_font)
            y += (bbox[3] - bbox[1]) + line_spacing_sub

    # Footer (market label) bottom-left
    footer_y = OG_HEIGHT - OG_PADDING - 28
    draw.text((OG_PADDING + 1, footer_y + 1), market_label, font=footer_font, fill=(0, 0, 0))
    draw.text((OG_PADDING, footer_y), market_label, font=footer_font, fill=(255, 255, 255))

    # Export
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def content_hash(*parts: Optional[str]) -> str:
    """Build a short content hash for cache busting."""
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()[:12]
