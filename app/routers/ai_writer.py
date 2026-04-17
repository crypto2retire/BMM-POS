import os
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


def build_landing_faq_prompt(req: AIWriteRequest, vendor_name: str, booth: str, items_summary: str) -> str:
    base = (
        f"You are an SEO copywriter for Bowenstreet Market, a vintage and handcrafted goods "
        f"marketplace at 2837 Bowen St, Oshkosh, Wisconsin. "
        f"Vendor: {vendor_name}. Booth: {booth}. They sell: {items_summary}. "
    )
    if req.action == "improve" and req.existing_content:
        base += (
            f"The vendor has these FAQs on their landing page:\n\n"
            f"{req.existing_content}\n\n"
            f"Improve them — make each question natural (how a real customer would ask it), "
            f"ensure answers are helpful and include relevant keywords for local SEO. "
            f"Return ONLY the improved FAQs in the same format."
        )
    else:
        base += (
            f"Write 5-7 FAQs for the vendor's landing page. These should answer questions "
            f"real customers would search for, like:\n"
            f"- What kind of items does this vendor sell?\n"
            f"- Where are they located? (Bowenstreet Market, 2837 Bowen St, Oshkosh WI)\n"
            f"- What are the market hours?\n"
            f"- Do they take custom orders?\n"
            f"- How can I contact them?\n"
            f"Include at least 2 location-specific questions for local SEO. "
            f"Format each FAQ as: Q: [question]\\nA: [answer]\\n\\n"
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


async def call_ai(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="AI assistant is not configured")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
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
                    "max_tokens": 500,
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

    elif req.content_type in ("booth_description", "landing_about", "landing_faq", "seo_meta"):
        items_summary, showcase = await get_vendor_context(db, current_user)
        existing_title = showcase.title if showcase else None

        if req.content_type == "booth_description":
            user_prompt = build_booth_prompt(req, vendor_name, booth, items_summary, existing_title)
        elif req.content_type == "landing_about":
            user_prompt = build_landing_about_prompt(req, vendor_name, booth, items_summary)
        elif req.content_type == "landing_faq":
            user_prompt = build_landing_faq_prompt(req, vendor_name, booth, items_summary)
        else:
            user_prompt = build_seo_prompt(req, vendor_name, booth, items_summary)

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

    text = await call_ai(system_prompt, user_prompt)

    return AIWriteResponse(content=text, tone_used=tone_key)


@router.get("/tones")
async def list_tones():
    return [
        {"key": k, "label": k.capitalize(), "description": v}
        for k, v in TONES.items()
    ]
