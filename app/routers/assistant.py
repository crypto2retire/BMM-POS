import json
import os
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.routers.auth import get_current_user
from app.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from app.services.barcode import generate_sku

router = APIRouter(prefix="/assistant", tags=["assistant"])

SYSTEM_PROMPT = """You are the Bowenstreet Market assistant. Bowenstreet Market is a vendor mall at 2837 Bowen St, Oshkosh WI 54901 with over 120 vendors selling handcrafted, vintage, and antique goods.

ADMIN/CASHIER CONTEXT:
If the user is an admin or cashier (not a vendor), inventory tool calls require knowing which vendor to act on.
For list_items: you may list all items across all vendors — do not require a vendor filter.
For add_item, edit_item, archive_item: if a vendor is not clear from the conversation, ask "Which vendor's items should I manage?" before proceeding.
Admins can also answer questions about the system, vendor management, reports, and POS operations.

You can take real actions in the system — adding, editing, and archiving items directly through conversation.

CAPABILITIES:
- Add new items to inventory (use add_item tool)
- Edit existing items (use edit_item tool — always list_items or get_item first to find the ID)
- Archive items that are sold or no longer available (use archive_item tool)
- List and search inventory (use list_items tool)
- Look up item details (use get_item tool)
- Write product descriptions and suggest categories
- Analyze photos to suggest item details

CONVERSATION STYLE:
- Be friendly and efficient. Get things done in as few messages as possible.
- When adding an item, only ask for what you need. Name and price are required. Everything else is optional — ask once if they want to add more details, don't ask field by field.
- When editing, confirm what you changed after doing it.
- When archiving, confirm before doing it: "Just to confirm — archive [item name]? It won't show in the POS anymore."
- Always confirm actions after completing them.
- Keep responses short. This is a mobile interface.

ADDING ITEMS — example flow:
Vendor: "Add a blue ceramic vase, $45"
Assistant: [calls add_item with name="Blue Ceramic Vase", price=45, category="Decor"]
Assistant: "Added! Blue Ceramic Vase at $45. Want to add a description or set it as available online?"

EDITING ITEMS — always find the item first:
Vendor: "Change the price on my oak table to $280"
Assistant: [calls list_items with search="oak table"] then [calls edit_item with item_id=X, price=280]
Assistant: "Done! Oak Dining Table updated to $280."

SALE PRICES — explain automatic activation:
When setting a sale price, remind vendors: sale prices activate and deactivate automatically based on the dates they set. No manual steps needed.

PAYOUT INFO:
- Rent is deducted from balance on the 27th of each month
- Payouts are processed on the 1st of each month via Zelle
- Balance shown on dashboard is their current earnings minus any deductions

WRITING DESCRIPTIONS:
- Start with the most important keyword naturally in the first sentence
- Include material, age/era if vintage, condition, dimensions if relevant
- Write 2-3 sentences, warm and inviting tone
- End with a detail that helps the buyer picture owning it
- Do NOT use the words "unique", "amazing", or "beautiful"

PHOTO ANALYSIS:
If given a photo, identify the item type, suggest a name, category, price range based on typical resale values, and write a description. Then ask if they want to add it."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_item",
            "description": "Add a new item to the vendor's inventory",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Item name"},
                    "vendor_id": {"type": "integer", "description": "Vendor ID — required when acting on behalf of a specific vendor (admin/cashier use)"},
                    "category": {"type": "string", "description": "Category such as Jewelry, Furniture, Vintage, Art, Handcrafted, Clothing, Books, Decor"},
                    "price": {"type": "number", "description": "Regular price in dollars"},
                    "description": {"type": "string", "description": "Item description"},
                    "quantity": {"type": "integer", "description": "Number in stock, default 1"},
                    "sale_price": {"type": "number", "description": "Sale price if on sale"},
                    "sale_start": {"type": "string", "description": "Sale start date YYYY-MM-DD"},
                    "sale_end": {"type": "string", "description": "Sale end date YYYY-MM-DD"},
                    "is_online": {"type": "boolean", "description": "Whether to show on website"},
                    "is_tax_exempt": {"type": "boolean", "description": "Whether item is tax exempt"},
                },
                "required": ["name", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_item",
            "description": "Edit an existing item in the vendor's inventory",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "The ID of the item to edit"},
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "price": {"type": "number"},
                    "description": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "sale_price": {"type": "number"},
                    "sale_start": {"type": "string"},
                    "sale_end": {"type": "string"},
                    "is_online": {"type": "boolean"},
                    "is_tax_exempt": {"type": "boolean"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archive_item",
            "description": "Archive (remove) an item so it no longer appears in the POS or website. Does not permanently delete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "The ID of the item to archive"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_items",
            "description": "List the vendor's current inventory items, optionally filtered by status or category",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: active, sold, removed. Default active."},
                    "vendor_id": {"type": "integer", "description": "Filter by vendor ID. Omit to list all items (admin only)."},
                    "category": {"type": "string", "description": "Filter by category name"},
                    "search": {"type": "string", "description": "Search by item name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_item",
            "description": "Get details of a specific item by ID or name",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "Item ID"},
                    "name": {"type": "string", "description": "Item name to search for"},
                },
            },
        },
    },
]


def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Assistant not configured. Please add your OpenRouter API key.",
        )
    return key


async def _execute_tool(
    tool_name: str,
    tool_args: dict,
    vendor: Vendor,
    db: AsyncSession,
) -> tuple[str, Optional[str], Optional[int]]:
    """Execute a tool call directly via SQLAlchemy.
    Returns (result_text, action_taken, item_id).
    """

    is_vendor = vendor.role == "vendor"

    if tool_name == "add_item":
        # For admin/cashier, vendor_id must be in tool_args; fall back to own id for vendors
        target_vendor_id = tool_args.get("vendor_id") if not is_vendor else vendor.id
        if not target_vendor_id:
            return "ERROR: vendor_id is required for admin/cashier to add an item. Please specify which vendor.", None, None
        sku = await generate_sku(target_vendor_id, db)
        barcode_val = uuid.uuid4().hex[:12].upper()
        item = Item(
            vendor_id=target_vendor_id,
            sku=sku,
            barcode=barcode_val,
            name=tool_args["name"],
            price=tool_args["price"],
            category=tool_args.get("category"),
            description=tool_args.get("description"),
            quantity=tool_args.get("quantity", 1),
            sale_price=tool_args.get("sale_price"),
            sale_start=tool_args.get("sale_start"),
            sale_end=tool_args.get("sale_end"),
            is_online=tool_args.get("is_online", False),
            is_tax_exempt=tool_args.get("is_tax_exempt", False),
            status="active",
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        result = (
            f"SUCCESS: Added item '{item.name}' with ID={item.id}, "
            f"SKU={item.sku}, price=${float(item.price):.2f}."
        )
        return result, "item_added", item.id

    if tool_name == "edit_item":
        item_id = tool_args["item_id"]
        q = select(Item).where(Item.id == item_id)
        if is_vendor:
            q = q.where(Item.vendor_id == vendor.id)
        row = await db.execute(q)
        item = row.scalar_one_or_none()
        if not item:
            return f"ERROR: Item ID {item_id} not found or does not belong to you.", None, None

        changed = []
        for field in ("name", "category", "description", "quantity", "is_online", "is_tax_exempt"):
            if field in tool_args:
                setattr(item, field, tool_args[field])
                changed.append(field)
        for field in ("price", "sale_price"):
            if field in tool_args:
                setattr(item, field, tool_args[field])
                changed.append(field)
        for field in ("sale_start", "sale_end"):
            if field in tool_args:
                setattr(item, field, tool_args[field])
                changed.append(field)

        await db.commit()
        await db.refresh(item)
        result = (
            f"SUCCESS: Updated '{item.name}' (ID={item.id}). "
            f"Changed: {', '.join(changed)}. "
            f"Current price: ${float(item.price):.2f}."
        )
        return result, "item_edited", item.id

    if tool_name == "archive_item":
        item_id = tool_args["item_id"]
        q = select(Item).where(Item.id == item_id)
        if is_vendor:
            q = q.where(Item.vendor_id == vendor.id)
        row = await db.execute(q)
        item = row.scalar_one_or_none()
        if not item:
            return f"ERROR: Item ID {item_id} not found or does not belong to you.", None, None
        item.status = "removed"
        await db.commit()
        result = f"SUCCESS: Archived '{item.name}' (ID={item.id}). It will no longer appear in the POS or online."
        return result, "item_archived", item.id

    if tool_name == "list_items":
        status_filter = tool_args.get("status", "active")
        category_filter = tool_args.get("category")
        search_filter = tool_args.get("search")
        arg_vendor_id = tool_args.get("vendor_id")

        q = select(Item)
        # Vendors always see only their items; admin/cashier see all unless vendor_id specified
        if is_vendor:
            q = q.where(Item.vendor_id == vendor.id)
        elif arg_vendor_id:
            q = q.where(Item.vendor_id == arg_vendor_id)

        if status_filter:
            q = q.where(Item.status == status_filter)
        if category_filter:
            q = q.where(Item.category.ilike(f"%{category_filter}%"))
        if search_filter:
            q = q.where(Item.name.ilike(f"%{search_filter}%"))
        q = q.order_by(Item.created_at.desc()).limit(50)

        rows = await db.execute(q)
        items = rows.scalars().all()

        if not items:
            return "No items found matching those criteria.", None, None

        lines = [f"Found {len(items)} item(s):"]
        for i, it in enumerate(items, 1):
            sale_info = f" (sale: ${float(it.sale_price):.2f})" if it.sale_price else ""
            lines.append(
                f"{i}. [{it.id}] {it.name} — ${float(it.price):.2f}{sale_info} | "
                f"Qty: {it.quantity} | {it.category or 'No category'} | {it.status}"
            )
        return "\n".join(lines), None, None

    if tool_name == "get_item":
        item_id = tool_args.get("item_id")
        name = tool_args.get("name")

        if item_id:
            q = select(Item).where(Item.id == item_id)
            if is_vendor:
                q = q.where(Item.vendor_id == vendor.id)
            row = await db.execute(q)
            item = row.scalar_one_or_none()
        elif name:
            q = select(Item).where(Item.name.ilike(f"%{name}%"))
            if is_vendor:
                q = q.where(Item.vendor_id == vendor.id)
            row = await db.execute(q)
            item = row.scalars().first()
        else:
            return "ERROR: Provide either item_id or name.", None, None

        if not item:
            return "ERROR: Item not found.", None, None

        sale_info = ""
        if item.sale_price:
            sale_info = (
                f"\n  Sale price: ${float(item.sale_price):.2f}"
                f" ({item.sale_start} to {item.sale_end})"
            )
        result = (
            f"Item ID: {item.id}\n"
            f"  Name: {item.name}\n"
            f"  SKU: {item.sku}\n"
            f"  Category: {item.category or 'None'}\n"
            f"  Price: ${float(item.price):.2f}{sale_info}\n"
            f"  Quantity: {item.quantity}\n"
            f"  Status: {item.status}\n"
            f"  Online: {item.is_online}\n"
            f"  Description: {item.description or 'None'}"
        )
        return result, None, item.id

    return f"ERROR: Unknown tool '{tool_name}'.", None, None


async def _call_openrouter(
    api_key: str,
    messages: list,
    include_tools: bool = True,
) -> dict:
    payload: dict = {
        "model": "google/gemini-2.0-flash-001",
        "max_tokens": 500,
        "messages": messages,
    }
    if include_tools:
        payload["tools"] = TOOLS

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://bowenstreetmarket.com",
                    "X-Title": "Bowenstreet Market POS",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Assistant timed out")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Network error: {exc}")

    if resp.status_code == 401:
        raise HTTPException(
            status_code=503,
            detail="Assistant not configured. Please add your OpenRouter API key.",
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Assistant unavailable")

    return resp.json()


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    data: AssistantChatRequest,
    current_user: Vendor = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    api_key = _get_api_key()

    if data.image_base64 and data.image_mime_type:
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{data.image_mime_type};base64,{data.image_base64}"},
            },
            {"type": "text", "text": data.message},
        ]
    else:
        user_content = data.message

    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    action_taken: Optional[str] = None
    item_id: Optional[int] = None

    # Prepend form context to system prompt if provided
    if data.form_context:
        messages[0]["content"] = SYSTEM_PROMPT + "\n\nCurrent context: " + data.form_context

    # Multi-round tool-calling loop (max 4 rounds to prevent runaway)
    for _round in range(4):
        try:
            body = await _call_openrouter(api_key, messages, include_tools=True)
        except HTTPException as exc:
            return AssistantChatResponse(
                reply=f"Assistant error: {exc.detail}",
                action_taken=action_taken,
                item_id=item_id,
            )
        except Exception as exc:
            return AssistantChatResponse(
                reply="Assistant is temporarily unavailable. Please try again.",
                action_taken=action_taken,
                item_id=item_id,
            )

        choice = body["choices"][0]
        assistant_message = choice["message"]
        finish_reason = choice.get("finish_reason", "")
        tool_calls = assistant_message.get("tool_calls")

        if not (finish_reason == "tool_calls" or tool_calls):
            # No more tool calls — final reply
            reply = assistant_message.get("content") or ""
            return AssistantChatResponse(reply=reply, action_taken=action_taken, item_id=item_id)

        # Append the assistant's tool-call message to conversation
        messages.append({
            "role": "assistant",
            "content": assistant_message.get("content"),
            "tool_calls": tool_calls,
        })

        # Execute every tool in this round and append results
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            try:
                tool_args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                tool_args = {}

            try:
                result_text, at, iid = await _execute_tool(tool_name, tool_args, current_user, db)
            except Exception as exc:
                result_text = f"ERROR: Tool '{tool_name}' failed — {exc}"
                at, iid = None, None

            if at:
                action_taken = at
            if iid:
                item_id = iid

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    # Fallback: force a final reply without tools
    try:
        body_final = await _call_openrouter(api_key, messages, include_tools=False)
        reply = body_final["choices"][0]["message"].get("content") or ""
    except Exception:
        # Return whatever tool results we accumulated as a plain summary
        tool_results = [m["content"] for m in messages if m.get("role") == "tool"]
        reply = "\n".join(tool_results) if tool_results else "Sorry, I couldn't complete that request."
    return AssistantChatResponse(reply=reply, action_taken=action_taken, item_id=item_id)
