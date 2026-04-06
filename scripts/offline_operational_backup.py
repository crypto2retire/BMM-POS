#!/usr/bin/env python3
import argparse
import asyncio
import gzip
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


def _resolve_database_url() -> str:
    return (
        os.environ.get("DATABASE_URL", "")
        or os.environ.get("DATABASE_PRIVATE_URL", "")
        or os.environ.get("DATABASE_PUBLIC_URL", "")
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


_RAW_DATABASE_URL = _resolve_database_url()
if not _RAW_DATABASE_URL:
    print("offline backup requires DATABASE_URL", file=sys.stderr, flush=True)
    raise RuntimeError("DATABASE_URL is not configured")

_ASYNC_DATABASE_URL, _CONNECT_ARGS = _get_async_url(_RAW_DATABASE_URL)
_ENGINE = create_async_engine(
    _ASYNC_DATABASE_URL,
    echo=False,
    connect_args=_CONNECT_ARGS,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)


DEFAULT_OUTPUT_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "BMM-POS"
    / "offline"
    / "current-operational-backup.json.gz"
)

SNAPSHOT_MODELS = [
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


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items()}
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in row.__table__.columns:
        payload[column.name] = _serialize_value(getattr(row, column.name))
    return payload


def _ordered_select(model: type[Any]):
    stmt = select(model)
    primary_keys = list(model.__table__.primary_key.columns)
    if primary_keys:
        stmt = stmt.order_by(*primary_keys)
    return stmt


async def _fetch_rows(model: type[Any]) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(_ordered_select(model))
        return [_serialize_row(row) for row in result.scalars().all()]


async def build_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "snapshot_kind": "bmm_pos_operational_backup",
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
        "counts": {},
        "excluded_tables": [
            "item_images",
            "studio_images",
        ],
        "notes": [
            "Binary image blobs are excluded to keep the backup portable and small.",
            "Item and booth image URLs remain present on their parent records.",
            "This file contains customer information, password hashes, and operational settings.",
        ],
    }

    for table_name, model in SNAPSHOT_MODELS:
        rows = await _fetch_rows(model)
        snapshot["tables"][table_name] = rows
        snapshot["counts"][table_name] = len(rows)

    return snapshot


def write_snapshot(snapshot: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with gzip.open(temp_path, "wt", encoding="utf-8") as fh:
        json.dump(snapshot, fh, separators=(",", ":"), ensure_ascii=True)

    os.chmod(temp_path, 0o600)
    os.replace(temp_path, output_path)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a single operational backup snapshot for offline BMM-POS recovery."
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("OFFLINE_BACKUP_PATH", str(DEFAULT_OUTPUT_PATH)),
        help="Destination .json.gz path. Defaults to ~/Library/Application Support/BMM-POS/offline/current-operational-backup.json.gz",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    snapshot = await build_snapshot()
    write_snapshot(snapshot, output_path)

    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "generated_at": snapshot["generated_at"],
                "counts": snapshot["counts"],
            },
            indent=2,
        )
    )
    await _ENGINE.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
