#!/usr/bin/env python3
"""
Migrate vendor and inventory data from dev DB to production via bulk import API.
Preserves existing barcodes so items can be sold without relabeling.
Run from workspace root: python scripts/migrate_to_prod.py
"""
import asyncio
import csv
import io
import os
import httpx

PROD_URL = "https://bowenstreetmm.com"
ADMIN_EMAIL = "admin@bowenstreetmarket.com"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    raise SystemExit("Set ADMIN_PASSWORD env var before running this script.")

CHUNK_SIZE = 5000


async def get_token(client):
    resp = await client.post(
        f"{PROD_URL}/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def get_dev_db():
    import asyncpg
    url = os.environ["DATABASE_URL"]
    return await asyncpg.connect(url)


async def export_vendors(conn):
    rows = await conn.fetch("""
        SELECT name, email, phone, booth_number, monthly_rent, commission_rate,
               payout_method, zelle_handle
        FROM vendors
        WHERE role='vendor' AND is_active=true
        ORDER BY name
    """)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "email", "phone", "booth_number", "monthly_rent",
                     "commission_rate", "payout_method", "zelle_handle"])
    for r in rows:
        writer.writerow([r["name"], r["email"], r["phone"], r["booth_number"],
                         str(r["monthly_rent"]), str(r["commission_rate"]),
                         r["payout_method"], r["zelle_handle"]])
    return buf.getvalue(), len(rows)


async def export_items_chunk(conn, offset, limit):
    rows = await conn.fetch("""
        SELECT i.name, i.sku, i.price, i.barcode, i.quantity, i.category,
               i.description, i.is_tax_exempt, i.is_consignment,
               i.consignment_rate, i.sale_price, v.name as vendor_name
        FROM items i
        JOIN vendors v ON i.vendor_id = v.id
        WHERE i.status = 'active'
        ORDER BY i.id
        OFFSET $1 LIMIT $2
    """, offset, limit)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "price", "vendor_name", "barcode", "sku", "quantity",
                     "category", "description", "tax_exempt", "consignment",
                     "consignment_rate", "sale_price"])
    for r in rows:
        writer.writerow([
            r["name"], str(r["price"]), r["vendor_name"], r["barcode"],
            r["sku"], r["quantity"], r["category"], r["description"],
            "true" if r["is_tax_exempt"] else "false",
            "true" if r["is_consignment"] else "false",
            str(r["consignment_rate"]) if r["consignment_rate"] else "",
            str(r["sale_price"]) if r["sale_price"] else "",
        ])
    return buf.getvalue(), len(rows)


async def upload_csv(client, token, endpoint, csv_data, filename):
    resp = await client.post(
        f"{PROD_URL}/api/v1/bulk-import/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, csv_data.encode(), "text/csv")},
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()


async def upload_batch_items(client, token, csv_data, filename):
    resp = await client.post(
        f"{PROD_URL}/api/v1/bulk-import/batch-items",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, csv_data.encode(), "text/csv")},
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()


async def main():
    conn = await get_dev_db()
    print("Connected to dev database")

    total_items = await conn.fetchval("SELECT count(*) FROM items WHERE status='active'")
    total_vendors = await conn.fetchval("SELECT count(*) FROM vendors WHERE role='vendor' AND is_active=true")
    print(f"Dev DB: {total_vendors} vendors, {total_items} active items to migrate")

    vendor_csv, vendor_count = await export_vendors(conn)
    print(f"Exported {vendor_count} vendors ({len(vendor_csv)} bytes)")

    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        print("Authenticated with production API")

        print("\n--- Uploading vendors ---")
        result = await upload_csv(client, token, "vendors", vendor_csv, "vendors.csv")
        print(f"  {result['summary']}")
        if result.get("errors"):
            for e in result["errors"][:5]:
                print(f"  Error: {e}")

        print(f"\n--- Uploading inventory ({total_items} items in chunks of {CHUNK_SIZE}) ---")
        print("  Using fast batch-items endpoint (raw SQL, preserves barcodes)")
        total_created = 0
        total_errors = 0

        for offset in range(0, total_items, CHUNK_SIZE):
            chunk_csv, chunk_count = await export_items_chunk(conn, offset, CHUNK_SIZE)
            if chunk_count == 0:
                break
            chunk_num = offset // CHUNK_SIZE + 1
            print(f"  Chunk {chunk_num}: {chunk_count} items ({len(chunk_csv):,} bytes)...", end=" ", flush=True)

            try:
                result = await upload_batch_items(client, token, chunk_csv, f"items_{chunk_num}.csv")
                created = result.get("created_count", 0)
                errors = len(result.get("errors", []))
                total_created += created
                total_errors += errors
                print(f"created={created}, errors={errors}")
                if result.get("errors"):
                    for e in result["errors"][:3]:
                        print(f"    Error: {e}")
            except httpx.HTTPStatusError as e:
                print(f"FAILED: HTTP {e.response.status_code} - {e.response.text[:200]}")
                total_errors += chunk_count
            except Exception as e:
                print(f"FAILED: {e}")
                total_errors += chunk_count

        print(f"\n=== MIGRATION COMPLETE ===")
        print(f"Vendors: {vendor_count} exported")
        print(f"Items: {total_created} created, {total_errors} errors")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
