import logging
import os
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from pydantic import BaseModel

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.config import settings

logger = logging.getLogger("bmm-data-sync")

router = APIRouter(prefix="/data-sync", tags=["data-sync"])

SYNC_SECRET = os.environ.get("ADMIN_PASSWORD", "")


def _ser(val):
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return str(val)
    return val


@router.get("/export/vendors")
async def export_vendors(key: str = Query(...), db: AsyncSession = Depends(get_db)):
    if key != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")
    result = await db.execute(select(Vendor))
    vendors = result.scalars().all()
    data = []
    for v in vendors:
        data.append({c.name: _ser(getattr(v, c.name)) for c in Vendor.__table__.columns})
    return {"vendors": data, "count": len(data)}


@router.get("/export/items")
async def export_items(
    key: str = Query(...),
    offset: int = Query(0),
    limit: int = Query(5000),
    db: AsyncSession = Depends(get_db),
):
    if key != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")
    total_result = await db.execute(select(func.count()).select_from(Item))
    total = total_result.scalar()
    result = await db.execute(select(Item).order_by(Item.id).offset(offset).limit(limit))
    items = result.scalars().all()
    data = []
    for it in items:
        data.append({c.name: _ser(getattr(it, c.name)) for c in Item.__table__.columns})
    return {"items": data, "count": len(data), "total": total, "offset": offset}


@router.post("/import/vendors")
async def import_vendors(key: str = Query(...), source_url: str = Query(...), db: AsyncSession = Depends(get_db)):
    if key != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{source_url}/api/v1/data-sync/export/vendors?key={key}")
        resp.raise_for_status()
        vendor_data = resp.json()

    await db.execute(text("DELETE FROM items"))
    await db.execute(text("DELETE FROM vendor_balances"))
    await db.execute(text("DELETE FROM booth_showcases"))
    await db.execute(text("DELETE FROM vendors"))
    await db.commit()

    inserted = 0
    for vd in vendor_data["vendors"]:
        vd.pop("created_at", None)
        vendor = Vendor(**{k: v for k, v in vd.items() if hasattr(Vendor, k) and v is not None})
        db.add(vendor)
        inserted += 1

    await db.commit()
    return {"imported_vendors": inserted}


@router.post("/import/items")
async def import_items(key: str = Query(...), source_url: str = Query(...), db: AsyncSession = Depends(get_db)):
    if key != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    import httpx

    await db.execute(text("DELETE FROM items"))
    await db.commit()

    total_imported = 0
    offset = 0
    batch_size = 5000

    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            resp = await client.get(
                f"{source_url}/api/v1/data-sync/export/items?key={key}&offset={offset}&limit={batch_size}"
            )
            resp.raise_for_status()
            item_data = resp.json()

            if not item_data["items"]:
                break

            for itd in item_data["items"]:
                itd.pop("created_at", None)
                if itd.get("photo_urls") and isinstance(itd["photo_urls"], list):
                    pass
                item = Item(**{k: v for k, v in itd.items() if hasattr(Item, k) and v is not None})
                db.add(item)
                total_imported += 1

            await db.commit()
            offset += batch_size

            if len(item_data["items"]) < batch_size:
                break

    return {"imported_items": total_imported}


@router.post("/import/all")
async def import_all(key: str = Query(...), source_url: str = Query(...), db: AsyncSession = Depends(get_db)):
    if key != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    vendors_result = await import_vendors(key=key, source_url=source_url, db=db)
    items_result = await import_items(key=key, source_url=source_url, db=db)

    vb_count = await db.execute(select(func.count()).select_from(VendorBalance))

    return {
        "vendors": vendors_result["imported_vendors"],
        "items": items_result["imported_items"],
        "vendor_balances_auto_created": vb_count.scalar(),
    }
