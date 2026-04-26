import os
import sys
import json
import traceback
import logging
import signal
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, Response, FileResponse, HTMLResponse
from pathlib import Path
from sqlalchemy import text, select, func

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


# ── Graceful shutdown ──
_shutdown_event = asyncio.Event()


def _handle_shutdown_signal(sig: int, frame) -> None:
    signame = signal.Signals(sig).name
    print(f"BMM-POS: received {signame}, starting graceful shutdown...", file=sys.stderr, flush=True)
    _shutdown_event.set()


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGTERM, _handle_shutdown_signal)
signal.signal(signal.SIGINT, _handle_shutdown_signal)


try:
    print("BMM-POS: importing database...", file=sys.stderr, flush=True)
    from app.database import AsyncSessionLocal, engine, Base
    print("BMM-POS: importing routers...", file=sys.stderr, flush=True)
    from app.routers import auth, vendors, items, sales, pos, assistant, storefront, storefront_assistant, rent, admin, reports, settings, studio, bulk_import, notifications, booth_showcase, data_sync, ai_writer, security_deposits, errors
    from app.routers.diagnose import router as diagnose_router
    from app.routers.inventory_verify import router as inventory_verify_router
    from app.routers.accounting import router as accounting_router
    print("BMM-POS: all imports OK", file=sys.stderr, flush=True)
except Exception as _import_err:
    print(f"BMM-POS FATAL IMPORT ERROR: {type(_import_err).__name__}: {_import_err}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_checks.clear()

    import app.models  # noqa: F401

    # ── Light schema check (create_all is idempotent, only creates missing tables) ──
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS: database schema OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_schema")
    except Exception as e:
        print(f"BMM-POS: schema create_all FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_schema", e, critical=True)

    # ── Ensure 'cost' column exists on items table ──
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'items' AND column_name = 'cost'"
            ))
            if not result.scalar_one_or_none():
                await conn.execute(text(
                    "ALTER TABLE items ADD COLUMN cost NUMERIC(10,2) DEFAULT NULL"
                ))
                print("BMM-POS: added 'cost' column to items table", file=sys.stderr, flush=True)
        _record_startup_ok("items_cost_column")
    except Exception as e:
        print(f"BMM-POS: items cost column check FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("items_cost_column", e)

    # ── Ensure 'unit_cost' column exists on sale_items table ──
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sale_items' AND column_name = 'unit_cost'"
            ))
            if not result.scalar_one_or_none():
                await conn.execute(text(
                    "ALTER TABLE sale_items ADD COLUMN unit_cost NUMERIC(10,2) DEFAULT NULL"
                ))
                print("BMM-POS: added 'unit_cost' column to sale_items table", file=sys.stderr, flush=True)
        _record_startup_ok("sale_items_unit_cost_column")
    except Exception as e:
        print(f"BMM-POS: sale_items unit_cost column check FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("sale_items_unit_cost_column", e)

    # ── Ensure 'square_payment_id' column exists on rent_payments table ──
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'rent_payments' AND column_name = 'square_payment_id'"
            ))
            if not result.scalar_one_or_none():
                await conn.execute(text(
                    "ALTER TABLE rent_payments ADD COLUMN square_payment_id VARCHAR(200) DEFAULT NULL"
                ))
                await conn.execute(text(
                    "CREATE INDEX idx_rentpayments_square_id ON rent_payments(square_payment_id)"
                ))
                print("BMM-POS: added 'square_payment_id' column to rent_payments table", file=sys.stderr, flush=True)
        _record_startup_ok("rent_payments_square_payment_id_column")
    except Exception as e:
        print(f"BMM-POS: rent_payments square_payment_id column check FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("rent_payments_square_payment_id_column", e)

    # ── Fix NULL item statuses ──
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "UPDATE items SET status = 'active' WHERE status IS NULL OR status = ''"
            ))
            count = result.rowcount or 0
            if count > 0:
                print(f"BMM-POS: fixed {count} items with NULL/empty status", file=sys.stderr, flush=True)
        _record_startup_ok("items_status_fix")
    except Exception as e:
        print(f"BMM-POS: items status fix FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("items_status_fix", e)

    # ── DB connectivity check ──
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("BMM-POS: database connection OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_connection")
    except Exception as e:
        print(f"BMM-POS: DATABASE CONNECTION FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_connection", e, critical=True)

    # ── Vendor balances backfill ──
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

    # ── Deduplicate vendor_balances rows ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                DELETE FROM vendor_balances
                WHERE id NOT IN (
                    SELECT MIN(id) FROM vendor_balances GROUP BY vendor_id
                )
            """))
            await session.commit()
            count = result.rowcount or 0
            if count > 0:
                print(
                    f"BMM-POS: deduplicated vendor_balances — removed {count} duplicate rows",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("vendor_balances_dedup")
    except Exception as e:
        print(f"BMM-POS: vendor_balances dedup FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("vendor_balances_dedup", e)

    # ── Deduplicate rent_payments rows ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                DELETE FROM rent_payments
                WHERE id NOT IN (
                    SELECT MAX(id) FROM rent_payments GROUP BY vendor_id, period_month, status
                )
            """))
            await session.commit()
            count = result.rowcount or 0
            if count > 0:
                print(
                    f"BMM-POS: deduplicated rent_payments — removed {count} duplicate rows",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("rent_payments_dedup")
    except Exception as e:
        print(f"BMM-POS: rent_payments dedup FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("rent_payments_dedup", e)

    # ── Deduplicate booth_showcases rows ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                DELETE FROM booth_showcases
                WHERE id NOT IN (
                    SELECT MAX(id) FROM booth_showcases GROUP BY vendor_id
                )
            """))
            await session.commit()
            count = result.rowcount or 0
            if count > 0:
                print(
                    f"BMM-POS: deduplicated booth_showcases — removed {count} duplicate rows",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("booth_showcases_dedup")
    except Exception as e:
        print(f"BMM-POS: booth_showcases dedup FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("booth_showcases_dedup", e)

    try:
        if os.environ.get("SEED_DEMO_ACCOUNTS", "").lower() not in ("true", "1", "yes"):
            print(
                "BMM-POS: auto-seed skipped — set SEED_DEMO_ACCOUNTS=true to seed demo accounts",
                file=sys.stderr,
                flush=True,
            )
            _record_startup_ok("auto_seed_accounts")
            # Skip seeding without exiting

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
                 booth_number=None, monthly_rent=0, password=admin_pw,
                 role="admin", is_vendor=False, is_active=True, commission_rate=0),
            dict(name="Cashier", email="cashier@bowenstreetmarket.com", phone="920-555-0005",
                 booth_number=None, monthly_rent=0, password=cashier_pw,
                 role="cashier", is_vendor=False, is_active=True, commission_rate=0),
            dict(name="Sarah Johnson", email="sarah@email.com", phone="920-555-0002",
                 booth_number="A-12", monthly_rent=250, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Mike Chen", email="mike@email.com", phone="920-555-0003",
                 booth_number="B-07", monthly_rent=300, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Linda Martinez", email="linda@email.com", phone="920-555-0004",
                 booth_number="C-22", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Nora Williams", email="nora@email.com", phone="920-555-0006",
                 booth_number="D-01", monthly_rent=275, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Sammy Davis", email="sammy@email.com", phone="920-555-0007",
                 booth_number="D-05", monthly_rent=250, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Ashley Brown", email="ashley@email.com", phone="920-555-0008",
                 booth_number="E-02", monthly_rent=300, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Anne Taylor", email="anne@email.com", phone="920-555-0009",
                 booth_number="E-10", monthly_rent=225, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Paula Garcia", email="paula@email.com", phone="920-555-0010",
                 booth_number="F-03", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
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

    # ── Fix leftover admin+vendor hybrid accounts ──
    try:
        async with AsyncSessionLocal() as session:
            # Anyone with role=admin/cashier AND is_vendor=True should be role=vendor
            result = await session.execute(
                text("SELECT id, name, role FROM vendors WHERE role IN ('admin','cashier') AND is_vendor = true")
            )
            hybrids = result.fetchall()
            if hybrids:
                ids = [row[0] for row in hybrids]
                names = [f"{row[1]} (was {row[2]})" for row in hybrids]
                await session.execute(
                    text("UPDATE vendors SET role = 'vendor' WHERE id = ANY(:ids)"),
                    {"ids": ids},
                )
                await session.commit()
                print(
                    f"BMM-POS: fixed {len(ids)} hybrid accounts to vendor-only: {', '.join(names)}",
                    file=sys.stderr, flush=True,
                )
        _record_startup_ok("fix_hybrid_accounts")
    except Exception as e:
        print(f"BMM-POS: fix hybrid accounts FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("fix_hybrid_accounts", e)

    # ── Expire old pending reservations ──
    try:
        async with AsyncSessionLocal() as session:
            from app.models.reservation import Reservation
            from app.models.item import Item
            from sqlalchemy.orm import selectinload
            from sqlalchemy import text as sa_text
            # Gracefully handle missing column by checking information_schema first
            col_check = await session.execute(
                sa_text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'reservations' AND column_name = 'expires_at'
                """)
            )
            if not col_check.scalar_one_or_none():
                print("BMM-POS: expires_at column not present yet, skipping reservation expiration", file=sys.stderr, flush=True)
                _record_startup_ok("expire_reservations")
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
                result = await session.execute(
                    select(Reservation)
                    .where(Reservation.status == "pending")
                    .where(Reservation.expires_at.isnot(None))
                    .where(Reservation.expires_at < cutoff)
                    .options(selectinload(Reservation.item))
                )
                expired = result.scalars().all()
                count = 0
                for r in expired:
                    r.status = "expired"
                    if r.item:
                        r.item.reserved_quantity = max(0, r.item.reserved_quantity - 1)
                    count += 1
                if count > 0:
                    await session.commit()
                    print(f"BMM-POS: expired {count} abandoned reservations", file=sys.stderr, flush=True)
                _record_startup_ok("expire_reservations")
    except Exception as e:
        print(f"BMM-POS: reservation expiration FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("expire_reservations", e)

    # ── Backup age check ──
    try:
        async with AsyncSessionLocal() as session:
            backup_result = await session.execute(
                text("SELECT value FROM store_settings WHERE key = 'last_backup_at'")
            )
            backup_val = backup_result.scalar_one_or_none()
            if backup_val:
                from datetime import timezone
                try:
                    last_backup = datetime.fromisoformat(backup_val.replace("Z", "+00:00"))
                    hours_since = (datetime.now(timezone.utc) - last_backup).total_seconds() / 3600
                    if hours_since > 48:
                        print(f"BMM-POS: WARNING — last backup was {hours_since:.1f} hours ago", file=sys.stderr, flush=True)
                    else:
                        print(f"BMM-POS: last backup {hours_since:.1f} hours ago — OK", file=sys.stderr, flush=True)
                        _record_startup_ok("backup_check")
                except Exception:
                    print("BMM-POS: WARNING — backup timestamp unreadable", file=sys.stderr, flush=True)
            else:
                print("BMM-POS: WARNING — no backup record found (set 'last_backup_at' in store_settings)", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: backup check FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)

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

    # ── Seed default chart of accounts ──
    try:
        async with AsyncSessionLocal() as session:
            from app.models.accounting import Account as Acc
            from sqlalchemy import select as sa_select
            result = await session.execute(sa_select(Acc).where(Acc.is_system == True))
            existing = result.scalars().all()
            if len(existing) < 18:
                defaults = [
                    (1000, "Cash on Hand", "asset", True, "Cash in register and petty cash"),
                    (1010, "Checking Account", "asset", True, "Primary business checking"),
                    (1100, "Accounts Receivable", "asset", True, "Money owed to you by customers"),
                    (2000, "Accounts Payable", "liability", True, "Bills you need to pay"),
                    (2200, "Sales Tax Payable", "liability", True, "Sales tax collected, owed to state"),
                    (2300, "Gift Card Liability", "liability", True, "Outstanding gift card balances"),
                    (3000, "Owner's Equity", "equity", True, "Owner's investment and retained earnings"),
                    (4000, "Sales Revenue — In Store", "income", True, "Revenue from in-store sales"),
                    (4010, "Sales Revenue — Online", "income", True, "Revenue from online orders"),
                    (4020, "Class & Event Revenue", "income", True, "Revenue from studio classes and events"),
                    (5000, "Cost of Goods Sold", "cogs", True, "Direct cost of products sold"),
                    (6000, "Rent", "expense", True, "Store rent and occupancy costs"),
                    (6010, "Utilities", "expense", True, "Electric, water, internet, phone"),
                    (6100, "Payroll & Wages", "expense", True, "Employee wages and related costs"),
                    (6200, "Supplies & Materials", "expense", True, "Store supplies, packaging, materials"),
                    (6300, "Marketing & Advertising", "expense", True, "Advertising, promotions, social media"),
                    (6400, "Insurance", "expense", True, "Business and liability insurance"),
                    (6500, "Professional Services", "expense", True, "Legal, accounting, consulting"),
                    (6600, "Bank & Processing Fees", "expense", True, "Credit card fees, bank charges"),
                    (6700, "Repairs & Maintenance", "expense", True, "Equipment repair and maintenance"),
                    (6900, "Other Expenses", "expense", True, "Miscellaneous business expenses"),
                ]
                existing_nums = {a.number for a in existing}
                added = 0
                for num, name, atype, sys, desc in defaults:
                    if num in existing_nums:
                        continue
                    session.add(Acc(number=num, name=name, account_type=atype, is_system=sys, description=desc, is_active=True))
                    added += 1
                if added > 0:
                    await session.commit()
                    print(f"BMM-POS: seeded {added} default chart of accounts", file=sys.stderr, flush=True)
        _record_startup_ok("chart_of_accounts_seed")
    except Exception as e:
        print(f"BMM-POS: chart of accounts seed FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("chart_of_accounts_seed", e)

    yield

    # ── Graceful shutdown cleanup ──
    print("BMM-POS: shutting down, waiting for in-flight requests...", file=sys.stderr, flush=True)
    # Give in-flight requests up to 5 seconds to finish
    try:
        await asyncio.wait_for(_shutdown_event.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        pass
    # Dispose DB engine connections
    try:
        await engine.dispose()
        print("BMM-POS: database engine disposed", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: engine dispose error: {e}", file=sys.stderr, flush=True)
    print("BMM-POS: shutdown complete", file=sys.stderr, flush=True)


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
    # Only allow localhost in explicit dev mode to prevent CORS abuse in production.
    if os.environ.get("BMM_DEV_MODE") == "1" or os.environ.get("RAILWAY_ENVIRONMENT") != "production":
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

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)


_DEV_MODE = os.environ.get("BMM_DEV_MODE") == "1" or os.environ.get("RAILWAY_ENVIRONMENT") != "production"

@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if path.endswith(".html") or path == "/" or path.endswith("/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif (path.endswith(".css") or path.endswith(".js") or path.endswith(".webp") or
            path.endswith(".png") or path.endswith(".jpg") or path.endswith(".jpeg") or
            path.endswith(".gif") or path.endswith(".svg") or path.endswith(".woff") or
            path.endswith(".woff2") or path.endswith(".ttf") or path.endswith(".ico")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    """Enforce max request body size for non-upload endpoints."""
    if request.method in ("POST", "PUT", "PATCH"):
        path = request.url.path.lower()
        is_upload = any(seg in path for seg in ("/photo", "/image", "/upload", "/logo", "/video", "/import", "/bulk"))
        max_size = 50 * 1024 * 1024 if is_upload else 1 * 1024 * 1024  # 50MB uploads, 1MB JSON
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_size:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large (max {max_size // 1024 // 1024}MB)"},
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Referrer policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Strict Transport Security — Railway always serves HTTPS
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    # Permissions Policy — restrict sensitive APIs
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), "
        "payment=(self), fullscreen=(self)"
    )
    # Content Security Policy
    # Note: 'unsafe-inline' is needed for Square SDK and inline styles.
    # Future improvement: generate nonce values per-request and tag all inline scripts/styles.
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://js.squareup.com https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https://bowenstreet-media.nyc3.digitaloceanspaces.com https://*.digitaloceanspaces.com https://*.squarecdn.com; "
        "connect-src 'self' https://*.squareup.com https://api.openrouter.ai https://*.digitaloceanspaces.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "upgrade-insecure-requests;"
    )
    response.headers["Content-Security-Policy"] = csp
    return response


@app.middleware("http")
async def subdomain_landing_redirect(request: Request, call_next):
    """Route *.bowenstreetmarket.com subdomains to /{slug}."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    for domain in ("bowenstreetmarket.com", "www.bowenstreetmarket.com"):
        if host == domain or host == f"www.{domain}":
            break
    else:
        slug = host.split(".")[0]
        if slug and slug not in ("www", "api", "admin", "pos", "shop", "vendor"):
            if request.url.path in ("/", ""):
                from starlette.datastructures import URL
                scope = request.scope.copy()
                new_path = f"/{slug}"
                scope["path"] = new_path
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode()
                request = Request(scope, request.receive)
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from app.database import AsyncSessionLocal
    from app.services.error_logger import log_error

    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        # 4xx client errors — don't log, just return
        if exc.status_code < 500:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        # 5xx server errors — log to DB
        try:
            async with AsyncSessionLocal() as session:
                await log_error(
                    db=session,
                    exc=exc,
                    source="api",
                    request=request,
                    level="error",
                )
        except Exception:
            pass
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    # Unhandled exceptions — log to DB
    try:
        async with AsyncSessionLocal() as session:
            await log_error(
                db=session,
                exc=exc,
                source="api",
                request=request,
                level="critical",
            )
    except Exception:
        pass

    print(f"BMM-POS EXCEPTION on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    """Railway health check — returns 200 as long as the app is running."""
    payload = _startup_health_payload()
    # Railway needs 200 even if some startup tasks had warnings
    status_code = 200 if payload["status"] in ("ok", "degraded") else 503
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/health/db")
async def health_db():
    """Deep health check — verifies database connectivity."""
    try:
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable", "detail": str(e)},
        )


@app.get("/health/circuit-breakers")
async def health_circuit_breakers():
    """Check circuit breaker status for external services."""
    from app.services.circuit_breaker import get_breaker_status
    return {"status": "ok", "circuit_breakers": get_breaker_status()}


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
app.include_router(diagnose_router, prefix="/api/v1")
app.include_router(errors.router, prefix="/api/v1")

app.include_router(accounting_router, prefix="")

app.include_router(square_webhook.router, prefix="/api/v1")

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
    """Dynamic sitemap: market home, /vendors hub, every published vendor
    landing page, and every specialty category page. Includes <lastmod>
    from BoothShowcase.updated_at when available.
    """
    import re as _sm_re
    from datetime import datetime, timezone as _tz
    from app.database import get_db as _get_db
    from app.models.booth_showcase import BoothShowcase

    BASE = "https://www.bowenstreetmarket.com"

    def _slug(s: str) -> str:
        s = _sm_re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
        return _sm_re.sub(r"[-\s]+", "-", s) or "misc"

    urls: list[tuple[str, str | None, str, str]] = []
    # (loc, lastmod, changefreq, priority)

    today = datetime.now(_tz.utc).date().isoformat()

    urls.append((f"{BASE}/", today, "daily", "1.0"))
    urls.append((f"{BASE}/shop/index.html", today, "daily", "0.9"))
    urls.append((f"{BASE}/shop/booths.html", today, "weekly", "0.8"))
    urls.append((f"{BASE}/vendors", today, "weekly", "0.8"))

    try:
        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(BoothShowcase.is_published == True)
            )
            showcases = result.scalars().all()

            specialty_latest: dict = {}  # slug -> (display_name, latest_updated_at)

            for sc in showcases:
                lastmod = sc.updated_at.date().isoformat() if sc.updated_at else today

                if (sc.landing_page_enabled != False) and sc.landing_slug:
                    urls.append((f"{BASE}/{sc.landing_slug}", lastmod, "weekly", "0.7"))

                    for spec in (sc.landing_specialties or []):
                        # If landing_page_enabled is not explicitly set, assume True for backward compat
                        enabled = sc.landing_page_enabled if sc.landing_page_enabled is not None else True
                        if not enabled:
                            continue
                        name = str(spec or "").strip()
                        if not name:
                            continue
                        slug = _slug(name)
                        prev = specialty_latest.get(slug)
                        if prev is None or (sc.updated_at and (prev[1] is None or sc.updated_at > prev[1])):
                            specialty_latest[slug] = (name[:60], sc.updated_at)

            for slug, (_name, updated) in specialty_latest.items():
                lastmod = updated.date().isoformat() if updated else today
                urls.append((f"{BASE}/specialty/{slug}", lastmod, "weekly", "0.6"))
            break
    except Exception as exc:
        logging.getLogger(__name__).warning("sitemap generation fell back: %s", exc)

    # Deduplicate by loc (preserving first occurrence / priority)
    seen = set()
    unique = []
    for u in urls:
        if u[0] in seen:
            continue
        seen.add(u[0])
        unique.append(u)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, cf, pr in unique:
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append(f"    <changefreq>{cf}</changefreq>")
        parts.append(f"    <priority>{pr}</priority>")
        parts.append("  </url>")
    parts.append('</urlset>')

    return Response(content="\n".join(parts), media_type="application/xml")


def _mix_hex(fg: str, bg: str, opacity: float) -> str:
    """Mix two hex colors, returning a hex string."""
    try:
        fg = fg.lstrip("#")
        bg = bg.lstrip("#")
        if len(fg) == 3:
            fg = fg[0] * 2 + fg[1] * 2 + fg[2] * 2
        if len(bg) == 3:
            bg = bg[0] * 2 + bg[1] * 2 + bg[2] * 2
        fn, bn = int(fg, 16), int(bg, 16)
        r = round(((fn >> 16) & 255) * opacity + ((bn >> 16) & 255) * (1 - opacity))
        g = round(((fn >> 8) & 255) * opacity + ((bn >> 8) & 255) * (1 - opacity))
        b = round((fn & 255) * opacity + (bn & 255) * (1 - opacity))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return fg


# ── Phase 3: SEO hub + specialty category pages ──────────────────────
@app.get("/vendors", response_class=HTMLResponse)
async def vendors_hub_page(request: Request):
    """Server-rendered A–Z vendor directory with JSON-LD CollectionPage/ItemList.
    Client JS fetches /api/v1/booth-showcase/public + /api/v1/storefront/specialties
    and renders the full filterable grid. Server renders meta + JSON-LD for SEO.
    """
    from html import escape as _html_esc
    page = Path("frontend/shop/vendors.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    html = page.read_text(encoding="utf-8")

    page_url = "https://www.bowenstreetmarket.com/vendors"
    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(BoothShowcase.is_published == True)
                .where(BoothShowcase.landing_page_enabled != False)
            )
            showcases = result.scalars().all()
            vendor_count = len(showcases)

            list_items = []
            for idx, sc in enumerate(showcases[:50], start=1):
                if not sc.vendor or not sc.landing_slug:
                    continue
                list_items.append({
                    "@type": "ListItem",
                    "position": idx,
                    "url": f"https://www.bowenstreetmarket.com/{sc.landing_slug}",
                    "name": sc.vendor.name,
                })

            ld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "CollectionPage",
                        "@id": f"{page_url}#page",
                        "url": page_url,
                        "name": "All Vendors — Bowenstreet Market",
                        "description": f"Browse all {vendor_count} vendors at Bowenstreet Market in Oshkosh, WI.",
                        "isPartOf": {"@type": "WebSite", "name": "Bowenstreet Market", "url": "https://www.bowenstreetmarket.com"},
                    },
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                            {"@type": "ListItem", "position": 2, "name": "Vendors", "item": page_url},
                        ],
                    },
                    {
                        "@type": "ItemList",
                        "name": "All Vendors",
                        "numberOfItems": vendor_count,
                        "itemListElement": list_items,
                    },
                ],
            }
            jsonld_esc = _html_esc(json.dumps(ld, ensure_ascii=False), quote=False)
            html = html.replace(
                '<script type="application/ld+json" id="hub-jsonld"></script>',
                f'<script type="application/ld+json" id="hub-jsonld">{jsonld_esc}</script>',
            )
            html = html.replace(
                '<!--VENDOR_COUNT-->',
                _html_esc(str(vendor_count)),
            )
            break
    except Exception as exc:
        logging.getLogger(__name__).warning("/vendors server-render fell back: %s", exc)

    return HTMLResponse(html)


@app.get("/specialty/{slug}", response_class=HTMLResponse)
async def specialty_page(slug: str, request: Request):
    """Server-rendered specialty category page (e.g. /specialty/vintage-books).
    DEBUG: if you see THIS docstring on /specialty/*, Railway is running the latest code.
    Validates the slug against published showcases; 404 otherwise. Injects
    title, canonical, OG, and JSON-LD ItemList. Client JS does fetch-to-render.
    """
    import re as _sp_re
    from html import escape as _html_esc

    if "." in slug or "/" in slug or not _sp_re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        raise HTTPException(status_code=404)

    page = Path("frontend/shop/specialty.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    html = page.read_text(encoding="utf-8")

    def _slug(s: str) -> str:
        s = _sp_re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
        return _sp_re.sub(r"[-\s]+", "-", s) or "misc"

    _not_found = False
    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(BoothShowcase.is_published == True)
                .where(BoothShowcase.landing_page_enabled != False)
            )
            all_showcases = result.scalars().all()

            matching = []
            display_name = None
            for sc in all_showcases:
                for spec in (sc.landing_specialties or []):
                    spec_slug = _slug(spec)
                    if spec_slug == slug:
                        matching.append(sc)
                        if display_name is None:
                            display_name = str(spec or "").strip()
                        break

            if not matching:
                _not_found = True
                break

            page_url = f"https://www.bowenstreetmarket.com/specialty/{slug}"
            title = f"{display_name} Vendors — Bowenstreet Market"
            desc = (
                f"Browse {len(matching)} vendors specializing in {display_name.lower()} "
                f"at Bowenstreet Market in Oshkosh, WI. See their booths, stories, and inventory."
            )
            if len(desc) > 160:
                desc = desc[:157] + "…"

            list_items = []
            for idx, sc in enumerate(matching[:50], start=1):
                if not sc.vendor or not sc.landing_slug:
                    continue
                list_items.append({
                    "@type": "ListItem",
                    "position": idx,
                    "url": f"https://www.bowenstreetmarket.com/{sc.landing_slug}",
                    "name": sc.vendor.name,
                })

            ld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "CollectionPage",
                        "@id": f"{page_url}#page",
                        "url": page_url,
                        "name": title,
                        "description": desc,
                        "isPartOf": {"@type": "WebSite", "name": "Bowenstreet Market", "url": "https://www.bowenstreetmarket.com"},
                    },
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                            {"@type": "ListItem", "position": 2, "name": "Vendors", "item": "https://www.bowenstreetmarket.com/vendors"},
                            {"@type": "ListItem", "position": 3, "name": display_name, "item": page_url},
                        ],
                    },
                    {
                        "@type": "ItemList",
                        "name": f"Vendors — {display_name}",
                        "numberOfItems": len(matching),
                        "itemListElement": list_items,
                    },
                ],
            }

            title_esc = _html_esc(title, quote=True)
            desc_esc = _html_esc(desc, quote=True)
            name_esc = _html_esc(display_name, quote=False)
            slug_esc = _html_esc(slug, quote=True)
            jsonld_esc = _html_esc(json.dumps(ld, ensure_ascii=False), quote=False)

            html = html.replace('<!--SPECIALTY_TITLE-->', title_esc)
            html = html.replace('<!--SPECIALTY_DESC-->', desc_esc)
            html = html.replace('<!--SPECIALTY_NAME-->', name_esc)
            html = html.replace('<!--SPECIALTY_SLUG-->', slug_esc)
            html = html.replace('<!--SPECIALTY_URL-->', page_url)
            html = html.replace(
                '<script type="application/ld+json" id="specialty-jsonld"></script>',
                f'<script type="application/ld+json" id="specialty-jsonld">{jsonld_esc}</script>',
            )
            break  # only need one db session
    except Exception as exc:
        logging.getLogger(__name__).warning("/specialty/%s server-render failed: %s", slug, exc)

    if _not_found:
        raise HTTPException(status_code=404, detail="Specialty not found")

    return HTMLResponse(html)


@app.get("/og/{filename}")
async def og_image_root(filename: str):
    """Serve OG image at /og/{slug}.png by delegating to the booth-showcase
    router. This lets the vendor landing page reference a clean,
    top-level og:image URL.
    """
    from fastapi import HTTPException as _HTTPException
    if not filename.endswith(".png") and not filename.endswith(".jpg"):
        raise _HTTPException(status_code=404)
    slug = filename.rsplit(".", 1)[0]
    if not slug:
        raise _HTTPException(status_code=404)
    from app.database import get_db as _get_db
    from app.routers.booth_showcase import get_og_image as _get_og_image
    async for db in _get_db():
        return await _get_og_image(slug=slug, db=db)
    raise _HTTPException(status_code=500)


@app.get("/{slug}")
async def vendor_landing_page(slug: str, request: Request):
    # Root-level vendor landing pages: bowenstreetmarket.com/{vendor-name}
    # Only match simple slugs — no dots, no slashes, not a known directory
    if "." in slug or "/" in slug:
        raise HTTPException(status_code=404)
    _reserved = ("shop", "admin", "pos", "vendor", "vendors", "specialty",
                 "static", "api", "health", "favicon", "manifest", "robots",
                 "llms", "sitemaps", "sitemap", "docs", "og")
    if slug in _reserved:
        raise HTTPException(status_code=404)
    page = Path("frontend/shop/vendor-page.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)

    html = page.read_text(encoding="utf-8")

    debug_mode = request.query_params.get("debug") == "1"

    # ── Server-side theme pre-render ──
    # Fetch showcase + vendor in one shot to avoid extra queries
    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        from html import escape as _html_esc

        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(
                    BoothShowcase.landing_slug == slug,
                    BoothShowcase.landing_page_enabled != False,
                )
            )
            sc = result.scalar_one_or_none()

            if debug_mode:
                debug_payload = {
                    "slug": slug,
                    "record_found": bool(sc),
                    "landing_page_enabled": bool(sc.landing_page_enabled) if sc else False,
                    "landing_template": (sc.landing_template or "classic") if sc else None,
                    "landing_theme": sc.landing_theme if sc else None,
                    "updated_at": sc.updated_at.isoformat() if (sc and sc.updated_at) else None,
                }
                debug_json = _html_esc(json.dumps(debug_payload, indent=2), quote=False)
                html = html.replace(
                    '<div id="admin-debug-banner" class="admin-debug-banner" aria-live="polite"></div>',
                    '<div id="admin-debug-banner" class="admin-debug-banner" aria-live="polite" style="display:block">'
                    '<div class="debug-title">Debug Query: server-side landing payload snapshot</div>'
                    f'<div>Source: <code>/api/v1/booth-showcase/landing/{_html_esc(slug)}</code></div>'
                    f'<div class="debug-values"><code>{debug_json}</code></div>'
                    '</div>',
                )

            template = sc.landing_template or "classic"

            # 1. Always swap template CSS link (even without a saved theme)
            html = html.replace(
                'href="/static/css/landing-classic.css"',
                f'href="/static/css/landing-{template}.css"',
            )

            if sc:
                theme = sc.landing_theme
                if theme:
                    c = theme.get("colors", {})
                    f = theme.get("fonts", {})
                    text_c = c.get("text", "#111827")
                    bg_c = c.get("background", "#F9FAFB")
                    primary = c.get("primary", "#2563EB")
                    secondary = c.get("secondary", "#64748B")
                    card_bg = c.get("card_background", "#FFFFFF")
                    accent = c.get("accent", primary)

                    border_c = _mix_hex(text_c, bg_c, 0.15)

                    # New theme properties
                    spacing = theme.get("spacing", {})
                    cards = theme.get("cards", {})
                    body_size = f.get("body_size", "16")
                    heading_weight = f.get("heading_weight", "600")
                    heading_letter_spacing = theme.get("fonts", {}).get("heading_letter_spacing", "0")
                    
                    section_padding = {"compact": "1.5", "comfortable": "2.5", "spacious": "4"}.get(
                        spacing.get("section_padding", "comfortable"), "2.5"
                    )
                    content_width = {"narrow": "800", "medium": "1000", "wide": "1200"}.get(
                        spacing.get("content_width", "medium"), "1000"
                    )
                    border_radius = spacing.get("border_radius", "0")
                    card_image_ratio = cards.get("image_ratio", "3/4")
                    grid_density = cards.get("grid_density", "comfortable")
                    grid_min_width = {"compact": "160px", "comfortable": "200px", "spacious": "280px"}.get(
                        grid_density, "200px"
                    )
                    
                    css_vars = (
                        f"--landing-primary: {primary};"
                        f"--landing-secondary: {secondary};"
                        f"--landing-background: {bg_c};"
                        f"--landing-text: {text_c};"
                        f"--landing-accent: {accent};"
                        f"--landing-card-bg: {card_bg};"
                        f"--landing-bg-dark: {bg_c};"
                        f"--landing-border: {border_c};"
                        f"--landing-heading-font: '{f.get('heading', 'Inter')}', serif;"
                        f"--landing-heading-weight: {heading_weight};"
                        f"--landing-heading-style: {f.get('heading_style', 'normal')};"
                        f"--landing-heading-letter-spacing: {heading_letter_spacing}em;"
                        f"--landing-body-font: '{f.get('body', 'Inter')}', sans-serif;"
                        f"--landing-body-weight: {f.get('body_weight', '400')};"
                        f"--landing-body-size: {body_size};"
                        f"--landing-section-padding: {section_padding};"
                        f"--landing-content-width: {content_width};"
                        f"--landing-border-radius: {border_radius};"
                        f"--landing-card-image-ratio: {card_image_ratio};"
                        f"--landing-grid-min-width: {grid_min_width};"
                    )

                    critical_css = ""
                    try:
                        css_path = Path(f"frontend/static/css/landing-{template}.css")
                        if css_path.exists():
                            raw_css = css_path.read_text(encoding="utf-8")
                            critical_lines = []
                            in_block = False
                            brace_depth = 0
                            for line in raw_css.split("\n"):
                                stripped = line.strip()
                                if any(kw in stripped for kw in [".landing-nav", ".landing-hero", ".landing-about", "body.themed", "@keyframes landing-fade"]):
                                    in_block = True
                                if in_block:
                                    critical_lines.append(line)
                                    brace_depth += stripped.count("{") - stripped.count("}")
                                    if brace_depth <= 0 and "{" in "".join(critical_lines):
                                        in_block = False
                                        brace_depth = 0
                            critical_css = "\n".join(critical_lines)
                    except Exception:
                        pass

                    html = html.replace('class="no-theme"', 'class="themed"')

                    html = html.replace(
                        '<style id="theme-vars"></style>',
                        f'<style id="theme-vars">:root {{ {css_vars} }}'
                        'body.themed { background-image: none !important; background-attachment: scroll !important; }'
                        'body.themed *:not(.hero-bg):not(.hero-photo):not(.hero-tile):not(.hero-slide):not(.hero-portrait):not(.landing-hero-bg) { background-image: none !important; background-attachment: scroll !important; }'
                        f'{critical_css}'
                        '</style>',
                    )

                    html = html.replace(
                        '<body class="themed">',
                        f'<body class="themed" data-ssr-theme="true" style="background:{bg_c};color:{text_c}">',
                    )

            # 5. Pre-render SEO meta tags (always, even without a saved theme)
            vendor_name = sc.vendor.name if sc and sc.vendor else "Vendor"
            title = (sc.landing_meta_title or f"{vendor_name} — Bowenstreet Market") if sc else "Vendor — Bowenstreet Market"

            fallback_desc = None
            if sc:
                story_blocks = sc.landing_story_blocks or {}
                if isinstance(story_blocks, dict):
                    for _key in ("specialty", "origin", "process", "values", "whats_new"):
                        _val = (story_blocks.get(_key) or "").strip()
                        if _val:
                            _clean = " ".join(_val.split())
                            fallback_desc = _clean[:157] + "…" if len(_clean) > 160 else _clean
                            break
                if not fallback_desc and (sc.landing_about or "").strip():
                    _clean = " ".join(sc.landing_about.split())
                    fallback_desc = _clean[:157] + "…" if len(_clean) > 160 else _clean
            desc = (
                (sc.landing_meta_desc or fallback_desc or f"Shop {vendor_name} at Bowenstreet Market in Oshkosh, WI.")
                if sc
                else "Shop at Bowenstreet Market in Oshkosh, WI."
            )
            photos = (sc.photo_urls or []) if sc else []

            title_esc = _html_esc(title, quote=True)
            desc_esc = _html_esc(desc, quote=True)

            html = html.replace(
                '<title id="page-title">Vendor — Bowenstreet Market</title>',
                f'<title id="page-title">{title_esc}</title>',
            )
            html = html.replace(
                'name="description" content="Visit this vendor\'s booth at Bowenstreet Market — handcrafted, vintage, and antique goods in Oshkosh, Wisconsin."',
                f'name="description" content="{desc_esc}"',
            )
            html = html.replace(
                'property="og:title" content="Vendor — Bowenstreet Market"',
                f'property="og:title" content="{title_esc}"',
            )
            html = html.replace(
                'property="og:description" content="Visit this vendor\'s booth at Bowenstreet Market."',
                f'property="og:description" content="{desc_esc}"',
            )
            html = html.replace(
                'property="og:url" content=""',
                f'property="og:url" content="https://www.bowenstreetmarket.com/{slug}"',
            )
            og_image_url = f"https://www.bowenstreetmarket.com/og/{slug}.png"
            html = html.replace(
                'property="og:image" content=""',
                f'property="og:image" content="{og_image_url}"',
            )
            if 'name="twitter:image"' not in html:
                html = html.replace(
                    f'property="og:image" content="{og_image_url}"',
                    f'property="og:image" content="{og_image_url}">\n    <meta name="twitter:image" content="{og_image_url}"',
                )
            html = html.replace(
                '<link rel="canonical" href="">',
                f'<link rel="canonical" href="https://www.bowenstreetmarket.com/{slug}">',
            )

            # ── JSON-LD (LocalBusiness + FAQPage + BreadcrumbList) ──
            try:
                page_url = f"https://www.bowenstreetmarket.com/{slug}"
                specialties = list(sc.landing_specialties or []) if sc else []
                ld_nodes = []

                # Phase 3.1: derive priceRange from vendor items
                price_range = None
                try:
                    if sc and sc.vendor_id:
                        from app.models.item import Item
                        price_rows = await db.execute(
                            select(
                                func.min(Item.price).label("min_p"),
                                func.max(Item.price).label("max_p"),
                            ).where(
                                Item.vendor_id == sc.vendor_id,
                                Item.status == "active",
                                Item.price > 0,
                            )
                        )
                        row = price_rows.one_or_none()
                        if row and row.min_p is not None and row.max_p is not None:
                            mn = float(row.min_p)
                            mx = float(row.max_p)
                            if abs(mx - mn) < 0.01:
                                price_range = f"${mn:.0f}"
                            else:
                                price_range = f"${mn:.0f}\u2013${mx:.0f}"
                except Exception:
                    logger.exception("vendor_landing_page: priceRange derivation failed")
                    price_range = None

                business_node = {
                    "@context": "https://schema.org",
                    "@type": "LocalBusiness",
                    "@id": f"{page_url}#vendor",
                    "name": vendor_name,
                    "url": page_url,
                    "description": desc,
                    "parentOrganization": {
                        "@type": "Organization",
                        "name": "Bowenstreet Market",
                        "url": "https://www.bowenstreetmarket.com",
                    },
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "2837 Bowen St",
                        "addressLocality": "Oshkosh",
                        "addressRegion": "WI",
                        "postalCode": "54901",
                        "addressCountry": "US",
                    },
                }
                if price_range:
                    business_node["priceRange"] = price_range

                # Phase 3.1: derive openingHoursSpecification from hours_* settings
                # Falls back to store_hours_json if present, but primarily reads
                # the per-day settings already editable in admin Settings UI.
                try:
                    from app.models.store_setting import StoreSetting
                    import re as _hrs_re

                    def _parse_hours_str(val: str):
                        """Parse '10:00 AM - 6:00 PM' into ('10:00', '18:00').
                        Returns None if closed or unparseable."""
                        if not val or val.strip().lower() in ("closed", ""):
                            return None
                        # Match patterns like "10:00 AM - 6:00 PM" or "10AM-6PM"
                        m = _hrs_re.match(
                            r'(\d{1,2}):?(\d{2})?\s*(AM|PM)?\s*[-–to]+\s*(\d{1,2}):?(\d{2})?\s*(AM|PM)?',
                            val.strip(), _hrs_re.IGNORECASE
                        )
                        if not m:
                            return None
                        def _to24(h, mins, ampm):
                            h = int(h)
                            mins = int(mins) if mins else 0
                            if ampm:
                                ampm = ampm.upper()
                                if ampm == 'PM' and h != 12:
                                    h += 12
                                elif ampm == 'AM' and h == 12:
                                    h = 0
                            return f"{h:02d}:{mins:02d}"
                        opens = _to24(m.group(1), m.group(2), m.group(3))
                        closes = _to24(m.group(4), m.group(5), m.group(6))
                        return (opens, closes)

                    _day_keys = [
                        ("Monday", "hours_monday"),
                        ("Tuesday", "hours_tuesday"),
                        ("Wednesday", "hours_wednesday"),
                        ("Thursday", "hours_thursday"),
                        ("Friday", "hours_friday"),
                        ("Saturday", "hours_saturday"),
                        ("Sunday", "hours_sunday"),
                    ]
                    hrs_rows = await db.execute(
                        select(StoreSetting).where(
                            StoreSetting.key.in_([k for _, k in _day_keys])
                        )
                    )
                    hrs_map = {r.key: r.value for r in hrs_rows.scalars().all()}

                    # Group days with identical hours to produce compact specs
                    hours_groups: dict[tuple, list] = {}
                    for day_name, db_key in _day_keys:
                        val = hrs_map.get(db_key, "")
                        parsed = _parse_hours_str(val)
                        if parsed:
                            hours_groups.setdefault(parsed, []).append(day_name)

                    if hours_groups:
                        specs = []
                        for (opens, closes), days in hours_groups.items():
                            specs.append({
                                "@type": "OpeningHoursSpecification",
                                "dayOfWeek": days,
                                "opens": opens,
                                "closes": closes,
                            })
                        business_node["openingHoursSpecification"] = specs
                    else:
                        # Fallback: check store_hours_json if per-day settings are all empty/closed
                        hrs_json_row = await db.execute(
                            select(StoreSetting).where(StoreSetting.key == "store_hours_json")
                        )
                        hrs_setting = hrs_json_row.scalar_one_or_none()
                        if hrs_setting and hrs_setting.value:
                            parsed_json = json.loads(hrs_setting.value)
                            if isinstance(parsed_json, list) and parsed_json:
                                specs = []
                                for entry in parsed_json:
                                    if not isinstance(entry, dict):
                                        continue
                                    days = entry.get("days") or []
                                    opens = (entry.get("opens") or "").strip()
                                    closes = (entry.get("closes") or "").strip()
                                    if not days or not opens or not closes:
                                        continue
                                    specs.append({
                                        "@type": "OpeningHoursSpecification",
                                        "dayOfWeek": days if isinstance(days, list) else [days],
                                        "opens": opens,
                                        "closes": closes,
                                    })
                                if specs:
                                    business_node["openingHoursSpecification"] = specs
                except Exception:
                    logger.exception("vendor_landing_page: openingHours injection failed")

                ld_nodes.append(business_node)

                ld_nodes.append({
                    "@context": "https://schema.org",
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                        {"@type": "ListItem", "position": 2, "name": "Vendors", "item": f"{page_url}#vendors"},
                        {"@type": "ListItem", "position": 3, "name": vendor_name, "item": page_url},
                    ],
                })

                if sc and sc.landing_faq:
                    try:
                        faq_data = json.loads(sc.landing_faq) if isinstance(sc.landing_faq, str) else sc.landing_faq
                        faq_entities = []
                        for item in (faq_data if isinstance(faq_data, list) else []):
                            q = item.get("question", "").strip()
                            a = item.get("answer", "").strip()
                            if q and a:
                                faq_entities.append({
                                    "@type": "Question",
                                    "name": q,
                                    "acceptedAnswer": {"@type": "Answer", "text": a},
                                })
                            if len(faq_entities) >= 20:
                                break
                        if faq_entities:
                            ld_nodes.append({
                                "@context": "https://schema.org",
                                "@type": "FAQPage",
                                "mainEntity": faq_entities[:20],
                            })
                    except Exception:
                        pass

                ld_script = "\n".join(
                    f'<script type="application/ld+json">{json.dumps(n, ensure_ascii=False)}</script>'
                    for n in ld_nodes
                )
                html = html.replace("</head>", ld_script + "\n</head>", 1)
            except Exception:
                logger.exception("vendor_landing_page: JSON-LD injection failed")

            break  # only need one db session
    except Exception:
        logger.exception("vendor_landing_page: pre-render failed, serving unmodified")

    return HTMLResponse(
        html,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/shop/vendor/{vendor_id:int}")
async def vendor_inventory_page(vendor_id: int):
    page = Path("frontend/shop/vendor-inventory.html")
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
