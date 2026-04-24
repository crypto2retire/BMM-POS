import os
import time
import uuid
import json
import logging
import httpx
from typing import Optional
from fastapi import HTTPException

from app.services.circuit_breaker import circuit_breaker

logger = logging.getLogger(__name__)

POYNT_API_BASE = "https://services.poynt.net"


def _get_config():
    app_id = os.environ.get("POYNT_APP_ID", "")
    private_key = os.environ.get("POYNT_PRIVATE_KEY", "")
    business_id = os.environ.get("POYNT_BUSINESS_ID", "")
    store_id = os.environ.get("POYNT_STORE_ID", "")
    terminal_id = os.environ.get("POYNT_TERMINAL_ID", "")

    if "=" in app_id:
        app_id = app_id.split("=", 1)[1]

    if not all([app_id, private_key, business_id]):
        raise HTTPException(
            status_code=422,
            detail="GoDaddy Poynt is not configured. Set POYNT_APP_ID, POYNT_PRIVATE_KEY, and POYNT_BUSINESS_ID environment variables.",
        )
    if not terminal_id:
        raise HTTPException(
            status_code=422,
            detail="POYNT_TERMINAL_ID is not configured. Cannot send payment to terminal.",
        )
    if not store_id:
        raise HTTPException(
            status_code=422,
            detail="POYNT_STORE_ID is not configured.",
        )
    return app_id, private_key, business_id, store_id, terminal_id


def _build_app_jwt(app_id: str, private_key_pem: str) -> str:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "sub": app_id,
        "iss": app_id,
        "aud": "https://services.poynt.net",
        "iat": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_enc = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_enc = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_enc}.{payload_enc}".encode()

    pem = private_key_pem
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")
    if not pem.startswith("-----"):
        pem = f"-----BEGIN RSA PRIVATE KEY-----\n{pem}\n-----END RSA PRIVATE KEY-----"

    private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_enc = b64url(signature)

    return f"{header_enc}.{payload_enc}.{sig_enc}"


_cached_token = {"token": None, "expires_at": 0}


async def get_access_token() -> str:
    if _cached_token["token"] and time.time() < _cached_token["expires_at"] - 60:
        return _cached_token["token"]

    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    app_jwt = _build_app_jwt(app_id, private_key_pem)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{POYNT_API_BASE}/token",
            data={
                "grantType": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": app_jwt,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "api-version": "1.2"},
        )
        if resp.status_code != 200:
            logger.error(f"Poynt token error {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=422, detail=f"Poynt authentication failed: {resp.text[:200]}")
        data = resp.json()
        token = data.get("accessToken") or data.get("access_token")
        expires_in = data.get("expiresIn", 3600)
        _cached_token["token"] = token
        _cached_token["expires_at"] = time.time() + expires_in
        return token


@circuit_breaker("poynt")
async def send_payment_to_terminal(amount_cents: int, currency: str = "USD", order_ref: str = "") -> dict:
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    reference_id = str(uuid.uuid4())

    # Payment data must be serialized as a JSON string
    payment_data = json.dumps({
        "action": "sale",
        "purchaseAmount": amount_cents,
        "currency": currency,
        "referenceId": reference_id,
        "callbackUrl": "https://bowenstreetmarket.com/api/v1/pos/poynt/callback",
        "skipReceiptScreen": True,
        "disableTip": True,
        "notes": order_ref,
    })

    cloud_message = {
        "ttl": 90,
        "businessId": business_id,
        "storeId": store_id,
        "deviceId": terminal_id,
        "data": payment_data,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{POYNT_API_BASE}/cloudMessages",
            json=cloud_message,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "api-version": "1.2",
                "Poynt-Request-Id": str(uuid.uuid4()),
            },
        )
        logger.info(f"Poynt cloud message response {resp.status_code}: {resp.text[:500]}")

        if resp.status_code not in (200, 201, 202):
            logger.error(f"Poynt cloud message error {resp.status_code}: {resp.text}")
            detail = "Failed to send payment to terminal."
            if resp.status_code == 404:
                detail = "Terminal not found or offline. Check that the terminal is powered on and connected."
            elif resp.status_code in (401, 403):
                detail = "Poynt authentication error. Please contact admin."
            raise HTTPException(status_code=422, detail=detail)

        return {"reference_id": reference_id}


@circuit_breaker("poynt")
async def check_terminal_payment(reference_id: str) -> dict:
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{POYNT_API_BASE}/businesses/{business_id}/transactions",
            params={"limit": 10},
            headers={
                "Authorization": f"Bearer {token}",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            logger.error(f"Poynt transaction query error {resp.status_code}: {resp.text}")
            return {"status": "ERROR", "transaction_id": None, "detail": resp.text[:200]}

        data = resp.json()
        transactions = data.get("list") or data.get("transactions") or []

        for txn in transactions:
            txn_ref = txn.get("references", [])
            txn_context = txn.get("context", {})
            txn_notes = txn.get("notes", "")

            ref_match = False
            for ref in txn_ref:
                if ref.get("id") == reference_id or ref.get("customType") == reference_id:
                    ref_match = True
                    break

            if not ref_match and reference_id not in (txn_notes or ""):
                fund_txn = txn.get("fundingSource", {}).get("entryDetails", {})
                action_ref = txn.get("actionReferenceId", "")
                if action_ref != reference_id:
                    continue

            txn_status = txn.get("status", "")
            txn_id = str(txn.get("id", ""))
            txn_amount = txn.get("amounts", {}).get("transactionAmount", 0)

            if txn_status in ("CAPTURED", "AUTHORIZED"):
                return {
                    "status": "APPROVED",
                    "transaction_id": txn_id,
                    "amount_cents": txn_amount,
                }
            elif txn_status in ("DECLINED", "VOIDED", "REFUNDED"):
                return {
                    "status": "DECLINED",
                    "transaction_id": txn_id,
                }

        return {"status": "PENDING", "transaction_id": None}


@circuit_breaker("poynt")
async def verify_transaction(transaction_id: str) -> dict:
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{POYNT_API_BASE}/businesses/{business_id}/transactions/{transaction_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            return {"valid": False, "detail": f"Transaction not found: {resp.status_code}"}

        txn = resp.json()
        txn_status = txn.get("status", "")
        txn_amount = txn.get("amounts", {}).get("transactionAmount", 0)

        if txn_status in ("CAPTURED", "AUTHORIZED"):
            return {
                "valid": True,
                "status": txn_status,
                "amount_cents": txn_amount,
                "transaction_id": str(txn.get("id", "")),
            }
        return {"valid": False, "status": txn_status}


async def find_recent_transaction(amount_cents: int) -> dict:
    """Search recent transactions for one matching the expected amount (within last 2 minutes)."""
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{POYNT_API_BASE}/businesses/{business_id}/transactions",
            params={"limit": 5},
            headers={
                "Authorization": f"Bearer {token}",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            logger.error(f"Poynt transaction poll error {resp.status_code}: {resp.text}")
            return {"status": "PENDING", "transaction_id": None}

        data = resp.json()
        transactions = data.get("list") or data.get("transactions") or []

        import time as _time
        now_ms = int(_time.time() * 1000)
        two_minutes_ago_ms = now_ms - 120000

        for txn in transactions:
            txn_status = txn.get("status", "")
            txn_amount = txn.get("amounts", {}).get("transactionAmount", 0)
            txn_created = txn.get("createdAt", 0)

            # Match by amount and recency (within last 2 minutes)
            if txn_amount == amount_cents and txn_created > two_minutes_ago_ms:
                txn_id = str(txn.get("id", ""))

                if txn_status in ("CAPTURED", "AUTHORIZED"):
                    return {
                        "status": "APPROVED",
                        "transaction_id": txn_id,
                        "amount_cents": txn_amount,
                    }
                elif txn_status in ("DECLINED", "VOIDED", "REFUNDED"):
                    return {
                        "status": "DECLINED",
                        "transaction_id": txn_id,
                    }

        return {"status": "PENDING", "transaction_id": None}
