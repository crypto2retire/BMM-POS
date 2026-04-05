# Task: Clear Cart When Receipt Modal is Closed

## Problem
After completing a cash (or any) sale, the receipt modal appears. If the cashier clicks the **X button** to close the receipt instead of clicking "New Sale →", the cart is NOT cleared. The old transaction stays in the POS, blocking the next sale.

## Root Cause
The X button on the receipt modal (line ~1068 in `frontend/pos/index.html`) just hides the modal:
```html
<button onclick="document.getElementById('receipt-modal').classList.add('hidden')" ...>✕</button>
```

It should call `startNewSale()` which properly clears the cart, resets all state, and hides the modal.

## Fix

### File: `frontend/pos/index.html`

Find this button (inside the receipt modal, around line 1068):

```html
<button onclick="document.getElementById('receipt-modal').classList.add('hidden')" style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--text-light);font-size:1.4rem;cursor:pointer;line-height:1;padding:4px 8px;z-index:1" title="Close">✕</button>
```

**Replace with:**

```html
<button onclick="startNewSale()" style="position:absolute;top:10px;right:14px;background:none;border:none;color:var(--text-light);font-size:1.4rem;cursor:pointer;line-height:1;padding:4px 8px;z-index:1" title="Close">✕</button>
```

That's it — one attribute change: `onclick="startNewSale()"`.

The `startNewSale()` function (already exists at line ~2577) does everything needed:
- Clears the cart array
- Resets currentSale, discounts, Poynt state
- Hides the receipt modal
- Re-renders the empty cart
- Focuses the barcode input
- Shows "Ready for next sale" toast

## Testing
1. Scan an item, complete a cash sale
2. When the receipt appears, click the **X button** (not "New Sale")
3. Verify the cart is empty and ready for the next transaction
4. Repeat with card payment to confirm same behavior
5. Also verify the "New Sale →" button still works as before

## One file changed
- `frontend/pos/index.html` (one onclick attribute)
