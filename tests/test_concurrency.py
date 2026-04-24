"""
Concurrency / race-condition tests for BMM-POS.

SAFETY: Requires BMM_TEST_MODE=1. Only touches rows with __TEST__ identifiers.
Run: BMM_TEST_MODE=1 pytest tests/test_concurrency.py -v
"""
import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.item import Item
from app.models.sale import Sale, SaleItem
from app.models.reservation import Reservation
from app.models.vendor import Vendor, VendorBalance


# ── Helpers ──

async def _get_item_quantity(item_id: int) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Item.quantity, Item.reserved_quantity).where(Item.id == item_id))
        row = result.one()
        return row.quantity, row.reserved_quantity


async def _count_sales_for_item(item_id: int) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SaleItem)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(SaleItem.item_id == item_id, Sale.is_voided.is_(False))
        )
        return len(result.scalars().all())


async def _count_reservations_for_item(item_id: int) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Reservation).where(
                Reservation.item_id == item_id,
                Reservation.status == "pending"
            )
        )
        return len(result.scalars().all())


# ── Test 1: POS checkout — only 1 of N concurrent buyers succeeds for qty=1 item ──

@pytest.mark.asyncio
async def test_pos_checkout_overselling_race(client: AsyncClient, test_item, cashier_token: str):
    """10 cashiers try to sell the last item simultaneously. Only 1 should succeed."""
    barcode = test_item.barcode
    payload = {
        "items": [{"barcode": barcode, "quantity": 1}],
        "payment_method": "cash",
        "cash_tendered": "20.00",
    }
    headers = {"Authorization": f"Bearer {cashier_token}"}

    async def _buy():
        try:
            return await client.post("/api/v1/pos/sale", json=payload, headers=headers)
        except Exception as exc:
            return exc

    # Fire 8 requests concurrently
    responses = await asyncio.gather(*[_buy() for _ in range(8)], return_exceptions=True)

    successes = [r for r in responses if hasattr(r, "status_code") and r.status_code == 201]
    stock_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code == 400 and "stock" in (r.json().get("detail") or "").lower()]
    other_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code not in (201, 400)]

    # At most 1 sale should succeed
    assert len(successes) <= 1, f"Expected at most 1 POS sale, got {len(successes)}"
    assert len(other_errors) == 0, f"Unexpected errors: {[r.status_code for r in other_errors]}"

    # Verify final quantity
    qty, reserved = await _get_item_quantity(test_item.id)
    sold_count = await _count_sales_for_item(test_item.id)

    if len(successes) == 1:
        assert qty == 0, f"Expected qty=0 after sale, got {qty}"
        assert sold_count == 1, f"Expected 1 sale row, got {sold_count}"
    else:
        # All failed — qty should still be 1
        assert qty == 1, f"Expected qty=1 when all failed, got {qty}"


# ── Test 2: Sales checkout — same race via /api/v1/sales/ ──

@pytest.mark.asyncio
async def test_sales_checkout_overselling_race(client: AsyncClient, test_item, cashier_token: str):
    """10 requests to /api/v1/sales/ for the last item. Only 1 should succeed."""
    barcode = test_item.barcode
    payload = {
        "items": [{"barcode": barcode, "quantity": 1}],
        "payment_method": "cash",
        "cash_tendered": "20.00",
    }
    headers = {"Authorization": f"Bearer {cashier_token}"}

    async def _buy():
        try:
            return await client.post("/api/v1/sales/", json=payload, headers=headers)
        except Exception as exc:
            return exc

    responses = await asyncio.gather(*[_buy() for _ in range(8)], return_exceptions=True)

    successes = [r for r in responses if hasattr(r, "status_code") and r.status_code == 201]
    other_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code not in (201, 400)]

    assert len(successes) <= 1, f"Expected at most 1 sale, got {len(successes)}"
    assert len(other_errors) == 0, f"Unexpected errors: {[r.status_code for r in other_errors]}"

    qty, _ = await _get_item_quantity(test_item.id)
    if len(successes) == 1:
        assert qty == 0, f"Expected qty=0 after sale, got {qty}"
    else:
        assert qty == 1, f"Expected qty=1 when all failed, got {qty}"


# ── Test 3: Storefront checkout — only 1 online reservation for qty=1 item ──

@pytest.mark.asyncio
async def test_storefront_checkout_race(client: AsyncClient, test_item):
    """10 online shoppers try to reserve the last item. Only 1 reservation should succeed."""
    payload = {
        "item_ids": [test_item.id],
        "customer_name": "Test Shopper",
        "customer_phone": "555-TEST",
        "customer_email": "test@example.com",
        "idempotency_key": None,  # deliberately no key — testing raw race
    }

    async def _reserve():
        try:
            return await client.post("/api/v1/storefront/create-cart-payment", json=payload)
        except Exception as exc:
            return exc

    responses = await asyncio.gather(*[_reserve() for _ in range(8)], return_exceptions=True)

    successes = [r for r in responses if hasattr(r, "status_code") and r.status_code in (200, 201)]
    stock_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code == 400]
    other_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code not in (200, 201, 400)]

    # Should have at most 1 successful reservation
    assert len(successes) <= 1, f"Expected at most 1 storefront reservation, got {len(successes)}"
    assert len(other_errors) == 0, f"Unexpected errors: {[r.status_code for r in other_errors]}"

    qty, reserved = await _get_item_quantity(test_item.id)
    pending_count = await _count_reservations_for_item(test_item.id)

    if len(successes) == 1:
        assert reserved == 1, f"Expected reserved_quantity=1, got {reserved}"
        assert pending_count == 1, f"Expected 1 pending reservation, got {pending_count}"
    else:
        assert reserved == 0, f"Expected reserved_quantity=0 when all failed, got {reserved}"
        assert pending_count == 0, f"Expected 0 pending reservations, got {pending_count}"


# ── Test 4: Storefront idempotency — duplicate key returns existing ──

@pytest.mark.asyncio
async def test_storefront_idempotency(client: AsyncClient, test_item_qty_5):
    """Same idempotency key should return the existing reservation, not create a duplicate."""
    item = test_item_qty_5
    payload = {
        "item_ids": [item.id],
        "customer_name": "Test Shopper",
        "customer_phone": "555-TEST",
        "customer_email": "test@example.com",
        "idempotency_key": "test-idempotency-abc-123",
    }

    r1 = await client.post("/api/v1/storefront/create-cart-payment", json=payload)
    assert r1.status_code in (200, 201), f"First request failed: {r1.text}"

    r2 = await client.post("/api/v1/storefront/create-cart-payment", json=payload)
    assert r2.status_code in (200, 201), f"Second request failed: {r2.text}"

    # Should return same checkout_group_id
    data1 = r1.json()
    data2 = r2.json()
    assert data1["reference_id"] == data2["reference_id"], "Idempotency failed: different reference IDs"

    # Should only be 1 pending reservation for this item
    pending_count = await _count_reservations_for_item(item.id)
    assert pending_count == 1, f"Expected 1 pending reservation, got {pending_count}"


# ── Test 5: POS void-sale restores inventory correctly ──

@pytest.mark.asyncio
async def test_void_sale_restores_inventory(client: AsyncClient, test_item, cashier_token: str):
    """Selling then voiding should restore the original quantity."""
    barcode = test_item.barcode
    sale_payload = {
        "items": [{"barcode": barcode, "quantity": 1}],
        "payment_method": "cash",
        "cash_tendered": "20.00",
    }
    headers = {"Authorization": f"Bearer {cashier_token}"}

    # Make the sale
    r = await client.post("/api/v1/pos/sale", json=sale_payload, headers=headers)
    assert r.status_code == 201, f"Sale failed: {r.text}"
    sale_id = r.json()["id"]

    qty_after_sale, _ = await _get_item_quantity(test_item.id)
    assert qty_after_sale == 0, f"Expected qty=0 after sale, got {qty_after_sale}"

    # Void it
    void_r = await client.post(
        f"/api/v1/pos/sales/{sale_id}/void",
        json={"reason": "test void"},
        headers=headers,
    )
    assert void_r.status_code in (200, 204), f"Void failed: {void_r.text}"

    qty_after_void, _ = await _get_item_quantity(test_item.id)
    assert qty_after_void == 1, f"Expected qty=1 after void, got {qty_after_void}"


# ── Test 6: Multiple concurrent buyers for qty=N item — exactly N succeed ──

@pytest.mark.asyncio
async def test_pos_checkout_qty_5_exactly_5_sales(client: AsyncClient, test_item_qty_5, cashier_token: str):
    """8 buyers try to buy a qty=5 item. Exactly 5 should succeed."""
    barcode = test_item_qty_5.barcode
    payload = {
        "items": [{"barcode": barcode, "quantity": 1}],
        "payment_method": "cash",
        "cash_tendered": "20.00",
    }
    headers = {"Authorization": f"Bearer {cashier_token}"}

    async def _buy():
        try:
            return await client.post("/api/v1/pos/sale", json=payload, headers=headers)
        except Exception as exc:
            return exc

    responses = await asyncio.gather(*[_buy() for _ in range(8)], return_exceptions=True)

    successes = [r for r in responses if hasattr(r, "status_code") and r.status_code == 201]
    stock_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code == 400 and "stock" in (r.json().get("detail") or "").lower()]
    other_errors = [r for r in responses if hasattr(r, "status_code") and r.status_code not in (201, 400)]

    assert len(other_errors) == 0, f"Unexpected errors: {[r.status_code for r in other_errors]}"
    assert len(successes) == 5, f"Expected exactly 5 sales for qty=5 item, got {len(successes)}"

    qty, _ = await _get_item_quantity(test_item_qty_5.id)
    assert qty == 0, f"Expected qty=0 after 5 sales, got {qty}"

    sold_count = await _count_sales_for_item(test_item_qty_5.id)
    assert sold_count == 5, f"Expected 5 sale rows, got {sold_count}"
