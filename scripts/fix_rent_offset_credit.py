import argparse
import asyncio
import os
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def get_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offset an accidental monthly rent sweep by crediting each active vendor's "
            "rent balance and marking the month as paid when needed."
        )
    )
    parser.add_argument(
        "--period",
        default=None,
        help="Target period in YYYY-MM format. Defaults to the current month.",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres connection string. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the script only prints a dry run.",
    )
    parser.add_argument(
        "--reason",
        default="Offset accidental rent charge after pre-go-live vendor rent collection",
        help="Reason stored on inserted rent payment rows and the idempotency marker.",
    )
    return parser.parse_args()


def period_start_from_arg(raw_period: str | None) -> date:
    if raw_period:
        year_str, month_str = raw_period.split("-", 1)
        return date(int(year_str), int(month_str), 1)
    today = date.today()
    return date(today.year, today.month, 1)


async def main() -> None:
    args = parse_args()
    if not args.db_url:
        raise SystemExit("DATABASE_URL is required. Pass --db-url or export DATABASE_URL.")

    period_start = period_start_from_arg(args.period)
    marker_key = f"manual_fix_rent_offset_{period_start.isoformat()}_v1"
    engine = create_async_engine(get_async_url(args.db_url), echo=False)

    summary_query = text(
        """
        SELECT
            v.id,
            v.name,
            v.booth_number,
            COALESCE(v.monthly_rent, 0)::numeric(10,2) AS monthly_rent,
            COALESCE(vb.balance, 0)::numeric(10,2) AS sales_balance,
            COALESCE(vb.rent_balance, 0)::numeric(10,2) AS rent_balance,
            EXISTS (
                SELECT 1
                FROM rent_payments rp
                WHERE rp.vendor_id = v.id
                  AND rp.period_month = :period_start
                  AND rp.status = 'paid'
            ) AS has_paid_rent
        FROM vendors v
        LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
        WHERE v.status = 'active'
          AND v.role = 'vendor'
          AND COALESCE(v.monthly_rent, 0) > 0
        ORDER BY v.name
        """
    )

    async with engine.begin() as conn:
        marker = await conn.execute(
            text("SELECT value FROM store_settings WHERE key = :key"),
            {"key": marker_key},
        )
        if marker.scalar_one_or_none():
            raise SystemExit(
                f"Correction marker {marker_key!r} already exists. This fix has already been applied."
            )

        rows = (await conn.execute(summary_query, {"period_start": period_start})).mappings().all()
        total_credit = sum(Decimal(str(row["monthly_rent"])) for row in rows)
        missing_paid_count = sum(0 if row["has_paid_rent"] else 1 for row in rows)

        print(f"Target period: {period_start.isoformat()}")
        print(f"Vendors affected: {len(rows)}")
        print(f"Total rent credit: ${total_credit:.2f}")
        print(f"Missing paid-rent records to insert: {missing_paid_count}")
        print()

        for row in rows:
            print(
                f"- #{row['id']} {row['name']} ({row['booth_number'] or '—'}): "
                f"monthly_rent=${Decimal(str(row['monthly_rent'])):.2f}, "
                f"sales_balance=${Decimal(str(row['sales_balance'])):.2f}, "
                f"rent_balance=${Decimal(str(row['rent_balance'])):.2f}, "
                f"has_paid_rent={row['has_paid_rent']}"
            )

        if not args.apply:
            print("\nDry run only. Re-run with --apply to write the correction.")
            return

        await conn.execute(
            text(
                """
                INSERT INTO vendor_balances (vendor_id, balance, rent_balance)
                SELECT v.id, 0.00, 0.00
                FROM vendors v
                LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
                WHERE v.status = 'active'
                  AND v.role = 'vendor'
                  AND COALESCE(v.monthly_rent, 0) > 0
                  AND vb.id IS NULL
                """
            )
        )

        await conn.execute(
            text(
                """
                UPDATE vendor_balances vb
                SET rent_balance = COALESCE(vb.rent_balance, 0) + COALESCE(v.monthly_rent, 0)
                FROM vendors v
                WHERE vb.vendor_id = v.id
                  AND v.status = 'active'
                  AND v.role = 'vendor'
                  AND COALESCE(v.monthly_rent, 0) > 0
                """
            )
        )

        await conn.execute(
            text(
                """
                INSERT INTO rent_payments (
                    vendor_id, amount, period_month, method, status, notes, processed_at
                )
                SELECT
                    v.id,
                    COALESCE(v.monthly_rent, 0),
                    :period_start,
                    'manual',
                    'paid',
                    :reason,
                    NOW()
                FROM vendors v
                WHERE v.status = 'active'
                  AND v.role = 'vendor'
                  AND COALESCE(v.monthly_rent, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM rent_payments rp
                      WHERE rp.vendor_id = v.id
                        AND rp.period_month = :period_start
                        AND rp.status = 'paid'
                  )
                """
            ),
            {
                "period_start": period_start,
                "reason": args.reason,
            },
        )

        await conn.execute(
            text(
                """
                INSERT INTO store_settings (key, value, description)
                VALUES (:key, 'done', :description)
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    description = EXCLUDED.description
                """
            ),
            {
                "key": marker_key,
                "description": args.reason,
            },
        )

        print("\nCorrection applied successfully.")
        print(f"Inserted marker: {marker_key}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
