import os
import time
import uuid
import json
import logging
import httpx
from typing import Optional
from fastapi import HTTPException

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
            status_code=503,
            detail="GoDaddy Poynt is not configured. Set POYNT_APP_ID, POYNT_PRIVATE_KEY, and POYNT_BUSINESS_ID environment variables.",
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
            raise HTTPException(status_code=502, detail=f"Poynt token error: {resp.text[:200]}")
        data = resp.json()
        token = data.get("accessToken") or data.get("access_token")
        expires_in = data.get("expiresIn", 3600)
        _cached_token["token"] = token
        _cached_token["expires_at"] = time.time() + expires_in
        return token


async def create_terminal_order(amount_cents: int, currency: str = "USD", order_ref: str = "") -> str:
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    order_id = str(uuid.uuid4())

    order_payload = {
        "id": order_id,
        "context": {
            "businessId": business_id,
            "storeId": store_id,
            "source": "WEB",
        },
        "amounts": {
            "currency": currency,
            "transactionAmount": amount_cents,
            "orderAmount": amount_cents,
        },
        "items": [
            {
                "name": "BMM-POS Sale",
                "sku": order_ref or "POS",
                "unitOfMeasure": "EACH",
                "quantity": {"value": 1, "unitOfMeasure": "EACH"},
                "unitPrice": amount_cents,
                "tax": 0,
                "discount": 0,
                "fee": 0,
            }
        ],
        "statuses": {"status": "OPENED"},
        "notes": f"Order ref: {order_ref}",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{POYNT_API_BASE}/businesses/{business_id}/orders",
            json=order_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "api-version": "1.2",
                "Poynt-Request-Id": str(uuid.uuid4()),
            },
        )
        if resp.status_code not in (200, 201):
            logger.error(f"Poynt create order error {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=502, detail=f"Poynt create order error: {resp.text[:200]}")
        data = resp.json()
        created_order_id = data.get("id") or data.get("orderId") or order_id

        if terminal_id and store_id:
            try:
                await _send_payment_to_terminal(
                    client, token, business_id, store_id, terminal_id,
                    created_order_id, amount_cents, currency,
                )
            except Exception as e:
                logger.warning(f"Terminal push failed (order still created): {e}")

        return created_order_id


async def _send_payment_to_terminal(
    client: httpx.AsyncClient,
    token: str,
    business_id: str,
    store_id: str,
    terminal_id: str,
    order_id: str,
    amount_cents: int,
    currency: str,
):
    action_payload = {
        "action": "AUTHORIZE",
        "purchaseAction": "SALE",
        "amounts": {
            "transactionAmount": amount_cents,
            "orderAmount": amount_cents,
            "currency": currency,
        },
        "orderId": order_id,
        "referenceId": str(uuid.uuid4()),
        "callbackUrl": "-",
        "skipReceiptScreen": True,
        "disableTip": True,
    }

    resp = await client.post(
        f"{POYNT_API_BASE}/businesses/{business_id}/stores/{store_id}/terminals/{terminal_id}/requests",
        json=action_payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "api-version": "1.2",
            "Poynt-Request-Id": str(uuid.uuid4()),
        },
    )
    if resp.status_code not in (200, 201, 202):
        logger.error(f"Poynt terminal request error {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=502, detail=f"Poynt terminal error: {resp.text[:200]}")
    logger.info(f"Payment sent to terminal {terminal_id} for order {order_id}")
    return resp.json()


async def get_transaction_for_order(order_id: str) -> dict:
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{POYNT_API_BASE}/businesses/{business_id}/transactions",
            params={"orderID": order_id},
            headers={
                "Authorization": f"Bearer {token}",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            logger.error(f"Poynt status error {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=502, detail=f"Poynt status error: {resp.text[:200]}")

        data = resp.json()
        transactions = data.get("list") or data.get("transactions") or []

        if not transactions:
            return {"status": "PENDING", "transaction_id": None}

        txn = transactions[-1]
        txn_status = txn.get("status", "PENDING")
        txn_id = str(txn.get("id", ""))

        if txn_status in ("CAPTURED", "APPROVED", "AUTHORIZED"):
            return {"status": "APPROVED", "transaction_id": txn_id}
        elif txn_status in ("DECLINED", "VOIDED", "REFUNDED"):
            return {"status": "DECLINED", "transaction_id": txn_id}
        else:
            return {"status": "PENDING", "transaction_id": None}
