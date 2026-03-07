from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx
from app.models.vendor import Vendor
from app.routers.auth import get_current_user

router = APIRouter(prefix="/assistant", tags=["assistant"])

SYSTEM_PROMPT = """You are the Bowenstreet Market vendor assistant. Bowenstreet Market is a vendor mall at 2837 Bowen St, Oshkosh WI 54901 with over 120 vendors selling handcrafted, vintage, and antique goods.

You help vendors with:
1. Adding items — walk them through: name, category, price, description, photos, sale dates, label type
2. Editing items — explain what each field does, remind them sale prices activate automatically by date
3. Archiving items — explain the difference between removing (hides from POS) and deleting
4. Understanding their sales and balance — explain how payouts work (deducted on 27th, paid on 1st)
5. Writing item descriptions — if given a description or photo, write a compelling, SEO-friendly product description
6. General questions about how the system works

When writing product descriptions:
- Start with the most important keyword naturally in the first sentence
- Include material, age/era if vintage, condition, dimensions if relevant
- Write 2-3 sentences, warm and inviting tone
- End with a detail that helps the buyer picture owning it
- Do NOT use the words "unique", "amazing", or "beautiful"

Keep responses concise and friendly. This is a mobile interface so avoid long walls of text.
If you see an image, describe what you see and suggest a product name, category, and description."""


class ChatRequest(BaseModel):
    message: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str


def _get_api_key() -> str:
    import os
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Assistant not configured. Please add your OpenRouter API key.",
        )
    return key


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    current_user: Vendor = Depends(get_current_user),
):
    api_key = _get_api_key()

    if data.image_base64 and data.image_mime_type:
        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{data.image_mime_type};base64,{data.image_base64}"
                },
            },
            {"type": "text", "text": data.message},
        ]
    else:
        user_content = data.message

    payload = {
        "model": "google/gemini-2.0-flash",
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

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
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Network error: {e}")

    if resp.status_code == 401:
        raise HTTPException(
            status_code=503,
            detail="Assistant not configured. Please add your OpenRouter API key.",
        )
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Assistant unavailable")

    body = resp.json()
    reply = body["choices"][0]["message"]["content"]
    return ChatResponse(reply=reply)
