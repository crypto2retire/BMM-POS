# Phase 4: Poynt Payment Bridge — Claude Code Prompt

Copy this entire prompt and paste it into Claude Code when you're in the BMM-POS directory.

---

**PASTE EVERYTHING BELOW THIS LINE INTO CLAUDE CODE:**

---

Read CLAUDE.md first for full project context.

I need you to add the Phase 4 Poynt Payment Bridge enhancements to the current codebase. The current code already has basic Poynt endpoints (`/poynt/charge` and `/poynt/status/{reference_id}`) and a working poynt.py service. I need you to add DB tracking, a callback endpoint, and a Terminal/Manual choice modal. Apply these changes EXACTLY as specified:

## 1. Create NEW file: `app/models/poynt_payment.py`

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PoyntPayment(Base):
    __tablename__ = "poynt_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    poynt_transaction_id: Mapped[Optional[str]] = mapped_column(String(200))
    sale_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

## 2. Create NEW file: `migrations/003_poynt_payments.sql`

```sql
CREATE TABLE IF NOT EXISTS poynt_payments (
    id SERIAL PRIMARY KEY,
    reference_id VARCHAR(100) UNIQUE,
    amount_cents INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    poynt_transaction_id VARCHAR(200),
    sale_id INTEGER REFERENCES sales(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id);
CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status);
```

## 3. Edit `app/models/__init__.py`

Add this import and include PoyntPayment in __all__:

```python
from app.models.poynt_payment import PoyntPayment
```

Add `"PoyntPayment"` to the `__all__` list.

## 4. Edit `app/main.py`

Inside the lifespan function, in the `try` block that does column migrations (after the `balance_adjustments` CREATE TABLE), add:

```python
            # Poynt payments table (Phase 4)
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS poynt_payments (
                    id SERIAL PRIMARY KEY,
                    reference_id VARCHAR(100) UNIQUE,
                    amount_cents INTEGER,
                    status VARCHAR(20) DEFAULT 'pending',
                    poynt_transaction_id VARCHAR(200),
                    sale_id INTEGER REFERENCES sales(id),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status)"
            ))
```

Place this BEFORE the `await session.commit()` line.

## 5. Edit `app/routers/pos.py`

Add these imports at the top (alongside existing imports):

```python
import uuid
from fastapi import Request
from app.models.poynt_payment import PoyntPayment
```

Then REPLACE the existing `poynt_charge` endpoint with this version that creates a DB record:

```python
@router.post("/poynt/charge", response_model=PoyntChargeResponse)
async def poynt_charge(
    request: Request,
    data: PoyntChargeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")
    amount_cents = math.ceil(data.amount * 100)
    reference_id = f"BMM-{uuid.uuid4().hex[:12]}"

    # Create pending payment record
    payment = PoyntPayment(
        reference_id=reference_id,
        amount_cents=amount_cents,
        status="pending",
    )
    db.add(payment)
    await db.commit()

    try:
        await poynt.send_payment_to_terminal(
            amount_cents=amount_cents,
            currency="USD",
            order_ref=reference_id,
        )
    except Exception as e:
        payment.status = "error"
        await db.commit()
        raise

    return PoyntChargeResponse(reference_id=reference_id)
```

REPLACE the existing `poynt_status` endpoint with this version that reads from DB:

```python
@router.get("/poynt/status/{reference_id}", response_model=PoyntStatusResponse)
async def poynt_status(
    reference_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(
        select(PoyntPayment).where(PoyntPayment.reference_id == reference_id)
    )
    payment = result.scalar_one_or_none()

    if not payment:
        # Fall back to polling Poynt API directly
        api_result = await poynt.check_terminal_payment(reference_id)
        return PoyntStatusResponse(
            status=api_result["status"].lower(),
            transaction_id=api_result.get("transaction_id"),
            amount_cents=api_result.get("amount_cents"),
        )

    return PoyntStatusResponse(
        status=payment.status,
        transaction_id=payment.poynt_transaction_id,
        amount_cents=payment.amount_cents,
    )
```

ADD this NEW callback endpoint (place it right after the poynt_status endpoint). This endpoint is PUBLIC (no auth) so Poynt servers can call it:

```python
@router.post("/poynt/callback", status_code=status.HTTP_200_OK)
async def poynt_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Callback from Poynt terminal — updates payment status."""
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok"}

    reference_id = None
    txn_status = "pending"
    txn_id = None

    # Extract reference_id from various payload locations
    if "referenceId" in payload:
        reference_id = payload["referenceId"]
    elif "notes" in payload:
        reference_id = payload["notes"]
    elif "transactions" in payload:
        for txn in payload.get("transactions", []):
            for ref in txn.get("references", []):
                if ref.get("id", "").startswith("BMM-"):
                    reference_id = ref["id"]
                    break

    # Extract status
    raw_status = payload.get("status", "")
    if isinstance(payload.get("transactions"), list) and payload["transactions"]:
        raw_status = payload["transactions"][0].get("status", raw_status)
        txn_id = str(payload["transactions"][0].get("id", ""))

    if raw_status.upper() in ("APPROVED", "CAPTURED", "AUTHORIZED"):
        txn_status = "approved"
    elif raw_status.upper() in ("DECLINED", "VOIDED", "REFUNDED", "FAILED"):
        txn_status = "declined"

    if reference_id:
        result = await db.execute(
            select(PoyntPayment).where(PoyntPayment.reference_id == reference_id)
        )
        payment = result.scalar_one_or_none()
        if payment and payment.status == "pending":
            payment.status = txn_status
            if txn_id:
                payment.poynt_transaction_id = txn_id
            await db.commit()

    return {"status": "ok"}
```

Also REMOVE the old `/payment-callback` stub endpoint if it exists (the one that just returns `{"status": "ok"}` with no logic).

## 6. Edit `app/schemas/sale.py`

Update the `PoyntChargeRequest` to use `sale_reference` instead of `order_ref`:

```python
class PoyntChargeRequest(BaseModel):
    amount: float
    sale_reference: str = ""
```

Update `PoyntChargeResponse` to include success and message:

```python
class PoyntChargeResponse(BaseModel):
    success: bool = True
    reference_id: str
    message: str = "Payment sent to terminal"
```

Update `PoyntStatusResponse` — rename transaction_id to poynt_transaction_id:

```python
class PoyntStatusResponse(BaseModel):
    status: str
    poynt_transaction_id: Optional[str] = None
    amount_cents: Optional[int] = None
```

NOTE: After changing the schema field names, make sure all references in pos.py are updated accordingly (transaction_id → poynt_transaction_id in the response construction).

## 7. Edit `frontend/pos/index.html`

### 7a. Change the CARD button (around line 918):

Replace:
```html
<button class="pay-btn card" id="card-btn" onclick="startCardPayment()" disabled>
    💳 CARD (Poynt)
</button>
```

With:
```html
<button class="pay-btn card" id="card-btn" onclick="openCardChoice()" disabled>
    💳 CARD
</button>
```

### 7b. Add a card choice modal (after the existing card-overlay div, around line 995):

```html
<!-- Card Choice Modal -->
<div class="pos-modal-overlay hidden" id="card-choice-modal">
    <div class="pos-modal" style="max-width:400px">
        <h2>💳 Card Payment</h2>
        <div id="card-choice-amount" style="font-size:1.8rem;font-weight:800;color:#C9A96E;text-align:center;margin:1rem 0"></div>
        <div style="display:flex;flex-direction:column;gap:0.75rem;margin:1.5rem 0">
            <button onclick="startTerminalPayment()" style="padding:1rem;background:#1a4b8c;border:1px solid #1a4b8c;color:#fff;font-weight:700;font-size:1rem;cursor:pointer;font-family:'Roboto',sans-serif">
                📡 Charge Terminal
            </button>
            <button onclick="startManualCard()" style="padding:1rem;background:#374151;border:1px solid #555;color:#D1D5DB;font-weight:600;font-size:0.95rem;cursor:pointer;font-family:'Roboto',sans-serif">
                ⌨ Manual Card Entry
            </button>
        </div>
        <button onclick="document.getElementById('card-choice-modal').classList.add('hidden')" class="cancel-btn" style="width:100%">Cancel</button>
    </div>
</div>
```

### 7c. Add state variables (in the State section near line 1473):

Add after the existing `poyntOrderId` and `poyntPollTimer` variables:

```javascript
let poyntReferenceId = null;
let poyntPollCount = 0;
let poyntPollStart = null;
```

### 7d. Add new JavaScript functions (in the script section, after the existing `cancelCardPayment` function):

```javascript
    function openCardChoice() {
        if (cart.length === 0) return;
        const { total } = calcTotals();
        document.getElementById('card-choice-amount').textContent = '$' + total.toFixed(2);
        document.getElementById('card-choice-modal').classList.remove('hidden');
    }

    async function startTerminalPayment() {
        document.getElementById('card-choice-modal').classList.add('hidden');
        const { total } = calcTotals();

        // Show the waiting overlay with spinner
        document.getElementById('card-amount-display').textContent = '$' + total.toFixed(2);
        document.getElementById('card-confirm-btn').disabled = true;
        document.getElementById('card-confirm-btn').textContent = 'Waiting for terminal...';
        document.getElementById('card-overlay').classList.remove('hidden');

        try {
            const resp = await apiPost('/api/v1/pos/poynt/charge', {
                amount: total,
                sale_reference: 'POS-' + Date.now()
            });
            poyntReferenceId = resp.reference_id;
            poyntPollStart = Date.now();
            poyntPollCount = 0;
            pollPoyntStatus();
        } catch (err) {
            document.getElementById('card-overlay').classList.add('hidden');
            showToast('Failed to send to terminal: ' + err.message, 'error');
        }
    }

    async function pollPoyntStatus() {
        if (!poyntReferenceId) return;

        // 90-second timeout
        if (Date.now() - poyntPollStart > 90000) {
            document.getElementById('card-confirm-btn').disabled = false;
            document.getElementById('card-confirm-btn').textContent = '⏱ Timed out — Tap to Retry';
            document.getElementById('card-confirm-btn').onclick = retryTerminalPayment;
            return;
        }

        try {
            const resp = await apiGet('/api/v1/pos/poynt/status/' + poyntReferenceId);

            if (resp.status === 'approved' || resp.status === 'APPROVED' || resp.status === 'CAPTURED') {
                // Payment approved — record the sale
                clearInterval(poyntPollTimer);
                document.getElementById('card-confirm-btn').textContent = 'Payment approved! Recording...';
                try {
                    const payload = buildSalePayload('card');
                    payload.card_transaction_id = resp.poynt_transaction_id || resp.transaction_id || poyntReferenceId;
                    const sale = await apiPost('/api/v1/pos/sale', payload);
                    currentSale = sale;
                    document.getElementById('card-overlay').classList.add('hidden');
                    showReceiptModal(sale);
                    poyntReferenceId = null;
                } catch (saleErr) {
                    showToast('Payment approved but sale recording failed: ' + saleErr.message, 'error');
                    document.getElementById('card-confirm-btn').disabled = false;
                    document.getElementById('card-confirm-btn').textContent = 'Retry Record Sale';
                    document.getElementById('card-confirm-btn').onclick = confirmCardPayment;
                }
            } else if (resp.status === 'declined' || resp.status === 'DECLINED') {
                document.getElementById('card-confirm-btn').disabled = false;
                document.getElementById('card-confirm-btn').textContent = '❌ Declined — Tap to Retry';
                document.getElementById('card-confirm-btn').onclick = retryTerminalPayment;
                showToast('Card was declined', 'error');
            } else {
                // Still pending — poll again in 3 seconds
                poyntPollTimer = setTimeout(pollPoyntStatus, 3000);
            }
        } catch (err) {
            // Network error — keep trying
            poyntPollTimer = setTimeout(pollPoyntStatus, 3000);
        }
    }

    function retryTerminalPayment() {
        poyntReferenceId = null;
        document.getElementById('card-overlay').classList.add('hidden');
        startTerminalPayment();
    }

    async function startManualCard() {
        document.getElementById('card-choice-modal').classList.add('hidden');
        // Use the existing manual card flow
        startCardPayment();
    }
```

### 7e. Update the cancelCardPayment function to also clear Poynt state:

Replace the existing `cancelCardPayment` function with:

```javascript
    function cancelCardPayment() {
        document.getElementById('card-overlay').classList.add('hidden');
        poyntReferenceId = null;
        poyntPollCount = 0;
        poyntPollStart = null;
        if (poyntPollTimer) { clearTimeout(poyntPollTimer); poyntPollTimer = null; }
        // Reset the confirm button to default state
        document.getElementById('card-confirm-btn').disabled = false;
        document.getElementById('card-confirm-btn').textContent = 'Payment Received ✓';
        document.getElementById('card-confirm-btn').onclick = function() { confirmCardPayment(); };
        document.getElementById('barcode-input').focus();
    }
```

## 8. Add Poynt env vars to `app/config.py`

Add these 5 fields to the Settings class (after the existing `square_application_id` line):

```python
    poynt_app_id: str = ""
    poynt_business_id: str = ""
    poynt_store_id: str = ""
    poynt_terminal_id: str = ""
    poynt_private_key: str = ""
```

## IMPORTANT NOTES:
- Do NOT modify any files other than the ones listed above
- Do NOT change existing endpoint paths — keep `/poynt/charge` and `/poynt/status/{reference_id}` (with slash, not dash)
- Make sure the `poynt_callback` endpoint does NOT require authentication (no `Depends(get_current_user)`)
- Test that imports are correct after changes
- After making all changes, commit with message: "Phase 4: Add Poynt Payment Bridge — DB tracking, callback endpoint, terminal/manual choice modal"
- Then push to origin main: `git push origin main`
