# PRIORITY: Fix Vendor Balance Display — Balances Not Showing

## Problem
The vendor API endpoints (`GET /api/v1/vendors/` and `GET /api/v1/vendors/{vendor_id}`) do NOT return `current_balance`. The `VendorResponse` schema in `app/schemas/vendor.py` doesn't include it, and the endpoints don't join the `vendor_balances` table. The frontend reads `vendor.current_balance` which comes back as `undefined`, showing $0.00 everywhere.

The sale credit code in `pos.py` (lines 371-381) IS correctly writing to `vendor_balances`. The data is in the database — it's just not being sent to the frontend.

## Files to Change

### 1. `app/schemas/vendor.py` — Add `current_balance` to VendorResponse

Find the `VendorResponse` class and add `current_balance`:

```python
class VendorResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    booth_number: Optional[str] = None
    role: str
    is_active: bool
    is_vendor: bool = False
    monthly_rent: Decimal
    commission_rate: Decimal
    status: Optional[str] = "active"
    rent_flagged: Optional[bool] = False
    payout_method: Optional[str] = None
    zelle_handle: Optional[str] = None
    label_preference: Optional[str] = "standard"
    pdf_label_size: Optional[str] = "2.25x1.25"
    assistant_name: Optional[str] = None
    notes: Optional[str] = None
    theme_preference: Optional[str] = "dark"
    font_size_preference: Optional[str] = "medium"
    created_at: datetime
    current_balance: Optional[Decimal] = Decimal("0.00")   # <-- ADD THIS LINE

    class Config:
        from_attributes = True
```

### 2. `app/routers/vendors.py` — Join vendor_balances in both endpoints

**Replace the entire `list_vendors` function** (starts around line 19):

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

    # Attach current_balance to each vendor object
    for v in vendors:
        v.current_balance = balance_map.get(v.id, Decimal("0.00"))

    return vendors
```

**Replace the entire `get_vendor` function** (starts around line 59):

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

    # Attach current balance
    bal_result = await db.execute(
        select(VendorBalance.balance).where(VendorBalance.vendor_id == vendor_id)
    )
    bal = bal_result.scalar_one_or_none()
    vendor.current_balance = bal if bal is not None else Decimal("0.00")

    return vendor
```

**Make sure VendorBalance is imported** at the top of `app/routers/vendors.py`. Find the imports and add VendorBalance:

```python
from app.models.vendor import Vendor, VendorBalance
```

Also make sure `Decimal` is imported:

```python
from decimal import Decimal
```

### 3. `app/main.py` — Safety: Ensure all vendors have balance rows

In the lifespan function, AFTER the existing consignment cleanup block (around line 298), add this new block to ensure every vendor has a `vendor_balances` row:

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

## What This Fixes

1. **Admin dashboard** (`/admin/index.html`) — vendor table and cards will show actual balances instead of $0.00
2. **Vendor dashboard** (`/vendor/dashboard.html`) — "Current Balance" card will show actual balance
3. **Payout preview** — Already reads from `vendor_balances` directly, so that was working. But now the admin can SEE balances before processing payouts.
4. **Rent credits** — Rent payments are tracked in `rent_payments` table and correctly handled during payout processing. The confusion was that vendor balances appeared as $0 everywhere.

## Important Notes

- Do NOT change `pos.py` — the sale credit logic there is correct and working
- Do NOT change `admin.py` — the payout processing reads from `vendor_balances` directly
- The only issue was the vendor API not returning the balance data
- The `Decimal` import and `VendorBalance` import in `vendors.py` are critical

## Test After Deploy

1. Check admin dashboard — vendor balances should show non-zero for any vendor with sales
2. Check vendor dashboard — "Current Balance" should show actual balance
3. Make a test sale — vendor balance should increase
4. Check payout preview — gross sales column should match vendor balances
