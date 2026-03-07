import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, text
from passlib.context import CryptContext

from app.config import settings
from app.models.vendor import Vendor
from app.models.item import Item

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.pop("sslmode", None)
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


engine = create_async_engine(get_async_url(settings.database_url))
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


VENDORS_DATA = [
    {
        "name": "Admin User",
        "email": "admin@bowenstreetmarket.com",
        "password": "admin123",
        "role": "admin",
        "booth_number": None,
        "monthly_rent": 0,
        "payout_method": "zelle",
        "zelle_handle": None,
        "phone": None,
    },
    {
        "name": "Sarah Johnson",
        "email": "sarah@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "A-12",
        "monthly_rent": 175,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0101",
        "phone": "920-555-0101",
    },
    {
        "name": "Mike Chen",
        "email": "mike@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "B-07",
        "monthly_rent": 200,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0102",
        "phone": "920-555-0102",
    },
    {
        "name": "Linda Kowalski",
        "email": "linda@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "C-22",
        "monthly_rent": 150,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0103",
        "phone": "920-555-0103",
    },
]

ITEMS_PER_VENDOR = [
    [
        {"name": "Silver Necklace", "category": "Jewelry", "price": 45.00, "description": "Handcrafted sterling silver necklace", "quantity": 3},
        {"name": "Antique Dresser", "category": "Furniture", "price": 285.00, "description": "1920s oak dresser with original hardware", "quantity": 1},
        {"name": "Vintage Camera", "category": "Vintage", "price": 95.00, "description": "Working 1960s film camera", "quantity": 2},
        {"name": "Watercolor Print", "category": "Art", "price": 55.00, "description": "Original botanical watercolor", "quantity": 5},
        {"name": "Knitted Scarf", "category": "Handcrafted", "price": 28.00, "description": "Hand-knitted wool scarf", "quantity": 8, "sale": True},
    ],
    [
        {"name": "Jade Bracelet", "category": "Jewelry", "price": 75.00, "description": "Natural jade stone bracelet", "quantity": 4},
        {"name": "Rocking Chair", "category": "Furniture", "price": 340.00, "description": "Restored Victorian rocking chair", "quantity": 1},
        {"name": "Vinyl Record Set", "category": "Vintage", "price": 35.00, "description": "Classic rock collection, 10 records", "quantity": 6},
        {"name": "Oil Painting", "category": "Art", "price": 175.00, "description": "Original landscape oil painting", "quantity": 1},
        {"name": "Ceramic Bowl", "category": "Handcrafted", "price": 32.00, "description": "Hand-thrown stoneware bowl", "quantity": 10, "sale": True},
    ],
    [
        {"name": "Pearl Earrings", "category": "Jewelry", "price": 65.00, "description": "Freshwater pearl drop earrings", "quantity": 3},
        {"name": "Bookcase", "category": "Furniture", "price": 195.00, "description": "Solid pine 5-shelf bookcase", "quantity": 2},
        {"name": "Tin Toy Collection", "category": "Vintage", "price": 120.00, "description": "Set of 6 vintage tin wind-up toys", "quantity": 1},
        {"name": "Charcoal Portrait", "category": "Art", "price": 85.00, "description": "Custom charcoal portrait on demand", "quantity": 1},
        {"name": "Beeswax Candles", "category": "Handcrafted", "price": 18.00, "description": "Set of 4 hand-poured beeswax candles", "quantity": 15, "sale": True},
    ],
]


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Vendor).where(Vendor.email == "admin@bowenstreetmarket.com"))
        if result.scalar_one_or_none():
            print("Database already seeded. Skipping.")
            return

        today = date.today()
        sale_end = today + timedelta(days=14)

        created_vendors = []
        for vdata in VENDORS_DATA:
            vendor = Vendor(
                name=vdata["name"],
                email=vdata["email"],
                password_hash=pwd_context.hash(vdata["password"]),
                role=vdata["role"],
                booth_number=vdata["booth_number"],
                monthly_rent=vdata["monthly_rent"],
                payout_method=vdata["payout_method"],
                zelle_handle=vdata["zelle_handle"],
                phone=vdata["phone"],
            )
            db.add(vendor)
            await db.flush()
            created_vendors.append(vendor)

        await db.flush()

        vendor_items = []
        for idx, vendor in enumerate(created_vendors[1:], 0):
            items_data = ITEMS_PER_VENDOR[idx]
            item_seq = 1
            for idata in items_data:
                sku = f"BSM-{vendor.id:04d}-{item_seq:06d}"
                import uuid
                barcode_val = f"{vendor.id:04d}{item_seq:08d}"

                is_sale = idata.get("sale", False)
                item = Item(
                    vendor_id=vendor.id,
                    sku=sku,
                    barcode=barcode_val,
                    name=idata["name"],
                    category=idata["category"],
                    price=idata["price"],
                    description=idata.get("description"),
                    quantity=idata["quantity"],
                    sale_price=round(idata["price"] * 0.8, 2) if is_sale else None,
                    sale_start=today if is_sale else None,
                    sale_end=sale_end if is_sale else None,
                )
                db.add(item)
                item_seq += 1

        await db.commit()

        print("\n" + "="*60)
        print("  BMM-POS SEED DATA SUMMARY")
        print("="*60)
        print("\nLOGIN CREDENTIALS:")
        print(f"  Admin:  admin@bowenstreetmarket.com / admin123")
        print(f"  Sarah:  sarah@email.com / vendor123")
        print(f"  Mike:   mike@email.com / vendor123")
        print(f"  Linda:  linda@email.com / vendor123")
        print("\nVENDORS CREATED:")
        for v in created_vendors:
            print(f"  [{v.role.upper()}] {v.name} — {v.email}" + (f" | Booth {v.booth_number} | Rent ${v.monthly_rent}/mo" if v.booth_number else ""))
        print(f"\nITEMS CREATED: {3 * 5} items (5 per vendor, 1 sale item each)")
        print(f"  Sale period: {today} to {sale_end}")
        print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
