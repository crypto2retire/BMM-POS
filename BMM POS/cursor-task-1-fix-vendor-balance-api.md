# Task 1 (QUICK FIX): Make Vendor API Return Balance Data

## Problem
The `VendorResponse` schema was just updated to include `current_balance`, but the API endpoints don't populate it. This means all balances show $0.

## What Was Already Done
`app/schemas/vendor.py` — `VendorResponse` now has:
```python
current_balance: Optional[Decimal] = Decimal("0.00")
```

## Changes Needed

### 1. `app/routers/vendors.py` — Update `list_vendors` (around line 19)

Replace the function with:

```python
@router.get("/", response_model=List[VendorResponse])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin"))
):
    result = await db.execute(select(Vendor).order_by(Vendor.name))
    vendors = result.scalars().all()

    # Fetch all balances in one query
    bal_result = await db.execute(
        select(VendorBalance.vendor_id, VendorBalance.balance)
    )
    balance_map = {row.vendor_id: row.balance for row in bal_result.all()}

    for v in vendors:
        v.current_balance = balance_map.get(v.id, Decimal("0.00"))

    return vendors
```

### 2. `app/routers/vendors.py` — Update `get_vendor` (around line 59)

Replace the function with:

```python
@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user)
):
    if current_user.role != "admin" and current_user.id != vendor_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    bal_result = await db.execute(
        select(VendorBalance.balance).where(VendorBalance.vendor_id == vendor_id)
    )
    bal = bal_result.scalar_one_or_none()
    vendor.current_balance = bal if bal is not None else Decimal("0.00")

    return vendor
```

### 3. `app/main.py` — Add vendor_balances backfill (after the consignment cleanup block, around line 298)

Add this new block:

```python
    # ── Ensure every vendor has a vendor_balances row ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                INSERT INTO vendor_balances (vendor_id, balance)
                SELECT v.id, 0.00
                FROM vendors v
                LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
                WHERE vb.id IS NULL
            """))
            await session.commit()
            count = result.rowcount
            if count > 0:
                print(f"BMM-POS: Created missing vendor_balances rows for {count} vendors", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"BMM-POS: vendor_balances backfill note: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
```

## Imports Already Present
`VendorBalance` and `Decimal` are already imported in `vendors.py` — no new imports needed.

## Test
After deploy, check admin dashboard vendor list — balances should show actual numbers instead of $0.00.
