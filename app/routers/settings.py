from typing import Optional, Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.store_setting import StoreSetting
from app.models.vendor import Vendor
from app.routers.auth import require_admin, require_cashier_or_admin, get_current_user

router = APIRouter(prefix="/admin/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "store_name": settings.store_name,
    "store_address": "2837 Bowen St, Oshkosh, WI 54901",
    "store_phone": "(920) 289-0252",
    "store_email": "info@bowenstreetmarket.com",
    "store_state": "WI",
    "store_postcode": "54901",
    "store_country": "US",
    "hours_monday": "Closed",
    "hours_tuesday": "Closed",
    "hours_wednesday": "10:00 AM - 6:00 PM",
    "hours_thursday": "10:00 AM - 6:00 PM",
    "hours_friday": "10:00 AM - 6:00 PM",
    "hours_saturday": "10:00 AM - 4:00 PM",
    "hours_sunday": "10:00 AM - 4:00 PM",
    "tax_rate": str(settings.tax_rate),
    "multi_tax_enabled": "false",
    "commission_rate": "0",
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
    "require_photo_description_online": "true",
    "module_rent": "true",
    "module_studio": "true",
    "module_gift_cards": "true",
    "module_consignment": "true",
    "module_ai_assistant": "true",
    "module_csv_import": "true",
    "module_time_clock": "false",
    "module_split_payments": "true",
    "label_show_price": "true",
    "label_show_booth": "true",
    "notify_product_sold": "true",
    "notify_payout": "false",
    "notify_expiring": "false",
    "notify_weekly_report": "true",
    "notify_order_confirmation": "true",
    "notify_order_ready_pickup": "true",
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
    "role_manage_vendors_cashier": "true",
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
    "role_inventory_verify_vendor": "false",
    "role_inventory_verify_cashier": "true",
    "email_tpl_product_sold_subject": "",
    "email_tpl_product_sold_greeting": "",
    "email_tpl_product_sold_body": "",
    "email_tpl_product_sold_closing": "",
    "email_tpl_payout_processed_subject": "",
    "email_tpl_payout_processed_greeting": "",
    "email_tpl_payout_processed_body": "",
    "email_tpl_payout_processed_closing": "",
    "email_tpl_payout_with_rent_subject": "",
    "email_tpl_payout_with_rent_greeting": "",
    "email_tpl_payout_with_rent_body": "",
    "email_tpl_payout_with_rent_closing": "",
    "email_tpl_rent_due_subject": "",
    "email_tpl_rent_due_greeting": "",
    "email_tpl_rent_due_body": "",
    "email_tpl_rent_due_closing": "",
    "email_tpl_rent_overdue_15day_subject": "",
    "email_tpl_rent_overdue_15day_greeting": "",
    "email_tpl_rent_overdue_15day_body": "",
    "email_tpl_rent_overdue_15day_closing": "",
    "email_tpl_rent_overdue_27day_subject": "",
    "email_tpl_rent_overdue_27day_greeting": "",
    "email_tpl_rent_overdue_27day_body": "",
    "email_tpl_rent_overdue_27day_closing": "",
    "email_tpl_rent_shortfall_subject": "",
    "email_tpl_rent_shortfall_greeting": "",
    "email_tpl_rent_shortfall_body": "",
    "email_tpl_rent_shortfall_closing": "",
    "email_tpl_vendor_welcome_subject": "",
    "email_tpl_vendor_welcome_greeting": "",
    "email_tpl_vendor_welcome_body": "",
    "email_tpl_vendor_welcome_closing": "",
    "email_tpl_expiring_items_subject": "",
    "email_tpl_expiring_items_greeting": "",
    "email_tpl_expiring_items_body": "",
    "email_tpl_expiring_items_closing": "",
    "email_tpl_weekly_report_subject": "",
    "email_tpl_weekly_report_greeting": "",
    "email_tpl_weekly_report_body": "",
    "email_tpl_weekly_report_closing": "",
    "email_tpl_order_confirmation_subject": "",
    "email_tpl_order_confirmation_greeting": "",
    "email_tpl_order_confirmation_body": "",
    "email_tpl_order_confirmation_closing": "",
    "email_tpl_order_ready_pickup_subject": "",
    "email_tpl_order_ready_pickup_greeting": "",
    "email_tpl_order_ready_pickup_body": "",
    "email_tpl_order_ready_pickup_closing": "",
    "webstore_enabled": "false",
    "webstore_title": "Bowenstreet Market — Handcrafted, Vintage & More",
    "webstore_description": "Shop handcrafted, vintage, and antique items from 120+ local vendors in Oshkosh, WI.",
    "webstore_sort": "newest",
    "webstore_per_page": "24",
    "webstore_cards_enabled": "true",
    "webstore_giftcards_enabled": "false",
    "webstore_fulfillment": "pickup",
    "webstore_pickup_instructions": "Pick up at front desk during business hours",
    "webstore_email_prepared": "true",
    "webstore_email_fulfilled": "true",
    "webstore_email_confirmation": "true",
    "webstore_facebook_url": "https://www.facebook.com/bowenstreetmarket",
    "webstore_facebook_on": "true",
    "webstore_instagram_url": "https://www.instagram.com/bowenstreetmarket",
    "webstore_instagram_on": "true",
    "webstore_tiktok_url": "https://www.tiktok.com/@bowenstreetmarket",
    "webstore_tiktok_on": "true",
    "webstore_twitter_url": "",
    "webstore_twitter_on": "false",
    "webstore_ga_id": "",
    "webstore_gtm_id": "",
    "webstore_fb_pixel": "",
    "webstore_google_verification": "",
    "webstore_pinterest_key": "",
    "square_application_id": settings.square_application_id or "",
    "square_location_id": settings.square_location_id or "",
}

SERVER_ONLY_SETTINGS = {"square_access_token"}


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


def _truthy_setting(val: Optional[str]) -> bool:
    if val is None:
        return False
    return str(val).lower() in ("true", "1", "yes")


# Base keys matching Settings → User Roles (suffix _vendor / _cashier in DB)
ROLE_FEATURE_SLUGS = (
    "role_view_dashboard",
    "role_manage_items",
    "role_view_sales",
    "role_process_sales",
    "role_void_sales",
    "role_manage_gift_cards",
    "role_view_reports",
    "role_manage_vendors",
    "role_manage_rent",
    "role_import_data",
    "role_change_settings",
    "role_balance_adjustments",
    "role_print_labels",
    "role_view_ai_assistant",
    "role_manage_studio",
    "role_inventory_verify",
)


async def role_feature_allowed(db: AsyncSession, user: Vendor, feature_slug: str) -> bool:
    """
    Resolve User Roles checkbox for the logged-in user.
    Admins always allowed; vendor/cashier use role_{slug}_{role} in store_settings.
    """
    if user.role == "admin":
        return True
    if user.role not in ("vendor", "cashier"):
        return False
    key = f"{feature_slug}_{user.role}"
    default = DEFAULT_SETTINGS.get(key, "false")
    val = await get_setting(db, key, default)
    return _truthy_setting(val)


async def collect_role_permissions(db: AsyncSession, user: Vendor) -> dict[str, bool]:
    return {slug: await role_feature_allowed(db, user, slug) for slug in ROLE_FEATURE_SLUGS}


def require_role_feature(feature_slug: str) -> Callable[..., Awaitable[Vendor]]:
    """Any authenticated role (vendor/cashier/admin) must have the User Roles permission."""

    async def _checker(
        db: AsyncSession = Depends(get_db),
        user: Vendor = Depends(get_current_user),
    ) -> Vendor:
        if not await role_feature_allowed(db, user, feature_slug):
            raise HTTPException(
                status_code=403,
                detail="This feature is disabled for your role in Settings → User Roles.",
            )
        return user

    return _checker


def require_staff_feature(feature_slug: str) -> Callable[..., Awaitable[Vendor]]:
    """Admin or cashier only, plus the given User Roles permission (vendors never pass staff gate)."""

    async def _checker(
        db: AsyncSession = Depends(get_db),
        user: Vendor = Depends(require_cashier_or_admin),
    ) -> Vendor:
        if not await role_feature_allowed(db, user, feature_slug):
            raise HTTPException(
                status_code=403,
                detail="This feature is disabled for your role in Settings → User Roles.",
            )
        return user

    return _checker


def require_any_staff_feature(*feature_slugs: str) -> Callable[..., Awaitable[Vendor]]:
    """Cashier/admin must have at least one of the listed permissions (admin always passes)."""

    async def _checker(
        db: AsyncSession = Depends(get_db),
        user: Vendor = Depends(require_cashier_or_admin),
    ) -> Vendor:
        for slug in feature_slugs:
            if await role_feature_allowed(db, user, slug):
                return user
        raise HTTPException(
            status_code=403,
            detail="This feature is not enabled for your role in Settings → User Roles.",
        )

    return _checker


async def role_allows_manage_vendors(db: AsyncSession, user: Vendor) -> bool:
    return await role_feature_allowed(db, user, "role_manage_vendors")


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

    for key in SERVER_ONLY_SETTINGS:
        existing.pop(key, None)

    return existing


@router.post("")
async def save_settings(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
    for key, value in payload.items():
        if key in SERVER_ONLY_SETTINGS and (value is None or not str(value).strip()):
            continue
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
