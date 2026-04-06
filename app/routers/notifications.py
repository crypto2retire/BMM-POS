import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.store_setting import StoreSetting
from app.models.vendor import Vendor, VendorBalance
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.routers.auth import get_current_user, require_admin
from app.services.email import send_email, send_email_safe, _get_gmail_access_token, _get_sender_email
from app.timezone import STORE_TZ
from app.services.email_templates import (
    test_email,
    product_sold_email,
    vendor_welcome_email,
    order_confirmation_email,
    weekly_report_email,
    EMAIL_TEMPLATE_DEFAULTS,
    sale_digest_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _log_email_delivery_result(result: dict, *, context: str, email: str) -> None:
    if result.get("success"):
        return
    logger.error(
        "Email delivery failed during %s for %s: %s",
        context,
        email,
        result.get("error", "Unknown error"),
    )


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
        error_msg = str(e)
        logger.warning(f"Could not get connected email: {error_msg}")
        if "SMTP" not in error_msg:
            from app.services.email import _has_smtp_credentials
            if _has_smtp_credentials():
                import os
                return {"connected": True, "email": os.environ.get("GMAIL_ADDRESS")}
        return {"connected": False, "email": None, "error": error_msg}


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
        error_msg = result.get("error", "Unknown error")
        if "BadCredentials" in str(error_msg) or "Username and Password not accepted" in str(error_msg):
            raise HTTPException(
                status_code=400,
                detail="Gmail credentials are invalid. Please update the Gmail App Password in your environment variables.",
            )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to send email: {error_msg}",
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
    result = await send_email_safe(vendor.email, subject, html_body, plain_body)
    _log_email_delivery_result(result, context="product sold notification", email=vendor.email)


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
    result = await send_email_safe(email, subject, html_body, plain_body)
    _log_email_delivery_result(result, context="vendor welcome notification", email=email)


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
    result = await send_email_safe(receipt_email, subject, html_body, plain_body)
    _log_email_delivery_result(result, context="order confirmation", email=receipt_email)


async def bg_notify_product_sold(
    vendor_id: int,
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

            # Check vendor's notification preference
            vendor = await db.get(Vendor, vendor_id)
            if not vendor or not vendor.email:
                return
            pref = getattr(vendor, 'sale_notify_preference', 'instant')
            if pref != 'instant':
                # Non-instant: skip email now, batched emails sent by scheduled task
                return

            # Get vendor's current balance for the email
            from app.models.vendor import VendorBalance
            balance_row = await db.execute(
                select(VendorBalance.balance).where(VendorBalance.vendor_id == vendor_id)
            )
            current_balance = float(balance_row.scalar_one_or_none() or 0)

            subject, html_body, plain_body = await product_sold_email(
                vendor_name=vendor_name, item_name=item_name, item_sku=item_sku,
                sale_price=sale_price, sale_id=sale_id, sold_at=sold_at,
                current_balance=current_balance, db=db,
            )
            result = await send_email_safe(vendor_email, subject, html_body, plain_body)
            _log_email_delivery_result(result, context="background product sold notification", email=vendor_email)
    except Exception as e:
        logger.exception("Background product sold notification failed")


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
            result = await send_email_safe(receipt_email, subject, html_body, plain_body)
            _log_email_delivery_result(result, context="background order confirmation", email=receipt_email)
    except Exception as e:
        logger.exception("Background order confirmation failed")


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
    result = await send_email_safe(vendor.email, subject, html_body, plain_body)
    _log_email_delivery_result(result, context="weekly report", email=vendor.email)


@router.post("/send-sale-digests")
async def send_sale_digests(
    period: str = "daily",
    db: AsyncSession = Depends(get_db),
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """
    Send batched sale digest emails to vendors with matching notification preference.
    period: "daily", "weekly", or "monthly"
    Can be called manually or by a scheduled task.
    """
    # Auth: accept either a valid cron secret OR admin JWT
    cron_secret = os.getenv("CRON_SECRET")
    if x_cron_secret and cron_secret and x_cron_secret == cron_secret:
        pass  # Cron auth OK
    elif authorization:
        from app.routers.auth import get_user_from_authorization_header
        try:
            user = await get_user_from_authorization_header(authorization, db)
            if user.role != "admin":
                raise HTTPException(status_code=403, detail="Admin only")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        raise HTTPException(status_code=401, detail="Auth required: send X-Cron-Secret header or admin Bearer token")

    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="period must be daily, weekly, or monthly")

    if not await _is_notification_enabled(db, "notify_product_sold"):
        return {"message": "Product sold notifications are disabled globally", "sent": 0}

    CST = STORE_TZ
    now = datetime.now(CST)

    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_label = f"Daily ({start.strftime('%b %d')})"
    elif period == "weekly":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=7)
        period_label = f"Weekly ({start.strftime('%b %d')} – {(end - timedelta(days=1)).strftime('%b %d')})"
    else:  # monthly
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end.replace(day=1) - timedelta(days=1)
        start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_label = f"Monthly ({start.strftime('%B %Y')})"

    # Find vendors with this notification preference (include is_vendor staff)
    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.sale_notify_preference == period,
            Vendor.is_active == True,
            Vendor.email.isnot(None),
            (Vendor.role == "vendor") | (Vendor.is_vendor == True),
        )
    )
    vendors = vendors_result.scalars().all()

    if not vendors:
        return {"message": f"No vendors with {period} notification preference", "sent": 0}

    sent_count = 0
    for vendor in vendors:
        # Get sales for this vendor in the period
        sale_items_result = await db.execute(
            select(SaleItem, Sale, Item).join(
                Sale, SaleItem.sale_id == Sale.id
            ).join(
                Item, SaleItem.item_id == Item.id
            ).where(
                SaleItem.vendor_id == vendor.id,
                Sale.is_voided == False,
                Sale.created_at >= start,
                Sale.created_at < end,
            ).order_by(Sale.created_at)
        )
        rows = sale_items_result.all()

        if not rows:
            continue  # No sales for this vendor in the period

        items = []
        total_revenue = 0.0
        for si, sale, item in rows:
            items.append({
                "item_name": item.name,
                "item_sku": item.sku or "",
                "sale_price": float(si.line_total),
                "sale_id": sale.id,
                "sold_at": sale.created_at.astimezone(CST).strftime("%b %d at %I:%M %p"),
            })
            total_revenue += float(si.line_total)

        # Get current balance
        balance_row = await db.execute(
            select(VendorBalance.balance).where(VendorBalance.vendor_id == vendor.id)
        )
        current_balance = float(balance_row.scalar_one_or_none() or 0)

        try:
            subject, html_body, plain_body = await sale_digest_email(
                vendor_name=vendor.name or "Vendor",
                period_label=period_label,
                items=items,
                total_revenue=total_revenue,
                current_balance=current_balance,
                db=db,
            )
            result = await send_email_safe(vendor.email, subject, html_body, plain_body)
            _log_email_delivery_result(
                result,
                context=f"{period} sale digest for vendor {vendor.id}",
                email=vendor.email,
            )
            sent_count += 1
        except Exception:
            logger.exception("Failed to send %s digest to vendor %s", period, vendor.id)

    return {"message": f"Sent {sent_count} {period} digest email(s)", "sent": sent_count}
