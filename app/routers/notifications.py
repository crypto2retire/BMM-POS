import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.store_setting import StoreSetting
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, require_admin
from app.services.email import send_email, send_email_safe, _get_gmail_access_token, _get_sender_email
from app.services.email_templates import (
    test_email,
    product_sold_email,
    vendor_welcome_email,
    order_confirmation_email,
    weekly_report_email,
    EMAIL_TEMPLATE_DEFAULTS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _is_notification_enabled(db: AsyncSession, key: str) -> bool:
    result = await db.execute(
        select(StoreSetting.value).where(StoreSetting.key == key)
    )
    val = result.scalar_one_or_none()
    if val is None:
        from app.routers.settings import DEFAULT_SETTINGS
        val = DEFAULT_SETTINGS.get(key, "false")
    return val == "true" or val == "1"


@router.get("/connected-email")
async def get_connected_email(
    _admin: Vendor = Depends(require_admin),
):
    try:
        access_token = await _get_gmail_access_token()
        email_address = await _get_sender_email(access_token)
        if email_address and email_address != "me":
            return {"connected": True, "email": email_address}
        return {"connected": True, "email": None}
    except Exception as e:
        logger.warning(f"Could not get connected email: {e}")
        return {"connected": False, "email": None, "error": str(e)}


@router.get("/email-templates")
async def get_email_templates(
    _admin: Vendor = Depends(require_admin),
):
    return EMAIL_TEMPLATE_DEFAULTS


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

    subject, html_body, plain_body = await product_sold_email(
        vendor_name=vendor.name or "Vendor",
        item_name=item_name,
        item_sku=item_sku,
        sale_price=sale_price,
        sale_id=sale_id,
        sold_at=sold_at,
        db=db,
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

    subject, html_body, plain_body = await vendor_welcome_email(
        vendor_name=vendor_name,
        email=email,
        password=password,
        booth=booth,
        login_url=login_url,
        db=db,
    )
    await send_email_safe(email, subject, html_body, plain_body)


async def notify_order_confirmation(
    db: AsyncSession,
    receipt_email: str,
    customer_name: str,
    sale_id: int,
    items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    payment_method: str,
):
    if not await _is_notification_enabled(db, "notify_order_confirmation"):
        return
    if not receipt_email:
        return

    subject, html_body, plain_body = await order_confirmation_email(
        customer_name=customer_name,
        sale_id=sale_id,
        items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        payment_method=payment_method,
        db=db,
    )
    await send_email_safe(receipt_email, subject, html_body, plain_body)


async def bg_notify_product_sold(
    vendor_name: str,
    vendor_email: str,
    item_name: str,
    item_sku: str,
    sale_price: float,
    sale_id: int,
    sold_at: str,
):
    try:
        async with AsyncSessionLocal() as db:
            if not await _is_notification_enabled(db, "notify_product_sold"):
                return
            subject, html_body, plain_body = await product_sold_email(
                vendor_name=vendor_name, item_name=item_name, item_sku=item_sku,
                sale_price=sale_price, sale_id=sale_id, sold_at=sold_at, db=db,
            )
            await send_email_safe(vendor_email, subject, html_body, plain_body)
    except Exception as e:
        logger.warning(f"Background product sold notification failed: {e}")


async def bg_notify_order_confirmation(
    receipt_email: str,
    customer_name: str,
    sale_id: int,
    items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    payment_method: str,
):
    try:
        async with AsyncSessionLocal() as db:
            if not await _is_notification_enabled(db, "notify_order_confirmation"):
                return
            subject, html_body, plain_body = await order_confirmation_email(
                customer_name=customer_name, sale_id=sale_id, items=items,
                subtotal=subtotal, tax=tax, total=total,
                payment_method=payment_method, db=db,
            )
            await send_email_safe(receipt_email, subject, html_body, plain_body)
    except Exception as e:
        logger.warning(f"Background order confirmation failed: {e}")


async def notify_weekly_report(
    db: AsyncSession,
    vendor: Vendor,
    period_label: str,
    total_sales: float,
    items_sold: int,
    current_balance: float,
    active_items: int,
    expiring_count: int = 0,
):
    if not await _is_notification_enabled(db, "notify_weekly_report"):
        return
    if not vendor.email:
        return

    subject, html_body, plain_body = await weekly_report_email(
        vendor_name=vendor.name or "Vendor",
        period_label=period_label,
        total_sales=total_sales,
        items_sold=items_sold,
        current_balance=current_balance,
        active_items=active_items,
        expiring_count=expiring_count,
        db=db,
    )
    await send_email_safe(vendor.email, subject, html_body, plain_body)
