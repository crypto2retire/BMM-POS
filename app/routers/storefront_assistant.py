import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.models.studio_class import StudioClass
from app.models.class_registration import ClassRegistration
from app.routers.settings import get_setting, DEFAULT_SETTINGS

router = APIRouter(prefix="/storefront/assistant", tags=["public-assistant"])

_rate_limit_store: dict = defaultdict(list)
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 15


def _check_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if t > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    _rate_limit_store[client_ip].append(now)


SYSTEM_PROMPT = """You are the Bowenstreet Market shopping assistant. Bowenstreet Market is a vendor mall at 2837 Bowen St, Oshkosh WI 54901 with 120+ vendors selling handcrafted, vintage, and antique goods.

You help CUSTOMERS (not vendors or staff) with:
- Searching for items in the online shop
- Finding vendors and their booth showcases
- Answering questions about store hours, location, phone number, and policies
- Showing upcoming classes and workshops
- Helping customers register for classes

PERSONALITY:
- Warm, friendly, and enthusiastic about the market
- Knowledgeable about handcrafted, vintage, and antique goods
- Concise but helpful — don't write essays
- If a customer asks about something you can't help with (vendor accounts, POS, admin functions), politely explain you're the public shopping assistant and suggest they contact the store directly

IMPORTANT RULES:
- When showing items, mention the vendor name and price. If an item is on sale, highlight the sale price.
- When showing classes, include date, time, instructor, price, and spots available.
- When sharing store hours, format them nicely for the customer.
- For class registration, you need the customer's name, email, and optionally phone. Ask for these details.
- Never make up information. If your tools don't return results, say so honestly.
- Keep responses brief and scannable. Use short lists when showing multiple results.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_items",
            "description": "Search for items available in the online shop. Returns matching products with name, price, vendor, and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term to find items by name, description, or category"
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category name"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 8)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Get a list of all available item categories in the shop with item counts.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_vendors",
            "description": "Search for vendors/booths at Bowenstreet Market. Returns vendor names, booth numbers, and whether they have a showcase or landing page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term to find vendors by name"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_info",
            "description": "Get store information including hours, phone number, address, and policies.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_classes",
            "description": "List upcoming studio classes and workshops. Returns class title, date, time, instructor, price, and availability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter classes by category (e.g. painting, pottery)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "register_for_class",
            "description": "Register a customer for a studio class. Requires the class ID, customer name, and email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "integer",
                        "description": "The ID of the class to register for"
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Customer's full name"
                    },
                    "customer_email": {
                        "type": "string",
                        "description": "Customer's email address"
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "Customer's phone number (optional)"
                    },
                    "num_spots": {
                        "type": "integer",
                        "description": "Number of spots to reserve (default 1)"
                    }
                },
                "required": ["class_id", "customer_name", "customer_email"]
            }
        }
    },
]


def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Assistant not available")
    return key


async def _execute_tool(tool_name: str, args: dict, db: AsyncSession) -> str:
    if tool_name == "search_items":
        query_text = args.get("query", "")
        category = args.get("category")
        max_results = min(args.get("max_results", 8), 15)

        from app.models.booth_showcase import BoothShowcase

        q = (
            select(
                Item.id, Item.name, Item.description, Item.price,
                Item.sale_price, Item.category, Item.quantity,
                Item.image_path,
                Vendor.name.label("vendor_name"),
                Vendor.booth_number.label("vendor_booth"),
                BoothShowcase.title.label("booth_title"),
            )
            .join(Vendor, Item.vendor_id == Vendor.id)
            .outerjoin(BoothShowcase, BoothShowcase.vendor_id == Vendor.id)
            .where(Item.status == "active", Item.quantity > 0,
                   Vendor.is_active == True, Item.is_online == True)
            .where(or_(Item.image_path.isnot(None), Item.photo_urls != []))
        )
        if query_text:
            pattern = f"%{query_text}%"
            q = q.where(or_(
                Item.name.ilike(pattern),
                Item.description.ilike(pattern),
                Item.category.ilike(pattern),
            ))
        if category:
            q = q.where(Item.category.ilike(f"%{category}%"))

        q = q.order_by(Item.created_at.desc()).limit(max_results)
        result = await db.execute(q)
        rows = result.all()

        if not rows:
            return "No items found matching that search."

        lines = []
        for r in rows:
            price_str = f"${float(r.price):.2f}"
            if r.sale_price:
                price_str = f"~~${float(r.price):.2f}~~ **SALE ${float(r.sale_price):.2f}**"
            display_name = r.booth_title or r.vendor_name
            lines.append(
                f"- [{r.name}](/shop?item={r.id}) — {price_str} (by {display_name}, booth {r.vendor_booth or 'N/A'}, category: {r.category or 'uncategorized'})"
            )
        return f"Found {len(rows)} item(s):\n" + "\n".join(lines)

    elif tool_name == "get_categories":
        result = await db.execute(
            select(Item.category, func.count(Item.id))
            .where(Item.status == "active", Item.quantity > 0,
                   Item.category.isnot(None), Item.is_online == True)
            .group_by(Item.category)
            .order_by(func.count(Item.id).desc())
        )
        rows = result.all()
        if not rows:
            return "No categories found."
        lines = [f"- {cat} ({count} items)" for cat, count in rows]
        return "Available categories:\n" + "\n".join(lines)

    elif tool_name == "search_vendors":
        query_text = args.get("query", "")
        from app.models.booth_showcase import BoothShowcase

        q = (
            select(
                Vendor.id, Vendor.name, Vendor.booth_number,
                BoothShowcase.title.label("booth_title"),
                BoothShowcase.is_published.label("has_showcase"),
                BoothShowcase.landing_page_enabled.label("has_landing_page"),
                BoothShowcase.landing_slug.label("landing_slug"),
            )
            .outerjoin(BoothShowcase, BoothShowcase.vendor_id == Vendor.id)
            .where(Vendor.is_active == True)
            .where(or_(Vendor.role == "vendor", Vendor.is_vendor == True))
        )
        if query_text:
            pattern = f"%{query_text}%"
            q = q.where(or_(
                Vendor.name.ilike(pattern),
                BoothShowcase.title.ilike(pattern),
            ))

        q = q.order_by(Vendor.name).limit(20)
        result = await db.execute(q)
        rows = result.all()

        if not rows:
            return "No vendors found matching that search."

        lines = []
        for r in rows:
            display_name = r.booth_title or r.name
            parts = [f"- {display_name} (booth {r.booth_number or 'N/A'})"]
            if r.has_showcase:
                parts.append(" — [view booth showcase](/shop/booths.html)")
            if r.has_landing_page and r.landing_slug:
                parts.append(f" — [visit vendor page](/v/{r.landing_slug})")
            lines.append("".join(parts))
        return f"Found {len(rows)} vendor(s):\n" + "\n".join(lines)

    elif tool_name == "get_store_info":
        keys = [
            "store_name", "store_address", "store_phone", "store_email",
            "hours_monday", "hours_tuesday", "hours_wednesday",
            "hours_thursday", "hours_friday", "hours_saturday", "hours_sunday",
            "return_policy_text",
        ]
        info = {}
        for k in keys:
            val = await get_setting(db, k)
            info[k] = val if val is not None else DEFAULT_SETTINGS.get(k, "")

        return (
            f"Store: {info['store_name']}\n"
            f"Address: {info['store_address']}\n"
            f"Phone: {info['store_phone']}\n"
            f"Email: {info['store_email']}\n"
            f"Hours:\n"
            f"  Monday: {info['hours_monday']}\n"
            f"  Tuesday: {info['hours_tuesday']}\n"
            f"  Wednesday: {info['hours_wednesday']}\n"
            f"  Thursday: {info['hours_thursday']}\n"
            f"  Friday: {info['hours_friday']}\n"
            f"  Saturday: {info['hours_saturday']}\n"
            f"  Sunday: {info['hours_sunday']}\n"
            f"Return Policy: {info['return_policy_text']}"
        )

    elif tool_name == "list_classes":
        category = args.get("category")
        q = (
            select(StudioClass)
            .where(StudioClass.is_published == True,
                   StudioClass.is_cancelled == False,
                   StudioClass.class_date >= date.today())
            .order_by(StudioClass.class_date, StudioClass.start_time)
            .limit(15)
        )
        if category:
            q = q.where(StudioClass.category.ilike(f"%{category}%"))

        result = await db.execute(q)
        classes = result.scalars().all()

        if not classes:
            return "No upcoming classes found."

        lines = []
        for c in classes:
            spots_left = c.capacity - c.enrolled
            time_str = c.start_time.strftime("%-I:%M %p") if c.start_time else "TBD"
            end_str = f" - {c.end_time.strftime('%-I:%M %p')}" if c.end_time else ""
            price_str = f"${float(c.price):.2f}" if c.price else "Free"
            status = f"{spots_left} spots left" if spots_left > 0 else "FULL"
            lines.append(
                f"- [ID {c.id}] {c.title} — {c.class_date.strftime('%b %d, %Y')} at {time_str}{end_str} "
                f"with {c.instructor or 'TBD'} | {price_str} | {status}"
            )
        return f"Upcoming classes ({len(classes)}):\n" + "\n".join(lines)

    elif tool_name == "register_for_class":
        class_id = args.get("class_id")
        name = args.get("customer_name", "").strip()
        email = args.get("customer_email", "").strip().lower()
        phone = args.get("customer_phone", "").strip() or None
        try:
            num_spots = int(args.get("num_spots", 1))
        except (TypeError, ValueError):
            num_spots = 1

        if not class_id or not name or not email:
            return "ERROR: class_id, customer_name, and customer_email are required."

        if num_spots < 1 or num_spots > 10:
            return "ERROR: Must register for 1–10 spots."

        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email) or len(email) > 254:
            return "ERROR: Please provide a valid email address."

        if len(name) > 200 or len(name) < 1:
            return "ERROR: Please provide a valid name."

        from sqlalchemy import with_for_update
        result = await db.execute(
            select(StudioClass).where(
                StudioClass.id == class_id,
                StudioClass.is_published == True,
                StudioClass.is_cancelled == False,
            ).with_for_update()
        )
        cls = result.scalar_one_or_none()
        if not cls:
            return "ERROR: Class not found or not available."
        if cls.class_date < date.today():
            return "ERROR: This class has already passed."

        spots_left = cls.capacity - cls.enrolled
        if num_spots > spots_left:
            return f"ERROR: Only {spots_left} spot(s) remaining in this class."

        existing = await db.execute(
            select(ClassRegistration).where(
                ClassRegistration.class_id == class_id,
                ClassRegistration.customer_email == email,
                ClassRegistration.status == "confirmed",
            )
        )
        if existing.scalar_one_or_none():
            return f"You're already registered for {cls.title}!"

        reg = ClassRegistration(
            class_id=class_id,
            customer_name=name,
            customer_email=email,
            customer_phone=phone,
            num_spots=num_spots,
            status="confirmed",
        )
        db.add(reg)
        cls.enrolled += num_spots
        await db.commit()

        return (
            f"Successfully registered {name} for {cls.title} on "
            f"{cls.class_date.strftime('%b %d, %Y')}! "
            f"A confirmation has been noted for {email}."
        )

    return f"ERROR: Unknown tool '{tool_name}'."


class PublicChatRequest(BaseModel):
    message: str
    page_context: Optional[str] = None


class PublicChatResponse(BaseModel):
    reply: str


@router.post("/chat")
async def public_chat(
    data: PublicChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _check_rate_limit(request)
    api_key = _get_api_key()

    if not data.message or not data.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    if len(data.message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long")

    extra = ""
    if data.page_context:
        extra = f"\n\nThe customer is currently on: {data.page_context}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + extra},
        {"role": "user", "content": data.message},
    ]

    for _round in range(3):
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "max_tokens": 400,
            "messages": messages,
            "tools": TOOLS,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "https://bowenstreetmarket.com",
                        "X-Title": "Bowenstreet Market Public Assistant",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException:
                return PublicChatResponse(reply="I'm sorry, I'm having trouble connecting right now. Please try again in a moment.")
            except httpx.RequestError:
                return PublicChatResponse(reply="I'm having a connection issue. Please try again shortly.")

        if resp.status_code != 200:
            return PublicChatResponse(reply="I'm temporarily unavailable. Please try again in a moment.")

        try:
            body = resp.json()
            choice = body["choices"][0]
            assistant_message = choice["message"]
            finish_reason = choice.get("finish_reason", "")
            tool_calls = assistant_message.get("tool_calls")
        except (KeyError, IndexError, ValueError) as exc:
            print(f"Public assistant: malformed LLM response: {exc}", file=sys.stderr, flush=True)
            return PublicChatResponse(reply="I'm having a little trouble right now. Could you try asking again?")

        if not (finish_reason == "tool_calls" or tool_calls):
            reply = assistant_message.get("content") or "I'm not sure how to help with that. Could you rephrase your question?"
            return PublicChatResponse(reply=reply)

        messages.append({
            "role": "assistant",
            "content": assistant_message.get("content"),
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
            except json.JSONDecodeError:
                fn_args = {}

            tool_result = await _execute_tool(fn_name, fn_args, db)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

    reply = messages[-1].get("content", "") if messages else ""
    return PublicChatResponse(reply=reply or "I found some information but had trouble formatting it. Could you try asking again?")
