#!/usr/bin/env python3
import argparse
import asyncio
import csv
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx


SQUARE_BASE = "https://connect.squareup.com"
SQUARE_API_VERSION = "2024-02-15"
DEFAULT_EXPORT_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "BMM-POS"
    / "offline"
    / "square"
    / "current"
)

CUSTOMER_FIELDS = [
    "id",
    "reference_id",
    "given_name",
    "family_name",
    "company_name",
    "nickname",
    "email_address",
    "phone_number",
    "creation_source",
    "birthday",
    "created_at",
    "updated_at",
    "version",
    "segment_ids",
    "note",
    "preferences_email_unsubscribed",
    "address_line_1",
    "address_line_2",
    "address_locality",
    "address_administrative_district_level_1",
    "address_postal_code",
    "address_country",
]

PAYMENT_FIELDS = [
    "id",
    "order_id",
    "customer_id",
    "location_id",
    "status",
    "source_type",
    "receipt_number",
    "receipt_url",
    "amount_money",
    "approved_money",
    "tip_money",
    "total_money",
    "app_fee_money",
    "refunded_money",
    "delay_duration",
    "delay_action",
    "created_at",
    "updated_at",
    "card_brand",
    "card_last_4",
    "card_entry_method",
]
SALES_FIELDS = PAYMENT_FIELDS

ORDER_FIELDS = [
    "id",
    "location_id",
    "customer_id",
    "ticket_name",
    "state",
    "source_name",
    "created_at",
    "updated_at",
    "closed_at",
    "total_money",
    "total_tax_money",
    "total_discount_money",
    "total_tip_money",
    "net_amount_due_money",
]

ORDER_LINE_ITEM_FIELDS = [
    "order_id",
    "line_uid",
    "catalog_object_id",
    "catalog_version",
    "name",
    "variation_name",
    "item_type",
    "quantity",
    "base_price_money",
    "gross_sales_money",
    "total_discount_money",
    "total_tax_money",
    "total_money",
    "note",
]

INVOICE_FIELDS = [
    "id",
    "invoice_number",
    "title",
    "description",
    "location_id",
    "order_id",
    "primary_recipient_customer_id",
    "status",
    "delivery_method",
    "public_url",
    "scheduled_at",
    "created_at",
    "updated_at",
    "accepted_payment_methods_card",
    "accepted_payment_methods_square_gift_card",
    "accepted_payment_methods_bank_account",
    "accepted_payment_methods_buy_now_pay_later",
]

REFUND_FIELDS = [
    "id",
    "payment_id",
    "order_id",
    "location_id",
    "status",
    "reason",
    "destination_type",
    "amount_money",
    "created_at",
    "updated_at",
]

PAYOUT_FIELDS = [
    "id",
    "status",
    "location_id",
    "payout_type",
    "arrival_date",
    "created_at",
    "updated_at",
    "amount_money",
    "destination_type",
]


def _get_env(name: str) -> str:
    return os.environ.get(name, "") or os.environ.get(name.lower(), "")


def _access_token() -> str:
    return _get_env("SQUARE_ACCESS_TOKEN")


def _location_id() -> str:
    return _get_env("SQUARE_LOCATION_ID")


def _export_enabled() -> bool:
    raw = _get_env("SQUARE_OFFLINE_EXPORT_ENABLED")
    if not raw:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _headers() -> dict[str, str]:
    token = _access_token()
    if not token:
        raise RuntimeError("Square export requires SQUARE_ACCESS_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Square-Version": SQUARE_API_VERSION,
    }


def _money_amount(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    amount = payload.get("amount")
    if amount is None:
        return ""
    try:
        return f"{int(amount) / 100:.2f}"
    except Exception:
        return str(amount)


def _join_values(values: Iterable[Any] | None) -> str:
    if not values:
        return ""
    return "|".join(str(v) for v in values if v not in (None, ""))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = {key: ("" if value is None else value) for key, value in row.items()}
            writer.writerow(normalized)
    os.replace(temp_path, path)


def _write_json_gz(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temp_path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, separators=(",", ":"))
    os.replace(temp_path, path)


async def _get_paginated(
    client: httpx.AsyncClient,
    path: str,
    data_key: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        if method == "GET":
            query = dict(params or {})
            if cursor:
                query["cursor"] = cursor
            resp = await client.get(path, params=query)
        else:
            payload = dict(body or {})
            if cursor:
                payload["cursor"] = cursor
            resp = await client.post(path, json=payload)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get(data_key, []) or [])
        cursor = data.get("cursor")
        if not cursor:
            break
    return records


def _flatten_customer(customer: dict[str, Any]) -> dict[str, Any]:
    address = customer.get("address") or {}
    preferences = customer.get("preferences") or {}
    return {
        "id": customer.get("id", ""),
        "reference_id": customer.get("reference_id", ""),
        "given_name": customer.get("given_name", ""),
        "family_name": customer.get("family_name", ""),
        "company_name": customer.get("company_name", ""),
        "nickname": customer.get("nickname", ""),
        "email_address": customer.get("email_address", ""),
        "phone_number": customer.get("phone_number", ""),
        "creation_source": customer.get("creation_source", ""),
        "birthday": customer.get("birthday", ""),
        "created_at": customer.get("created_at", ""),
        "updated_at": customer.get("updated_at", ""),
        "version": customer.get("version", ""),
        "segment_ids": _join_values(customer.get("segment_ids")),
        "note": customer.get("note", ""),
        "preferences_email_unsubscribed": preferences.get("email_unsubscribed", ""),
        "address_line_1": address.get("address_line_1", ""),
        "address_line_2": address.get("address_line_2", ""),
        "address_locality": address.get("locality", ""),
        "address_administrative_district_level_1": address.get("administrative_district_level_1", ""),
        "address_postal_code": address.get("postal_code", ""),
        "address_country": address.get("country", ""),
    }


def _flatten_payment(payment: dict[str, Any]) -> dict[str, Any]:
    details = payment.get("card_details") or {}
    card = details.get("card") or {}
    return {
        "id": payment.get("id", ""),
        "order_id": payment.get("order_id", ""),
        "customer_id": payment.get("customer_id", ""),
        "location_id": payment.get("location_id", ""),
        "status": payment.get("status", ""),
        "source_type": payment.get("source_type", ""),
        "receipt_number": payment.get("receipt_number", ""),
        "receipt_url": payment.get("receipt_url", ""),
        "amount_money": _money_amount(payment.get("amount_money")),
        "approved_money": _money_amount(payment.get("approved_money")),
        "tip_money": _money_amount(payment.get("tip_money")),
        "total_money": _money_amount(payment.get("total_money")),
        "app_fee_money": _money_amount(payment.get("app_fee_money")),
        "refunded_money": _money_amount(payment.get("refunded_money")),
        "delay_duration": payment.get("delay_duration", ""),
        "delay_action": payment.get("delay_action", ""),
        "created_at": payment.get("created_at", ""),
        "updated_at": payment.get("updated_at", ""),
        "card_brand": card.get("card_brand", ""),
        "card_last_4": card.get("last_4", ""),
        "card_entry_method": details.get("entry_method", ""),
    }


def _flatten_order(order: dict[str, Any]) -> dict[str, Any]:
    totals = order.get("net_amounts") or {}
    source = order.get("source") or {}
    return {
        "id": order.get("id", ""),
        "location_id": order.get("location_id", ""),
        "customer_id": order.get("customer_id", ""),
        "ticket_name": order.get("ticket_name", ""),
        "state": order.get("state", ""),
        "source_name": source.get("name", ""),
        "created_at": order.get("created_at", ""),
        "updated_at": order.get("updated_at", ""),
        "closed_at": order.get("closed_at", ""),
        "total_money": _money_amount(order.get("total_money")),
        "total_tax_money": _money_amount(order.get("total_tax_money")),
        "total_discount_money": _money_amount(order.get("total_discount_money")),
        "total_tip_money": _money_amount(order.get("total_tip_money")),
        "net_amount_due_money": _money_amount(totals.get("total_money")),
    }


def _flatten_order_line_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in order.get("line_items") or []:
        gross = line.get("gross_sales_money") or line.get("gross_sales_money") or {}
        rows.append({
            "order_id": order.get("id", ""),
            "line_uid": line.get("uid", ""),
            "catalog_object_id": line.get("catalog_object_id", ""),
            "catalog_version": line.get("catalog_version", ""),
            "name": line.get("name", ""),
            "variation_name": line.get("variation_name", ""),
            "item_type": line.get("item_type", ""),
            "quantity": line.get("quantity", ""),
            "base_price_money": _money_amount(line.get("base_price_money")),
            "gross_sales_money": _money_amount(gross),
            "total_discount_money": _money_amount(line.get("total_discount_money")),
            "total_tax_money": _money_amount(line.get("total_tax_money")),
            "total_money": _money_amount(line.get("total_money")),
            "note": line.get("note", ""),
        })
    return rows


def _flatten_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    accepted = invoice.get("accepted_payment_methods") or {}
    recipient = invoice.get("primary_recipient") or {}
    customer = recipient.get("customer_id", "")
    return {
        "id": invoice.get("id", ""),
        "invoice_number": invoice.get("invoice_number", ""),
        "title": invoice.get("title", ""),
        "description": invoice.get("description", ""),
        "location_id": invoice.get("location_id", ""),
        "order_id": invoice.get("order_id", ""),
        "primary_recipient_customer_id": customer,
        "status": invoice.get("status", ""),
        "delivery_method": invoice.get("delivery_method", ""),
        "public_url": invoice.get("public_url", ""),
        "scheduled_at": invoice.get("scheduled_at", ""),
        "created_at": invoice.get("created_at", ""),
        "updated_at": invoice.get("updated_at", ""),
        "accepted_payment_methods_card": accepted.get("card", ""),
        "accepted_payment_methods_square_gift_card": accepted.get("square_gift_card", ""),
        "accepted_payment_methods_bank_account": accepted.get("bank_account", ""),
        "accepted_payment_methods_buy_now_pay_later": accepted.get("buy_now_pay_later", ""),
    }


def _flatten_refund(refund: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": refund.get("id", ""),
        "payment_id": refund.get("payment_id", ""),
        "order_id": refund.get("order_id", ""),
        "location_id": refund.get("location_id", ""),
        "status": refund.get("status", ""),
        "reason": refund.get("reason", ""),
        "destination_type": refund.get("destination_type", ""),
        "amount_money": _money_amount(refund.get("amount_money")),
        "created_at": refund.get("created_at", ""),
        "updated_at": refund.get("updated_at", ""),
    }


def _flatten_payout(payout: dict[str, Any]) -> dict[str, Any]:
    destination = payout.get("destination") or {}
    return {
        "id": payout.get("id", ""),
        "status": payout.get("status", ""),
        "location_id": payout.get("location_id", ""),
        "payout_type": payout.get("payout_type", ""),
        "arrival_date": payout.get("arrival_date", ""),
        "created_at": payout.get("created_at", ""),
        "updated_at": payout.get("updated_at", ""),
        "amount_money": _money_amount(payout.get("amount_money")),
        "destination_type": destination.get("type", ""),
    }


async def export_square_data(export_dir: Path) -> dict[str, Any]:
    if not _export_enabled():
        return {"exported": False, "reason": "disabled"}
    if not _access_token():
        return {"exported": False, "reason": "missing_square_access_token"}

    export_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "snapshot_kind": "square_operational_backup",
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "location_id": _location_id(),
        "datasets": {},
        "counts": {},
        "notes": [
            "CSV headers are stable and intended for future import tooling.",
            "JSON snapshot preserves raw Square payloads for full-fidelity offline recovery.",
            "sales.csv mirrors payments.csv because Square sales flow through payment records in this export.",
        ],
    }

    async with httpx.AsyncClient(
        base_url=SQUARE_BASE,
        headers=_headers(),
        timeout=45.0,
    ) as client:
        customers = await _get_paginated(
            client,
            "/v2/customers/search",
            "customers",
            method="POST",
            body={"limit": 100},
        )
        payments = await _get_paginated(
            client,
            "/v2/payments",
            "payments",
            method="GET",
            params={"sort_order": "ASC", "limit": 100},
        )
        invoices = await _get_paginated(
            client,
            "/v2/invoices/search",
            "invoices",
            method="POST",
            body={"limit": 100},
        )
        refunds = await _get_paginated(
            client,
            "/v2/refunds",
            "refunds",
            method="GET",
            params={"sort_order": "ASC", "limit": 100},
        )
        payouts = await _get_paginated(
            client,
            "/v2/payouts",
            "payouts",
            method="GET",
            params={"limit": 100},
        )

        orders: list[dict[str, Any]] = []
        if _location_id():
            orders = await _get_paginated(
                client,
                "/v2/orders/search",
                "orders",
                method="POST",
                body={
                    "location_ids": [_location_id()],
                    "limit": 100,
                    "query": {
                        "sort": {
                            "sort_field": "CREATED_AT",
                            "sort_order": "ASC",
                        }
                    },
                },
            )
        else:
            metadata["orders_skipped_reason"] = "missing_square_location_id"

    customer_rows = [_flatten_customer(customer) for customer in customers]
    payment_rows = [_flatten_payment(payment) for payment in payments]
    invoice_rows = [_flatten_invoice(invoice) for invoice in invoices]
    refund_rows = [_flatten_refund(refund) for refund in refunds]
    payout_rows = [_flatten_payout(payout) for payout in payouts]
    order_rows = [_flatten_order(order) for order in orders]
    order_line_rows: list[dict[str, Any]] = []
    for order in orders:
        order_line_rows.extend(_flatten_order_line_items(order))

    _write_csv(export_dir / "customers.csv", CUSTOMER_FIELDS, customer_rows)
    _write_csv(export_dir / "payments.csv", PAYMENT_FIELDS, payment_rows)
    _write_csv(export_dir / "sales.csv", SALES_FIELDS, payment_rows)
    _write_csv(export_dir / "orders.csv", ORDER_FIELDS, order_rows)
    _write_csv(export_dir / "order_line_items.csv", ORDER_LINE_ITEM_FIELDS, order_line_rows)
    _write_csv(export_dir / "invoices.csv", INVOICE_FIELDS, invoice_rows)
    _write_csv(export_dir / "refunds.csv", REFUND_FIELDS, refund_rows)
    _write_csv(export_dir / "payouts.csv", PAYOUT_FIELDS, payout_rows)

    metadata["datasets"] = {
        "customers": customers,
        "payments": payments,
        "sales": payments,
        "orders": orders,
        "order_line_items": order_line_rows,
        "invoices": invoices,
        "refunds": refunds,
        "payouts": payouts,
    }
    metadata["counts"] = {
        "customers": len(customer_rows),
        "payments": len(payment_rows),
        "sales": len(payment_rows),
        "orders": len(order_rows),
        "order_line_items": len(order_line_rows),
        "invoices": len(invoice_rows),
        "refunds": len(refund_rows),
        "payouts": len(payout_rows),
    }
    _write_json_gz(export_dir / "square-backup.json.gz", metadata)
    return {
        "exported": True,
        "export_dir": str(export_dir),
        "generated_at": metadata["generated_at"],
        "counts": metadata["counts"],
        "orders_skipped_reason": metadata.get("orders_skipped_reason", ""),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Square customers, payments, orders, invoices, refunds, and payouts for offline recovery."
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("SQUARE_OFFLINE_EXPORT_DIR", str(DEFAULT_EXPORT_DIR)),
        help="Destination directory for square-backup.json.gz and CSV files.",
    )
    args = parser.parse_args()
    result = await export_square_data(Path(args.output_dir).expanduser().resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
