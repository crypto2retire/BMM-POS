# Task: Fix Tax Exempt Not Working in POS

## Problem
When a manual sale item is marked "Tax Exempt", the checkbox value is saved to the database correctly, and the backend sale endpoint already skips tax on tax-exempt items (see `app/routers/pos.py` line ~230). BUT the frontend `calcTotals()` function in `frontend/pos/index.html` ignores `is_tax_exempt` and taxes everything at 5%.

This means the total shown to the cashier includes tax on tax-exempt items, even though the backend will calculate it correctly. The displayed total is wrong.

## File to edit
`frontend/pos/index.html`

## The fix

### Step 1 — Update `calcTotals()` (around line ~1769)

Current code:
```javascript
function calcTotals() {
    let subtotal = 0;
    for (const { item, quantity } of cart) {
        subtotal += getActivePrice(item) * quantity;
    }
    const taxAmount = subtotal * TAX_RATE;
    const total = subtotal + taxAmount;
    return {
        subtotal: Math.round(subtotal * 100) / 100,
        taxAmount: Math.round(taxAmount * 100) / 100,
        total: Math.round(total * 100) / 100,
    };
}
```

Replace with:
```javascript
function calcTotals() {
    let subtotal = 0;
    let taxableSubtotal = 0;
    for (const { item, quantity } of cart) {
        const lineTotal = getActivePrice(item) * quantity;
        subtotal += lineTotal;
        if (!item.is_tax_exempt) {
            taxableSubtotal += lineTotal;
        }
    }
    const taxAmount = taxableSubtotal * TAX_RATE;
    const total = subtotal + taxAmount;
    return {
        subtotal: Math.round(subtotal * 100) / 100,
        taxAmount: Math.round(taxAmount * 100) / 100,
        total: Math.round(total * 100) / 100,
    };
}
```

### Step 2 — Show tax-exempt badge in cart rows

In the `renderCart()` function, around line ~1823 where the consignment tag is built, add a tax-exempt tag right after it:

```javascript
const taxExTag = item.is_tax_exempt ? ' <span style="background:#065F46;color:#6EE7B7;font-size:0.6rem;padding:1px 5px;border-radius:2px;font-weight:700;vertical-align:middle">TE</span>' : '';
```

Then append `${taxExTag}` right after `${consignTag}` in the HTML template on that same line.

### Step 3 — Verify the search/scan endpoint returns is_tax_exempt

Check that `app/routers/pos.py` search and scan endpoints include `is_tax_exempt` in their response. The `/api/v1/pos/search` and `/api/v1/pos/scan/{barcode}` endpoints should already return the full item object which includes this field. If not, add it.

## Test
1. Add a regular item to cart — tax should apply (5%)
2. Use manual entry with "Tax Exempt" checked — that item should show "TE" badge and NOT be taxed
3. Mix taxable + tax-exempt items — only taxable items should have tax applied
4. The total shown in POS should match what the backend calculates
5. Commit and push to main
