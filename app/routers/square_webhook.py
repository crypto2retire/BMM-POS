"""Square webhook handler for payment confirmations.

Square sends payment.updated events when a payment changes status.
We verify the webhook signature, then confirm the associated reservation(s).
"""
import hmac
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings
from app.models.reservation import Reservation
from app.models.item import Item

router = APIRouter(prefix="/webhooks/square", tags=["webhooks"])


def _verify_square_signature(request_body: bytes, signature: str, signature_key: str) -> bool:
    """Verify Square webhook signature using HMAC-SHA256."""
    if not signature_key:
        return False
    expected = hmac.new(
        signature_key.encode("utf-8"),
        request_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/payment")
async def square_payment_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Square payment.updated webhook events."""
    body = await request.body()
    signature = request.headers.get("x-square-signature", "")

    # If signature key is configured, verify the signature
    if settings.square_signature_key:
        if not _verify_square_signature(body, signature, settings.square_signature_key):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type", "")
    data = event.get("data", {})
    obj = data.get("object", {})
    payment = obj.get("payment", {})

    # We only care about completed payments
    if event_type != "payment.updated":
        return {"status": "ignored", "reason": f"event type {event_type} not handled"}

    payment_status = payment.get("status", "").upper()
    if payment_status != "COMPLETED":
        return {"status": "ignored", "reason": f"payment status {payment_status}"}

    payment_id = payment.get("id", "")
    if not payment_id:
        return {"status": "ignored", "reason": "missing payment id"}

    # Find reservations by square_payment_id
    result = await db.execute(
        select(Reservation)
        .where(Reservation.square_payment_id == payment_id)
        .options(selectinload(Reservation.item))
    )
    reservations = result.scalars().all()

    if not reservations:
        return {"status": "ignored", "reason": "no reservations found for payment"}

    # Check if already completed
    already_done = all(r.status == "completed" for r in reservations)
    if already_done:
        return {"status": "already_completed"}

    # Lock items and finalize
    item_ids = [r.item_id for r in reservations if r.item_id]
    if item_ids:
        await db.execute(select(Item).where(Item.id.in_(item_ids)).with_for_update())

    confirmed = 0
    for reservation in reservations:
        if reservation.status == "completed":
            continue
        reservation.status = "completed"
        if reservation.item:
            reservation.item.quantity = max(0, reservation.item.quantity - 1)
            reservation.item.reserved_quantity = max(0, reservation.item.reserved_quantity - 1)
            if reservation.item.quantity <= 0:
                reservation.item.status = "sold"
        confirmed += 1

    await db.commit()
    return {"status": "confirmed", "reservations_confirmed": confirmed}
