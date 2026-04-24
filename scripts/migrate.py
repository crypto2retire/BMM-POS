"""
BMM-POS database migration script.

Runs all schema additions and one-time data fixes that previously ran on
every app startup inside main.py's lifespan block.  Railway executes this
as a pre-deploy command so the app container starts clean and fast.

Usage:
    python scripts/migrate.py

Railway railway.toml:
    [deploy]
    preDeployCommand = "python scripts/migrate.py"

Safe to run multiple times — every DDL statement uses IF NOT EXISTS / IF EXISTS,
and every data fix is gated by a store_settings marker so it only runs once.
"""

import asyncio
import os
import sys
import uuid
from typing import Optional

# Allow running from repo root: python scripts/migrate.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, select, or_
from app.database import AsyncSessionLocal, engine, Base
from app.models.item import Item
from app.models.item_image import ItemImage
from app.services import spaces as spaces_svc


# ─────────────────────────────────────────────────────────────────────────────
# Marker helpers (same logic as main.py, duplicated here to keep script self-
# contained so it works even if main.py changes)
# ─────────────────────────────────────────────────────────────────────────────

async def _has_marker(session, key: str) -> bool:
    result = await session.execute(
        text("SELECT value FROM store_settings WHERE key = :key"),
        {"key": key},
    )
    return bool(result.scalar_one_or_none())


async def _set_marker(session, key: str, description: str) -> None:
    await session.execute(
        text("""
            INSERT INTO store_settings (key, value, description)
            VALUES (:key, 'done', :description)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                description = EXCLUDED.description
        """),
        {"key": key, "description": description},
    )


async def _missing_columns(session, table_name: str, required: list[str]) -> list[str]:
    result = await session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :tbl
            """
        ),
        {"tbl": table_name},
    )
    existing = {row[0] for row in result}
    return [col for col in required if col not in existing]


def _ext_for_content_type(content_type: Optional[str]) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return mapping.get((content_type or "").lower(), "jpg")


def _is_legacy_item_path(url: Optional[str]) -> bool:
    if not url:
        return True
    return url.startswith("/api/v1/items/") or url.startswith("/static/uploads/items/")


def _is_public_image_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return (
        url.startswith("http://")
        or url.startswith("https://")
        or url.startswith("/api/v1/items/")
        or url.startswith("/static/")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main migration
# ─────────────────────────────────────────────────────────────────────────────

# Advisory-lock key: a fixed 64-bit int. Only one DB session can hold this
# lock at a time. If two Railway containers try to migrate concurrently
# (blue/green overlap), the second one waits for the first to finish instead
# of racing ALTER TABLEs and deadlocking. Any stable constant is fine.
_MIGRATION_LOCK_KEY = 837412059621  # arbitrary; chosen once, never change.


async def run():
    print("BMM-POS migrate: starting", flush=True)

    # ── Step 0: acquire an advisory lock so only one migrator runs at a time
    # Hold the lock on a dedicated connection for the entire migration; release
    # on exit. pg_advisory_lock is session-scoped so a crash auto-releases it.
    import app.models  # noqa: F401 — registers all models with Base.metadata

    # Railway's internal DNS occasionally returns "Temporary failure in name
    # resolution" for the first connection attempt during pre-deploy. Retry
    # with backoff instead of failing the whole deploy.
    import socket
    lock_conn = None
    last_err: Optional[BaseException] = None
    for attempt in range(1, 7):  # ~1+2+4+8+16+32 = 63s max
        try:
            lock_conn = await engine.connect()
            break
        except (socket.gaierror, OSError) as e:
            last_err = e
            delay = 2 ** (attempt - 1)
            print(
                f"BMM-POS migrate: DB connect attempt {attempt} failed ({e!r}); "
                f"retrying in {delay}s…",
                flush=True,
            )
            await asyncio.sleep(delay)
    if lock_conn is None:
        print(f"BMM-POS migrate: giving up after retries: {last_err!r}", flush=True)
        raise last_err  # type: ignore[misc]
    try:
        print(f"BMM-POS migrate: acquiring advisory lock {_MIGRATION_LOCK_KEY}…", flush=True)
        await lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATION_LOCK_KEY})
        print("BMM-POS migrate: advisory lock acquired", flush=True)

        # ── Step 1: create all tables that don't yet exist ──────────────────
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS migrate: schema create_all OK", flush=True)

        async with AsyncSessionLocal() as session:

            # ── Step 2: ALTER TABLE column additions ────────────────────────────
            column_alters_marker = "startup_task_column_alters_v6"
            column_alters = [
                # vendors
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS rent_flagged BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_vendor BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS commission_rate NUMERIC(5,4) NOT NULL DEFAULT 0.1000",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS label_preference VARCHAR(20) NOT NULL DEFAULT 'dymo'",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS pdf_label_size VARCHAR(30) NOT NULL DEFAULT '2.25x1.25'",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS assistant_name VARCHAR(50)",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS assistant_enabled BOOLEAN NOT NULL DEFAULT true",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS auto_payout_enabled BOOLEAN NOT NULL DEFAULT true",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS notes TEXT",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS theme_preference VARCHAR(10) NOT NULL DEFAULT 'dark'",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS font_size_preference VARCHAR(10) NOT NULL DEFAULT 'medium'",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS sale_notify_preference VARCHAR(10) NOT NULL DEFAULT 'instant'",
                # vendors — additional columns (previously only in lifespan)
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS consignment_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0000",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS security_deposit_amount NUMERIC(10,2) NOT NULL DEFAULT 0.00",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS security_deposit_balance NUMERIC(10,2) NOT NULL DEFAULT 0.00",
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS landing_page_fee NUMERIC(10,2) NOT NULL DEFAULT 0.00",
                # items
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS image_path VARCHAR(500)",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS is_consignment BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS consignment_rate NUMERIC(5,4)",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS label_printed BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS archive_expires_at TIMESTAMPTZ",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS import_source VARCHAR(50)",
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS reserved_quantity INTEGER NOT NULL DEFAULT 0",
                # sale_items
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS is_consignment BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS consignment_rate NUMERIC(5,4)",
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS consignment_amount NUMERIC(10,2)",
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS discount_type VARCHAR(10)",
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)",
                "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10,2)",
                # sales
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS is_voided BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS voided_by INTEGER REFERENCES vendors(id)",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS void_reason TEXT",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount_type VARCHAR(10)",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)",
                "ALTER TABLE sales ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10,2)",
                # reservations
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS customer_email VARCHAR(200)",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS public_id VARCHAR(36)",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS checkout_group_id VARCHAR(36)",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
                "CREATE INDEX IF NOT EXISTS ix_reservations_idempotency_key ON reservations(idempotency_key) WHERE idempotency_key IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS ix_reservations_expires_at ON reservations(expires_at) WHERE status = 'pending'",
                # rent_payments
                "ALTER TABLE rent_payments ADD COLUMN IF NOT EXISTS reference_tag VARCHAR(32)",
                "CREATE INDEX IF NOT EXISTS ix_rent_payments_reference_tag ON rent_payments(reference_tag) WHERE reference_tag IS NOT NULL",
                # class_registrations
                "ALTER TABLE class_registrations ADD COLUMN IF NOT EXISTS public_id VARCHAR(36)",
                "ALTER TABLE class_registrations ADD COLUMN IF NOT EXISTS square_payment_id VARCHAR(200)",
                "ALTER TABLE class_registrations ADD COLUMN IF NOT EXISTS pending_expires_at TIMESTAMPTZ",
                # vendor_balances
                "ALTER TABLE vendor_balances ADD COLUMN IF NOT EXISTS rent_balance NUMERIC(10,2) NOT NULL DEFAULT 0.00",
                # eod_reports
                "ALTER TABLE eod_reports ADD COLUMN IF NOT EXISTS denomination_counts JSONB",
                # booth_showcases landing page columns
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_page_enabled BOOLEAN DEFAULT FALSE",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_slug VARCHAR(100)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_about TEXT",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_contact_email VARCHAR(200)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_contact_phone VARCHAR(50)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_website VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_facebook VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_instagram VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_tiktok VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_twitter VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_etsy VARCHAR(300)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_meta_title VARCHAR(200)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_meta_desc VARCHAR(500)",
                # booth_showcases landing page personalization
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_template VARCHAR(50) NOT NULL DEFAULT 'classic'",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_theme JSONB",
                # ── Phase 1: hero variants + section deck + differentiation signals ──
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_hero_style VARCHAR(30) NOT NULL DEFAULT 'classic'",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_layout JSONB",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_specialties TEXT[]",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_era TEXT[]",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_materials TEXT[]",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_story_blocks JSONB",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_tagline VARCHAR(200)",
                "ALTER TABLE booth_showcases ADD COLUMN IF NOT EXISTS landing_year_started INTEGER",
            ]
            if not await _has_marker(session, column_alters_marker):
                missing = await _missing_columns(
                    session,
                    "booth_showcases",
                    ["landing_template", "landing_theme"],
                )
                if missing:
                    for sql in column_alters:
                        await session.execute(text(sql))
                    await _set_marker(
                        session,
                        column_alters_marker,
                        "Column alterations applied (v6)",
                    )
                    print(
                        f"BMM-POS migrate: {len(column_alters)} column alterations applied",
                        flush=True,
                    )
                else:
                    await _set_marker(
                        session,
                        column_alters_marker,
                        "Column alterations already present; skipped (v6)",
                    )
                    print(
                        "BMM-POS migrate: column alterations skipped (already applied)",
                        flush=True,
                    )
            else:
                print(
                    "BMM-POS migrate: column alterations already applied (marker present)",
                    flush=True,
                )

            # ── Step 2b: v7 column additions (post-v6 new columns) ─────────────
            v7_marker = "startup_task_column_alters_v7"
            v7_alters = [
                "ALTER TABLE items ADD COLUMN IF NOT EXISTS reserved_quantity INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
                "ALTER TABLE rent_payments ADD COLUMN IF NOT EXISTS reference_tag VARCHAR(32)",
            ]
            if not await _has_marker(session, v7_marker):
                for sql in v7_alters:
                    await session.execute(text(sql))
                await _set_marker(session, v7_marker, "Column alterations applied (v7)")
                print(f"BMM-POS migrate: {len(v7_alters)} v7 column alterations applied", flush=True)
            else:
                print("BMM-POS migrate: v7 column alterations already applied", flush=True)

            # ── Step 3: CREATE TABLE IF NOT EXISTS ─────────────────────────────
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
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER,
                    action VARCHAR(50) NOT NULL,
                    entity_type VARCHAR(50) NOT NULL,
                    entity_id VARCHAR(100),
                    details TEXT,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(500),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_audit_vendor ON audit_logs(vendor_id)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id SERIAL PRIMARY KEY,
                    level VARCHAR(20) NOT NULL DEFAULT 'error',
                    status VARCHAR(20) NOT NULL DEFAULT 'new',
                    source VARCHAR(50) NOT NULL,
                    endpoint VARCHAR(255),
                    method VARCHAR(10),
                    error_type VARCHAR(100) NOT NULL,
                    message TEXT NOT NULL,
                    stack_trace TEXT,
                    request_body TEXT,
                    user_id INTEGER,
                    user_email VARCHAR(200),
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(500),
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    acknowledged_by INTEGER REFERENCES vendors(id),
                    acknowledged_at TIMESTAMPTZ,
                    notes TEXT
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_status ON error_logs(status)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_level ON error_logs(level)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_source ON error_logs(source)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_type ON error_logs(error_type)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_occurred ON error_logs(occurred_at)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_error_logs_new ON error_logs(status, occurred_at) WHERE status = 'new'
            """))
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

            # ── Item variables and variants tables ────────────────────────────────
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS item_variables (
                    id SERIAL PRIMARY KEY,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    options TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_item_variables_item_id ON item_variables(item_id)
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS item_variants (
                    id SERIAL PRIMARY KEY,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    sku VARCHAR(100) UNIQUE,
                    barcode VARCHAR(100) UNIQUE,
                    variable_1_value VARCHAR(200),
                    variable_2_value VARCHAR(200),
                    price NUMERIC(10,2) NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    photo_url VARCHAR(500),
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_item_variant_values UNIQUE (item_id, variable_1_value, variable_2_value)
                )
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_item_variants_item_id ON item_variants(item_id)
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_item_variants_barcode ON item_variants(barcode) WHERE barcode IS NOT NULL
            """))
            print("BMM-POS migrate: item_variables + item_variants tables OK", flush=True)

            # ── Step 4: indexes ─────────────────────────────────────────────────
            # Ensure pg_trgm extension exists (needed for trigram indexes)
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

            index_statements = [
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id)",
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status)",
                "CREATE INDEX IF NOT EXISTS idx_eod_reports_date ON eod_reports(report_date)",
                # Storefront composite index (speeds up public shop queries)
                "CREATE INDEX IF NOT EXISTS idx_items_online_active ON items(status, is_online, quantity) WHERE status = 'active' AND is_online = true",
                # Search performance indexes
                "CREATE INDEX IF NOT EXISTS ix_items_name_trgm ON items USING gin (name gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_items_sku_trgm ON items USING gin (sku gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS ix_items_status ON items (status)",
                "CREATE INDEX IF NOT EXISTS ix_items_vendor_status ON items (vendor_id, status)",
                # Day 4 performance indexes (foreign keys + frequently filtered columns)
                "CREATE INDEX IF NOT EXISTS idx_items_status_online ON items(status, is_online)",
                "CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)",
                "CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_sales_created_voided ON sales(created_at, is_voided)",
                "CREATE INDEX IF NOT EXISTS idx_sales_cashier ON sales(cashier_id)",
                "CREATE INDEX IF NOT EXISTS idx_saleitems_sale ON sale_items(sale_id)",
                "CREATE INDEX IF NOT EXISTS idx_saleitems_item ON sale_items(item_id)",
                "CREATE INDEX IF NOT EXISTS idx_saleitems_vendor ON sale_items(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_rentpayments_vendor_period ON rent_payments(vendor_id, period_month)",
                "CREATE INDEX IF NOT EXISTS idx_rentpayments_status ON rent_payments(status)",
                "CREATE INDEX IF NOT EXISTS idx_payouts_vendor_period ON payouts(vendor_id, period_month)",
                "CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status)",
                "CREATE INDEX IF NOT EXISTS idx_vb_vendor ON vendor_balances(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_ba_vendor ON balance_adjustments(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_ba_admin ON balance_adjustments(adjusted_by)",
                "CREATE INDEX IF NOT EXISTS idx_vendors_status ON vendors(status)",
                "CREATE INDEX IF NOT EXISTS idx_vendors_role ON vendors(role)",
                "CREATE INDEX IF NOT EXISTS idx_vendors_booth ON vendors(booth_number)",
                "CREATE INDEX IF NOT EXISTS idx_reservations_item ON reservations(item_id)",
                "CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations(status)",
                # Unique constraint to prevent duplicate rent payments at DB level
                """DO $$ BEGIN
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_rent_payments_vendor_reference
                        ON rent_payments(vendor_id, reference_tag) WHERE status IN ('paid', 'received');
                EXCEPTION WHEN others THEN NULL; END $$""",
            ]
            # These two use DO blocks to swallow "already exists" errors safely
            index_statements_do = [
                """DO $$ BEGIN
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_reservations_public_id
                        ON reservations (public_id);
                EXCEPTION WHEN others THEN NULL; END $$""",
                """DO $$ BEGIN
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_class_registrations_public_id
                        ON class_registrations (public_id);
                EXCEPTION WHEN others THEN NULL; END $$""",
                """DO $$ BEGIN
                    CREATE INDEX IF NOT EXISTS ix_class_registrations_pending_expires_at
                        ON class_registrations (status, pending_expires_at);
                EXCEPTION WHEN others THEN NULL; END $$""",
                """DO $$ BEGIN
                    CREATE INDEX IF NOT EXISTS ix_reservations_checkout_group_id
                        ON reservations (checkout_group_id);
                EXCEPTION WHEN others THEN NULL; END $$""",
                """DO $$ BEGIN
                    CREATE UNIQUE INDEX IF NOT EXISTS ix_booth_showcases_landing_slug
                        ON booth_showcases (landing_slug) WHERE landing_slug IS NOT NULL;
                EXCEPTION WHEN others THEN NULL; END $$""",
            ]
            for sql in index_statements + index_statements_do:
                await session.execute(text(sql))
            print("BMM-POS migrate: indexes OK", flush=True)

            # ── Step 5: reservations public_id backfill + NOT NULL ──────────────
            rows = (await session.execute(
                text("SELECT id FROM reservations WHERE public_id IS NULL")
            )).fetchall()
            for row in rows:
                await session.execute(
                    text("UPDATE reservations SET public_id = :pid WHERE id = :rid"),
                    {"pid": str(uuid.uuid4()), "rid": row[0]},
                )
            if rows:
                print(f"BMM-POS migrate: backfilled public_id for {len(rows)} reservations", flush=True)
            await session.execute(text("""
                DO $$ BEGIN
                    ALTER TABLE reservations ALTER COLUMN public_id SET NOT NULL;
                EXCEPTION WHEN others THEN NULL; END $$
            """))

            class_rows = (await session.execute(
                text("SELECT id FROM class_registrations WHERE public_id IS NULL")
            )).fetchall()
            for row in class_rows:
                await session.execute(
                    text("UPDATE class_registrations SET public_id = :pid WHERE id = :rid"),
                    {"pid": str(uuid.uuid4()), "rid": row[0]},
                )
            if class_rows:
                print(f"BMM-POS migrate: backfilled class registration public_id for {len(class_rows)} rows", flush=True)
            await session.execute(text("""
                DO $$ BEGIN
                    ALTER TABLE class_registrations ALTER COLUMN public_id SET NOT NULL;
                EXCEPTION WHEN others THEN NULL; END $$
            """))

            # ── Step 6: one-time data fixes (marker-gated) ──────────────────────

            # 6a: Ricochet import_source backfill
            marker = "startup_task_import_source_backfill_v1"
            if not await _has_marker(session, marker):
                r = await session.execute(text(
                    "UPDATE items SET import_source = 'ricochet' "
                    "WHERE import_source IS NULL AND barcode IS NOT NULL"
                ))
                await _set_marker(session, marker, "One-time Ricochet import_source backfill")
                print(f"BMM-POS migrate: import_source backfill — {r.rowcount} items", flush=True)

            # 6b: Clear legacy consignment flags
            marker = "startup_task_consignment_cleanup_v1"
            if not await _has_marker(session, marker):
                r = await session.execute(text("""
                    UPDATE items
                    SET is_consignment = false, consignment_rate = NULL
                    WHERE is_consignment = true OR consignment_rate IS NOT NULL
                """))
                await _set_marker(session, marker, "One-time consignment flag cleanup")
                print(f"BMM-POS migrate: consignment cleanup — {r.rowcount} items", flush=True)

            # 6c: Default vendor payout_method to 'check'
            marker = "startup_task_vendor_payout_method_default_v1"
            if not await _has_marker(session, marker):
                r = await session.execute(text(
                    "UPDATE vendors SET payout_method = 'check' "
                    "WHERE payout_method IS NULL OR payout_method != 'check'"
                ))
                await _set_marker(session, marker, "One-time vendor payout_method default")
                print(f"BMM-POS migrate: payout_method default — {r.rowcount} vendors", flush=True)

            # 6d: Default untouched legacy label preferences to Dymo
            marker = "startup_task_default_label_preference_dymo_v1"
            if not await _has_marker(session, marker):
                await session.execute(text(
                    "ALTER TABLE vendors ALTER COLUMN label_preference SET DEFAULT 'dymo'"
                ))
                r = await session.execute(text("""
                    UPDATE vendors
                    SET label_preference = 'dymo'
                    WHERE COALESCE(label_preference, 'standard') = 'standard'
                      AND COALESCE(pdf_label_size, '2.25x1.25') = '2.25x1.25'
                """))
                await _set_marker(session, marker, "One-time default label preference set to Dymo")
                print(f"BMM-POS migrate: default label preference to dymo — {r.rowcount} vendors", flush=True)

            # 6d2: Move the live default Dymo stock from 30347 to 30336
            marker = "startup_task_default_dymo_size_30336_v1"
            if not await _has_marker(session, marker):
                await session.execute(text("""
                    UPDATE store_settings
                    SET value = '30336'
                    WHERE key = 'dymo_label_size'
                      AND COALESCE(value, '30347') = '30347'
                """))
                await _set_marker(session, marker, "One-time default dymo size changed to 30336")
                print("BMM-POS migrate: default dymo label size set to 30336", flush=True)

            # 6e: Migrate rent payments into rent_balance
            marker = "startup_task_rent_balance_migration_v1"
            if not await _has_marker(session, marker):
                r = await session.execute(text("""
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
                await _set_marker(session, marker, "One-time rent_balance migration")
                print(f"BMM-POS migrate: rent_balance migration — {r.rowcount} vendors", flush=True)

            # 6f: Move legacy item_images blobs to Spaces and rewrite image_path
            marker = "startup_task_item_images_to_spaces_v1"
            if not await _has_marker(session, marker):
                if not spaces_svc.spaces_enabled():
                    print("BMM-POS migrate: item_images->Spaces skipped — Spaces not configured", flush=True)
                else:
                    result = await session.execute(
                        select(Item, ItemImage)
                        .join(ItemImage, ItemImage.item_id == Item.id)
                        .where(
                            ItemImage.image_data.isnot(None),
                            or_(
                                Item.image_path.is_(None),
                                Item.image_path == "",
                                Item.image_path.like("/api/v1/items/%/image"),
                                Item.image_path.like("/static/uploads/items/%"),
                            ),
                        )
                    )
                    rows = result.all()
                    migrated = 0
                    failed = 0

                    for item, item_image in rows:
                        ext = _ext_for_content_type(item_image.content_type)
                        spaces_key = f"items/legacy/{item.id}.{ext}"
                        cdn_url = spaces_svc.upload_bytes(
                            item_image.image_data,
                            spaces_key,
                            item_image.content_type or "image/jpeg",
                        )
                        if not cdn_url:
                            failed += 1
                            continue

                        item.image_path = cdn_url
                        if not item.photo_urls or all(_is_legacy_item_path(url) for url in item.photo_urls):
                            item.photo_urls = [cdn_url]
                        migrated += 1

                    await _set_marker(session, marker, "One-time migration of item_images blobs to Spaces URLs")
                    print(
                        f"BMM-POS migrate: item_images to Spaces — migrated {migrated}, failed {failed}",
                        flush=True,
                    )

            # 6g: Rebuild booth showcase photos from surviving item images when booth uploads are gone
            marker = "startup_task_booth_showcase_photo_backfill_v1"
            if not await _has_marker(session, marker):
                from app.models.booth_showcase import BoothShowcase

                showcase_rows = (
                    await session.execute(
                        select(BoothShowcase).where(BoothShowcase.is_published == True)
                    )
                ).scalars().all()

                updated = 0
                skipped = 0
                for sc in showcase_rows:
                    current_urls = [url for url in (sc.photo_urls or []) if _is_public_image_url(url)]
                    if current_urls:
                        skipped += 1
                        continue

                    item_rows = (
                        await session.execute(
                            select(Item).where(
                                Item.vendor_id == sc.vendor_id,
                                Item.status == "active",
                            ).order_by(Item.created_at.desc()).limit(24)
                        )
                    ).scalars().all()

                    recovered_urls: list[str] = []
                    seen = set()
                    for item in item_rows:
                        candidates = []
                        if item.image_path:
                            candidates.append(item.image_path)
                        candidates.extend(item.photo_urls or [])
                        for candidate in candidates:
                            if not _is_public_image_url(candidate):
                                continue
                            if candidate in seen:
                                continue
                            seen.add(candidate)
                            recovered_urls.append(candidate)
                            if len(recovered_urls) >= 8:
                                break
                        if len(recovered_urls) >= 8:
                            break

                    if not recovered_urls:
                        skipped += 1
                        continue

                    sc.photo_urls = recovered_urls
                    if not sc.last_photo_update:
                        sc.last_photo_update = datetime.utcnow()
                    updated += 1

                await _set_marker(session, marker, "One-time booth showcase photo backfill from surviving vendor item images")
                print(
                    f"BMM-POS migrate: booth showcase photo backfill — updated {updated}, skipped {skipped}",
                    flush=True,
                )

            # ── Zero commission_rate for all vendors ──────────────────────
            marker = "startup_task_zero_commission_rate_v1"
            if not await _has_marker(session, marker):
                r = await session.execute(text(
                    "UPDATE vendors SET commission_rate = 0 WHERE commission_rate != 0"
                ))
                await _set_marker(session, marker, "Zero commission_rate for all vendors")
                print(f"BMM-POS migrate: zero commission_rate — {r.rowcount} vendors", flush=True)

            await session.commit()

        print("BMM-POS migrate: all migrations complete", flush=True)
    finally:
        # Release advisory lock + close the dedicated connection. If an
        # exception happened, the lock is released automatically when the
        # session closes, but calling pg_advisory_unlock is cheap and explicit.
        try:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATION_LOCK_KEY})
        except Exception:
            pass
        await lock_conn.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
