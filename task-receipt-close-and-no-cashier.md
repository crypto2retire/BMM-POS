# Task: Add X Close Button to Receipt Modal + Remove Cashier Names from Receipts

## File to edit
`frontend/pos/index.html`

---

## FIX 1: Add X close button to receipt modal

Find the receipt modal (around line ~1037-1044):

```html
<div class="pos-modal-overlay hidden" id="receipt-modal">
    <div class="pos-modal receipt-modal">
        <h2 id="receipt-modal-title">✅ Sale Complete</h2>
```

Add an X button in the upper right corner, right after the opening `<div class="pos-modal receipt-modal">` line:

```html
<div class="pos-modal-overlay hidden" id="receipt-modal">
    <div class="pos-modal receipt-modal" style="position:relative">
        <button onclick="document.getElementById('receipt-modal').classList.add('hidden')" style="position:absolute;top:10px;right:14px;background:none;border:none;color:#A8A6A1;font-size:1.4rem;cursor:pointer;line-height:1;padding:4px 8px;z-index:1" title="Close">✕</button>
        <h2 id="receipt-modal-title">✅ Sale Complete</h2>
```

---

## FIX 2: Remove cashier name from ALL receipt displays

There are 4 places where "Cashier: name" appears. Remove the cashier line from each:

### 2A. On-screen receipt in showReceiptModal() (~line 2281)

Find:
```javascript
                <p>Cashier: ${cashierName}</p>
                <p>Sale #${sale.id}</p>
```
Remove the Cashier line, keep Sale #:
```javascript
                <p>Sale #${sale.id}</p>
```

Also: the `cashierName` variable and `parseToken()` call at the top of this function (lines ~2190-2191) can stay — they might be used elsewhere. Just remove the line that displays it.

### 2B. Print receipt in printReceipt() (~line 2457)

Find:
```html
    <div><span class="meta-label">Cashier:</span> ${cashierName}</div>
    <div><span class="meta-label">Sale</span> #${sale.id}</div>
```
Remove the Cashier line:
```html
    <div><span class="meta-label">Sale</span> #${sale.id}</div>
```

### 2C. Receipt detail modal (~line 3360)

Find:
```javascript
                    <p>Cashier: ${cashierName}</p>
                    <p>Sale #${sale.id}</p>
```
Remove the Cashier line:
```javascript
                    <p>Sale #${sale.id}</p>
```

### 2D. Gift card transaction history (~line 2794)

Find:
```javascript
+ '<span style="color:#A8A6A1">' + escHtml(dateStr + ' ' + timeStr + ' · ' + (t.cashier_name||'') + (t.notes ? ' · ' + t.notes : '')) + '</span>'
```
Remove the cashier_name part:
```javascript
+ '<span style="color:#A8A6A1">' + escHtml(dateStr + ' ' + timeStr + (t.notes ? ' · ' + t.notes : '')) + '</span>'
```

---

## Test
1. Complete a sale — receipt modal should show X button in upper right
2. Click the X — modal closes
3. Receipt should NOT show "Cashier: Name" on screen
4. Print receipt should NOT show cashier name
5. Look up a past receipt — no cashier name
6. Check a gift card balance — transaction history should not show cashier names
7. Commit and push to main
