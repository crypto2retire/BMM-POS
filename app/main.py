import os
import sys
import traceback
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
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


async def _has_startup_marker(session, marker_key: str) -> bool:
    result = await session.execute(
        text("SELECT value FROM store_settings WHERE key = :key"),
        {"key": marker_key},
    )
    return bool(result.scalar_one_or_none())


async def _set_startup_marker(session, marker_key: str, description: str) -> None:
    await session.execute(
        text("""
            INSERT INTO store_settings (key, value, description)
            VALUES (:key, 'done', :description)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                description = EXCLUDED.description
        """),
        {"key": marker_key, "description": description},
    )


try:
    print("BMM-POS: importing database...", file=sys.stderr, flush=True)
    from app.database import AsyncSessionLocal, engine, Base
    print("BMM-POS: importing routers...", file=sys.stderr, flush=True)
    from app.routers import auth, vendors, items, sales, pos, assistant, storefront, storefront_assistant, rent, admin, reports, settings, studio, bulk_import, notifications, booth_showcase, data_sync, ai_writer
    from app.routers.inventory_verify import router as inventory_verify_router
    print("BMM-POS: all imports OK", file=sys.stderr, flush=True)
except Exception as _import_err:
    print(f"BMM-POS FATAL IMPORT ERROR: {type(_import_err).__name__}: {_import_err}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_checks.clear()

    # Ensure all models are registered with Base.metadata before create_all
    import app.models  # noqa: F401

    # Create any missing tables (safe to run on every startup — skips existing tables)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS: database schema OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_schema")
    except Exception as e:
        print(f"BMM-POS: schema create_all FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_schema", e, critical=True)

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
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "notes TEXT"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "theme_preference VARCHAR(10) NOT NULL DEFAULT 'dark'"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "font_size_preference VARCHAR(10) NOT NULL DEFAULT 'medium'"
            ))
            await session.execute(text("""
                ALTER TABLE vendors
                ADD COLUMN IF NOT EXISTS sale_notify_preference VARCHAR(10) NOT NULL DEFAULT 'instant'
            """))
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
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "verified_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "archive_expires_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS "
                "import_source VARCHAR(50)"
            ))
            import_source_marker = "startup_task_import_source_backfill_v1"
            if not await _has_startup_marker(session, import_source_marker):
                backfill_result = await session.execute(text(
                    "UPDATE items SET import_source = 'ricochet' "
                    "WHERE import_source IS NULL AND barcode IS NOT NULL"
                ))
                await _set_startup_marker(
                    session,
                    import_source_marker,
                    "Applied one-time startup backfill for Ricochet import_source tags.",
                )
                print(
                    f"BMM-POS: Ricochet import_source backfill marked complete ({backfill_result.rowcount} items)",
                    file=sys.stderr,
                    flush=True,
                )
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
            # Discount columns on sale_items and sales
            for tbl, col_def in [
                ("sale_items", "discount_type VARCHAR(10)"),
                ("sale_items", "discount_value NUMERIC(10,2)"),
                ("sale_items", "discount_amount NUMERIC(10,2)"),
                ("sales", "discount_type VARCHAR(10)"),
                ("sales", "discount_value NUMERIC(10,2)"),
                ("sales", "discount_amount NUMERIC(10,2)"),
            ]:
                await session.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col_def}"
                ))
            # Poynt payments table (Phase 4)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS poynt_payments (
                    id SERIAL PRIMARY KEY,
                    reference_id VARCHAR(100) UNIQUE,
                    amount_cents INTEGER,
                    status VARCHAR(20) DEFAULT 'pending',
                    poynt_transaction_id VARCHAR(200),
                    sale_id INTEGER REFERENCES sales(id),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status)"
            ))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS eod_reports (
                    id SERIAL PRIMARY KEY,
                    report_date DATE NOT NULL,
                    submitted_by INTEGER NOT NULL REFERENCES vendors(id),
                    submitted_by_name VARCHAR(200),
                    starting_balance NUMERIC(10,2) NOT NULL,
                    counted_cash NUMERIC(10,2) NOT NULL,
                    expected_cash NUMERIC(10,2) NOT NULL,
                    variance NUMERIC(10,2) NOT NULL,
                    deposit NUMERIC(10,2) NOT NULL,
                    total_revenue NUMERIC(10,2) NOT NULL DEFAULT 0,
                    total_tax NUMERIC(10,2) NOT NULL DEFAULT 0,
                    total_transactions INTEGER NOT NULL DEFAULT 0,
                    items_sold INTEGER NOT NULL DEFAULT 0,
                    cash_total NUMERIC(10,2) NOT NULL DEFAULT 0,
                    cash_count INTEGER NOT NULL DEFAULT 0,
                    card_total NUMERIC(10,2) NOT NULL DEFAULT 0,
                    card_count INTEGER NOT NULL DEFAULT 0,
                    gift_card_total NUMERIC(10,2) NOT NULL DEFAULT 0,
                    gift_card_count INTEGER NOT NULL DEFAULT 0,
                    voided_count INTEGER NOT NULL DEFAULT 0,
                    voided_total NUMERIC(10,2) NOT NULL DEFAULT 0,
                    cashier_breakdown JSONB,
                    notes TEXT,
                    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_eod_reports_date ON eod_reports(report_date)"
            ))
            await session.execute(text(
                "ALTER TABLE eod_reports ADD COLUMN IF NOT EXISTS denomination_counts JSONB"
            ))
            await session.commit()
            _record_startup_ok("column_migrations")
    except Exception as e:
        print(f"BMM-POS: column migration FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("column_migrations", e, critical=True)

    # Historical cleanup: run once so deploys stop mutating inventory flags.
    try:
        async with AsyncSessionLocal() as session:
            marker_key = "startup_task_consignment_cleanup_v1"
            if await _has_startup_marker(session, marker_key):
                print("BMM-POS: consignment cleanup already applied", file=sys.stderr, flush=True)
            else:
                result = await session.execute(text("""
                    UPDATE items
                    SET is_consignment = false,
                        consignment_rate = NULL
                    WHERE is_consignment = true OR consignment_rate IS NOT NULL
                """))
                await _set_startup_marker(
                    session,
                    marker_key,
                    "Applied one-time startup cleanup to clear legacy consignment flags.",
                )
                await session.commit()
                count = result.rowcount
                if count > 0:
                    print(f"BMM-POS: CLEARED consignment flags on {count} items", file=sys.stderr, flush=True)
                else:
                    print("BMM-POS: consignment check OK — no items flagged", file=sys.stderr, flush=True)
            _record_startup_ok("consignment_cleanup")
    except Exception as e:
        print(f"BMM-POS: CRITICAL — consignment cleanup failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("consignment_cleanup", e)

    # Historical defaulting: run once so startup does not overwrite payout choices.
    try:
        async with AsyncSessionLocal() as session:
            marker_key = "startup_task_vendor_payout_method_default_v1"
            if await _has_startup_marker(session, marker_key):
                print("BMM-POS: vendor payout_method default already applied", file=sys.stderr, flush=True)
            else:
                result = await session.execute(text("""
                    UPDATE vendors SET payout_method = 'check'
                    WHERE payout_method IS NULL OR payout_method != 'check'
                """))
                await _set_startup_marker(
                    session,
                    marker_key,
                    "Applied one-time startup default for vendor payout_method values.",
                )
                await session.commit()
                count = result.rowcount
                if count > 0:
                    print(f"BMM-POS: Set payout_method to 'check' for {count} vendors", file=sys.stderr, flush=True)
            _record_startup_ok("vendor_payout_method_default")
    except Exception as e:
        print(f"BMM-POS: payout_method default note: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("vendor_payout_method_default", e)

    # ── Add rent_balance column if missing ──
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text(
                "ALTER TABLE vendor_balances ADD COLUMN IF NOT EXISTS "
                "rent_balance NUMERIC(10,2) NOT NULL DEFAULT 0.00"
            ))
            await session.commit()
            print("BMM-POS: rent_balance column OK", file=sys.stderr, flush=True)
            _record_startup_ok("rent_balance_column")
    except Exception as e:
        print(f"BMM-POS: rent_balance column note: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("rent_balance_column", e)

    # ── Ensure every vendor has a vendor_balances row ──
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
            count = result.rowcount
            if count > 0:
                print(f"BMM-POS: Created missing vendor_balances rows for {count} vendors", file=sys.stderr, flush=True)
            _record_startup_ok("vendor_balances_backfill")
    except Exception as e:
        print(f"BMM-POS: vendor_balances backfill note: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("vendor_balances_backfill", e)

    # Historical migration: run once so deploys stop re-touching vendor balances.
    try:
        async with AsyncSessionLocal() as session:
            marker_key = "startup_task_rent_balance_migration_v1"
            if await _has_startup_marker(session, marker_key):
                print("BMM-POS: rent_balance migration already applied", file=sys.stderr, flush=True)
            else:
                result = await session.execute(text("""
                    UPDATE vendor_balances vb
                    SET rent_balance = rent_balance + sub.total_paid
                    FROM (
                        SELECT rp.vendor_id, SUM(rp.amount) as total_paid
                        FROM rent_payments rp
                        WHERE rp.status = 'paid'
                          AND rp.method != 'balance'
                          AND rp.processed_at >= CURRENT_DATE
                          AND NOT EXISTS (
                              SELECT 1 FROM vendor_balances vb2
                              WHERE vb2.vendor_id = rp.vendor_id AND vb2.rent_balance != 0
                          )
                        GROUP BY rp.vendor_id
                    ) sub
                    WHERE vb.vendor_id = sub.vendor_id
                """))
                await _set_startup_marker(
                    session,
                    marker_key,
                    "Applied one-time startup migration for rent_balance credits from paid rent payments.",
                )
                await session.commit()
                count = result.rowcount
                if count > 0:
                    print(f"BMM-POS: Migrated rent payments to rent_balance for {count} vendors", file=sys.stderr, flush=True)
            _record_startup_ok("rent_balance_migration")
    except Exception as e:
        print(f"BMM-POS: rent_balance migration note: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("rent_balance_migration", e)

    # Verify connectivity
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("BMM-POS: database connection OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_connection")
    except Exception as e:
        print(f"BMM-POS: DATABASE CONNECTION FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_connection", e, critical=True)

    # Auto-seed essential accounts if database is empty
    try:
        from app.models.vendor import Vendor
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
            vendor_count_result = await session.execute(text("SELECT COUNT(*) FROM vendors"))
            vendor_count = int(vendor_count_result.scalar() or 0)

            if vendor_count > 0:
                print(
                    f"BMM-POS: auto-seed skipped — {vendor_count} existing vendors detected",
                    file=sys.stderr,
                    flush=True,
                )
                _record_startup_ok("auto_seed_accounts")
            else:
                added = 0
                for acct in seed_accounts:
                    pw = acct.pop("password")
                    session.add(Vendor(**acct, password_hash=make_hash(pw)))
                    added += 1

                if added:
                    await session.commit()
                    print(f"BMM-POS: seeded {added} default vendor accounts", file=sys.stderr, flush=True)
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
