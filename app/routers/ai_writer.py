import os
import json
import re
import logging
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor
from app.models.item import Item
from app.models.booth_showcase import BoothShowcase
from app.routers.settings import require_role_feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-writer"])


async def _load_market_context(db) -> str:
    from app.models.store_setting import StoreSetting
    from sqlalchemy import select
    keys = ["store_address","store_phone","store_email",
            "hours_monday","hours_tuesday","hours_wednesday","hours_thursday",
            "hours_friday","hours_saturday","hours_sunday"]
    result = await db.execute(select(StoreSetting).where(StoreSetting.key.in_(keys)))
    rows = {r.key: r.value for r in result.scalars().all()}
    return "\n".join([
        "Market name: Bowenstreet Market",
        f"Address: {rows.get('store_address','2837 Bowen St, Oshkosh, WI 54901')}",
        f"Phone: {rows.get('store_phone','(920) 289-0252')}",
        f"Email: {rows.get('store_email','info@bowenstreetmarket.com')}",
        f"Hours — Mon: {rows.get('hours_monday','Closed')}",
        f"Hours — Tue: {rows.get('hours_tuesday','Closed')}",
        f"Hours — Wed: {rows.get('hours_wednesday','10:00 AM - 6:00 PM')}",
        f"Hours — Thu: {rows.get('hours_thursday','10:00 AM - 6:00 PM')}",
        f"Hours — Fri: {rows.get('hours_friday','10:00 AM - 6:00 PM')}",
        f"Hours — Sat: {rows.get('hours_saturday','10:00 AM - 4:00 PM')}",
        f"Hours — Sun: {rows.get('hours_sunday','10:00 AM - 4:00 PM')}",
        "Parking: Free on-site parking lot at the building.",
        "Region: Oshkosh, Wisconsin (Fox Valley / Winnebago County, near US-41).",
    ])

TONES = {
    "warm": "Write in a warm, welcoming, heartfelt tone — like a friend inviting someone to visit.",
    "professional": "Write in a polished, professional tone — confident and credible without being stiff.",
    "casual": "Write in a relaxed, casual, conversational tone — easy-going and approachable.",
    "playful": "Write in a fun, playful, energetic tone — cheerful and engaging.",
    "rustic": "Write in a rustic, down-to-earth tone — cozy, homey, and charming.",
    "elegant": "Write in a refined, elegant tone — sophisticated and tasteful.",
}

DEFAULT_TONE = "warm"


class AIWriteRequest(BaseModel):
    content_type: str
    tone: str = DEFAULT_TONE
    action: str = "write"
    existing_content: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AIWriteResponse(BaseModel):
    content: str
    tone_used: str


# ─────────────────────────────────────────────────────────────
# Landing Setup Assistant — one-shot populate of multiple fields
# ─────────────────────────────────────────────────────────────

# Allowlist of fields the setup assistant can generate.
# Keys are stable; the frontend maps them to DOM elements.
LANDING_SETUP_FIELDS = {
    "tagline",            # single string, 6-12 words
    "specialties",        # list[str], 4-6 items
    "story_origin",
    "story_specialty",
    "story_process",
    "story_values",
    "story_whats_new",
    "meta_title",
    "meta_description",
    "faq",
}


class LandingSetupRequest(BaseModel):
    description: str
    tone: str = DEFAULT_TONE
    needed_fields: list[str]  # subset of LANDING_SETUP_FIELDS


class LandingSetupResponse(BaseModel):
    fields: Dict[str, Any]        # key -> generated value (str or list[str])
    missing: list[str]            # keys that were requested but AI did not return
    tone_used: str


def build_product_prompt(req: AIWriteRequest, vendor_name: str) -> str:
    ctx = req.context or {}
    name = ctx.get("item_name", "an item")
    category = ctx.get("item_category", "")
    price = ctx.get("item_price", "")

    base = (
        f"You are a copywriter for Bowenstreet Market, a vintage and handcrafted goods "
        f"marketplace in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. "
    )

    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this product description for '{name}'"
            f"{' in the ' + category + ' category' if category else ''}"
            f"{' priced at ' + price if price else ''}:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve this description — fix grammar, make it more compelling, "
            f"and keep the vendor's voice and intent. Keep it to 2-3 sentences. "
            f"Return ONLY the improved description text, nothing else."
        )
    else:
        base += (
            f"Write a compelling 2-3 sentence product description for '{name}'"
            f"{' in the ' + category + ' category' if category else ''}"
            f"{' priced at ' + price if price else ''}. "
            f"Make customers want to pick it up. "
            f"Return ONLY the description text, nothing else."
        )

    return base


def build_booth_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str, existing_title: str = None) -> str:
    base = (
        f"You are a copywriter for Bowenstreet Market, a vintage and handcrafted goods "
        f"marketplace in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. "
    )
    if existing_title:
        base += f"Booth name: {existing_title}. "
    base += f"They sell: {items_summary}. "

    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this booth description:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve this description — fix grammar, make it more inviting, "
            f"and keep the vendor's voice. Write 2-3 short paragraphs (80-120 words). "
            f"Do NOT use hashtags or emojis. Return ONLY the improved description."
        )
    else:
        base += (
            f"Write 2-3 short paragraphs (80-120 words) that would make customers "
            f"want to visit this booth. Be genuine and specific to what they sell. "
            f"Do NOT use hashtags or emojis. Return ONLY the description text."
        )

    return base


def build_landing_about_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str) -> str:
    base = (
        f"You are a copywriter for Bowenstreet Market, a vintage and handcrafted goods "
        f"marketplace in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. "
        f"They sell: {items_summary}. "
    )

    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this 'About' section for their landing page:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve this — fix grammar, add warmth, make it tell their story better. "
            f"Keep it 3-4 paragraphs (150-250 words). "
            f"Return ONLY the improved text."
        )
    else:
        base += (
            f"Write a compelling 'About' section for the vendor's landing page. "
            f"Tell their story in 3-4 paragraphs (150-250 words). "
            f"Include what they sell, what makes their work special, and why customers love visiting. "
            f"Do NOT use hashtags or emojis. Return ONLY the about text."
        )

    return base


def build_landing_faq_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str, market_context: str) -> str:
    base = (
        f"You are an SEO copywriter for Bowenstreet Market, a vintage and handcrafted "
        f"goods marketplace. Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}.\n\n"
        f"MARKET FACTS (use these verbatim — never output placeholders like [Insert ...]):\n{market_context}\n\n"
    )
    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor has these FAQs:\n\n{req.existing_content}\n\n"
            f"Improve them — questions should sound natural, answers helpful and keyword-rich for local SEO. "
            f"Replace any bracketed placeholders like '[Insert hours]' or '[Exit Number]' with real values from MARKET FACTS. "
            f"Return ONLY the improved FAQs in the same format."
        )
    else:
        base += (
            f"Write 5-7 FAQs real customers would search. Include: what they sell, market location, hours, parking, custom orders, contact.\n"
            f"CRITICAL RULES:\n"
            f"- Use exact hours, address, and phone from MARKET FACTS.\n"
            f"- NEVER write bracketed placeholders like '[Insert ...]', '[Exit Number]', '[fill in]'.\n"
            f"- If a fact isn't in MARKET FACTS or vendor info, omit that question — do not fabricate.\n"
            f"- Include at least 2 location-specific questions for local SEO.\n"
            f"- Format: Q: [question]\\nA: [answer]\\n\\n\n"
            f"Return ONLY the FAQs, no intro or outro."
        )
    return base


# ── Phase 2: Structured story blocks ──
# Each block answers ONE focused question so the combined output feels
# genuinely distinct across vendors (instead of the usual "AI about" slop).
STORY_BLOCK_PROMPTS = {
    "origin": {
        "question": "How did you start?",
        "guidance": (
            "Write a short origin story — 2–3 sentences. Lead with a concrete moment, year, or "
            "object that started it all. Avoid generic lines like 'passionate about vintage'. "
            "Do not use hashtags or emojis."
        ),
    },
    "specialty": {
        "question": "What do you specialize in?",
        "guidance": (
            "Describe the specific thing this vendor hunts for, makes, or curates. 2–3 sentences. "
            "Name concrete categories, eras, or techniques (e.g. 'mid-century carnival glass', "
            "'hand-poured tallow soap'). Do not use hashtags or emojis."
        ),
    },
    "process": {
        "question": "How do you source or create it?",
        "guidance": (
            "Walk the customer through how pieces arrive at the booth — estate sales, auctions, "
            "workshop time, restoration. 2–4 sentences. Specific verbs beat adjectives. "
            "Do not use hashtags or emojis."
        ),
    },
    "values": {
        "question": "Why does this matter to you?",
        "guidance": (
            "One short paragraph (2–3 sentences) on what the vendor cares about — craftsmanship, "
            "sustainability, honoring history, supporting local makers. Personal, not corporate. "
            "Do not use hashtags or emojis."
        ),
    },
    "whats_new": {
        "question": "What just landed in the booth?",
        "guidance": (
            "2–3 sentences teasing what's new or seasonal right now. Reference actual item "
            "categories when available. Add urgency (\"just in\", \"this week\") without being salesy. "
            "Do not use hashtags or emojis."
        ),
    },
}


def build_landing_story_prompt(
    req: AIWriteRequest,
    vendor_name: str,
    booth: str,
    items_summary: str,
    block_key: str,
    showcase_extras: dict | None = None,
) -> str:
    spec = STORY_BLOCK_PROMPTS.get(block_key)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unknown story block: {block_key}")

    extras = showcase_extras or {}
    specialties = extras.get("specialties") or []
    era = extras.get("era") or []
    materials = extras.get("materials") or []
    year_started = extras.get("year_started")
    tagline = extras.get("tagline")

    hints = []
    if specialties: hints.append(f"Specialties: {', '.join(specialties[:6])}.")
    if era:         hints.append(f"Eras: {', '.join(era[:4])}.")
    if materials:   hints.append(f"Materials: {', '.join(materials[:6])}.")
    if year_started: hints.append(f"Vendor started in {year_started}.")
    if tagline:     hints.append(f"Tagline: {tagline}.")
    hint_str = " ".join(hints)

    base = (
        f"You are a copywriter for Bowenstreet Market, a vintage and handcrafted marketplace "
        f"at 437 Bowen St, Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. "
    )
    if hint_str:
        base += hint_str + " "

    base += f"You are writing the answer to ONE question: '{spec['question']}'. {spec['guidance']} "

    if req.action == "improve" and req.existing_content:
        base += (
            f"\n\nThe vendor wrote this draft:\n\"{req.existing_content}\"\n\n"
            "Tighten it, fix grammar, keep their voice. Return ONLY the improved text, no labels."
        )
    else:
        base += "Return ONLY the paragraph text itself — no question label, no intro, no outro."

    return base


def build_seo_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str) -> str:
    base = (
        f"You are an SEO copywriter for Bowenstreet Market in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. "
    )

    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this SEO meta description:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve it for search engines — make it 120-155 characters, "
            f"include relevant keywords, and make it click-worthy. "
            f"Return ONLY the improved meta description text."
        )
    else:
        base += (
            f"Write an SEO meta description (120-155 characters) for the vendor's landing page. "
            f"Include relevant keywords and make it click-worthy in search results. "
            f"Return ONLY the meta description text."
        )

    return base


def build_seo_title_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str) -> str:
    base = (
        f"You are an SEO copywriter for Bowenstreet Market in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. "
    )
    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this page title:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve it for search engines — keep it under 60 characters, "
            f"front-load the vendor's specialty, and end with ' | Bowenstreet Market'. "
            f"Return ONLY the improved title, no quotes."
        )
    else:
        base += (
            f"Write an SEO page title under 60 characters. Front-load the vendor's "
            f"specialty (what they're best known for), then the vendor name, ending "
            f"with ' | Bowenstreet Market'. Example format: 'Mid-Century Glassware — "
            f"Grandma's Treasures | Bowenstreet Market'. "
            f"Return ONLY the title, no quotes."
        )
    return base


def build_landing_tagline_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str, showcase_extras: dict | None = None) -> str:
    extras = showcase_extras or {}
    specialties = extras.get("specialties") or []
    hint = ""
    if specialties:
        hint = f"Known for: {', '.join(specialties[:4])}. "

    base = (
        f"You are a copywriter for Bowenstreet Market, a vintage and handcrafted "
        f"goods marketplace in Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. {hint}"
    )
    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor wrote this tagline:\n\n"
            f'"{req.existing_content}"\n\n'
            f"Improve it — tighter, more distinctive, 6-12 words. Specific beats generic "
            f"('Mid-century glassware, one cabinet at a time' beats 'Quality vintage finds'). "
            f"No hashtags or emojis. Return ONLY the tagline, no quotes."
        )
    else:
        base += (
            f"Write a short, distinctive tagline for the vendor's hero banner. "
            f"6-12 words. Concrete and specific — reference what they actually sell. "
            f"No hashtags or emojis. Return ONLY the tagline, no quotes."
        )
    return base


def build_landing_specialties_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str) -> str:
    base = (
        f"You are an SEO copywriter for Bowenstreet Market, a vintage and handcrafted "
        f"goods marketplace at 2837 Bowen St, Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. "
    )
    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor listed these specialties (comma-separated):\n\n"
            f'"{req.existing_content}"\n\n'
            f"Tighten and clean them up. Keep them as concrete, searchable categories "
            f"(e.g. 'Depression glass', 'Mid-century barware', 'Carnival glass'). "
            f"Return 4-6 items max as a SINGLE comma-separated line. "
            f"No hashtags, no numbering, no extra text."
        )
    else:
        base += (
            f"Write 4-6 specialty categories this vendor is known for, as a single "
            f"comma-separated line. Use searchable terms real shoppers would Google "
            f"(e.g. 'Depression glass, Mid-century barware, Carnival glass'). "
            f"No hashtags, no numbering, no extra text. "
            f"Return ONLY the comma-separated line."
        )
    return base


async def get_vendor_context(db: AsyncSession, vendor: Vendor):
    items_result = await db.execute(
        select(Item.name, Item.category).where(
            Item.vendor_id == vendor.id, Item.status == "active"
        ).limit(20)
    )
    items = items_result.fetchall()
    items_summary = ", ".join(
        [f"{r.name} ({r.category})" if r.category else r.name for r in items]
    ) if items else "various items"

    sc_result = await db.execute(
        select(BoothShowcase).where(BoothShowcase.vendor_id == vendor.id)
    )
    showcase = sc_result.scalar_one_or_none()

    return items_summary, showcase


async def call_ai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 500,
    timeout_s: float = 30.0,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant is not configured")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
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
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(status_code=504, detail="AI assistant timed out — please try again")

    if not resp.is_success:
        raise HTTPException(status_code=502, detail="AI assistant unavailable — please try again later")

    body = resp.json()
    text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="AI returned an empty response — please try again")

    return text


@router.post("/write", response_model=AIWriteResponse)
async def ai_write(
    req: AIWriteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role_feature("role_view_ai_assistant")),
):
    tone_key = req.tone if req.tone in TONES else DEFAULT_TONE
    tone_instruction = TONES[tone_key]

    system_prompt = (
        f"You are a helpful copywriter for Bowenstreet Market, a vintage and handcrafted "
        f"goods marketplace in Oshkosh, Wisconsin. {tone_instruction} "
        f"Never use hashtags or emojis unless specifically asked."
    )

    vendor_name = current_user.name
    booth = current_user.booth_number or "their booth"

    if req.content_type == "product_description":
        user_prompt = build_product_prompt(req, vendor_name)

    elif req.content_type in (
        "booth_description",
        "landing_about",
        "landing_faq",
        "seo_meta",
        "seo_meta_title",
        "landing_tagline",
        "landing_specialties",
    ):
        items_summary, showcase = await get_vendor_context(db, current_user)
        existing_title = showcase.title if showcase else None

        if req.content_type == "booth_description":
            user_prompt = build_booth_prompt(req, vendor_name, booth, items_summary, existing_title)
        elif req.content_type == "landing_about":
            user_prompt = build_landing_about_prompt(req, vendor_name, booth, items_summary)
        elif req.content_type == "landing_faq":
            market_context = await _load_market_context(db)
            user_prompt = build_landing_faq_prompt(req, vendor_name, booth, items_summary, market_context)
        elif req.content_type == "seo_meta":
            user_prompt = build_seo_prompt(req, vendor_name, booth, items_summary)
        elif req.content_type == "seo_meta_title":
            user_prompt = build_seo_title_prompt(req, vendor_name, booth, items_summary)
        elif req.content_type == "landing_tagline":
            showcase_extras = {}
            if showcase is not None:
                showcase_extras = {
                    "specialties": getattr(showcase, "landing_specialties", None) or [],
                    "era": getattr(showcase, "landing_era", None) or [],
                    "materials": getattr(showcase, "landing_materials", None) or [],
                    "year_started": getattr(showcase, "landing_year_started", None),
                }
            user_prompt = build_landing_tagline_prompt(
                req, vendor_name, booth, items_summary, showcase_extras
            )
        else:  # landing_specialties
            user_prompt = build_landing_specialties_prompt(req, vendor_name, booth, items_summary)

    elif req.content_type.startswith("story_"):
        # story_origin | story_specialty | story_process | story_values | story_whats_new
        block_key = req.content_type[len("story_"):]
        items_summary, showcase = await get_vendor_context(db, current_user)
        extras = {}
        if showcase is not None:
            extras = {
                "specialties": getattr(showcase, "landing_specialties", None) or [],
                "era": getattr(showcase, "landing_era", None) or [],
                "materials": getattr(showcase, "landing_materials", None) or [],
                "year_started": getattr(showcase, "landing_year_started", None),
                "tagline": getattr(showcase, "landing_tagline", None),
            }
        user_prompt = build_landing_story_prompt(
            req, vendor_name, booth, items_summary, block_key, extras
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {req.content_type}")

    max_tokens_for_type = 1500 if req.content_type == "landing_faq" else 500
    text = await call_ai(system_prompt, user_prompt, max_tokens=max_tokens_for_type)

    return AIWriteResponse(content=text, tone_used=tone_key)


def _setup_field_schema_line(field_key: str) -> str:
    """Return the per-field instruction line used inside the JSON schema block."""
    return {
        "tagline": '"tagline": "6-12 word distinctive tagline (no quotes, no brand name prefix, no hashtags)"',
        "specialties": '"specialties": ["4 to 6 short searchable category phrases, each 1-3 words, Title Case"]',
        "story_origin": '"story_origin": "2-4 sentences about how they got started / what pulled them into this"',
        "story_specialty": '"story_specialty": "2-4 sentences on what they are known for and what they specialize in"',
        "story_process": '"story_process": "2-4 sentences on how they source, restore, curate, or make"',
        "story_values": '"story_values": "2-4 sentences on what they believe in — craftsmanship, history, sustainability, etc."',
        "story_whats_new": '"story_whats_new": "2-4 sentences on what is fresh in their booth right now"',
        "meta_title": '"meta_title": "Under 60 characters. End with \' | Bowenstreet Market\'. No quotes."',
        "meta_description": '"meta_description": "120-160 characters, plain language, no all-caps, no hashtags."',
        "faq": '"faq": "3-5 question/answer pairs, each formatted exactly as \\"Q: ...\\\\nA: ...\\" separated by a blank line. Questions under 90 characters, answers 1-3 sentences."',
    }.get(field_key, "")


def build_landing_setup_prompt(
    description: str,
    needed_fields: list[str],
    vendor_name: str,
    booth: str,
    items_summary: str,
    market_context: str,
) -> str:
    """Build a single prompt asking Gemini for a JSON object containing ONLY the needed fields."""
    schema_lines = []
    for key in needed_fields:
        line = _setup_field_schema_line(key)
        if line:
            schema_lines.append("  " + line)
    schema_body = ",\n".join(schema_lines)

    return (
        f"A vendor at Bowenstreet Market has described their booth in their own words. "
        f"Use their description AND their actual inventory to draft a consistent, specific, "
        f"distinctive first draft of their landing-page content. Do not invent products they do not sell.\n\n"
        f"VENDOR: {vendor_name}\n"
        f"BOOTH: {booth}\n\n"
        f"MARKET FACTS (use these verbatim — never output placeholders like [Insert ...]):\n{market_context}\n\n"
        f"VENDOR'S DESCRIPTION (in their own words):\n"
        f'"""\n{description.strip()}\n"""\n\n'
        f"SAMPLE INVENTORY FROM THEIR BOOTH:\n{items_summary or 'No inventory listed yet.'}\n\n"
        f"RULES:\n"
        f"- Write in a distinctive voice — avoid generic antique-mall phrases like 'treasures', "
        f"'hidden gems', 'something for everyone', 'vintage and more'.\n"
        f"- Use concrete nouns from their inventory and description whenever possible.\n"
        f"- Do not invent product categories they did not mention or stock.\n"
        f"- Never use hashtags or emojis.\n"
        f"- Never use the phrase 'one-stop shop'.\n"
        f"- NEVER write bracketed placeholders like '[Insert hours]', '[Exit Number]', '[fill in]'. "
        f"Use real values from MARKET FACTS, or omit the detail entirely.\n\n"
        f"OUTPUT: Return ONLY valid JSON — no prose before or after, no markdown fences — matching this exact shape:\n"
        f"{{\n{schema_body}\n}}\n"
    )


def _strip_json_fences(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` fences. Strip them defensively."""
    t = text.strip()
    # Remove leading/trailing code fences
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


@router.post("/landing-setup", response_model=LandingSetupResponse)
async def landing_setup(
    req: LandingSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role_feature("role_view_ai_assistant")),
):
    # ── Validate description ──────────────────────────────────────
    desc = (req.description or "").strip()
    if len(desc) < 30:
        raise HTTPException(status_code=400, detail="Description must be at least 30 characters.")
    if len(desc) > 4000:
        raise HTTPException(status_code=400, detail="Description must be under 4000 characters.")

    # ── Validate needed fields against allowlist ──────────────────
    if not req.needed_fields:
        raise HTTPException(status_code=400, detail="No fields requested.")
    needed = [f for f in req.needed_fields if f in LANDING_SETUP_FIELDS]
    if not needed:
        raise HTTPException(status_code=400, detail="No valid fields requested.")

    tone_key = req.tone if req.tone in TONES else DEFAULT_TONE
    tone_instruction = TONES[tone_key]

    # ── Build prompts ─────────────────────────────────────────────
    system_prompt = (
        f"You are a helpful copywriter for Bowenstreet Market, a vintage and handcrafted "
        f"goods marketplace in Oshkosh, Wisconsin. {tone_instruction} "
        f"You return strict JSON only — no prose, no markdown fences."
    )

    items_summary, _showcase = await get_vendor_context(db, current_user)
    market_context = await _load_market_context(db)
    user_prompt = build_landing_setup_prompt(
        description=desc,
        needed_fields=needed,
        vendor_name=current_user.name,
        booth=current_user.booth_number or "their booth",
        items_summary=items_summary,
        market_context=market_context,
    )

    # ── Call AI (bigger token budget than single-field /write) ────
    raw = await call_ai(system_prompt, user_prompt, max_tokens=2500, timeout_s=45.0)
    cleaned = _strip_json_fences(raw)

    # ── Parse JSON defensively ────────────────────────────────────
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Best-effort salvage: find the first/last braces
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first != -1 and last != -1 and last > first:
            try:
                parsed = json.loads(cleaned[first:last + 1])
            except Exception:
                logging.warning("landing_setup: failed to parse JSON. Raw: %s", raw[:400])
                raise HTTPException(status_code=502, detail="AI returned malformed output — please try again.")
        else:
            logging.warning("landing_setup: no JSON object found. Raw: %s", raw[:400])
            raise HTTPException(status_code=502, detail="AI returned malformed output — please try again.")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="AI returned unexpected shape — please try again.")

    # ── Coerce types + filter to requested fields ─────────────────
    result: Dict[str, Any] = {}
    missing: list[str] = []
    for key in needed:
        if key not in parsed:
            missing.append(key)
            continue
        val = parsed[key]
        if key == "specialties":
            if isinstance(val, list):
                cleaned_list = [str(x).strip() for x in val if str(x).strip()]
                if cleaned_list:
                    result[key] = cleaned_list[:8]
                else:
                    missing.append(key)
            elif isinstance(val, str) and val.strip():
                # Comma-separated fallback
                cleaned_list = [p.strip() for p in val.split(",") if p.strip()]
                if cleaned_list:
                    result[key] = cleaned_list[:8]
                else:
                    missing.append(key)
            else:
                missing.append(key)
        else:
            if isinstance(val, (list, dict)):
                # Flatten arrays/objects to a readable string
                val = json.dumps(val) if isinstance(val, dict) else "\n".join(str(x) for x in val)
            text = str(val or "").strip().strip('"').strip("'").strip()
            if text:
                result[key] = text
            else:
                missing.append(key)

    return LandingSetupResponse(fields=result, missing=missing, tone_used=tone_key)


@router.get("/tones")
async def list_tones():
    return [
        {"key": k, "label": k.capitalize(), "description": v}
        for k, v in TONES.items()
    ]
