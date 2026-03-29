import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.store_setting import StoreSetting
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, require_admin
from app.services.email import send_email, send_email_safe
from app.services.email_templates import (
    test_email,
    product_sold_email,
    vendor_welcome_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _is_notification_enabled(db: AsyncSession, key: str) -> bool:
    result = await db.execute(
        select(StoreSetting.value).where(StoreSetting.key == key)
    )
    val = result.scalar_one_or_none()
    return val == "true" or val == "1"


class TestEmailPayload(BaseModel):
    to_email: Optional[str] = None


@router.post("/test-email")
async def send_test_email(
    payload: TestEmailPayload,
    db: AsyncSession = Depends(get_db),
    admin: Vendor = Depends(require_admin),
):
    to = payload.to_email or admin.email
    if not to:
        raise HTTPException(status_code=400, detail="No email address provided")

    subject, html_body, plain_body = test_email(admin.name or "Admin")
    result = await send_email(to, subject, html_body, plain_body)

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"Failed to send email: {result.get('error', 'Unknown error')}",
        )
    return {"message": f"Test email sent to {to}", "message_id": result.get("message_id")}


async def notify_product_sold(
    db: AsyncSession,
    vendor: Vendor,
    item_name: str,
    item_sku: str,
    sale_price: float,
    sale_id: int,
    sold_at: str,
):
    if not await _is_notification_enabled(db, "notify_product_sold"):
        return
    if not vendor.email:
        return

    subject, html_body, plain_body = product_sold_email(
        vendor_name=vendor.name or "Vendor",
        item_name=item_name,
        item_sku=item_sku,
        sale_price=sale_price,
        sale_id=sale_id,
        sold_at=sold_at,
    )
    await send_email_safe(vendor.email, subject, html_body, plain_body)


async def notify_vendor_welcome(
    db: AsyncSession,
    vendor_name: str,
    email: str,
    password: str,
    booth: str,
    login_url: str,
):
    if not await _is_notification_enabled(db, "auto_vendor_email"):
        return
    if not email:
        return

    subject, html_body, plain_body = vendor_welcome_email(
        vendor_name=vendor_name,
        email=email,
        password=password,
        booth=booth,
        login_url=login_url,
    )
    await send_email_safe(email, subject, html_body, plain_body)
