"""GoDaddy Poynt Payment Bridge — Cloud Message API integration.

Flow:
  1. generate_jwt_token() — RS256-signed JWT for Poynt API auth
  2. send_payment_request() — sends Cloud Message to terminal via WiFi
  3. verify_callback() — validates callback payload from Poynt servers
"""

import json
import time
import uuid
import httpx
import jwt
from fastapi import HTTPException
from app.config import settings

POYNT_API_BASE = "https://services.poynt.net"


def _require_config():
    """Raise 503 if any required Poynt env var is missing."""
    missing = []
    if not settings.poynt_app_id:
        missing.append("POYNT_APP_ID")
    if not settings.poynt_private_key:
        missing.append("POYNT_PRIVATE_KEY")
    if not settings.poynt_business_id:
        missing.append("POYNT_BUSINESS_ID")
    if not settings.poynt_store_id:
        missing.append("POYNT_STORE_ID")
    if not settings.poynt_terminal_id:
        missing.append("POYNT_TERMINAL_ID")
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Poynt not configured. Missing: {', '.join(missing)}",
        )


def generate_jwt_token() -> str:
    """Create a signed JWT using App ID + Private Key (RS256).

    Claims: iss=App ID, sub=App ID, aud=Poynt API, iat=now, exp=now+1h.
    """
    _require_config()
    now = int(time.time())
    payload = {
        "iss": settings.poynt_app_id,
        "sub": settings.poynt_app_id,
        "aud": "https://services.poynt.net",
        "iat": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
    }
    # The private key may have literal \n instead of real newlines from env vars
    private_key = settings.poynt_private_key.replace("\\n", "\n")
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _get_access_token() -> str:
    """Exchange app JWT for a Poynt access token."""
    app_jwt = generate_jwt_token()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{POYNT_API_BASE}/token",
            data={
                "grantType": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": app_jwt,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Poynt token error: {resp.text}")
        data = resp.json()
        return data.get("accessToken") or data.get("access_token")


async def send_payment_request(amount_cents: int, reference_id: str, callback_url: str) -> None:
    """Send a Cloud Message to the Poynt terminal to initiate a card payment.

    The terminal will display the payment screen. After the customer taps/swipes,
    Poynt calls our callback_url with the result.
    """
    _require_config()
    token = await _get_access_token()

    # The "data" field must be a JSON string inside the Cloud Message
    payment_data = json.dumps({
        "action": "SALE",
        "purchaseAmount": amount_cents,
        "tipAmount": 0,
        "currency": "USD",
        "referenceId": reference_id,
        "callbackUrl": callback_url,
    })

    cloud_message = {
        "businessId": settings.poynt_business_id,
        "storeId": settings.poynt_store_id,
        "deviceId": settings.poynt_terminal_id,
        "ttl": 500,
        "data": payment_data,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{POYNT_API_BASE}/cloudMessages",
            json=cloud_message,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "api-version": "1.2",
            },
        )
        if resp.status_code not in (200, 201, 202):
            raise HTTPException(
                status_code=502,
                detail=f"Poynt Cloud Message error ({resp.status_code}): {resp.text}",
            )


def verify_callback(payload: dict) -> dict:
    """Verify a callback payload from Poynt and extract result.

    Returns dict with keys: approved (bool), transaction_id (str or None).
    """
    status = (payload.get("status") or "").upper()
    transaction_id = payload.get("transactionId") or payload.get("transaction_id")
    reference_id = payload.get("referenceId") or payload.get("reference_id")

    approved = status in ("APPROVED", "CAPTURED", "AUTHORIZED")
    declined = status in ("DECLINED", "VOIDED", "REFUNDED", "FAILED")

    return {
        "approved": approved,
        "declined": declined,
        "transaction_id": str(transaction_id) if transaction_id else None,
        "reference_id": str(reference_id) if reference_id else None,
        "raw_status": status,
    }
