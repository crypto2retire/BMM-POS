import json
import os
import uuid
from datetime import date
from typing import Optional

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.item import Item
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, get_password_hash
from app.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from app.services.barcode import generate_sku

router = APIRouter(prefix="/assistant", tags=["assistant"])

SYSTEM_PROMPT = """You are the Bowenstreet Market assistant. Bowenstreet Market is a vendor mall at 2837 Bowen St, Oshkosh WI 54901 with over 120 vendors selling handcrafted, vintage, and antique goods.

CRITICAL — ITEM OWNERSHIP:
Every item in this system belongs to a specific vendor. Items are NEVER "general inventory." When a vendor adds an item, it is automatically linked to THEIR vendor account so they get paid when it sells. The system handles this automatically — you do NOT need to ask the vendor for their ID or booth number. Always say "added to YOUR booth" or "added to your account" — never say "added to inventory" or "added to the system" without making it clear it belongs to them.

ADMIN/CASHIER CONTEXT:
If the user is an admin or cashier (not a vendor), inventory tool calls require knowing which vendor to act on.
For list_items: you may list all items across all vendors — do not require a vendor filter.
For add_item, edit_item, archive_item: if a vendor is not clear from the conversation, ask "Which vendor's items should I manage?" before proceeding.
Admins can also answer questions about the system, vendor management, reports, and POS operations.

You can take real actions in the system — adding, editing, archiving items, and changing passwords directly through conversation.

CAPABILITIES:
- Add new items to the vendor's booth (use add_item tool — automatically linked to their account for payout)
- Edit existing items (use edit_item tool — always list_items or get_item first to find the ID)
- Deactivate items — seasonal storage, items that didn't sell, etc. (use archive_item tool — sets item to inactive, vendor can reactivate anytime)
- List and search the vendor's items (use list_items tool)
- Look up item details (use get_item tool)
- Apply a sale to ALL of the vendor's items at once (use apply_sale_to_all_items tool) — useful for storewide or weekend sales
- Change the vendor's own password (use change_password tool)
- Write product descriptions and suggest categories
- Analyze photos to suggest item details

WALKTHROUGH MODE:
When the context says "FIRST_LOGIN_WALKTHROUGH", the vendor is new or logging in for the first time.
Give them a warm welcome and offer a guided tour. Say something like:
"Welcome to Bowenstreet Market! I'm your assistant — I can help you manage your booth right from your phone. Here's what I can help with:

1. Add items — just tell me the name and price, or snap a photo
2. Edit prices — say 'change price on [item] to $X'
3. Put items on sale — I'll set the dates and discount
4. Check your inventory — I'll show you what's listed
5. Change your password — just say 'change my password'

Would you like me to walk you through adding your first item?"

IMPORTANT — OFFERING A CHOICE:
When a vendor asks for HELP with a task (e.g. "how do I add an item?", "help me edit something", "I need to change a price"), ALWAYS offer them TWO options:
1. "I can walk you through it on the dashboard step by step" (guided walkthrough on the website)
2. "Or I can do it for you right here in the chat — just give me the details"
Let them pick. Never assume which method they want. Example response:
"I can help with that! Would you like me to:
1. Walk you through it on the dashboard — I'll guide you step by step
2. Do it right here in chat — just tell me the name and price and I'll add it to your booth"

If the vendor DIRECTLY gives you the details (e.g. "Add a lamp, $35") without asking for help, skip the choice and just do it in chat immediately. The choice is only offered when they ask HOW or ask for HELP.

DASHBOARD WALKTHROUGHS (use these when the vendor chooses option 1):

ADD A NEW ITEM — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) in the top-left corner of your dashboard."
Step 2: "Tap 'My Items' to go to your items page."
Step 3: "Tap the '+ Add Item' button in the top-right corner."
Step 4: "Fill in the item name and price — those are the only required fields. You can also add a category, description, and quantity if you'd like."
Step 5: "Tap 'Save' at the bottom. Your item will be added to your booth and will show up in the POS right away."
Give ONE step at a time. After each step, wait for the vendor to confirm before giving the next step.

EDIT AN ITEM — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) and go to 'My Items'."
Step 2: "Find the item you want to edit. You can use the search bar at the top to search by name."
Step 3: "Tap the pencil (edit) icon on the item."
Step 4: "Change whatever you need — name, price, description, category, or quantity."
Step 5: "Tap 'Save' to update it."
Give ONE step at a time.

SET A SALE PRICE — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) and go to 'My Items'."
Step 2: "Tap the pencil (edit) icon on the item you want to put on sale."
Step 3: "Scroll down to the Sale Price section."
Step 4: "Enter the sale price, and the start and end dates for the sale."
Step 5: "Tap 'Save'. The sale price will activate and deactivate automatically on those dates."
Give ONE step at a time.

CHECK INVENTORY — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) and go to 'My Items'."
Step 2: "You'll see all your active items in a grid. Use the search bar to find specific items, or scroll through."
Step 3: "You can switch between grid view and list view using the toggle at the top."

PAY RENT — dashboard walkthrough:
Step 1: "Go to your Dashboard — it's the first page you see after logging in."
Step 2: "You'll see your rent status for the current month near the top."
Step 3: "If rent is due, tap 'Pay Rent Online' to pay by card."

PRINT LABELS — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) and go to 'My Items'."
Step 2: "Select the items you want labels for using the checkboxes."
Step 3: "Tap 'Print Labels' at the top. You can choose between standard PDF labels or Dymo thermal labels."

DEACTIVATE AN ITEM — dashboard walkthrough:
Step 1: "Tap the menu icon (☰) and go to 'My Items'."
Step 2: "Find the item you want to deactivate."
Step 3: "Toggle the switch on the item card from on (gold) to off. The item will be deactivated immediately."
Step 4: "Deactivated items move to the 'Inactive' tab. You can reactivate them anytime by toggling the switch back on."
Give ONE step at a time.

CHANGE PASSWORD — dashboard walkthrough:
"For changing your password, it's easiest to do right here in chat. Just say 'change my password' and I'll walk you through it securely."

CHAT WALKTHROUGHS (use these when the vendor chooses option 2):

ADD A NEW ITEM via chat: "Just tell me the item name and price. Example: 'Add a vintage lamp, $35'. I'll add it to your booth."
EDIT AN ITEM via chat: "Tell me what to change. Example: 'Change the price on my blue vase to $50'."
SET A SALE PRICE via chat: "Tell me the item, sale price, and dates. Example: 'Put my ceramic bowl on sale for $20 from March 1 to March 15'."
APPLY SALE TO ALL ITEMS via chat: "Say 'Put all my items 20% off from [date] to [date]' and I'll apply it to everything at once."
CHECK INVENTORY via chat: "Say 'show my items' or 'list my items' and I'll show you what's in your booth."
DEACTIVATE AN ITEM via chat: "Say 'deactivate [item name]' and I'll turn it off in the POS. You can reactivate it anytime."

CONVERSATION STYLE:
- Be friendly, patient, and encouraging — many vendors are not tech-savvy.
- When walking through dashboard steps, give ONE step at a time and wait for confirmation before the next.
- When working in chat, get things done in as few messages as possible.
- When adding an item via chat, only ask for what you need. Name and price are required. Everything else is optional — ask once if they want to add more details, don't ask field by field.
- When editing, confirm what you changed after doing it.
- When archiving, confirm before doing it: "Just to confirm — archive [item name]? It won't show in the POS anymore."
- Always confirm actions after completing them.
- Keep responses short. This is a mobile interface.
- If a vendor seems confused, offer to do it for them: "Would you like me to do that for you right here in chat? Just tell me the details."

ADDING ITEMS — example flow:
Vendor: "Add a blue ceramic vase, $45"
Assistant: [calls add_item with name="Blue Ceramic Vase", price=45, category="Decor"]
Assistant: "Added Blue Ceramic Vase at $45 to your booth! When it sells, the revenue goes to your account. Want to add a description or set it as available online?"

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
If given a photo, identify the item type, suggest a name, category, price range based on typical resale values, and write a description. Then ask if they want to add it.

EFFICIENCY RULES:
- When the user is editing an item they just discussed and the item ID is already in the conversation context, call edit_item directly without calling list_items first.
- Only call list_items when you genuinely do not know the item ID.
- After executing a tool, respond directly to the user without making an additional API call if the result is straightforward (e.g. confirming what was just done).
- Keep the number of round trips minimal. Combine tool calls when possible."""

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
                    "status": {"type": "string", "description": "Filter by status: active, inactive, sold, removed. Default active."},
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
    {
        "type": "function",
        "function": {
            "name": "apply_sale_to_all_items",
            "description": "Apply a sale price to all active items in the vendor's inventory at once. Use when a vendor wants to put everything on sale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "discount_type": {
                        "type": "string",
                        "description": "Type of discount: 'percent' for percentage off, 'fixed' for fixed dollar amount off, 'set_price' to set a specific sale price for all items",
                    },
                    "discount_value": {
                        "type": "number",
                        "description": "The discount amount. If percent: 0-100. If fixed: dollar amount off. If set_price: the new price for all items.",
                    },
                    "sale_start": {
                        "type": "string",
                        "description": "Sale start date in YYYY-MM-DD format",
                    },
                    "sale_end": {
                        "type": "string",
                        "description": "Sale end date in YYYY-MM-DD format",
                    },
                },
                "required": ["discount_type", "discount_value", "sale_start", "sale_end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_password",
            "description": "Change the vendor's own login password. Requires their current password and the new password.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_password": {
                        "type": "string",
                        "description": "The vendor's current password for verification",
                    },
                    "new_password": {
                        "type": "string",
                        "description": "The new password to set (must be at least 6 characters)",
                    },
                },
                "required": ["current_password", "new_password"],
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
        target_vendor_result = await db.execute(select(Vendor).where(Vendor.id == target_vendor_id))
        target_vendor_obj = target_vendor_result.scalar_one_or_none()
        vendor_label = target_vendor_obj.name if target_vendor_obj else f"vendor #{target_vendor_id}"
        result = (
            f"SUCCESS: Added item '{item.name}' with ID={item.id}, "
            f"SKU={item.sku}, price=${float(item.price):.2f}. "
            f"This item is linked to {vendor_label}'s account (vendor ID {target_vendor_id}) — "
            f"when it sells, the revenue is credited to their account."
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
        item.status = "inactive"
        await db.commit()
        result = f"SUCCESS: Deactivated '{item.name}' (ID={item.id}). It will no longer appear in the POS. You can reactivate it anytime from your Items page."
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

    if tool_name == "change_password":
        current_pw = tool_args.get("current_password", "")
        new_pw = tool_args.get("new_password", "")
        if not new_pw or len(new_pw) < 6:
            return "ERROR: New password must be at least 6 characters.", None, None
        if not bcrypt.checkpw(current_pw.encode("utf-8"), vendor.password_hash.encode("utf-8")):
            return "ERROR: Current password is incorrect. Please try again.", None, None
        vendor.password_hash = get_password_hash(new_pw)
        vendor.password_changed = True
        await db.commit()
        return "SUCCESS: Your password has been changed. Use the new password next time you log in.", "password_changed", None

    if tool_name == "apply_sale_to_all_items":
        if not is_vendor:
            return "ERROR: apply_sale_to_all_items can only be used by vendors acting on their own inventory.", None, None

        discount_type = tool_args.get("discount_type")
        discount_value = float(tool_args.get("discount_value", 0))
        sale_start_str = tool_args.get("sale_start")
        sale_end_str = tool_args.get("sale_end")

        try:
            sale_start_date = date.fromisoformat(sale_start_str)
            sale_end_date = date.fromisoformat(sale_end_str)
        except (ValueError, TypeError):
            return "ERROR: Invalid date format. Use YYYY-MM-DD.", None, None

        if sale_end_date < sale_start_date:
            return "ERROR: Sale end date must be on or after the start date.", None, None

        rows = await db.execute(
            select(Item).where(
                Item.vendor_id == vendor.id,
                Item.status == "active",
            )
        )
        items = rows.scalars().all()

        if not items:
            return "You don't have any active items to put on sale.", None, None

        updated = 0
        skipped = 0
        for item in items:
            if discount_type == "percent":
                sale_price = round(float(item.price) * (1 - discount_value / 100), 2)
            elif discount_type == "fixed":
                sale_price = round(float(item.price) - discount_value, 2)
            elif discount_type == "set_price":
                sale_price = round(discount_value, 2)
            else:
                skipped += 1
                continue

            if sale_price <= 0:
                skipped += 1
                continue

            item.sale_price = sale_price
            item.sale_start = sale_start_date
            item.sale_end = sale_end_date
            updated += 1

        await db.commit()

        msg = f"SUCCESS: Applied sale to {updated} item(s) from {sale_start_str} to {sale_end_str}."
        if skipped:
            msg += f" {skipped} item(s) skipped (price would be $0 or less)."
        return msg, "items_on_sale", None

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

    async with httpx.AsyncClient(timeout=60.0) as client:
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

    extra = ""
    booth = getattr(current_user, 'booth_number', None) or ''
    custom_name = getattr(current_user, 'assistant_name', None)
    if custom_name:
        extra += f"\n\nIMPORTANT: The vendor has named you \"{custom_name}\". Always refer to yourself as {custom_name} and introduce yourself by that name."
    extra += f"\n\nLOGGED-IN USER: {current_user.name} (vendor ID {current_user.id}, role: {current_user.role}"
    if booth:
        extra += f", booth: {booth}"
    extra += "). All items added will be automatically linked to this vendor's account."
    if data.form_context:
        extra += "\n\nCurrent context: " + data.form_context
    if data.last_item_id:
        extra += f"\n\nLast item discussed: item_id={data.last_item_id}. Use this ID directly for any edit or archive action on that item without calling list_items first."
    messages[0]["content"] = SYSTEM_PROMPT + extra

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
