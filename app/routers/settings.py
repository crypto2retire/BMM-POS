from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.store_setting import StoreSetting
from app.models.vendor import Vendor
from app.routers.auth import require_admin

router = APIRouter(prefix="/admin/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "store_name": settings.store_name,
    "store_address": "2837 Bowen St, Oshkosh, WI 54901",
    "store_phone": "(920) 555-0100",
    "store_email": "info@bowenstreetmarket.com",
    "store_state": "WI",
    "store_postcode": "54901",
    "store_country": "US",
    "hours_monday": "Closed",
    "hours_tuesday": "10:00 AM - 6:00 PM",
    "hours_wednesday": "10:00 AM - 6:00 PM",
    "hours_thursday": "10:00 AM - 6:00 PM",
    "hours_friday": "10:00 AM - 6:00 PM",
    "hours_saturday": "10:00 AM - 6:00 PM",
    "hours_sunday": "11:00 AM - 4:00 PM",
    "tax_rate": str(settings.tax_rate),
    "multi_tax_enabled": "false",
    "commission_rate": "10.0",
    "default_rent": "200.00",
    "rent_due_day": "27",
    "payout_day": "1",
    "return_policy_days": "0",
    "return_policy_text": "Sorry, no returns or refunds on any items.",
    "receipt_header": "Thank you for shopping at Bowenstreet Market!",
    "receipt_footer": "Return policy: No returns or refunds.",
    "receipt_signature": "false",
    "gift_receipts_enabled": "false",
    "advanced_cash": "true",
    "require_void_reason": "false",
    "auto_print_receipt": "false",
    "aging_on_tags": "false",
    "auto_vendor_email": "true",
    "vendor_online_store": "false",
    "vendor_photo_uploads": "true",
    "module_rent": "true",
    "module_studio": "true",
    "module_gift_cards": "true",
    "module_consignment": "true",
    "module_ai_assistant": "true",
    "module_csv_import": "true",
    "module_time_clock": "false",
    "module_split_payments": "true",
    "default_label_format": "standard",
    "dymo_label_size": "30347",
    "label_show_price": "true",
    "label_show_booth": "true",
    "label_show_aging": "false",
    "notify_product_sold": "true",
    "notify_payout": "false",
    "notify_expiring": "false",
    "notify_weekly_report": "true",
    "notify_rent_due": "false",
    "notify_admin_daily": "false",
    "notify_low_stock": "false",
    "role_view_dashboard_vendor": "true",
    "role_view_dashboard_cashier": "true",
    "role_manage_items_vendor": "true",
    "role_manage_items_cashier": "false",
    "role_view_sales_vendor": "true",
    "role_view_sales_cashier": "true",
    "role_process_sales_vendor": "false",
    "role_process_sales_cashier": "true",
    "role_void_sales_vendor": "false",
    "role_void_sales_cashier": "false",
    "role_manage_gift_cards_vendor": "false",
    "role_manage_gift_cards_cashier": "true",
    "role_view_reports_vendor": "true",
    "role_view_reports_cashier": "false",
    "role_manage_vendors_vendor": "false",
    "role_manage_vendors_cashier": "false",
    "role_manage_rent_vendor": "false",
    "role_manage_rent_cashier": "false",
    "role_import_data_vendor": "false",
    "role_import_data_cashier": "false",
    "role_change_settings_vendor": "false",
    "role_change_settings_cashier": "false",
    "role_balance_adjustments_vendor": "false",
    "role_balance_adjustments_cashier": "false",
    "role_print_labels_vendor": "true",
    "role_print_labels_cashier": "true",
    "role_view_ai_assistant_vendor": "true",
    "role_view_ai_assistant_cashier": "true",
    "role_manage_studio_vendor": "false",
    "role_manage_studio_cashier": "false",
    "square_application_id": settings.square_application_id or "",
    "square_location_id": settings.square_location_id or "",
    "square_access_token": settings.square_access_token or "",
}


async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    result = await db.execute(
        select(StoreSetting.value).where(StoreSetting.key == key)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else default


async def get_tax_rate(db: AsyncSession) -> float:
    val = await get_setting(db, "tax_rate")
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return settings.tax_rate


@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
    result = await db.execute(select(StoreSetting))
    rows = result.scalars().all()
    existing = {row.key: row.value for row in rows}

    missing = {k: v for k, v in DEFAULT_SETTINGS.items() if k not in existing}
    if missing:
        for k, v in missing.items():
            db.add(StoreSetting(key=k, value=v))
        await db.commit()
        existing.update(missing)

    return existing


@router.post("")
async def save_settings(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
    for key, value in payload.items():
        existing = await db.execute(
            select(StoreSetting).where(StoreSetting.key == key)
        )
        row = existing.scalar_one_or_none()
        if row:
            row.value = str(value)
            await db.merge(row)
        else:
            db.add(StoreSetting(key=key, value=str(value)))
    await db.commit()
    return {"message": "Settings saved"}
