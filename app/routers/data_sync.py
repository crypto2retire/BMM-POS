"""Data sync endpoints — import features removed, export-only."""

import logging
import os, re, asyncio, json, secrets
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor
from app.models.item import Item
from app.routers.auth import get_current_user

logger = logging.getLogger("data_sync")
router = APIRouter(prefix="/data-sync", tags=["data-sync"])


SYNC_TOKEN = os.environ.get("DATA_SYNC_TOKEN", "")


async def require_data_sync_access(
    source_url: str = Query(""),
    token: str = Query(""),
):
    if not SYNC_TOKEN:
        raise HTTPException(status_code=403, detail="Data sync is not configured.")
    if token != SYNC_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid sync token.")


# ── Export endpoints (read-only, still available) ─────────────────────

@router.get("/export/vendors")
async def export_vendors(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_data_sync_access),
):
    result = await db.execute(select(Vendor).order_by(Vendor.id))
    vendors = result.scalars().all()
    return {"vendors": [
        {c.name: getattr(v, c.name) for c in v.__table__.columns}
        for v in vendors
    ]}


@router.get("/export/items")
async def export_items(
    offset: int = Query(0, ge=0),
    limit: int = Query(5000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_data_sync_access),
):
    result = await db.execute(
        select(Item).order_by(Item.id).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    return {"items": [
        {c.name: getattr(i, c.name) for c in i.__table__.columns}
        for i in items
    ]}


# ── All import/scrape endpoints disabled ──────────────────────────────
# Removed: import/vendors, import/items, import/all, apply-scraped-images,
# store-images-to-db, set-photo-items-online, clear-item-photos,
# clear-booth-showcases, scrape-ricochet-images, scrape-status,
# scrape-rico-collect
# These were one-time migration tools no longer needed.
