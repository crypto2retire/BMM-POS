# Cursor Task: Add Sale Digest Emails (Notification Pref Part 3)

> **Depends on:** Parts 1 & 2 are already deployed. The `sale_notify_preference` column exists on the `vendors` table and the vendor dashboard dropdown is live.

---

## What to do

Add a digest email template and a new endpoint so vendors who chose "daily", "weekly", or "monthly" notification preference get a single batched summary email instead of instant per-sale emails.

**Two files to edit:**

---

### 1. `app/services/email_templates.py`

**A) Add a new entry to `EMAIL_TEMPLATE_DEFAULTS` dict** (add after the last template entry, before the closing `}`):

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

**B) Add this function at the end of the file** (after the last template function):

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

### 2. `app/routers/notifications.py`

**A) Add these imports at the top** (merge with existing imports — skip any already present):

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, and_
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.models.vendor import VendorBalance
from app.services.email_templates import sale_digest_email
```

**B) Add this endpoint at the end of the file:**

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
            await send_email_safe(vendor.email, subject, html_body, plain_body)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send {period} digest to vendor {vendor.id}: {e}")

    return {"message": f"Sent {sent_count} {period} digest email(s)", "sent": sent_count}
```

---

## Do NOT change

- Any other files
- The existing `bg_notify_product_sold` function (already updated in Part 1)
- The vendor dashboard (already updated in Part 2)

## After deploying

Test manually as admin: `POST /api/v1/notifications/send-sale-digests?period=daily`

The scheduled cron jobs (daily 8am, weekly Monday 8am, monthly 1st 8am CST) will be set up separately.
