import sys
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pathlib import Path
from sqlalchemy import text

from app.database import AsyncSessionLocal, engine, Base
from app.routers import auth, vendors, items, sales, pos, assistant, storefront, rent, admin, reports, settings


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
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "image_path VARCHAR(500)"
            ))
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
        import bcrypt
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM vendors"))
            count = result.scalar()
            if count == 0:
                print("BMM-POS: No vendors found — seeding essential accounts...", file=sys.stderr, flush=True)
                def make_hash(pw):
                    return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

                seed_vendors = [
                    Vendor(name="Admin", email="admin@bowenstreetmarket.com", phone="920-555-0001",
                           booth_number="A-01", monthly_rent=0, password_hash=make_hash("admin123"),
                           role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
                    Vendor(name="Sarah Johnson", email="sarah@email.com", phone="920-555-0002",
                           booth_number="A-12", monthly_rent=250, password_hash=make_hash("vendor123"),
                           role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
                    Vendor(name="Mike Chen", email="mike@email.com", phone="920-555-0003",
                           booth_number="B-07", monthly_rent=300, password_hash=make_hash("vendor123"),
                           role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
                    Vendor(name="Linda Martinez", email="linda@email.com", phone="920-555-0004",
                           booth_number="C-22", monthly_rent=200, password_hash=make_hash("vendor123"),
                           role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
                    Vendor(name="Cashier", email="cashier@bowenstreetmarket.com", phone="920-555-0005",
                           booth_number="B-01", monthly_rent=0, password_hash=make_hash("cashier123"),
                           role="cashier", is_vendor=True, is_active=True, commission_rate=0.10),
                ]
                for v in seed_vendors:
                    session.add(v)
                await session.commit()
                print(f"BMM-POS: Seeded {len(seed_vendors)} accounts", file=sys.stderr, flush=True)
            else:
                print(f"BMM-POS: {count} vendors already in DB", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: auto-seed FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    yield


app = FastAPI(
    title="BMM-POS",
    description="Bowenstreet Market POS System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"BMM-POS EXCEPTION on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
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
app.include_router(rent.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")

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
    <loc>https://www.bowenstreetmm.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>'''
    return Response(content=xml, media_type="application/xml")


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
