import uuid

import httpx

from app.config import settings

SQUARE_BASE = "https://connect.squareup.com"
SQUARE_API_VERSION = "2024-02-15"


def _access_token() -> str:
    return settings.square_access_token or ""


def _location_id() -> str:
    return settings.square_location_id or ""


def _application_id() -> str:
    return settings.square_application_id or ""


async def create_payment_link(name: str, price_cents: int, redirect_url: str) -> dict:
    token = _access_token()
    location = _location_id()
    if not token or not location:
        raise ValueError("Square credentials not configured (SQUARE_ACCESS_TOKEN / SQUARE_LOCATION_ID)")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{SQUARE_BASE}/v2/online-checkout/payment-links",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Square-Version": SQUARE_API_VERSION,
            },
            json={
                "idempotency_key": str(uuid.uuid4()),
                "quick_pay": {
                    "name": name,
                    "price_money": {"amount": price_cents, "currency": "USD"},
                    "location_id": location,
                },
                "checkout_options": {
                    "redirect_url": redirect_url,
                },
            },
        )

    if resp.status_code != 200:
        body = resp.text
        raise RuntimeError(f"Square API error {resp.status_code}: {body}")

    data = resp.json()
    link = data["payment_link"]
    return {
        "url": link["url"],
        "order_id": link.get("order_id", ""),
        "payment_link_id": link.get("id", ""),
    }
