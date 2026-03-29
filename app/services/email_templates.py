from datetime import datetime
from zoneinfo import ZoneInfo

CST = ZoneInfo("America/Chicago")

BRAND_BG = "#38383B"
BRAND_GOLD = "#C9A96E"
BRAND_TEXT = "#F0EDE8"
BRAND_SURFACE = "#2a2a2d"

EMAIL_TEMPLATE_DEFAULTS = {
    "product_sold": {
        "label": "Item Sold",
        "subject": "Item Sold: {item_name}",
        "greeting": "Hello {vendor_name},",
        "body": "One of your items has been sold at Bowenstreet Market!",
        "closing": "Your vendor balance has been credited. You can view your full sales history in your vendor dashboard.",
        "variables": ["vendor_name", "item_name", "item_sku", "sale_price", "sale_id", "sold_at"],
    },
    "payout_processed": {
        "label": "Payout Processed",
        "subject": "Payout Processed: ${payout_amount}",
        "greeting": "Hello {vendor_name},",
        "body": "Your vendor payout has been processed.",
        "closing": "If you have questions about this payout, please contact the front desk.",
        "variables": ["vendor_name", "payout_amount", "period", "method"],
    },
    "payout_with_rent": {
        "label": "Payout with Rent Deducted",
        "subject": "Payout Processed: ${net_payout} — {period}",
        "greeting": "Hello {vendor_name},",
        "body": "Your vendor payout for {period} has been processed. Booth rent has been deducted from your sales.",
        "closing": "If you have questions about this payout, please contact the front desk.",
        "variables": ["vendor_name", "gross_sales", "rent_deducted", "net_payout", "period", "method"],
    },
    "rent_due": {
        "label": "Rent Due Reminder",
        "subject": "Rent Due: ${amount} — {due_date}",
        "greeting": "Hello {vendor_name},",
        "body": "This is a friendly reminder that your booth rent is coming due.",
        "closing": "You can pay by cash, check, Zelle, or Square at the front desk. Thank you!",
        "variables": ["vendor_name", "amount", "due_date", "booth"],
    },
    "rent_overdue_15day": {
        "label": "Rent Overdue (15 Days)",
        "subject": "Rent Past Due: ${amount} — {period}",
        "greeting": "Hello {vendor_name},",
        "body": "This is a reminder that your booth rent for {period} is now 15 days past due.",
        "closing": "Please arrange payment at your earliest convenience. You can pay by cash, check, Zelle, or Square at the front desk.\n\nIf you have already made this payment, please disregard this notice and contact the front desk so we can update your account.",
        "variables": ["vendor_name", "amount", "booth", "period"],
    },
    "rent_overdue_27day": {
        "label": "Rent Overdue — Final Notice (27 Days)",
        "subject": "URGENT: Rent Past Due ${amount} — Final Notice",
        "greeting": "Hello {vendor_name},",
        "body": "This is a final notice that your booth rent for {period} is now 27 days past due.",
        "closing": "Please arrange payment immediately. Failure to pay may result in suspension of your booth privileges.\n\nIf you have already made this payment or need to discuss payment arrangements, please contact the front desk as soon as possible.",
        "variables": ["vendor_name", "amount", "booth", "period"],
    },
    "rent_shortfall": {
        "label": "Rent Shortfall Notice",
        "subject": "Rent Balance Due: ${shortfall} — {period}",
        "greeting": "Hello {vendor_name},",
        "body": "Your sales for {period} were not enough to cover your booth rent. The remaining balance is due.",
        "closing": "Please arrange payment for the remaining balance at the front desk by cash, check, Zelle, or Square.",
        "variables": ["vendor_name", "gross_sales", "rent_amount", "shortfall", "booth", "period"],
    },
    "vendor_welcome": {
        "label": "Vendor Welcome",
        "subject": "Welcome to Bowenstreet Market!",
        "greeting": "Hello {vendor_name},",
        "body": "Welcome to the Bowenstreet Market vendor family! Your account has been created and is ready to use.",
        "closing": "Please change your password after your first login. If you have any questions, visit the front desk or reply to this email.",
        "variables": ["vendor_name", "email", "password", "booth", "login_url"],
    },
    "expiring_items": {
        "label": "Items Expiring Soon",
        "subject": "{count} Item(s) Expiring Soon",
        "greeting": "Hello {vendor_name},",
        "body": "You have items that have been on the floor too long. Please review and update or remove these items.",
        "closing": "",
        "variables": ["vendor_name", "count", "days_threshold"],
    },
    "weekly_report": {
        "label": "Weekly Sales Report",
        "subject": "Weekly Report: {period_label}",
        "greeting": "Hello {vendor_name},",
        "body": "Here is your weekly summary for {period_label}.",
        "closing": "Log into your vendor dashboard for full details.",
        "variables": ["vendor_name", "period_label", "total_sales", "items_sold", "current_balance", "active_items"],
    },
    "order_confirmation": {
        "label": "Order Confirmation",
        "subject": "Order Confirmation #{sale_id}",
        "greeting": "Hello{customer_name_with_space},",
        "body": "Thank you for your purchase at Bowenstreet Market! Here is your order confirmation.",
        "closing": "Thank you for shopping at Bowenstreet Market!",
        "variables": ["customer_name", "sale_id"],
    },
}


async def get_custom_template(template_key: str, db=None) -> dict:
    if not db:
        return {}
    try:
        from sqlalchemy import select
        from app.models.store_setting import StoreSetting

        prefix = f"email_tpl_{template_key}_"
        result = await db.execute(
            select(StoreSetting).where(StoreSetting.key.like(f"email_tpl_{template_key}_%"))
        )
        rows = result.scalars().all()
        custom = {}
        for row in rows:
            field = row.key.replace(prefix, "")
            if row.value and row.value.strip():
                custom[field] = row.value
        return custom
    except Exception:
        return {}


def _apply_custom(defaults: dict, custom: dict, variables: dict) -> tuple:
    tpl_key = defaults.get("_key", "")
    subject = custom.get("subject") or defaults.get("subject", "")
    greeting = custom.get("greeting") or defaults.get("greeting", "")
    body_text = custom.get("body") or defaults.get("body", "")
    closing = custom.get("closing") or defaults.get("closing", "")

    try:
        subject = subject.format(**variables)
    except (KeyError, IndexError):
        pass
    try:
        greeting = greeting.format(**variables)
    except (KeyError, IndexError):
        pass
    try:
        body_text = body_text.format(**variables)
    except (KeyError, IndexError):
        pass
    try:
        closing = closing.format(**variables)
    except (KeyError, IndexError):
        pass

    return subject, greeting, body_text, closing


def _base_template(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{BRAND_BG};font-family:Georgia,'Times New Roman',serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BG}">
<tr><td align="center" style="padding:30px 15px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">

<tr><td style="background:{BRAND_SURFACE};padding:28px 30px;text-align:center;border-bottom:2px solid {BRAND_GOLD}">
<h1 style="margin:0;font-size:24px;color:{BRAND_GOLD};font-style:italic;font-weight:400;letter-spacing:1px">Bowenstreet Market</h1>
<p style="margin:4px 0 0;font-size:11px;color:#999;letter-spacing:2px;text-transform:uppercase;font-family:Arial,sans-serif">Handcrafted &middot; Vintage &middot; Antique</p>
</td></tr>

<tr><td style="background:{BRAND_SURFACE};padding:30px">
<h2 style="margin:0 0 18px;font-size:20px;color:{BRAND_TEXT};font-style:italic;font-weight:400">{title}</h2>
{body_html}
</td></tr>

<tr><td style="background:{BRAND_BG};padding:20px 30px;text-align:center;border-top:1px solid #555">
<p style="margin:0;font-size:11px;color:#888;font-family:Arial,sans-serif">
Bowenstreet Market &middot; 2837 Bowen St, Oshkosh WI 54901<br>
This is an automated notification. Please do not reply to this email.
</p>
</td></tr>

</table>
</td></tr></table>
</body></html>"""


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:15px;color:{BRAND_TEXT};line-height:1.6;font-family:Arial,sans-serif">{text}</p>'


def _info_row(label: str, value: str) -> str:
    return f"""<tr>
<td style="padding:8px 12px;font-size:13px;color:#aaa;font-family:Arial,sans-serif;border-bottom:1px solid #444;width:140px">{label}</td>
<td style="padding:8px 12px;font-size:14px;color:{BRAND_TEXT};font-family:Arial,sans-serif;border-bottom:1px solid #444">{value}</td>
</tr>"""


def _info_table(rows: list[tuple[str, str]]) -> str:
    inner = "".join(_info_row(l, v) for l, v in rows)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BG};margin:16px 0">{inner}</table>'


def _now_str() -> str:
    return datetime.now(CST).strftime("%-m/%-d/%Y %-I:%M %p")


async def product_sold_email(
    vendor_name: str,
    item_name: str,
    item_sku: str,
    sale_price: float,
    sale_id: int,
    sold_at: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("product_sold", db)
    variables = dict(vendor_name=vendor_name, item_name=item_name, item_sku=item_sku,
                     sale_price=f"{sale_price:.2f}", sale_id=str(sale_id), sold_at=sold_at)
    defaults = EMAIL_TEMPLATE_DEFAULTS["product_sold"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Item", item_name),
            ("SKU", item_sku),
            ("Sale Price", f"${sale_price:.2f}"),
            ("Sale #", str(sale_id)),
            ("Date", sold_at),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Item: {item_name}, SKU: {item_sku}, ${sale_price:.2f}. Sale #{sale_id} on {sold_at}."
    return subject, _base_template("Item Sold", body), plain


async def payout_processed_email(
    vendor_name: str,
    payout_amount: float,
    period: str,
    method: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("payout_processed", db)
    variables = dict(vendor_name=vendor_name, payout_amount=f"{payout_amount:.2f}", period=period, method=method)
    defaults = EMAIL_TEMPLATE_DEFAULTS["payout_processed"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Amount", f"${payout_amount:.2f}"),
            ("Period", period),
            ("Method", method),
            ("Processed", _now_str()),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Amount: ${payout_amount:.2f}, period: {period}, method: {method}."
    return subject, _base_template("Payout Processed", body), plain


def expiring_items_email(
    vendor_name: str,
    items: list[dict],
    days_threshold: int = 90,
) -> tuple[str, str, str]:
    count = len(items)
    subject = f"{count} Item{'s' if count != 1 else ''} Expiring Soon"
    item_rows = ""
    for it in items[:20]:
        item_rows += f'<tr><td style="padding:6px 12px;font-size:13px;color:{BRAND_TEXT};font-family:Arial,sans-serif;border-bottom:1px solid #444">{it.get("name","")}</td><td style="padding:6px 12px;font-size:13px;color:#aaa;font-family:Arial,sans-serif;border-bottom:1px solid #444">{it.get("sku","")}</td><td style="padding:6px 12px;font-size:13px;color:#aaa;font-family:Arial,sans-serif;border-bottom:1px solid #444">{it.get("days","")} days</td></tr>'
    body = (
        _p(f"Hello {vendor_name},")
        + _p(f"You have {count} item{'s' if count != 1 else ''} that {'have' if count != 1 else 'has'} been on the floor for over {days_threshold} days. Please review and update or remove these items.")
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BG};margin:16px 0"><tr><td style="padding:8px 12px;font-size:11px;color:{BRAND_GOLD};font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #555">Item</td><td style="padding:8px 12px;font-size:11px;color:{BRAND_GOLD};font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #555">SKU</td><td style="padding:8px 12px;font-size:11px;color:{BRAND_GOLD};font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #555">Age</td></tr>{item_rows}</table>'
        + (_p(f"...and {count - 20} more.") if count > 20 else "")
    )
    names = ", ".join(it.get("name", "") for it in items[:5])
    plain = f"Hello {vendor_name}, {count} items are expiring soon: {names}."
    return subject, _base_template("Items Expiring Soon", body), plain


def weekly_report_email(
    vendor_name: str,
    period_label: str,
    total_sales: float,
    items_sold: int,
    current_balance: float,
    active_items: int,
    expiring_count: int = 0,
) -> tuple[str, str, str]:
    subject = f"Weekly Report: {period_label}"
    body = (
        _p(f"Hello {vendor_name},")
        + _p(f"Here is your weekly summary for <strong>{period_label}</strong>.")
        + _info_table([
            ("Items Sold", str(items_sold)),
            ("Total Sales", f"${total_sales:.2f}"),
            ("Current Balance", f"${current_balance:.2f}"),
            ("Active Items", str(active_items)),
        ])
        + (_p(f"&#9888; You have {expiring_count} item{'s' if expiring_count != 1 else ''} that may need attention.") if expiring_count else "")
        + _p("Log into your vendor dashboard for full details.")
    )
    plain = f"Hello {vendor_name}, weekly report for {period_label}: {items_sold} items sold, ${total_sales:.2f} total, balance ${current_balance:.2f}."
    return subject, _base_template("Weekly Sales Report", body), plain


async def rent_due_email(
    vendor_name: str,
    amount: float,
    due_date: str,
    booth: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("rent_due", db)
    variables = dict(vendor_name=vendor_name, amount=f"{amount:.2f}", due_date=due_date, booth=booth)
    defaults = EMAIL_TEMPLATE_DEFAULTS["rent_due"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Booth", booth),
            ("Amount Due", f"${amount:.2f}"),
            ("Due Date", due_date),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Booth: {booth}, ${amount:.2f} due {due_date}."
    return subject, _base_template("Rent Due Reminder", body), plain


async def vendor_welcome_email(
    vendor_name: str,
    email: str,
    password: str,
    booth: str,
    login_url: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("vendor_welcome", db)
    variables = dict(vendor_name=vendor_name, email=email, password=password, booth=booth, login_url=login_url)
    defaults = EMAIL_TEMPLATE_DEFAULTS["vendor_welcome"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Booth", booth),
            ("Email", email),
            ("Temporary Password", password),
        ])
        + f'<p style="margin:20px 0;text-align:center"><a href="{login_url}" style="display:inline-block;background:{BRAND_GOLD};color:#1a1a1a;text-decoration:none;padding:12px 32px;font-size:14px;font-weight:600;font-family:Arial,sans-serif;letter-spacing:1px;text-transform:uppercase">Log In to Your Dashboard</a></p>'
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Log in at {login_url} with email: {email} and password: {password}."
    return subject, _base_template("Welcome!", body), plain


def order_confirmation_email(
    customer_name: str,
    sale_id: int,
    items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    payment_method: str,
) -> tuple[str, str, str]:
    subject = f"Order Confirmation #{sale_id}"
    item_rows = ""
    for it in items:
        item_rows += f'<tr><td style="padding:6px 12px;font-size:13px;color:{BRAND_TEXT};font-family:Arial,sans-serif;border-bottom:1px solid #444">{it.get("name","")}</td><td style="padding:6px 12px;font-size:13px;color:#aaa;font-family:Arial,sans-serif;border-bottom:1px solid #444;text-align:right">${it.get("price",0):.2f}</td></tr>'
    body = (
        _p(f"Hello{(' ' + customer_name) if customer_name else ''},")
        + _p(f"Thank you for your purchase at Bowenstreet Market! Here is your order confirmation.")
        + _info_table([
            ("Sale #", str(sale_id)),
            ("Date", _now_str()),
            ("Payment", payment_method),
        ])
        + f'<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_BG};margin:16px 0"><tr><td style="padding:8px 12px;font-size:11px;color:{BRAND_GOLD};font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #555">Item</td><td style="padding:8px 12px;font-size:11px;color:{BRAND_GOLD};font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #555;text-align:right">Price</td></tr>{item_rows}</table>'
        + _info_table([
            ("Subtotal", f"${subtotal:.2f}"),
            ("Tax", f"${tax:.2f}"),
            ("Total", f"<strong>${total:.2f}</strong>"),
        ])
        + _p("Thank you for shopping at Bowenstreet Market!")
    )
    names = ", ".join(it.get("name", "") for it in items[:5])
    plain = f"Order #{sale_id} confirmed. Items: {names}. Total: ${total:.2f}. Payment: {payment_method}."
    return subject, _base_template("Order Confirmation", body), plain


def test_email(admin_name: str) -> tuple[str, str, str]:
    subject = "Test Email from Bowenstreet Market POS"
    body = (
        _p(f"Hello {admin_name},")
        + _p("This is a test email from the Bowenstreet Market POS system. If you received this, your email notifications are configured correctly!")
        + _info_table([
            ("System", "BMM-POS"),
            ("Sent At", _now_str()),
            ("Status", "&#10003; Working"),
        ])
    )
    plain = f"Test email from BMM-POS sent at {_now_str()}. Email is working correctly."
    return subject, _base_template("Test Email", body), plain


async def rent_overdue_15day_email(
    vendor_name: str,
    amount: float,
    booth: str,
    period: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("rent_overdue_15day", db)
    variables = dict(vendor_name=vendor_name, amount=f"{amount:.2f}", booth=booth, period=period)
    defaults = EMAIL_TEMPLATE_DEFAULTS["rent_overdue_15day"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Booth", booth),
            ("Amount Due", f"${amount:.2f}"),
            ("Period", period),
            ("Status", "Past Due — 15 Days"),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Booth: {booth}, ${amount:.2f}, {period}."
    return subject, _base_template("Rent Past Due — 15 Days", body), plain


async def rent_overdue_27day_email(
    vendor_name: str,
    amount: float,
    booth: str,
    period: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("rent_overdue_27day", db)
    variables = dict(vendor_name=vendor_name, amount=f"{amount:.2f}", booth=booth, period=period)
    defaults = EMAIL_TEMPLATE_DEFAULTS["rent_overdue_27day"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Booth", booth),
            ("Amount Due", f"${amount:.2f}"),
            ("Period", period),
            ("Status", "Past Due — 27 Days (Final Notice)"),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"FINAL NOTICE: {greeting} {body_text} Booth: {booth}, ${amount:.2f}, {period}."
    return subject, _base_template("Final Notice — Rent Past Due", body), plain


async def payout_with_rent_email(
    vendor_name: str,
    gross_sales: float,
    rent_deducted: float,
    net_payout: float,
    period: str,
    method: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("payout_with_rent", db)
    variables = dict(vendor_name=vendor_name, gross_sales=f"{gross_sales:.2f}",
                     rent_deducted=f"{rent_deducted:.2f}", net_payout=f"{net_payout:.2f}",
                     period=period, method=method)
    defaults = EMAIL_TEMPLATE_DEFAULTS["payout_with_rent"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Gross Sales", f"${gross_sales:.2f}"),
            ("Rent Deducted", f"-${rent_deducted:.2f}"),
            ("Net Payout", f"${net_payout:.2f}"),
            ("Period", period),
            ("Method", method),
            ("Processed", _now_str()),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Gross: ${gross_sales:.2f}, rent: ${rent_deducted:.2f}, net: ${net_payout:.2f} via {method}."
    return subject, _base_template("Payout Processed", body), plain


async def rent_shortfall_email(
    vendor_name: str,
    gross_sales: float,
    rent_amount: float,
    shortfall: float,
    booth: str,
    period: str,
    db=None,
) -> tuple[str, str, str]:
    custom = await get_custom_template("rent_shortfall", db)
    variables = dict(vendor_name=vendor_name, gross_sales=f"{gross_sales:.2f}",
                     rent_amount=f"{rent_amount:.2f}", shortfall=f"{shortfall:.2f}",
                     booth=booth, period=period)
    defaults = EMAIL_TEMPLATE_DEFAULTS["rent_shortfall"]
    subject, greeting, body_text, closing = _apply_custom(defaults, custom, variables)

    body = (
        _p(greeting)
        + _p(body_text)
        + _info_table([
            ("Booth", booth),
            ("Gross Sales", f"${gross_sales:.2f}"),
            ("Monthly Rent", f"${rent_amount:.2f}"),
            ("Sales Applied to Rent", f"${gross_sales:.2f}"),
            ("Remaining Balance Due", f"${shortfall:.2f}"),
        ])
        + (_p(closing) if closing else "")
    )
    plain = f"{greeting} {body_text} Booth: {booth}, shortfall: ${shortfall:.2f}."
    return subject, _base_template("Rent Balance Due", body), plain
