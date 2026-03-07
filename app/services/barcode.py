import os
import tempfile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.item import Item


async def generate_sku(vendor_id: int, db: AsyncSession) -> str:
    result = await db.execute(
        select(func.count(Item.id)).where(Item.vendor_id == vendor_id)
    )
    count = result.scalar() or 0
    sequence = count + 1
    while True:
        sku = f"BSM-{vendor_id:04d}-{sequence:06d}"
        existing = await db.execute(select(Item).where(Item.sku == sku))
        if not existing.scalar_one_or_none():
            return sku
        sequence += 1


def generate_barcode_image(barcode_value: str, output_path: str) -> str:
    import barcode
    from barcode.writer import ImageWriter

    code128 = barcode.get("code128", barcode_value, writer=ImageWriter())
    filename = output_path.replace(".png", "")
    saved = code128.save(filename)
    return saved
