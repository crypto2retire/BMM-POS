# BMM-POS Critical Security Remediation Plan

## Overview
This plan addresses the 5 CRITICAL vulnerabilities identified in the security audit. Each phase builds on the previous. Estimated total effort: 3-4 days of focused development.

---

## Phase 1: Fix Race Conditions (Day 1)

### 1.1 POS Checkout — Inventory Overselling
**Files:** `app/routers/pos.py` (lines ~538-720)

**Problem:** Two concurrent sales can both check `item.quantity >= cart_item.quantity`, both pass, then both decrement → negative inventory.

**Solution:** Lock all cart items at the start of the transaction with `with_for_update()`.

**Implementation:**
```python
# In pos_create_sale(), BEFORE the cart validation loop (around line 538):

# 1. Lock all items in the cart first
barcodes = [ci.barcode for ci in data.items]
item_lock_result = await db.execute(
    select(Item)
    .options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants))
    .where(Item.barcode.in_(barcodes))
    .with_for_update()
)
locked_items = {i.barcode: i for i in item_lock_result.scalars().all()}

# 2. Replace the cart loop to use locked items
resolved_lines = []
for cart_item in data.items:
    item = locked_items.get(cart_item.barcode)
    if not item:
        raise HTTPException(status_code=404, detail=f"Item with barcode {cart_item.barcode!r} not found")
    if item.status != "active":
        raise HTTPException(status_code=400, detail=f"Item {item.name!r} is not available for sale")
    if item.quantity < cart_item.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock for {item.name!r}: have {item.quantity}, requested {cart_item.quantity}",
        )
    # ... rest of existing logic
```

**Testing:**
- Write a concurrency test that fires 10 simultaneous requests to buy the last item
- Verify only 1 succeeds, 9 get "Insufficient stock"

---

### 1.2 Sales Checkout — Same Race Condition
**Files:** `app/routers/sales.py` (lines ~145-273)

**Problem:** Same TOCTOU as POS. `create_sale()` selects items without locking.

**Solution:** Same pattern — lock items before quantity checks.

**Implementation:**
```python
# In create_sale(), after building resolved_items:
# Lock all items by ID
item_ids = [item.id for item, _, _, _ in resolved_items]
locked_result = await db.execute(
    select(Item).where(Item.id.in_(item_ids)).with_for_update()
)
locked_map = {i.id: i for i in locked_result.scalars().all()}

# Use locked items for quantity checks and updates
for item, qty, unit_price, line_total in resolved_items:
    locked_item = locked_map[item.id]
    # Check against locked_item.quantity
    if locked_item.quantity < qty:
        raise HTTPException(status_code=400, detail=f"Insufficient stock for {locked_item.name}")
    new_qty = locked_item.quantity - qty
    locked_item.quantity = new_qty
    if new_qty <= 0:
        locked_item.status = "sold"
```

---

### 1.3 Storefront Checkout — Reservation Race
**Files:** `app/routers/storefront.py` (lines ~465-480, 498-573)

**Problem:** `_load_checkout_items` checks stock without locking. Two online customers can reserve the same last item.

**Solution:** Add `with_for_update()` stock check and a `reserved_quantity` column to Item.

**Step 1 — Add migration for reserved_quantity:**
```sql
ALTER TABLE items ADD COLUMN IF NOT EXISTS reserved_quantity INTEGER NOT NULL DEFAULT 0;
```

**Step 2 — Update Item model:**
```python
# app/models/item.py
reserved_quantity: Mapped[int] = mapped_column(Integer, default=0)
```

**Step 3 — Lock and reserve in _load_checkout_items:**
```python
async def _load_checkout_items(db: AsyncSession, item_ids: list[int]) -> list[Item]:
    # Lock items first
    item_result = await db.execute(
        select(Item).where(Item.id.in_(item_ids)).with_for_update()
    )
    found_items = item_result.scalars().all()
    found_map = {item.id: item for item in found_items}
    
    ordered_items = []
    for item_id in item_ids:
        item = found_map.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item no longer available")
        # Check effective stock (quantity - reserved)
        effective_qty = item.quantity - item.reserved_quantity
        if effective_qty < 1:
            raise HTTPException(status_code=400, detail=f"{item.name} is out of stock")
        # Reserve it
        item.reserved_quantity += 1
        ordered_items.append(item)
    return ordered_items
```

**Step 4 — Commit reservation atomically with checkout creation**
The reservation increment happens inside the same transaction as the checkout creation.

---

### 1.4 Admin Payouts — Lost Updates
**Files:** `app/routers/admin.py` (lines ~733-878)

**Problem:** `process_payouts()` reads VendorBalance without locking. Concurrent runs overlap.

**Solution:** Lock each VendorBalance row before modifying.

**Implementation:**
```python
for v in vendors:
    # Lock the balance row
    bal_result = await db.execute(
        select(VendorBalance)
        .where(VendorBalance.vendor_id == v.id)
        .with_for_update()
    )
    bal = bal_result.scalar_one_or_none()
    # ... rest of existing logic
    # Also fix line 767: change `vendor.landing_page_fee` to `v.landing_page_fee`
```

---

### 1.5 Void Sale — Race Condition
**Files:** `app/routers/pos.py` (lines ~863-1008)

**Problem:** Sale row is locked, but Item rows are not when restoring quantities.

**Solution:** Lock items when restoring quantities in void.

**Implementation:**
```python
# After loading the sale and sale items, lock all related items
item_ids_to_restore = [si.item_id for si in sale.items]
if item_ids_to_restore:
    await db.execute(
        select(Item).where(Item.id.in_(item_ids_to_restore)).with_for_update()
    )

# Then proceed with quantity restoration
for sale_item in sale.items:
    item = await db.get(Item, sale_item.item_id)
    if item:
        item.quantity += sale_item.quantity
        if item.status == "sold":
            item.status = "active"
```

---

## Phase 2: Fix Payment Verification (Day 2)

### 2.1 Rent Confirmation — Verify Square Payment
**Files:** `app/routers/rent.py` (lines ~378-450)

**Problem:** `/rent-confirmed` marks rent as paid without verifying with Square.

**Solution:** Poll Square API before confirming.

**Implementation:**
```python
@app/routers/rent.py

async def verify_square_payment(payment_id: str) -> bool:
    """Call Square API to verify payment succeeded."""
    from app.services.square import _access_token
    import httpx
    
    token = _access_token()
    if not token:
        return False
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://connect.squareup.com/v2/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        payment = data.get("payment", {})
        return payment.get("status") == "COMPLETED"

# In rent_confirmed():
if not await verify_square_payment(data["square_payment_id"]):
    raise HTTPException(status_code=400, detail="Payment not verified with Square")
# ... proceed with existing logic
```

---

### 2.2 Storefront Payment — Verify + Deduct Inventory
**Files:** `app/routers/storefront.py` (lines ~580-620)

**Problem:** `/payment-confirmed` trusts client, never deducts inventory.

**Solution:** Verify Square payment, then atomically deduct inventory and release reservation.

**Implementation:**
```python
# In payment_confirmed():

# 1. Verify Square payment
if not await verify_square_payment(data["square_payment_id"]):
    raise HTTPException(status_code=400, detail="Payment verification failed")

# 2. Load reservations with item locks
res_result = await db.execute(
    select(Reservation)
    .where(Reservation.checkout_group_id == data["checkout_group_id"])
    .options(selectinload(Reservation.item))
)
reservations = res_result.scalars().all()

# 3. Lock items and finalize
item_ids = [r.item_id for r in reservations]
if item_ids:
    await db.execute(select(Item).where(Item.id.in_(item_ids)).with_for_update())

for r in reservations:
    r.status = "completed"
    r.square_payment_id = data["square_payment_id"]
    r.paid_at = datetime.utcnow()
    if r.item:
        # Deduct actual inventory and release reservation
        r.item.quantity -= 1
        r.item.reserved_quantity = max(0, r.item.reserved_quantity - 1)
        if r.item.quantity <= 0:
            r.item.status = "sold"

await db.commit()
```

---

### 2.3 Poynt Webhook — Add Signature Verification
**Files:** `app/routers/pos.py` (lines ~1077-1150)

**Problem:** Anyone can POST to `/pos/poynt/callback`.

**Solution:** Verify Poynt webhook signature using their public key.

**Implementation:**
```python
# Add to app/services/poynt.py:

import hmac
import hashlib
import base64

def verify_poynt_signature(payload: bytes, signature: str, key: str) -> bool:
    """Verify Poynt webhook HMAC signature."""
    if not signature or not key:
        return False
    expected = hmac.new(
        key.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

# In the callback handler:
async def poynt_callback(request: Request, ...):
    body = await request.body()
    signature = request.headers.get("Poynt-Signature") or request.headers.get("X-Poynt-Signature")
    
    # Use the webhook secret from config
    webhook_secret = settings.poynt_webhook_secret
    if webhook_secret and not verify_poynt_signature(body, signature, webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    data = await request.json()
    # ... rest of existing logic
```

**Note:** If Poynt uses a different signing scheme (e.g., JWT from their API), verify their specific documentation. The above is a standard HMAC pattern.

---

## Phase 3: Add Reservation TTL & Background Cleanup (Day 2-3)

### 3.1 Expire Abandoned Reservations
**File:** New background task in `app/main.py` lifespan.

**Problem:** Pending reservations never expire, permanently reserving inventory from abandoned carts.

**Solution:** Add a background task (in lifespan or via APScheduler) to expire old pending reservations.

**Implementation:**
```python
# In app/main.py lifespan, add:

async def expire_old_reservations(db: AsyncSession):
    """Release inventory from abandoned reservations older than 15 minutes."""
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    
    result = await db.execute(
        select(Reservation)
        .where(Reservation.status == "pending")
        .where(Reservation.created_at < cutoff)
        .options(selectinload(Reservation.item))
    )
    expired = result.scalars().all()
    
    for r in expired:
        r.status = "expired"
        if r.item:
            r.item.reserved_quantity = max(0, r.item.reserved_quantity - r.quantity)
    
    await db.commit()
    return len(expired)

# Call this every 5 minutes in the lifespan background task
```

**Note:** If not using a background task framework, you can trigger this on every startup or add an endpoint that an external cron calls.

---

## Phase 4: Add Idempotency Keys (Day 3)

### 4.1 Rent Payment Idempotency
**Files:** `app/routers/rent.py`, `app/services/rent_payments.py`

**Problem:** Multiple calls to `/rent-confirmed` with the same payment double-count rent.

**Solution:** Check for existing `RentPayment` with same `reference_tag` before processing.

**Implementation:**
```python
# In apply_rent_payment():

# Check for existing processed payment
existing = await db.execute(
    select(RentPayment).where(
        RentPayment.vendor_id == vendor_id,
        RentPayment.reference_tag == reference_tag,
        RentPayment.status.in_(["paid", "received"])
    )
)
if existing.scalar_one_or_none():
    return {"message": "Rent payment already processed", "already_processed": True}

# ... proceed with existing logic
```

---

### 4.2 Storefront Checkout Idempotency
**Files:** `app/routers/storefront.py`

**Problem:** Retries create duplicate reservations and payment links.

**Solution:** Accept client-provided `idempotency_key`, store it, return existing on retry.

**Implementation:**
```python
# In CreateCartPaymentRequest schema:
idempotency_key: Optional[str] = Field(None, max_length=64)

# In create_cart_payment():
client_key = data.idempotency_key or str(uuid.uuid4())

# Check for existing checkout with same key
existing = await db.execute(
    select(Reservation).where(
        Reservation.checkout_group_id == client_key,
        Reservation.status == "pending"
    ).limit(1)
)
if existing.scalar_one_or_none():
    # Return existing payment link
    return {"checkout_group_id": client_key, "payment_link": existing_link}
```

---

## Phase 5: Hardcoded Fixes (Day 3)

### 5.1 Fix Undefined Variable in Admin
**File:** `app/routers/admin.py` (lines 767, 933)

**Change:**
```python
# Change:
rent = float(v.monthly_rent or 0) + float(v.landing_page_fee or 0) + float(v.landing_page_fee or 0)
# From (broken):
# rent = float(v.monthly_rent or 0) + float(vendor.landing_page_fee or 0) ...
```

---

## Phase 6: Testing & Validation (Day 4)

### 6.1 Concurrency Tests
Write tests that fire multiple simultaneous requests:
```python
import asyncio
import httpx

async def test_overselling():
    """10 clients try to buy 1 item. Only 1 should succeed."""
    async with httpx.AsyncClient() as client:
        tasks = [
            client.post("/api/v1/pos/sale", json={
                "items": [{"barcode": "LAST-ITEM-01", "quantity": 1}]
            })
            for _ in range(10)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        successes = sum(1 for r in responses if getattr(r, 'status_code', 0) == 200)
        assert successes == 1, f"Expected 1 success, got {successes}"
```

### 6.2 Payment Verification Tests
- Mock Square API responses (success/failure)
- Verify `/payment-confirmed` rejects unverified payments
- Verify `/rent-confirmed` rejects unverified payments

### 6.3 Webhook Security Tests
- Send Poynt callback with missing signature → expect 401
- Send Poynt callback with wrong signature → expect 401
- Send valid signature → expect 200

### 6.4 Load Tests
- Run 100 concurrent checkout requests
- Verify response times stay under 500ms
- Verify no negative quantities in database

---

## Database Migrations Required

```sql
-- Phase 1: Add reserved_quantity to items
ALTER TABLE items ADD COLUMN IF NOT EXISTS reserved_quantity INTEGER NOT NULL DEFAULT 0;

-- Phase 2: Add idempotency key support to reservations
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);
CREATE INDEX ix_reservations_idempotency_key ON reservations(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Phase 3: Add unique constraint to prevent duplicate rent payments
CREATE UNIQUE INDEX ix_rent_payments_vendor_reference ON rent_payments(vendor_id, reference_tag) WHERE status IN ('paid', 'received');
```

---

## Rollout Strategy

1. **Deploy during off-hours** (mall closed, no active sales)
2. **Database migrations first** — add columns without breaking existing code
3. **Deploy code changes** — race condition fixes first, then payment verification
4. **Monitor error rates** for 24 hours after each deploy
5. **Run reconciliation report** — compare Square dashboard totals with local database totals
6. **Notify vendors** if any inventory discrepancies are found during the transition

---

## Success Criteria

- [ ] Concurrent checkout test passes (only 1 of 10 succeeds for last item)
- [ ] Payment confirmation test passes (rejects unverified payments)
- [ ] Poynt webhook test passes (rejects unsigned callbacks)
- [ ] No negative inventory quantities in database
- [ ] No duplicate RentPayment records for same reference_tag
- [ ] Reservation cleanup task runs every 5 minutes
- [ ] Response times under 500ms for checkout under load
