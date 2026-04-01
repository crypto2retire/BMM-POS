# Task: Vendor Sale Notification Preference — Part 3 (Digest Emails)

## Overview
Add an endpoint and email template for batched sale digest emails. Vendors with "daily", "weekly", or "monthly" notification preference get a single summary email listing all items sold during that period, with their current balance.

This endpoint will be called by a scheduled task / cron job.

**Depends on:** Parts 1 and 2 must be deployed first.

---

## Step 1: Add Digest Email Template

### File: `app/services/email_templates.py`

**Add a new template default** to the `EMAIL_TEMPLATE_DEFAULTS` dict (add after the last template entry, before the closing `}`):

```python
    "sale_digest": {
        "label": "Sale Digest",
        "subject": "{period_label} Sales Summary — {items_sold} item(s) sold",
        "greeting": "Hello {vendor_name},",
        "body": "Here is your {period_label} sales summary from Bowenstreet Market.",
        "closing": "View your full sales history and balance on your vendor dashboard.",
        "variables": ["vendor_name", "period_label", "items_sold", "total_revenue", "current_balance"],
    },
```

**Add the template function** at the end of the file (after the last template function):

```python
async def sale_digest_email(
    vendor_name: str,
    period_label: str,
    items: list[dict],
    total_revenue: float,
    current_balance: float,
    db=None,
) -> tuple[str, str, str]:
    """
    items: list of dicts with keys: item_name, item_sku, sale_price, sale_id, sold_at
    """
    custom = await get_custom_template("sale_digest", db)
    items_sold = len(items)
    variables = dict(
        vendor_name=vendor_name,
        period_label=period_label,
        items_sold=str(items_sold),
        total_revenue=f"{total_revenue:.2f}",
        current_balance=f"{current_balance:.2f}",
    )
    defaults = EMAIL_TEMPLATE_DEFAULTS["sale_digest"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    # Build item list table
    item_rows = ""
    for it in items:
        item_rows += _info_row(it["item_name"], f"${it['sale_price']:.2f}")
    items_table = f'<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BG};margin:16px 0">{item_rows}</table>' if item_rows else ""

    body = (
        _p(greeting)
        + _p(body_text)
        + items_table
        + _info_table([
            ("Items Sold", str(items_sold)),
            ("Total Revenue", f"${total_revenue:.2f}"),
            ("Current Balance", f"${current_balance:.2f}"),
        ])
        + (_p(closing) if closing else "")
    )

    # Plain text version
    items_plain = "; ".join(f"{it['item_name']} (${it['sale_price']:.2f})" for it in items)
    plain = (
        f"{greeting} {body_text} "
        f"Items sold: {items_plain}. "
        f"Total revenue: ${total_revenue:.2f}. Current balance: ${current_balance:.2f}."
    )
    return subject, _base_template(f"{period_label} Sales Summary", body), plain
```

---

## Step 2: Add Digest Endpoint

### File: `app/routers/notifications.py`

Add this import at the top (with the other email_templates imports):

```python
from app.services.email_templates import sale_digest_email
```

Also add these imports if not already present:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, and_
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.models.vendor import VendorBalance
```

**Add the digest endpoint** at the end of the file:

```python
@router.post("/send-sale-digests")
async def send_sale_digests(
    period: str = "daily",
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
    """
    Send batched sale digest emails to vendors with matching notification preference.
    period: "daily", "weekly", or "monthly"
    Can be called manually or by a scheduled task.
    """
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="period must be daily, weekly, or monthly")

    if not await _is_notification_enabled(db, "notify_product_sold"):
        return {"message": "Product sold notifications are disabled globally", "sent": 0}

    CST = ZoneInfo("America/Chicago")
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

    # Find vendors with this notification preference
    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.sale_notify_preference == period,
            Vendor.is_active == True,
            Vendor.role == "vendor",
            Vendor.email.isnot(None),
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
            await send_email_safe(vendor.email, subject, html_body, plain_body)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send {period} digest to vendor {vendor.id}: {e}")

    return {"message": f"Sent {sent_count} {period} digest email(s)", "sent": sent_count}
```

---

## Step 3: Also Add Vendors with is_vendor Flag

The query above filters `Vendor.role == "vendor"`, but some cashiers/admins also have booths (`is_vendor=True`). Update the vendor query to include them:

Replace the vendor query with:

```python
    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.sale_notify_preference == period,
            Vendor.is_active == True,
            Vendor.email.isnot(None),
            (Vendor.role == "vendor") | (Vendor.is_vendor == True),
        )
    )
```

---

## Step 4: Scheduled Calls

This endpoint can be called manually from the admin panel, or set up as a cron/scheduled task:

- **Daily digest:** Call `POST /api/v1/notifications/send-sale-digests?period=daily` at ~8:00 AM CST every day
- **Weekly digest:** Call `POST /api/v1/notifications/send-sale-digests?period=weekly` at ~8:00 AM CST every Monday
- **Monthly digest:** Call `POST /api/v1/notifications/send-sale-digests?period=monthly` at ~8:00 AM CST on the 1st of each month

These can be set up via Railway cron, an external scheduler, or a lightweight internal scheduler added later.

---

## Testing
1. Set a test vendor's preference to "daily"
2. Make a sale for that vendor
3. Call the digest endpoint manually: `POST /api/v1/notifications/send-sale-digests?period=daily` (as admin)
4. Verify the vendor receives a summary email with all items sold yesterday, total revenue, and current balance
5. Verify vendors with "instant" preference do NOT receive a digest email
6. Test with a vendor who had no sales — should be skipped (no email)

## Files Changed
- `app/services/email_templates.py` (new template default + function)
- `app/routers/notifications.py` (new endpoint)
