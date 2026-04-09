#!/usr/bin/env python3
import argparse
import asyncio
import gzip
import json
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.sqltypes import Date, DateTime, Integer, Time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("SECRET_KEY", "offline-restore-local")


DEFAULT_INPUT_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "BMM-POS"
    / "offline"
    / "current-operational-backup.json.gz"
)

def _resolve_target_database_url(cli_value: str | None) -> str:
    return (
        cli_value
        or os.environ.get("OFFLINE_RESTORE_DATABASE_URL", "")
        or os.environ.get("RESTORE_DATABASE_URL", "")
    )


def _get_async_url(url: str) -> tuple[str, dict[str, Any]]:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if "?" in url:
        base, query = url.split("?", 1)
    else:
        base, query = url, ""

    params: dict[str, str] = {}
    if query:
        for part in query.split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key] = value
            elif part:
                params[part] = ""

    sslmode = params.pop("sslmode", None)
    ssl_param = params.pop("ssl", None)
    ssl_value = sslmode or ssl_param
    needs_ssl = ssl_value in ("require", "verify-ca", "verify-full", "true", "True", "1")

    rebuilt_query = "&".join(f"{key}={value}" for key, value in params.items())
    normalized_url = f"{base}?{rebuilt_query}" if rebuilt_query else base
    return normalized_url, {"ssl": needs_ssl}


def _assert_safe_restore_target(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise RuntimeError("Restore target DATABASE_URL is missing a host")
    blocked_markers = (
        "railway.internal",
        ".up.railway.app",
        "proxy.rlwy.net",
    )
    if any(marker in host for marker in blocked_markers):
        raise RuntimeError(
            "Restore target points at Railway/public production. Restore must target a local fallback database."
        )


def _load_snapshot(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _deserialize_value(column: Any, value: Any) -> Any:
    if value is None:
        return None

    column_type = column.type
    if isinstance(column_type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(column_type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(column_type, Time) and isinstance(value, str):
        return time.fromisoformat(value)
    return value


def _coerce_rows_for_model(model: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows

    coerced_rows: list[dict[str, Any]] = []
    columns_by_name = {column.name: column for column in model.__table__.columns}
    for row in rows:
        coerced_row: dict[str, Any] = {}
        for key, value in row.items():
            column = columns_by_name.get(key)
            coerced_row[key] = _deserialize_value(column, value) if column is not None else value
        coerced_rows.append(coerced_row)
    return coerced_rows


def _sequence_reset_sql(model: Any) -> str | None:
    pk_columns = list(model.__table__.primary_key.columns)
    if len(pk_columns) != 1:
        return None

    pk_column = pk_columns[0]
    if not isinstance(pk_column.type, Integer):
        return None

    table_name = model.__table__.name
    column_name = pk_column.name
    return (
        f"SELECT setval("
        f"pg_get_serial_sequence('{table_name}', '{column_name}'), "
        f"GREATEST(COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0), 1), "
        f"true)"
    )


def _truncate_sql() -> str:
    _, models = _load_restore_metadata()
    table_names = ", ".join(model.__table__.name for _, model in models)
    return f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"


def _load_restore_metadata():
    from app.database import Base
    from app.models.booth_showcase import BoothShowcase
    from app.models.class_registration import ClassRegistration
    from app.models.eod_report import EodReport
    from app.models.gift_card import GiftCard, GiftCardTransaction
    from app.models.item import Item
    from app.models.legacy_history import LegacyFinancialHistory
    from app.models.payout import Payout
    from app.models.poynt_payment import PoyntPayment
    from app.models.rent import RentPayment
    from app.models.reservation import Reservation
    from app.models.sale import Sale, SaleItem
    from app.models.store_setting import StoreSetting
    from app.models.studio_class import StudioClass
    from app.models.vendor import BalanceAdjustment, Vendor, VendorBalance

    restore_models = [
        ("vendors", Vendor),
        ("vendor_balances", VendorBalance),
        ("balance_adjustments", BalanceAdjustment),
        ("items", Item),
        ("sales", Sale),
        ("sale_items", SaleItem),
        ("rent_payments", RentPayment),
        ("payouts", Payout),
        ("gift_cards", GiftCard),
        ("gift_card_transactions", GiftCardTransaction),
        ("reservations", Reservation),
        ("store_settings", StoreSetting),
        ("booth_showcases", BoothShowcase),
        ("legacy_financial_history", LegacyFinancialHistory),
        ("studio_classes", StudioClass),
        ("class_registrations", ClassRegistration),
        ("poynt_payments", PoyntPayment),
        ("eod_reports", EodReport),
    ]
    return Base, restore_models


async def restore_snapshot(snapshot: dict[str, Any], database_url: str) -> dict[str, Any]:
    _assert_safe_restore_target(database_url)
    os.environ["DATABASE_URL"] = database_url
    Base, restore_models = _load_restore_metadata()
    async_url, connect_args = _get_async_url(database_url)
    engine = create_async_engine(
        async_url,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    restored_counts: dict[str, int] = {}
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_truncate_sql()))

    async with SessionLocal() as session:
        for table_name, model in restore_models:
            rows = snapshot.get("tables", {}).get(table_name, []) or []
            rows = _coerce_rows_for_model(model, rows)
            if rows:
                await session.execute(insert(model), rows)
            restored_counts[table_name] = len(rows)
        await session.commit()

    async with engine.begin() as conn:
        for _, model in restore_models:
            reset_sql = _sequence_reset_sql(model)
            if reset_sql:
                await conn.execute(text(reset_sql))

    await engine.dispose()
    return restored_counts


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a BMM-POS offline snapshot into a local fallback Postgres database."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help="Path to current-operational-backup.json.gz",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Explicit restore target URL. Otherwise OFFLINE_RESTORE_DATABASE_URL or RESTORE_DATABASE_URL is used.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required to perform the destructive restore.",
    )
    args = parser.parse_args()

    if not args.force:
        print("Restore aborted: rerun with --force", file=sys.stderr)
        return 2

    target_url = _resolve_target_database_url(args.database_url)
    if not target_url:
        print("Restore requires OFFLINE_RESTORE_DATABASE_URL or --database-url", file=sys.stderr)
        return 2

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Snapshot file not found: {input_path}", file=sys.stderr)
        return 2

    snapshot = _load_snapshot(input_path)
    restored_counts = await restore_snapshot(snapshot, target_url)
    print(
        json.dumps(
            {
                "input_path": str(input_path),
                "generated_at": snapshot.get("generated_at"),
                "restored_counts": restored_counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
