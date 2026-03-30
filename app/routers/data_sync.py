import logging
import os
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, or_
from pydantic import BaseModel

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.item_image import ItemImage
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


def _ext(filename: str) -> str:
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1]
    return ".jpg"


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


class ImageMapping(BaseModel):
    sku: str
    image_filenames: str


@router.post("/apply-scraped-images")
async def apply_scraped_images(
    mappings: List[ImageMapping],
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if secret != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    matched = 0
    updated = 0
    skipped = 0

    for m in mappings:
        result = await db.execute(
            select(Item).where(
                or_(Item.sku == m.sku, Item.barcode == m.sku),
                Item.status == "active",
            )
        )
        items = result.scalars().all()
        if not items:
            continue
        matched += len(items)

        filenames = m.image_filenames.split("|")
        web_paths = [
            f"/static/uploads/items/rico_{m.sku}_{i}{_ext(fn)}"
            for i, fn in enumerate(filenames)
        ]

        for item in items:
            if item.photo_urls and len(item.photo_urls) > 0:
                skipped += 1
                continue
            item.photo_urls = web_paths
            item.image_path = web_paths[0] if web_paths else None
            updated += 1

    await db.commit()
    return {"matched": matched, "updated": updated, "skipped": skipped, "total_mappings": len(mappings)}


SCRAPED_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "static", "uploads", "items"
)


@router.post("/store-images-to-db")
async def store_images_to_db(
    secret: str = Query(...),
    batch_size: int = Query(50),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    if secret != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    rico_files = sorted([
        f for f in os.listdir(SCRAPED_IMAGES_DIR)
        if f.startswith("rico_") and not f.endswith(".gitkeep")
    ])

    if not rico_files:
        return {"error": "No rico_ image files found on disk", "dir": SCRAPED_IMAGES_DIR}

    sku_files = {}
    for fname in rico_files:
        parts = fname.split("_", 2)
        if len(parts) >= 3:
            sku = parts[1]
            if sku not in sku_files:
                sku_files[sku] = []
            sku_files[sku].append(fname)

    all_skus = sorted(sku_files.keys())
    batch_skus = all_skus[offset:offset + batch_size]

    if not batch_skus:
        return {"message": "No more SKUs to process", "total_skus": len(all_skus), "offset": offset}

    stored = 0
    skipped = 0
    errors = []

    LOGO_SIZE = 218508

    for sku in batch_skus:
        files = sku_files[sku]

        real_files = []
        for fn in files:
            fpath = os.path.join(SCRAPED_IMAGES_DIR, fn)
            try:
                if os.path.getsize(fpath) != LOGO_SIZE:
                    real_files.append(fn)
            except OSError:
                pass
        if not real_files:
            real_files = files

        best_file = real_files[0]

        result = await db.execute(
            select(Item).where(or_(Item.sku == sku, Item.barcode == sku)).limit(1)
        )
        item = result.scalar_one_or_none()
        if not item:
            skipped += 1
            continue

        existing = await db.execute(
            select(ItemImage).where(ItemImage.item_id == item.id)
        )
        old_img = existing.scalar_one_or_none()

        filepath = os.path.join(SCRAPED_IMAGES_DIR, best_file)
        try:
            with open(filepath, "rb") as f:
                image_data = f.read()

            ext = best_file.rsplit(".", 1)[-1].lower()
            content_type = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp", "gif": "image/gif"
            }.get(ext, "image/jpeg")

            if old_img:
                old_img.image_data = image_data
                old_img.content_type = content_type
            else:
                db.add(ItemImage(
                    item_id=item.id,
                    image_data=image_data,
                    content_type=content_type,
                ))

            item.image_path = f"/api/v1/items/{item.id}/image"

            photo_paths = [f"/static/uploads/items/{fn}" for fn in real_files]
            item.photo_urls = photo_paths

            stored += 1
        except Exception as e:
            errors.append({"sku": sku, "file": best_file, "error": str(e)})

    await db.commit()

    return {
        "stored": stored,
        "skipped": skipped,
        "errors": errors,
        "batch_offset": offset,
        "batch_size": batch_size,
        "total_skus": len(all_skus),
        "next_offset": offset + batch_size if (offset + batch_size) < len(all_skus) else None,
    }


@router.post("/clear-item-photos")
async def clear_item_photos(
    barcode: str = Query(...),
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if secret != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    result = await db.execute(
        select(Item).where(or_(Item.sku == barcode, Item.barcode == barcode))
    )
    items = result.scalars().all()
    cleared = 0
    for item in items:
        item.photo_urls = None
        item.image_path = None
        cleared += 1

        img_result = await db.execute(
            select(ItemImage).where(ItemImage.item_id == item.id)
        )
        old_img = img_result.scalar_one_or_none()
        if old_img:
            await db.delete(old_img)

    await db.commit()
    return {"cleared": cleared}
