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

# Allow running from repo root: python scripts/migrate.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import AsyncSessionLocal, engine, Base


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


# ─────────────────────────────────────────────────────────────────────────────
# Main migration
# ─────────────────────────────────────────────────────────────────────────────

async def run():
    print("BMM-POS migrate: starting", flush=True)

    # ── Step 1: create all tables that don't yet exist ──────────────────────
    import app.models  # noqa: F401 — registers all models with Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("BMM-POS migrate: schema create_all OK", flush=True)

    async with AsyncSessionLocal() as session:

        # ── Step 2: ALTER TABLE column additions ────────────────────────────
        column_alters = [
            # vendors
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS rent_flagged BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true",
            "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS is_vendor BOOLEAN NOT NULL DEFAULT false",
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
            # items
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS image_path VARCHAR(500)",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS is_consignment BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS consignment_rate NUMERIC(5,4)",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS label_printed BOOLEAN NOT NULL DEFAULT false",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS archive_expires_at TIMESTAMPTZ",
            "ALTER TABLE items ADD COLUMN IF NOT EXISTS import_source VARCHAR(50)",
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
        ]
        for sql in column_alters:
            await session.execute(text(sql))
        print(f"BMM-POS migrate: {len(column_alters)} column alterations applied", flush=True)

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

        # ── Step 4: indexes ─────────────────────────────────────────────────
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id)",
            "CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status)",
            "CREATE INDEX IF NOT EXISTS idx_eod_reports_date ON eod_reports(report_date)",
            # Storefront composite index (speeds up public shop queries)
            "CREATE INDEX IF NOT EXISTS idx_items_online_active ON items(status, is_online, quantity) WHERE status = 'active' AND is_online = true",
        ]
        # These two use DO blocks to swallow "already exists" errors safely
        index_statements_do = [
            """DO $$ BEGIN
                CREATE UNIQUE INDEX IF NOT EXISTS ix_reservations_public_id
                    ON reservations (public_id);
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

        # 6d: Default untouched legacy label preferences to Dymo 30347
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
            await _set_marker(session, marker, "One-time default label preference set to Dymo 30347")
            print(f"BMM-POS migrate: default label preference to dymo — {r.rowcount} vendors", flush=True)

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

        await session.commit()

    print("BMM-POS migrate: all migrations complete", flush=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
