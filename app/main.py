import os
import sys
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, Response, FileResponse, HTMLResponse
from pathlib import Path
from sqlalchemy import text

try:
    print("BMM-POS: importing database...", file=sys.stderr, flush=True)
    from app.database import AsyncSessionLocal, engine, Base
    print("BMM-POS: importing routers...", file=sys.stderr, flush=True)
    from app.routers import auth, vendors, items, sales, pos, assistant, storefront, storefront_assistant, rent, admin, reports, settings, studio, bulk_import, notifications, booth_showcase
    print("BMM-POS: all imports OK", file=sys.stderr, flush=True)
except Exception as _import_err:
    print(f"BMM-POS FATAL IMPORT ERROR: {type(_import_err).__name__}: {_import_err}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all models are registered with Base.metadata before create_all
    import app.models  # noqa: F401

    # Create any missing tables (safe to run on every startup — skips existing tables)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS: database schema OK", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: schema create_all FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    # Add columns that create_all won't add to existing tables
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "rent_flagged BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "is_active BOOLEAN NOT NULL DEFAULT true"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "is_vendor BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "commission_rate NUMERIC(5,4) NOT NULL DEFAULT 0.1000"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "label_preference VARCHAR(20) NOT NULL DEFAULT 'standard'"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "pdf_label_size VARCHAR(30) NOT NULL DEFAULT '2.25x1.25'"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "assistant_name VARCHAR(50)"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "image_path VARCHAR(500)"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "is_consignment BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "consignment_rate NUMERIC(5,4)"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "label_printed BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS "
                "is_consignment BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS "
                "consignment_rate NUMERIC(5,4)"
            ))
            await session.execute(text(
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS "
                "consignment_amount NUMERIC(10,2)"
            ))
            await session.execute(text(
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS "
                "is_voided BOOLEAN NOT NULL DEFAULT false"
            ))
            await session.execute(text(
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS "
                "voided_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS "
                "voided_by INTEGER REFERENCES vendors(id)"
            ))
            await session.execute(text(
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS "
                "void_reason TEXT"
            ))
            await session.execute(text(
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS "
                "customer_email VARCHAR(200)"
            ))
            await session.execute(text(
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS "
                "public_id VARCHAR(36)"
            ))
            backfill_result = await session.execute(text(
                "SELECT id FROM reservations WHERE public_id IS NULL"
            ))
            import uuid as _uuid_mod
            for row in backfill_result.fetchall():
                await session.execute(
                    text("UPDATE reservations SET public_id = :pid WHERE id = :rid"),
                    {"pid": str(_uuid_mod.uuid4()), "rid": row[0]}
                )
            await session.execute(text("""
                DO $$ BEGIN
                    ALTER TABLE reservations
                        ALTER COLUMN public_id SET NOT NULL;
                EXCEPTION WHEN others THEN NULL;
                END $$
            """))
            await session.execute(text("""
                DO $$ BEGIN
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_reservations_public_id
                        ON reservations (public_id);
                EXCEPTION WHEN others THEN NULL;
                END $$
            """))
            landing_cols = [
                "landing_page_enabled BOOLEAN DEFAULT FALSE",
                "landing_slug VARCHAR(100)",
                "landing_about TEXT",
                "landing_contact_email VARCHAR(200)",
                "landing_contact_phone VARCHAR(50)",
                "landing_website VARCHAR(300)",
                "landing_facebook VARCHAR(300)",
                "landing_instagram VARCHAR(300)",
                "landing_tiktok VARCHAR(300)",
                "landing_twitter VARCHAR(300)",
                "landing_etsy VARCHAR(300)",
                "landing_meta_title VARCHAR(200)",
                "landing_meta_desc VARCHAR(500)",
            ]
            for col_def in landing_cols:
                col_name = col_def.split()[0]
                await session.execute(text(
                    f"ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS {col_def}"
                ))
            await session.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_booth_showcases_landing_slug "
                "ON booth_showcases (landing_slug) WHERE landing_slug IS NOT NULL"
            ))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS balance_adjustments (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
                    adjusted_by INTEGER NOT NULL REFERENCES vendors(id),
                    amount NUMERIC(10,2) NOT NULL,
                    adjustment_type VARCHAR(10) NOT NULL,
                    reason TEXT NOT NULL,
                    balance_before NUMERIC(10,2) NOT NULL,
                    balance_after NUMERIC(10,2) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            await session.commit()
    except Exception as e:
        print(f"BMM-POS: column migration FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    # Verify connectivity
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("BMM-POS: database connection OK", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: DATABASE CONNECTION FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    # Auto-seed essential accounts if database is empty
    try:
        from app.models.vendor import Vendor
        from sqlalchemy import select as sa_select
        import bcrypt
        import secrets as _secrets

        def make_hash(pw):
            return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

        _admin_pw = os.environ.get("ADMIN_PASSWORD") or _secrets.token_urlsafe(16)
        _cashier_pw = os.environ.get("CASHIER_PASSWORD") or _secrets.token_urlsafe(16)
        _vendor_pw = _secrets.token_urlsafe(16)

        seed_accounts = [
            dict(name="Admin", email="admin@bowenstreetmarket.com", phone="920-555-0001",
                 booth_number="A-01", monthly_rent=0, password=_admin_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Sarah Johnson", email="sarah@email.com", phone="920-555-0002",
                 booth_number="A-12", monthly_rent=250, password=_vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Mike Chen", email="mike@email.com", phone="920-555-0003",
                 booth_number="B-07", monthly_rent=300, password=_vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Linda Martinez", email="linda@email.com", phone="920-555-0004",
                 booth_number="C-22", monthly_rent=200, password=_vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Cashier", email="cashier@bowenstreetmarket.com", phone="920-555-0005",
                 booth_number="B-01", monthly_rent=0, password=_cashier_pw,
                 role="cashier", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Nora Williams", email="nora@email.com", phone="920-555-0006",
                 booth_number="D-01", monthly_rent=275, password=_vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Sammy Davis", email="sammy@email.com", phone="920-555-0007",
                 booth_number="D-05", monthly_rent=250, password=_vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Ashley Brown", email="ashley@email.com", phone="920-555-0008",
                 booth_number="E-02", monthly_rent=300, password=_vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Anne Taylor", email="anne@email.com", phone="920-555-0009",
                 booth_number="E-10", monthly_rent=225, password=_vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Paula Garcia", email="paula@email.com", phone="920-555-0010",
                 booth_number="F-03", monthly_rent=200, password=_vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
        ]

        async with AsyncSessionLocal() as session:
            added = 0
            updated = 0
            for acct in seed_accounts:
                pw = acct.pop("password")
                result = await session.execute(
                    sa_select(Vendor).where(Vendor.email == acct["email"])
                )
                existing = result.scalar_one_or_none()
                if existing:
                    changed = False
                    if existing.role != acct.get("role"):
                        existing.role = acct["role"]
                        changed = True
                    if existing.is_vendor != acct.get("is_vendor"):
                        existing.is_vendor = acct["is_vendor"]
                        changed = True
                    if existing.booth_number != acct.get("booth_number"):
                        existing.booth_number = acct["booth_number"]
                        changed = True
                    if changed:
                        updated += 1
                else:
                    session.add(Vendor(**acct, password_hash=make_hash(pw)))
                    added += 1
            if added or updated:
                await session.commit()
            msg_parts = []
            if added:
                msg_parts.append(f"seeded {added} new")
            if updated:
                msg_parts.append(f"re-hashed {updated} passwords")
            if msg_parts:
                print(f"BMM-POS: {', '.join(msg_parts)}", file=sys.stderr, flush=True)
            else:
                total = await session.execute(text("SELECT COUNT(*) FROM vendors"))
                print(f"BMM-POS: {total.scalar()} vendors OK", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: auto-seed FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    yield


app = FastAPI(
    title="BMM-POS",
    description="Bowenstreet Market POS System",
    version="1.0.0",
    lifespan=lifespan,
)

_replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
_replit_domains = os.environ.get("REPLIT_DOMAINS", "")
_allowed_origins = [
    f"https://{_replit_domain}",
    *[f"https://{d.strip()}" for d in _replit_domains.split(",") if d.strip()],
] if _replit_domain else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"BMM-POS EXCEPTION on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(items.router, prefix="/api/v1")
app.include_router(sales.router, prefix="/api/v1")
app.include_router(pos.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(storefront.router, prefix="/api/v1")
app.include_router(storefront_assistant.router, prefix="/api/v1")
app.include_router(rent.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(studio.router, prefix="/api/v1")
app.include_router(bulk_import.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(booth_showcase.router, prefix="/api/v1")

@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    path = Path("frontend/static/llms.txt")
    return PlainTextResponse(path.read_text())


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    path = Path("frontend/static/robots.txt")
    return PlainTextResponse(path.read_text())


@app.get("/sitemap.xml", response_class=Response)
async def sitemap_xml():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.bowenstreetmm.com/shop/index.html</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://www.bowenstreetmm.com/shop/booths.html</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://www.bowenstreetmm.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>'''
    return Response(content=xml, media_type="application/xml")


@app.get("/v/{slug}")
async def vendor_landing_page(slug: str):
    page = Path("frontend/shop/vendor-page.html")
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
