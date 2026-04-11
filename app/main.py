import os
import sys
import traceback
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, Response, FileResponse, HTMLResponse
from pathlib import Path
from sqlalchemy import text

logger = logging.getLogger("bmm-startup")
_startup_checks: list[dict] = []


def _record_startup_ok(task: str) -> None:
    _startup_checks.append({"task": task, "status": "ok"})


def _record_startup_failure(task: str, exc: Exception, *, critical: bool = False) -> None:
    _startup_checks.append(
        {
            "task": task,
            "status": "failed",
            "critical": critical,
            "error_type": type(exc).__name__,
        }
    )
    logger.exception("Startup task failed: %s", task)


def _startup_health_payload() -> dict:
    failed = [check["task"] for check in _startup_checks if check["status"] == "failed"]
    return {
        "status": "degraded" if failed else "ok",
        "startup_failure_count": len(failed),
        "startup_failed_tasks": failed,
    }


try:
    print("BMM-POS: importing database...", file=sys.stderr, flush=True)
    from app.database import AsyncSessionLocal, engine, Base
    print("BMM-POS: importing routers...", file=sys.stderr, flush=True)
    from app.routers import auth, vendors, items, sales, pos, assistant, storefront, storefront_assistant, rent, admin, reports, settings, studio, bulk_import, notifications, booth_showcase, data_sync, ai_writer, security_deposits
    from app.routers.inventory_verify import router as inventory_verify_router
    print("BMM-POS: all imports OK", file=sys.stderr, flush=True)
except Exception as _import_err:
    print(f"BMM-POS FATAL IMPORT ERROR: {type(_import_err).__name__}: {_import_err}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_checks.clear()

    import app.models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS: database schema OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_schema")
    except Exception as e:
        print(f"BMM-POS: schema create_all FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_schema", e, critical=True)

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "consignment_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0000"
            ))
            await session.commit()
        _record_startup_ok("add_consignment_rate_column")
    except Exception as e:
        _record_startup_failure("add_consignment_rate_column", e)

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "security_deposit_amount NUMERIC(10,2) NOT NULL DEFAULT 0.00"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "security_deposit_balance NUMERIC(10,2) NOT NULL DEFAULT 0.00"
            ))
            await session.commit()
        _record_startup_ok("add_security_deposit_columns")
    except Exception as e:
        _record_startup_failure("add_security_deposit_columns", e)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                INSERT INTO vendor_balances (vendor_id, balance, rent_balance)
                SELECT v.id, 0.00, 0.00
                FROM vendors v
                LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
                WHERE vb.id IS NULL
            """))
            await session.commit()
            count = result.rowcount or 0
            if count > 0:
                print(
                    f"BMM-POS: created missing vendor_balances rows for {count} vendors",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("vendor_balances_backfill")
    except Exception as e:
        print(f"BMM-POS: vendor_balances backfill FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("vendor_balances_backfill", e)

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("BMM-POS: database connection OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_connection")
    except Exception as e:
        print(f"BMM-POS: DATABASE CONNECTION FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_connection", e, critical=True)

    try:
        from app.models.vendor import Vendor
        import bcrypt
        import secrets as _secrets

        def make_hash(pw: str) -> str:
            return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

        admin_pw = os.environ.get("ADMIN_PASSWORD") or _secrets.token_urlsafe(16)
        cashier_pw = os.environ.get("CASHIER_PASSWORD") or _secrets.token_urlsafe(16)
        vendor_pw = _secrets.token_urlsafe(16)

        seed_accounts = [
            dict(name="Admin", email="admin@bowenstreetmarket.com", phone="920-555-0001",
                 booth_number="A-01", monthly_rent=0, password=admin_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Sarah Johnson", email="sarah@email.com", phone="920-555-0002",
                 booth_number="A-12", monthly_rent=250, password=vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Mike Chen", email="mike@email.com", phone="920-555-0003",
                 booth_number="B-07", monthly_rent=300, password=vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Linda Martinez", email="linda@email.com", phone="920-555-0004",
                 booth_number="C-22", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
            dict(name="Cashier", email="cashier@bowenstreetmarket.com", phone="920-555-0005",
                 booth_number="B-01", monthly_rent=0, password=cashier_pw,
                 role="cashier", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Nora Williams", email="nora@email.com", phone="920-555-0006",
                 booth_number="D-01", monthly_rent=275, password=vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Sammy Davis", email="sammy@email.com", phone="920-555-0007",
                 booth_number="D-05", monthly_rent=250, password=vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Ashley Brown", email="ashley@email.com", phone="920-555-0008",
                 booth_number="E-02", monthly_rent=300, password=vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Anne Taylor", email="anne@email.com", phone="920-555-0009",
                 booth_number="E-10", monthly_rent=225, password=vendor_pw,
                 role="admin", is_vendor=True, is_active=True, commission_rate=0.10),
            dict(name="Paula Garcia", email="paula@email.com", phone="920-555-0010",
                 booth_number="F-03", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=False, is_active=True, commission_rate=0.10),
        ]

        async with AsyncSessionLocal() as session:
            vendor_count_result = await session.execute(text("SELECT COUNT(*) FROM vendors"))
            vendor_count = int(vendor_count_result.scalar() or 0)

            if vendor_count == 0:
                for acct in seed_accounts:
                    password = acct.pop("password")
                    session.add(Vendor(**acct, password_hash=make_hash(password)))
                await session.commit()
                print(
                    f"BMM-POS: seeded {len(seed_accounts)} default vendor accounts",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print(
                    f"BMM-POS: auto-seed skipped — {vendor_count} existing vendors detected",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("auto_seed_accounts")
    except Exception as e:
        print(f"BMM-POS: auto-seed FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("auto_seed_accounts", e)

    startup_summary = _startup_health_payload()
    if startup_summary["startup_failure_count"]:
        print(
            "BMM-POS: startup completed with warnings — failed tasks: "
            + ", ".join(startup_summary["startup_failed_tasks"]),
            file=sys.stderr,
            flush=True,
        )
    else:
        print("BMM-POS: startup checks all passed", file=sys.stderr, flush=True)

    yield


app = FastAPI(
    title="BMM-POS",
    description="Bowenstreet Market POS System",
    version="1.0.0",
    lifespan=lifespan,
)

def _normalize_origin(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value.rstrip("/")
    return f"https://{value}".rstrip("/")


def _build_allowed_origins() -> list[str]:
    origins: list[str] = []

    for raw_value in (
        os.environ.get("REPLIT_DEV_DOMAIN", ""),
        *os.environ.get("REPLIT_DOMAINS", "").split(","),
        *os.environ.get("CORS_ALLOWED_ORIGINS", "").split(","),
        os.environ.get("PUBLIC_APP_ORIGIN", ""),
        os.environ.get("RAILWAY_PUBLIC_DOMAIN", ""),
    ):
        origin = _normalize_origin(raw_value)
        if origin and origin not in origins:
            origins.append(origin)

    # Same-origin requests do not need CORS, but localhost dev often does.
    for localhost_origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ):
        if localhost_origin not in origins:
            origins.append(localhost_origin)

    return origins


_allowed_origins = _build_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    print(f"BMM-POS EXCEPTION on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    return _startup_health_payload()


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
app.include_router(inventory_verify_router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(booth_showcase.router, prefix="/api/v1")
app.include_router(security_deposits.router, prefix="/api/v1")
app.include_router(data_sync.router, prefix="/api/v1")
app.include_router(ai_writer.router, prefix="/api/v1")

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


@app.get("/shop/vendor/{vendor_id:int}")
async def vendor_inventory_page(vendor_id: int):
    page = Path("frontend/shop/vendor-inventory.html")
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
