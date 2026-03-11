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

# Default settings seeded on first GET when table is empty
DEFAULT_SETTINGS = {
    "store_name": settings.store_name,
    "store_address": "2837 Bowen St, Oshkosh, WI 54901",
    "store_phone": "(920) 555-0100",
    "store_email": "info@bowenstreetmarket.com",
    "hours_monday": "Closed",
    "hours_tuesday": "10:00 AM - 6:00 PM",
    "hours_wednesday": "10:00 AM - 6:00 PM",
    "hours_thursday": "10:00 AM - 6:00 PM",
    "hours_friday": "10:00 AM - 6:00 PM",
    "hours_saturday": "10:00 AM - 6:00 PM",
    "hours_sunday": "11:00 AM - 4:00 PM",
    "tax_rate": str(settings.tax_rate),
    "rent_due_day": "27",
    "payout_day": "1",
    "square_application_id": settings.square_application_id or "",
    "square_location_id": settings.square_location_id or "",
    "square_access_token": settings.square_access_token or "",
}


async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a single setting from the database."""
    result = await db.execute(
        select(StoreSetting.value).where(StoreSetting.key == key)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else default


async def get_tax_rate(db: AsyncSession) -> float:
    """Return the tax rate as a float, reading from DB first, falling back to config."""
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
    """Return all settings as a {key: value} dict. Seeds defaults if empty."""
    result = await db.execute(select(StoreSetting))
    rows = result.scalars().all()

    if not rows:
        for k, v in DEFAULT_SETTINGS.items():
            db.add(StoreSetting(key=k, value=v))
        await db.commit()

        result = await db.execute(select(StoreSetting))
        rows = result.scalars().all()

    return {row.key: row.value for row in rows}


@router.post("")
async def save_settings(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _admin: Vendor = Depends(require_admin),
):
    """Upsert one or more settings from a {key: value} dict."""
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
