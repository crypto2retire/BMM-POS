import sys
import uuid
import logging

import httpx

from app.config import settings
from app.services.circuit_breaker import circuit_breaker

SQUARE_BASE = "https://connect.squareup.com"
SQUARE_API_VERSION = "2024-02-15"
logger = logging.getLogger(__name__)


def _access_token() -> str:
    return settings.square_access_token or ""


def _location_id() -> str:
    return settings.square_location_id or ""


def _application_id() -> str:
    return settings.square_application_id or ""


def _parse_square_error(body: str) -> str:
    try:
        import json
        data = json.loads(body)
        errors = data.get("errors", [])
        if errors:
            code = errors[0].get("code", "")
            detail = errors[0].get("detail", "")
            if code == "INVALID_VALUE" and "location" in detail.lower():
                return "Square location ID is misconfigured. Please contact the store."
            if code == "UNAUTHORIZED":
                return "Square access token is invalid. Please contact the store."
            if detail:
                return f"Payment service error: {detail}"
    except Exception:
        logger.exception("Failed to parse Square error response")
    return "Payment service returned an unexpected error. Please contact the store."


@circuit_breaker("square")
async def create_payment_link(name: str, price_cents: int, redirect_url: str) -> dict:
    token = _access_token()
    location = _location_id()
    if not token or not location:
        raise ValueError("Square credentials not configured (SQUARE_ACCESS_TOKEN / SQUARE_LOCATION_ID)")

    try:
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
    except httpx.HTTPError:
        logger.exception(
            "Square payment link request failed for %r (%s cents)",
            name,
            price_cents,
        )
        raise

    if resp.status_code != 200:
        raw = resp.text
        print(f"BMM-POS Square API error {resp.status_code}: {raw}", file=sys.stderr, flush=True)
        raise RuntimeError(_parse_square_error(raw))

    data = resp.json()
    link = data["payment_link"]
    return {
        "url": link["url"],
        "order_id": link.get("order_id", ""),
        "payment_link_id": link.get("id", ""),
    }
