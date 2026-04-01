#!/usr/bin/env python3
"""
Match scraped Ricochet images to BMM-POS inventory items and update the database.

Usage:
  python3 scripts/import_scraped_images.py [--dry-run] [--db-url DATABASE_URL]

By default uses the local database. Pass --db-url for Railway production DB.
"""
import os
import sys
import csv
import shutil
import asyncio
import argparse
from pathlib import Path

SCRAPED_DIR = "scraped_images"
CSV_FILE = "scraped_items.csv"
DEST_DIR = "frontend/static/uploads/items"


async def run(dry_run=False, db_url=None):
    if db_url:
        os.environ["DATABASE_URL"] = db_url

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, update, text

    if db_url:
        engine_url = db_url
    else:
        from app.config import settings
        engine_url = settings.database_url

    if engine_url.startswith("postgres://"):
        engine_url = engine_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif engine_url.startswith("postgresql://") and "+asyncpg" not in engine_url:
        engine_url = engine_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(engine_url)
    params = parse_qs(parsed.query)
    ssl_mode = params.pop("sslmode", [None])[0]
    new_query = urlencode({k: v[0] for k, v in params.items()}) if params else ""
    engine_url = urlunparse(parsed._replace(query=new_query))

    connect_args = {}
    if ssl_mode and ssl_mode != "disable":
        import ssl as ssl_module
        ssl_ctx = ssl_module.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl_module.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    engine = create_async_engine(engine_url, connect_args=connect_args)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    if not os.path.exists(CSV_FILE):
        print(f"ERROR: {CSV_FILE} not found. Run the scraper first.")
        return

    scraped = {}
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            if sku:
                scraped[sku] = row

    print(f"Loaded {len(scraped)} scraped items from CSV")
    print(f"Scraped images directory: {os.path.abspath(SCRAPED_DIR)}")
    print(f"Destination directory: {os.path.abspath(DEST_DIR)}")

    os.makedirs(DEST_DIR, exist_ok=True)

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, sku, name, photo_urls, image_path FROM items WHERE status = 'active' AND sku IS NOT NULL AND sku != ''")
        )
        db_items = result.fetchall()
        print(f"Found {len(db_items)} active items with SKUs in database")

        matched = 0
        updated = 0
        skipped_no_images = 0
        skipped_already_has = 0
        not_found = 0
        copy_errors = 0

        for item_id, sku_val, name, existing_photos, existing_image in db_items:
            barcode_clean = (sku_val or "").strip()
            if not barcode_clean:
                continue

            if barcode_clean not in scraped:
                not_found += 1
                continue

            matched += 1
            row = scraped[barcode_clean]
            image_filenames_str = row.get("image_filenames", "")
            if not image_filenames_str:
                skipped_no_images += 1
                continue

            if existing_photos and len(existing_photos) > 0:
                skipped_already_has += 1
                continue

            image_filenames = image_filenames_str.split("|")
            copied_paths = []

            for filename in image_filenames:
                src_path = os.path.join(SCRAPED_DIR, filename)
                if not os.path.exists(src_path):
                    continue

                dest_filename = f"rico_{barcode_clean}_{len(copied_paths)}{Path(filename).suffix}"
                dest_path = os.path.join(DEST_DIR, dest_filename)
                web_path = f"/static/uploads/items/{dest_filename}"

                if not dry_run:
                    try:
                        shutil.copy2(src_path, dest_path)
                        copied_paths.append(web_path)
                    except Exception as e:
                        print(f"  Copy error for {filename}: {e}")
                        copy_errors += 1
                else:
                    copied_paths.append(web_path)

            if copied_paths:
                if not dry_run:
                    await session.execute(
                        text("UPDATE items SET photo_urls = :photos, image_path = :img WHERE id = :id"),
                        {"photos": copied_paths, "img": copied_paths[0], "id": item_id}
                    )
                updated += 1
                if updated <= 10:
                    print(f"  {'[DRY RUN] ' if dry_run else ''}Updated: {name[:50]} (barcode={barcode_clean}) -> {len(copied_paths)} images")

        if not dry_run:
            await session.commit()

        print(f"\n{'=== DRY RUN RESULTS ===' if dry_run else '=== IMPORT RESULTS ==='}")
        print(f"  DB items with barcodes: {len(db_items)}")
        print(f"  Matched to scraped:     {matched}")
        print(f"  Updated with images:    {updated}")
        print(f"  No scraped images:      {skipped_no_images}")
        print(f"  Already had images:     {skipped_already_has}")
        print(f"  No match in scraped:    {not_found}")
        print(f"  Copy errors:            {copy_errors}")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Import scraped Ricochet images into BMM-POS")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--db-url", type=str, help="Database URL (default: local)")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, db_url=args.db_url))


if __name__ == "__main__":
    main()
