import logging
import os, re, asyncio, json, random
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text, func, or_
from pydantic import BaseModel
import httpx

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.item_image import ItemImage
from app.config import settings
from app.services import spaces as spaces_svc

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


def _ext_for_content_type(content_type: Optional[str]) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get((content_type or "").lower(), ".jpg")


def _store_item_image_url(item_id: int, image_data: bytes, content_type: str, source_prefix: str = "ricochet") -> str:
    ext = _ext_for_content_type(content_type)
    spaces_key = f"items/{source_prefix}/{item_id}{ext}"
    cdn_url = spaces_svc.upload_bytes(image_data, spaces_key, content_type)
    return cdn_url or f"/api/v1/items/{item_id}/image"


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

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tmp"
)
RICO_CACHE_FILE = os.path.join(CACHE_DIR, "ricochet_product_cache.json")


@router.post("/store-images-to-db")
async def store_images_to_db(
    secret: str = Query(...),
    batch_size: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
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

            stored_url = _store_item_image_url(item.id, image_data, content_type, "ricochet")
            item.image_path = stored_url
            item.photo_urls = [stored_url]

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


@router.post("/set-photo-items-online")
async def set_photo_items_online(
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if secret != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid key")

    result = await db.execute(
        select(Item).where(
            Item.status == "active",
            Item.image_path.isnot(None),
            Item.image_path != "",
            Item.is_online == False,
        )
    )
    items = result.scalars().all()
    updated = 0
    for item in items:
        item.is_online = True
        updated += 1

    await db.commit()
    return {"updated": updated, "message": f"Set {updated} items with photos to online"}


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


@router.post("/clear-booth-showcases")
async def clear_booth_showcases(
    password: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")

    result = await db.execute(text("DELETE FROM booth_showcases"))
    count = result.rowcount
    await db.commit()
    return {"detail": f"Deleted {count} booth showcase(s). All vendors start fresh."}


RICO_BASE = "https://bowenstreet.ricoconsign.com"
RICO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0"}
RICO_CATEGORIES = [
    "Accesories", "Stickers", "Books", "Furniture", "Original Art",
    "Outside", "BowenStreet Repeats", "Handmade items", "Candles",
    "Cards", "Clothing", "Decorations", "Jewelry", "Vintage",
    "Specialty Items", "Upcycled Items", "Studio Class",
    "Vintage Furniture", "Second hand clothes", "Adult clothing",
    "Kids clothing", "Used furniture", "Vintage Clothing",
]

_scrape_status = {"running": False, "matched": 0, "skipped": 0, "errors": 0, "total_products": 0, "done": False, "message": ""}

_product_cache: list = []

RICO_TIMEOUT = httpx.Timeout(45.0, connect=20.0)
RICO_MIN_DELAY = float(os.environ.get("RICO_SCRAPE_MIN_DELAY", "1.1"))
RICO_MAX_DELAY = float(os.environ.get("RICO_SCRAPE_MAX_DELAY", "1.9"))
RICO_RETRY_DELAYS = (3, 8, 20)


def _ensure_cache_dir() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def _save_product_cache() -> None:
    _ensure_cache_dir()
    with open(RICO_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_product_cache, f)


def _load_product_cache() -> int:
    global _product_cache
    if not os.path.exists(RICO_CACHE_FILE):
        return 0
    with open(RICO_CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        _product_cache = data
        return len(_product_cache)
    return 0


async def _rico_pause(multiplier: float = 1.0) -> None:
    await asyncio.sleep(random.uniform(RICO_MIN_DELAY, RICO_MAX_DELAY) * multiplier)


async def _rico_get(client: httpx.AsyncClient, url: str):
    last_error = None
    for attempt, retry_delay in enumerate((0,) + RICO_RETRY_DELAYS):
        if retry_delay:
            await asyncio.sleep(retry_delay)
        try:
            resp = await client.get(url)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code}"
                continue
            return resp
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"Ricochet request failed for {url}: {last_error}")


async def _scrape_and_store_images():
    from app.database import AsyncSessionLocal
    from bs4 import BeautifulSoup
    from urllib.parse import quote

    _scrape_status.update(running=True, matched=0, skipped=0, errors=0, total_products=0, done=False, message="Collecting product URLs...")

    async with httpx.AsyncClient(headers=RICO_HEADERS, timeout=RICO_TIMEOUT, follow_redirects=True) as client:
        product_urls = set()
        s3_pat = re.compile(r"ricoconsign-assets\.s3\.")
        sku_pat = re.compile(r"rico\.sku\s*=\s*'([^']+)'")

        for cat in RICO_CATEGORIES:
            page = 1
            while True:
                url = f"{RICO_BASE}/store/category/{quote(cat)}" if page == 1 else f"{RICO_BASE}/nextpage?page={page}&category={quote(cat)}"
                try:
                    resp = await _rico_get(client, url)
                    if resp.status_code != 200:
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("a", href=re.compile(r"/store/product/"))
                    if not links:
                        break
                    new = 0
                    for link in links:
                        href = link.get("href", "")
                        if href.startswith("/"):
                            href = RICO_BASE + href
                        if href not in product_urls:
                            product_urls.add(href)
                            new += 1
                    if new == 0:
                        break
                    page += 1
                    await _rico_pause()
                except Exception:
                    break

        _scrape_status["total_products"] = len(product_urls)
        _scrape_status["message"] = f"Found {len(product_urls)} products. Processing..."

        LOGO_SIZE = 218508

        for i, prod_url in enumerate(product_urls):
            try:
                resp = await _rico_get(client, prod_url)
                if resp.status_code != 200:
                    _scrape_status["errors"] += 1
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                sku = ""
                for script in soup.find_all("script"):
                    txt = script.string or ""
                    m = sku_pat.search(txt)
                    if m:
                        sku = m.group(1)
                        break
                if not sku:
                    _scrape_status["skipped"] += 1
                    continue

                image_urls = []
                seen = set()
                for img in soup.find_all("img", src=s3_pat):
                    src = img.get("src", "")
                    if src and src not in seen:
                        seen.add(src)
                        image_urls.append(src)
                if not image_urls:
                    _scrape_status["skipped"] += 1
                    continue

                img_resp = await _rico_get(client, image_urls[0])
                if img_resp.status_code != 200:
                    _scrape_status["errors"] += 1
                    continue
                image_data = img_resp.content
                if len(image_data) == LOGO_SIZE:
                    if len(image_urls) > 1:
                        img_resp = await _rico_get(client, image_urls[1])
                        if img_resp.status_code != 200 or len(img_resp.content) == LOGO_SIZE:
                            _scrape_status["skipped"] += 1
                            continue
                        image_data = img_resp.content
                    else:
                        _scrape_status["skipped"] += 1
                        continue

                ext = image_urls[0].rsplit(".", 1)[-1].split("?")[0].lower()
                content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

                try:
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Item).where(or_(Item.sku == sku, Item.barcode == sku)).limit(1)
                        )
                        item = result.scalar_one_or_none()
                        if not item:
                            _scrape_status["skipped"] += 1
                            continue

                        existing = await db.execute(
                            select(ItemImage).where(ItemImage.item_id == item.id)
                        )
                        old_img = existing.scalar_one_or_none()
                        if old_img:
                            old_img.image_data = image_data
                            old_img.content_type = content_type
                        else:
                            db.add(ItemImage(item_id=item.id, image_data=image_data, content_type=content_type))

                        stored_url = _store_item_image_url(item.id, image_data, content_type, "ricochet")
                        item.image_path = stored_url
                        item.photo_urls = [stored_url]
                        await db.flush()
                        await db.commit()
                        _scrape_status["matched"] += 1
                        logger.info(f"Stored image for item {item.id} (sku={sku})")
                except Exception as db_err:
                    _scrape_status["errors"] += 1
                    logger.error(f"DB error for sku {sku}: {db_err}")

                if i % 10 == 0:
                    _scrape_status["message"] = f"Processing {i+1}/{len(product_urls)}... Matched: {_scrape_status['matched']}"
                await _rico_pause()

            except Exception as e:
                _scrape_status["errors"] += 1
                logger.error(f"Scrape error for {prod_url}: {e}")

    _scrape_status["done"] = True
    _scrape_status["running"] = False
    _scrape_status["message"] = f"Done! Matched {_scrape_status['matched']} items, skipped {_scrape_status['skipped']}, errors {_scrape_status['errors']}"


@router.post("/scrape-ricochet-images")
async def scrape_ricochet_images(
    password: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")
    if _scrape_status["running"]:
        return {"detail": "Scrape already running", **_scrape_status}

    background_tasks.add_task(_scrape_and_store_images)
    return {"detail": "Scrape started in background. Check /data-sync/scrape-status for progress."}


@router.get("/scrape-status")
async def scrape_status(password: str = Query(...)):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")
    return _scrape_status


_collect_status = {"running": False, "done": False, "message": "", "count": 0}


async def _collect_ricochet_products():
    from bs4 import BeautifulSoup
    from urllib.parse import quote

    _product_cache.clear()
    try:
        if os.path.exists(RICO_CACHE_FILE):
            os.remove(RICO_CACHE_FILE)
    except OSError:
        pass
    _collect_status.update(running=True, done=False, message="Collecting product URLs...", count=0)
    s3_pat = re.compile(r"ricoconsign-assets\.s3\.")
    sku_pat = re.compile(r"rico\.sku\s*=\s*'([^']+)'")

    try:
        async with httpx.AsyncClient(headers=RICO_HEADERS, timeout=RICO_TIMEOUT, follow_redirects=True) as client:
            product_urls = set()
            for cat in RICO_CATEGORIES:
                page = 1
                while True:
                    url = f"{RICO_BASE}/store/category/{quote(cat)}" if page == 1 else f"{RICO_BASE}/nextpage?page={page}&category={quote(cat)}"
                    try:
                        resp = await _rico_get(client, url)
                        if resp.status_code != 200:
                            break
                        soup = BeautifulSoup(resp.text, "html.parser")
                        links = soup.find_all("a", href=re.compile(r"/store/product/"))
                        if not links:
                            break
                        new = 0
                        for link in links:
                            href = link.get("href", "")
                            if href.startswith("/"):
                                href = RICO_BASE + href
                            if href not in product_urls:
                                product_urls.add(href)
                                new += 1
                        if new == 0:
                            break
                        page += 1
                        await _rico_pause()
                    except Exception:
                        break

            _collect_status["message"] = f"Found {len(product_urls)} products. Scraping details..."

            for i, prod_url in enumerate(product_urls):
                try:
                    resp = await _rico_get(client, prod_url)
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    sku = ""
                    for script in soup.find_all("script"):
                        m = sku_pat.search(script.string or "")
                        if m:
                            sku = m.group(1)
                            break
                    if not sku:
                        continue
                    image_urls = []
                    for img in soup.find_all("img", src=s3_pat):
                        src = img.get("src", "")
                        if src and src not in image_urls:
                            image_urls.append(src)
                    if not image_urls:
                        continue
                    _product_cache.append({"sku": sku, "image_urls": image_urls})
                    if len(_product_cache) % 25 == 0:
                        _save_product_cache()
                    if i % 20 == 0:
                        _collect_status["message"] = f"Scraped {i+1}/{len(product_urls)}... cached {len(_product_cache)}"
                    await _rico_pause()
                except Exception:
                    continue
    except Exception as e:
        _collect_status["message"] = f"Error: {e}"

    _save_product_cache()
    _collect_status.update(running=False, done=True, count=len(_product_cache), message=f"Done! Cached {len(_product_cache)} products with images")


@router.post("/scrape-rico-collect")
async def scrape_rico_collect(
    password: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")
    if _collect_status["running"]:
        return {"detail": "Collection already running", **_collect_status}
    background_tasks.add_task(_collect_ricochet_products)
    return {"detail": "Collection started in background. Check /data-sync/scrape-rico-status for progress."}


@router.get("/scrape-rico-status")
async def scrape_rico_status_endpoint(password: str = Query(...)):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")
    cached = len(_product_cache) or _load_product_cache()
    return {**_collect_status, "cached_products": cached}


@router.post("/scrape-rico-store")
async def scrape_rico_store(
    password: str = Query(...),
    batch_offset: int = Query(0, ge=0),
    batch_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    if password != SYNC_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password")
    if not _product_cache:
        loaded = _load_product_cache()
        if not loaded:
            return {"detail": "No product cache. Call /scrape-rico-collect first.", "matched": 0}

    batch = _product_cache[batch_offset:batch_offset + batch_size]
    if not batch:
        return {"detail": "All batches processed", "matched": 0, "total_cached": len(_product_cache), "offset": batch_offset}

    LOGO_SIZE = 218508
    matched = 0
    skipped = 0
    errors = 0

    async with httpx.AsyncClient(headers=RICO_HEADERS, timeout=RICO_TIMEOUT, follow_redirects=True) as client:
        for prod in batch:
            sku = prod["sku"]
            image_urls = prod["image_urls"]
            try:
                result = await db.execute(
                    select(Item).where(or_(Item.sku == sku, Item.barcode == sku)).limit(1)
                )
                item = result.scalar_one_or_none()
                if not item:
                    skipped += 1
                    continue

                img_resp = await _rico_get(client, image_urls[0])
                if img_resp.status_code != 200:
                    errors += 1
                    continue
                image_data = img_resp.content
                if len(image_data) == LOGO_SIZE and len(image_urls) > 1:
                    img_resp = await _rico_get(client, image_urls[1])
                    if img_resp.status_code != 200 or len(img_resp.content) == LOGO_SIZE:
                        skipped += 1
                        continue
                    image_data = img_resp.content
                elif len(image_data) == LOGO_SIZE:
                    skipped += 1
                    continue

                ext = image_urls[0].rsplit(".", 1)[-1].split("?")[0].lower()
                content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

                existing = await db.execute(
                    select(ItemImage).where(ItemImage.item_id == item.id)
                )
                old_img = existing.scalar_one_or_none()
                if old_img:
                    old_img.image_data = image_data
                    old_img.content_type = content_type
                else:
                    db.add(ItemImage(item_id=item.id, image_data=image_data, content_type=content_type))

                stored_url = _store_item_image_url(item.id, image_data, content_type, "ricochet")
                item.image_path = stored_url
                item.photo_urls = [stored_url]
                matched += 1
                await _rico_pause(0.75)
            except Exception as e:
                errors += 1
                logger.error(f"Store error for sku {sku}: {e}")

    await db.commit()
    return {
        "matched": matched,
        "skipped": skipped,
        "errors": errors,
        "batch_offset": batch_offset,
        "batch_size": batch_size,
        "next_offset": batch_offset + batch_size,
        "total_cached": len(_product_cache),
        "remaining": max(0, len(_product_cache) - batch_offset - batch_size),
    }
