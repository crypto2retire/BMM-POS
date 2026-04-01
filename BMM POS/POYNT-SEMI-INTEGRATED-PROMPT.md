# Semi-Integrated Poynt Flow — Claude Code Prompt

Copy everything below the line into Claude Code (in the BMM-POS directory).

---

**PASTE EVERYTHING BELOW INTO CLAUDE CODE:**

---

Read CLAUDE.md first for context.

I need to update the Poynt terminal payment flow to use a "semi-integrated" approach. The Cloud Messages API doesn't work with our GoDaddy Poynt credentials, so instead of sending the payment amount to the terminal automatically, the cashier will enter the amount on the terminal manually, and the POS will poll the Poynt Transactions API to detect when the payment completes.

Apply these changes:

## 1. Update `frontend/pos/index.html`

### 1a. Update the choice modal's "Charge Terminal" button text

In the `card-choice-modal` div, change the "Charge Terminal" button text from:
```
📡 Charge Terminal
```
to:
```
📡 Terminal Payment
```

### 1b. Replace the `startTerminalPayment` function

Replace the entire `startTerminalPayment` function with this version that skips the Cloud Message and goes straight to polling:

```javascript
    async function startTerminalPayment() {
        document.getElementById('card-choice-modal').classList.add('hidden');
        const { total } = calcTotals();

        // Show the waiting overlay — cashier will enter amount on terminal manually
        document.getElementById('card-amount-display').textContent = '$' + total.toFixed(2);
        document.getElementById('card-confirm-btn').disabled = true;
        document.getElementById('card-confirm-btn').textContent = 'Waiting for terminal payment...';
        document.getElementById('card-overlay').classList.remove('hidden');

        // Update instructions in the overlay
        const instrEl = document.getElementById('card-overlay').querySelector('[data-instructions]');
        if (instrEl) instrEl.textContent = 'Enter this amount on the Poynt terminal and process the card. The POS will detect the payment automatically.';

        // Start polling the Transactions API for a matching payment
        poyntExpectedAmount = Math.round(total * 100); // amount in cents
        poyntPollStart = Date.now();
        poyntPollCount = 0;
        pollForTransaction();
    }
```

### 1c. Add `poyntExpectedAmount` state variable

Near the other poynt state variables (around `poyntReferenceId`, `poyntPollCount`, `poyntPollStart`), add:

```javascript
let poyntExpectedAmount = null;
```

### 1d. Add the `pollForTransaction` function

Add this new function right after the existing `pollPoyntStatus` function:

```javascript
    async function pollForTransaction() {
        // 120-second timeout (longer since cashier has to manually enter amount)
        if (Date.now() - poyntPollStart > 120000) {
            document.getElementById('card-confirm-btn').disabled = false;
            document.getElementById('card-confirm-btn').textContent = '⏱ No payment detected — Tap to Retry';
            document.getElementById('card-confirm-btn').onclick = function() { startTerminalPayment(); };
            return;
        }

        try {
            const resp = await apiGet('/api/v1/pos/poynt/poll-transactions?amount_cents=' + poyntExpectedAmount);

            if (resp.status === 'APPROVED') {
                // Found a matching transaction!
                clearTimeout(poyntPollTimer);
                document.getElementById('card-confirm-btn').textContent = 'Payment detected! Recording sale...';
                try {
                    const payload = buildSalePayload('card');
                    payload.card_transaction_id = resp.transaction_id || ('POYNT-' + Date.now());
                    const sale = await apiPost('/api/v1/pos/sale', payload);
                    currentSale = sale;
                    document.getElementById('card-overlay').classList.add('hidden');
                    showReceiptModal(sale);
                    poyntExpectedAmount = null;
                } catch (saleErr) {
                    showToast('Payment detected but sale recording failed: ' + saleErr.message, 'error');
                    document.getElementById('card-confirm-btn').disabled = false;
                    document.getElementById('card-confirm-btn').textContent = 'Retry Record Sale';
                    document.getElementById('card-confirm-btn').onclick = confirmCardPayment;
                }
            } else {
                // Not found yet — poll again in 3 seconds
                poyntPollTimer = setTimeout(pollForTransaction, 3000);
            }
        } catch (err) {
            // Network error — keep trying
            poyntPollTimer = setTimeout(pollForTransaction, 3000);
        }
    }
```

### 1e. Update the `retryTerminalPayment` function

Replace the existing function:
```javascript
    function retryTerminalPayment() {
        poyntReferenceId = null;
        poyntExpectedAmount = null;
        document.getElementById('card-overlay').classList.add('hidden');
        startTerminalPayment();
    }
```

### 1f. Update the card-overlay instructions div

In the card-overlay HTML (around line 983), change the instruction text div to include a `data-instructions` attribute:

Change:
```html
<div style="color:#A8A6A1;font-size:0.9rem;margin-bottom:1rem;line-height:1.4">
    Process this amount on the Poynt terminal, then confirm below once payment is complete.
</div>
```
To:
```html
<div data-instructions style="color:#A8A6A1;font-size:0.9rem;margin-bottom:1rem;line-height:1.4">
    Enter this amount on the Poynt terminal and process the card. The POS will detect the payment automatically.
</div>
```

### 1g. Update `cancelCardPayment` to also clear `poyntExpectedAmount`:

In the `cancelCardPayment` function, add `poyntExpectedAmount = null;` alongside the other state resets.

## 2. Add a new backend endpoint: `GET /api/v1/pos/poynt/poll-transactions`

In `app/routers/pos.py`, add this new endpoint (after the existing poynt endpoints):

```python
@router.get("/poynt/poll-transactions")
async def poynt_poll_transactions(
    amount_cents: int = Query(..., description="Expected transaction amount in cents"),
    current_user: Vendor = Depends(get_current_user),
):
    """Poll Poynt Transactions API for a recent transaction matching the expected amount."""
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await poynt.find_recent_transaction(amount_cents)
    return result
```

Make sure `Query` is imported from fastapi (it should already be).

## 3. Add `find_recent_transaction` to `app/services/poynt.py`

Add this new function at the end of the file:

```python
async def find_recent_transaction(amount_cents: int) -> dict:
    """Search recent transactions for one matching the expected amount (within last 2 minutes)."""
    app_id, private_key_pem, business_id, store_id, terminal_id = _get_config()
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{POYNT_API_BASE}/businesses/{business_id}/transactions",
            params={"limit": 5},
            headers={
                "Authorization": f"Bearer {token}",
                "api-version": "1.2",
            },
        )
        if resp.status_code != 200:
            logger.error(f"Poynt transaction poll error {resp.status_code}: {resp.text}")
            return {"status": "PENDING", "transaction_id": None}

        data = resp.json()
        transactions = data.get("list") or data.get("transactions") or []

        import time as _time
        now_ms = int(_time.time() * 1000)
        two_minutes_ago_ms = now_ms - 120000

        for txn in transactions:
            txn_status = txn.get("status", "")
            txn_amount = txn.get("amounts", {}).get("transactionAmount", 0)
            txn_created = txn.get("createdAt", 0)

            # Match by amount and recency (within last 2 minutes)
            if txn_amount == amount_cents and txn_created > two_minutes_ago_ms:
                txn_id = str(txn.get("id", ""))

                if txn_status in ("CAPTURED", "AUTHORIZED"):
                    return {
                        "status": "APPROVED",
                        "transaction_id": txn_id,
                        "amount_cents": txn_amount,
                    }
                elif txn_status in ("DECLINED", "VOIDED", "REFUNDED"):
                    return {
                        "status": "DECLINED",
                        "transaction_id": txn_id,
                    }

        return {"status": "PENDING", "transaction_id": None}
```

## IMPORTANT NOTES:
- Keep the existing `startCardPayment` and `confirmCardPayment` functions as they are (they're the Manual Card Entry fallback)
- Keep the existing `pollPoyntStatus` function (it's used by the DB-based polling when Cloud Messages eventually work)
- Keep the existing `/poynt/charge` and `/poynt/status` endpoints intact
- The new `find_recent_transaction` matches by AMOUNT and RECENCY (last 2 minutes) since we don't have a reference_id to match against
- After making all changes, commit with message: "Switch Poynt to semi-integrated: poll Transactions API instead of Cloud Messages"
- Then push to origin main
