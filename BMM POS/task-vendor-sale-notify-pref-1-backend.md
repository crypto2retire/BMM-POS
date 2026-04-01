# Task: Vendor Sale Notification Preference — Part 1 (Backend + DB)

## Overview
Add a per-vendor preference for how they want to be notified when their items sell: **instant**, **daily**, **weekly**, or **monthly**. Default is **instant** (current behavior). Emails include item name, sale price, and the vendor's updated running balance.

---

## Step 1: Add Column to Vendor Model

### File: `app/models/vendor.py`

Add this field to the `Vendor` class, after `font_size_preference`:

```python
    sale_notify_preference: Mapped[str] = mapped_column(String(10), default="instant", nullable=False, server_default="instant")
```

Valid values: `"instant"`, `"daily"`, `"weekly"`, `"monthly"`

---

## Step 2: Auto-Migration in `app/main.py`

In the `lifespan` function, add with the other ALTER TABLE statements:

```python
            await conn.execute(text("""
                ALTER TABLE vendors
                ADD COLUMN IF NOT EXISTS sale_notify_preference VARCHAR(10) NOT NULL DEFAULT 'instant'
            """))
```

---

## Step 3: Update Preferences Schema and Endpoint

### File: `app/routers/auth.py`

**Update the `DisplayPreferencesUpdate` model** (around line 151):

Find:
```python
class DisplayPreferencesUpdate(BaseModel):
    theme_preference: Optional[str] = None
    font_size_preference: Optional[str] = None
```

Replace with:
```python
class DisplayPreferencesUpdate(BaseModel):
    theme_preference: Optional[str] = None
    font_size_preference: Optional[str] = None
    sale_notify_preference: Optional[str] = None
```

**Update the `update_preferences` endpoint** (around line 156):

Add this block after the `font_size_preference` validation (after line 174, before `await db.commit()`):

```python
    valid_notify_prefs = {"instant", "daily", "weekly", "monthly"}
    if prefs.sale_notify_preference is not None:
        if prefs.sale_notify_preference not in valid_notify_prefs:
            raise HTTPException(status_code=400, detail=f"Invalid notification preference. Must be one of: {valid_notify_prefs}")
        current_user.sale_notify_preference = prefs.sale_notify_preference
```

**Update the return dict** to include the new field:

```python
    return {
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "sale_notify_preference": current_user.sale_notify_preference,
        "detail": "Preferences updated.",
    }
```

**Update the `/me` GET endpoint** to also return the field. Find where `theme_preference` and `font_size_preference` are returned in the `/me` response and add:

```python
        "sale_notify_preference": user.sale_notify_preference,
```

---

## Step 4: Update Product Sold Notification Logic

### File: `app/routers/notifications.py`

The key change: `bg_notify_product_sold` should check the vendor's preference. If it's "instant", send immediately (current behavior). If it's "daily", "weekly", or "monthly", skip the instant email — the batched emails will be sent by a scheduled task (Part 2).

**Update `bg_notify_product_sold`** (around line 178):

Find:
```python
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
```

Replace with:
```python
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
            await send_email_safe(vendor_email, subject, html_body, plain_body)
    except Exception as e:
        logger.warning(f"Background product sold notification failed: {e}")
```

Add the `select` import at the top of the file if not already there:
```python
from sqlalchemy import select
```

---

## Step 5: Update product_sold_email Template to Include Balance

### File: `app/services/email_templates.py`

**Update the `product_sold_email` function** signature and body:

Find:
```python
async def product_sold_email(
    vendor_name: str,
    item_name: str,
    item_sku: str,
    sale_price: float,
    sale_id: int,
    sold_at: str,
    db=None,
) -> tuple[str, str, str]:
```

Replace with:
```python
async def product_sold_email(
    vendor_name: str,
    item_name: str,
    item_sku: str,
    sale_price: float,
    sale_id: int,
    sold_at: str,
    current_balance: float = None,
    db=None,
) -> tuple[str, str, str]:
```

Then in the info table inside that function, find:
```python
        + _info_table([
            ("Item", item_name),
            ("SKU", item_sku),
            ("Sale Price", f"${sale_price:.2f}"),
            ("Sale #", str(sale_id)),
            ("Date", sold_at),
        ])
```

Replace with:
```python
        + _info_table([
            ("Item", item_name),
            ("SKU", item_sku),
            ("Sale Price", f"${sale_price:.2f}"),
            ("Sale #", str(sale_id)),
            ("Date", sold_at),
        ] + ([("Current Balance", f"${current_balance:.2f}")] if current_balance is not None else []))
```

Also update the plain text line to include balance:
```python
    balance_str = f" Current balance: ${current_balance:.2f}." if current_balance is not None else ""
    plain = f"{greeting} {body_text} Item: {item_name}, SKU: {item_sku}, ${sale_price:.2f}. Sale #{sale_id} on {sold_at}.{balance_str}"
```

---

## Step 6: Update POS to Pass vendor_id

### File: `app/routers/pos.py`

Find where `bg_notify_product_sold` is called (around line 458):

```python
                asyncio.ensure_future(bg_notify_product_sold(
                    vendor_name=si.vendor.name or "Vendor",
                    vendor_email=si.vendor.email,
                    item_name=si.item.name,
                    item_sku=si.item.sku or "",
                    sale_price=float(si.line_total),
                    sale_id=sale.id,
                    sold_at=sold_at_str,
                ))
```

Replace with:
```python
                asyncio.ensure_future(bg_notify_product_sold(
                    vendor_id=si.vendor.id,
                    vendor_name=si.vendor.name or "Vendor",
                    vendor_email=si.vendor.email,
                    item_name=si.item.name,
                    item_sku=si.item.sku or "",
                    sale_price=float(si.line_total),
                    sale_id=sale.id,
                    sold_at=sold_at_str,
                ))
```

Also check if there are other places `bg_notify_product_sold` is called (e.g., in `sales.py`) and add `vendor_id` there too.

---

## Testing
1. Deploy and verify the migration runs (check `sale_notify_preference` column exists on vendors)
2. Make a test sale — with default "instant" preference, vendor should still get the email with the new "Current Balance" row
3. Change a vendor's preference to "daily" via the API: `PUT /api/v1/auth/me/preferences` with `{"sale_notify_preference": "daily"}`
4. Make another sale — no email should be sent (it's batched now)
5. Change back to "instant" and verify emails resume

## Files Changed
- `app/models/vendor.py` (new column)
- `app/main.py` (migration)
- `app/routers/auth.py` (schema + endpoint)
- `app/routers/notifications.py` (preference check + balance)
- `app/services/email_templates.py` (balance in template)
- `app/routers/pos.py` (pass vendor_id)
