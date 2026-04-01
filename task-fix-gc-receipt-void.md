# Task: Fix Gift Card Payment — Receipt Print and Void Not Working

## Problem
After completing a gift card payment, the Print Receipt and Void buttons don't work. Root cause: `processGcPayment()` in `frontend/pos/index.html` never sets `currentSale = sale`, so `printReceipt()` and `openVoidModal()` (which both rely on `currentSale`) silently fail.

Secondary bug: `processGcPayment()` builds the items array manually instead of using `buildSalePayload()`, so any per-item or cart-wide discounts are lost on gift card payments.

## File to edit
`frontend/pos/index.html`

## The fix

Find `processGcPayment()` (around line ~2909). Current code:

```javascript
async function processGcPayment() {
    var bc = document.getElementById('gc-pay-barcode').value.replace(/\D/g, '').trim();
    var errEl = document.getElementById('gc-pay-error');
    if (!bc) { errEl.textContent = 'Please scan the gift card'; return; }
    errEl.textContent = '';
    var btn = document.getElementById('gc-pay-submit');
    btn.disabled = true; btn.textContent = 'Processing...';
    try {
        var items = cart.map(function(c) { return { barcode: c.item.barcode, quantity: c.quantity }; });
        var sale = await apiPost('/api/v1/pos/sale', {
            items: items,
            payment_method: 'gift_card',
            gift_card_barcode: bc
        });
        closeGcPayModal();
        cart = [];
        renderCart();
        showReceiptModal(sale);
    } catch (err) {
        errEl.textContent = err.message || 'Payment failed';
    } finally {
        btn.disabled = false; btn.textContent = 'Pay with Gift Card';
    }
}
```

Replace with:

```javascript
async function processGcPayment() {
    var bc = document.getElementById('gc-pay-barcode').value.replace(/\D/g, '').trim();
    var errEl = document.getElementById('gc-pay-error');
    if (!bc) { errEl.textContent = 'Please scan the gift card'; return; }
    errEl.textContent = '';
    var btn = document.getElementById('gc-pay-submit');
    btn.disabled = true; btn.textContent = 'Processing...';
    try {
        var payload = buildSalePayload('gift_card');
        payload.gift_card_barcode = bc;
        var sale = await apiPost('/api/v1/pos/sale', payload);
        closeGcPayModal();
        currentSale = sale;
        cart = [];
        renderCart();
        showReceiptModal(sale);
    } catch (err) {
        errEl.textContent = err.message || 'Payment failed';
    } finally {
        btn.disabled = false; btn.textContent = 'Pay with Gift Card';
    }
}
```

Two changes:
1. **Added `currentSale = sale;`** before `showReceiptModal(sale)` — this fixes print receipt and void
2. **Uses `buildSalePayload('gift_card')`** instead of manually building items — this ensures discounts are included in gift card payments

## Test
1. Add items to cart, pay with gift card
2. After sale completes, click "Print Receipt" — should open print dialog
3. Click "Void This Sale" — should show void confirmation and work
4. Apply a discount to an item, then pay with gift card — discount should appear on receipt
5. Commit and push to main
