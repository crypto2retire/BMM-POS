import os
import time
import uuid
import json
import httpx
from typing import Optional
from fastapi import HTTPException

POYNT_API_BASE = "https://services.poynt.net"


def _get_config():
    app_id = os.environ.get("POYNT_APP_ID")
    private_key = os.environ.get("POYNT_PRIVATE_KEY")
    business_id = os.environ.get("POYNT_BUSINESS_ID")
    store_id = os.environ.get("POYNT_STORE_ID")

    if not all([app_id, private_key, business_id]):
        raise HTTPException(
            status_code=503,
            detail="GoDaddy Poynt is not configured. Set POYNT_APP_ID, POYNT_PRIVATE_KEY, and POYNT_BUSINESS_ID environment variables.",
        )
    return app_id, private_key, business_id, store_id


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

    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_enc = b64url(signature)

    return f"{header_enc}.{payload_enc}.{sig_enc}"


async def get_access_token() -> str:
    app_id, private_key_pem, business_id, store_id = _get_config()
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
            raise HTTPException(status_code=502, detail=f"Poynt token error: {resp.text}")
        return resp.json().get("accessToken") or resp.json().get("access_token")


async def create_terminal_order(amount_cents: int, currency: str = "USD", order_ref: str = "") -> str:
    app_id, private_key_pem, business_id, store_id = _get_config()
    token = await get_access_token()

    order_payload = {
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
                "sku": order_ref,
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
            },
        )
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"Poynt create order error: {resp.text}")
        data = resp.json()
        return data.get("id") or data.get("orderId")


async def get_transaction_for_order(order_id: str) -> dict:
    app_id, private_key_pem, business_id, store_id = _get_config()
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
            raise HTTPException(status_code=502, detail=f"Poynt status error: {resp.text}")

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
