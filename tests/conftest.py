"""
Test fixtures for BMM-POS concurrency and integration tests.

SAFETY: Tests require BMM_TEST_MODE=1 to run against the real database.
All test data is prefixed with __TEST__ for easy identification and cleanup.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

# Safety gate
if os.environ.get("BMM_TEST_MODE") != "1":
    pytest.skip(
        "Tests skipped: set BMM_TEST_MODE=1 to run against the database",
        allow_module_level=True,
    )

from app.main import app
from app.database import AsyncSessionLocal, engine
from app.models.vendor import Vendor, VendorBalance
from app.models.item import Item
from app.models.sale import Sale, SaleItem
from app.models.reservation import Reservation
from app.models.payout import Payout
from app.models.rent import RentPayment
from app.routers.auth import get_password_hash, create_access_token


# ── Module-level test identifiers ──
_TEST_RUN_ID = uuid.uuid4().hex[:8]


def _test_email(role: str) -> str:
    return f"__TEST__{_TEST_RUN_ID}_{role}@bowenstreet.test"


def _test_barcode(suffix: str = "") -> str:
    return f"__TEST__{_TEST_RUN_ID}_{suffix}"


# ── Database helpers ──

async def _clean_test_data():
    """Remove all rows created by this test run."""
    async with AsyncSessionLocal() as session:
        # Delete in dependency order
        await session.execute(
            delete(SaleItem).where(SaleItem.sale_id.in_(
                select(Sale.id).where(Sale.cashier_id.in_(
                    select(Vendor.id).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
                ))
            ))
        )
        await session.execute(
            delete(Sale).where(Sale.cashier_id.in_(
                select(Vendor.id).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
            ))
        )
        await session.execute(
            delete(Reservation).where(Reservation.item_id.in_(
                select(Item.id).where(Item.sku.like(f"__TEST__{_TEST_RUN_ID}_%"))
            ))
        )
        await session.execute(
            delete(Payout).where(Payout.vendor_id.in_(
                select(Vendor.id).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
            ))
        )
        await session.execute(
            delete(RentPayment).where(RentPayment.vendor_id.in_(
                select(Vendor.id).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
            ))
        )
        await session.execute(
            delete(Item).where(Item.sku.like(f"__TEST__{_TEST_RUN_ID}_%"))
        )
        await session.execute(
            delete(VendorBalance).where(VendorBalance.vendor_id.in_(
                select(Vendor.id).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
            ))
        )
        await session.execute(
            delete(Vendor).where(Vendor.email.like(f"__TEST__{_TEST_RUN_ID}_%"))
        )
        await session.commit()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def cleanup_module():
    """Cleanup before and after the test module."""
    await _clean_test_data()
    yield
    await _clean_test_data()


# ── Test entity factories ──

async def _create_test_vendor(role: str = "vendor", monthly_rent: Decimal = Decimal("0")) -> Vendor:
    async with AsyncSessionLocal() as session:
        vendor = Vendor(
            name=f"Test {role.title()} {_TEST_RUN_ID}",
            email=_test_email(role),
            phone="555-TEST",
            booth_number=f"T{_TEST_RUN_ID}",
            monthly_rent=monthly_rent,
            password_hash=get_password_hash("TestPass123!"),
            role=role,
            status="active",
            is_active=True,
            is_vendor=(role == "vendor"),
        )
        session.add(vendor)
        await session.commit()
        await session.refresh(vendor)
        return vendor


async def _create_test_item(vendor_id: int, quantity: int = 1, price: Decimal = Decimal("10.00")) -> Item:
    async with AsyncSessionLocal() as session:
        sku = f"__TEST__{_TEST_RUN_ID}_{uuid.uuid4().hex[:6]}"
        barcode = f"__TEST__{_TEST_RUN_ID}_{uuid.uuid4().hex[:6]}"
        item = Item(
            vendor_id=vendor_id,
            sku=sku,
            barcode=barcode,
            name=f"Test Item {sku}",
            price=price,
            quantity=quantity,
            reserved_quantity=0,
            status="active",
            is_online=True,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def _set_vendor_balance(vendor_id: int, balance: Decimal, rent_balance: Decimal = Decimal("0")):
    async with AsyncSessionLocal() as session:
        vb = await session.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == vendor_id)
        )
        row = vb.scalar_one_or_none()
        if row:
            row.balance = balance
            row.rent_balance = rent_balance
        else:
            session.add(VendorBalance(vendor_id=vendor_id, balance=balance, rent_balance=rent_balance))
        await session.commit()


def _make_token(vendor: Vendor) -> str:
    return create_access_token(data={
        "sub": vendor.email,
        "role": vendor.role,
        "vendor_id": vendor.id,
        "name": vendor.name,
        "av": int(getattr(vendor, "auth_version", 0) or 0),
        "is_vendor": getattr(vendor, "is_vendor", False),
        "booth_number": vendor.booth_number,
    })


# ── Pytest fixtures ──

@pytest_asyncio.fixture(scope="module")
async def test_vendor() -> Vendor:
    return await _create_test_vendor(role="vendor")


@pytest_asyncio.fixture(scope="module")
async def test_cashier() -> Vendor:
    return await _create_test_vendor(role="cashier")


@pytest_asyncio.fixture(scope="module")
async def test_admin() -> Vendor:
    return await _create_test_vendor(role="admin")


@pytest_asyncio.fixture
async def test_item(test_vendor: Vendor) -> Item:
    """Fresh item with qty=1 for each test."""
    return await _create_test_item(vendor_id=test_vendor.id, quantity=1)


@pytest_asyncio.fixture
async def test_item_qty_5(test_vendor: Vendor) -> Item:
    return await _create_test_item(vendor_id=test_vendor.id, quantity=5)


@pytest_asyncio.fixture(scope="module")
async def client():
    """Async HTTP client mounted to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def cashier_token(test_cashier: Vendor) -> str:
    return _make_token(test_cashier)


@pytest_asyncio.fixture
async def admin_token(test_admin: Vendor) -> str:
    return _make_token(test_admin)
