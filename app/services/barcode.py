import os
import random
import re
import string
import tempfile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.item import Item

BARCODE_CHARS = string.digits
BARCODE_LENGTH = 6


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


async def generate_short_barcode(db: AsyncSession) -> str:
    for _ in range(100):  # safety limit
        code = "".join(random.choices(BARCODE_CHARS, k=BARCODE_LENGTH))
        existing = await db.execute(select(Item).where(Item.barcode == code))
        if not existing.scalar_one_or_none():
            return code
    raise RuntimeError("Failed to generate unique barcode after 100 attempts")


def generate_barcode_image(barcode_value: str, output_path: str) -> str:
    import barcode
    from barcode.writer import ImageWriter

    bc = barcode.get("code128", barcode_value, writer=ImageWriter())
    filename = output_path.replace(".png", "")
    saved = bc.save(filename)
    return saved


_SCANNABLE_BARCODE_RE = re.compile(r"^\d{6}$")


async def maybe_upgrade_barcode(item: Item, db: AsyncSession) -> bool:
    """
    Lazy conversion used by label reprint routes.

    If item.barcode is already a 6-digit numeric code, or is a manual-item
    placeholder (MAN-*), do nothing. Otherwise replace it with a fresh
    scanable 6-digit code so the new label prints with a Code128 Subset C
    barcode that fits the Dymo 30347 label and scans reliably.

    Caller is responsible for committing the session. We flush so that the
    uniqueness SELECT inside generate_short_barcode sees the new value when
    called repeatedly in a batch loop.

    Returns True if upgraded, False if left untouched.
    """
    import sys
    current = (item.barcode or "").strip()
    if not current:
        print(f"[BARCODE UPGRADE] item {item.id} '{item.name}': no barcode, skipping", file=sys.stderr)
        return False
    if current.startswith("MAN-"):
        print(f"[BARCODE UPGRADE] item {item.id} '{item.name}': MAN-* barcode '{current}', skipping", file=sys.stderr)
        return False
    if _SCANNABLE_BARCODE_RE.fullmatch(current):
        print(f"[BARCODE UPGRADE] item {item.id} '{item.name}': already 6-digit '{current}', skipping", file=sys.stderr)
        return False
    try:
        new_code = await generate_short_barcode(db)
        old_code = current
        item.barcode = new_code
        await db.flush()
        print(f"[BARCODE UPGRADE] item {item.id} '{item.name}': '{old_code}' -> '{new_code}'", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[BARCODE UPGRADE] item {item.id} '{item.name}': FAILED to upgrade '{current}': {e}", file=sys.stderr)
        return False
