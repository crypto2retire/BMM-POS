# Cursor Task 4: Dual-Balance Frontend Display

## Context
The backend now returns three balance numbers for each vendor:
- `sales_balance` — accumulated from POS sales, resets to $0 after payout
- `rent_balance` — prepaid rent credit (positive = ahead, negative = owes rent)
- `combined_balance` — `sales_balance + rent_balance` (the "bottom line")

The API responses have been updated:
- `/api/v1/admin/vendor-overview` → each vendor row now includes `sales_balance`, `rent_balance`, `combined_balance`
- `/api/v1/admin/rent-payout-ledger` → vendor cards now include `sales_balance`, `rent_balance`; summary includes `total_sales_balances`, `total_rent_balances`
- `/api/v1/vendors/{id}` → returns `sales_balance`, `rent_balance`, `current_balance` (= combined)
- `/api/v1/vendors/{id}/balance` → returns `balance` (sales), `rent_balance`, `combined_balance`

## Task 1: Admin Vendor Dashboard — Show All Three Balances

**File:** `frontend/static/js/admin-vendor-dashboard.js`

### 1A. Vendor Table Row
Currently the table shows one "Balance" column with `v.balance`. Change it to show all three numbers stacked in the cell.

Find the table header that says `Balance` and replace the single balance cell with a stacked display:

```
Sales: $X.XX
Rent: $X.XX
Combined: $X.XX
```

Combined should be bold and colored (red if negative, green if positive). Sales and Rent lines should be smaller, muted text.

**Replace the balance `<td>` in the table row** (around line 109-110):
```javascript
// OLD:
'<td style="color:' + (v.balance < 0 ? 'var(--danger)' : 'var(--success-light)') + ';font-weight:600">' +
fmt(v.balance) +

// NEW:
'<td>' +
'<div style="font-size:0.75rem;color:var(--text-light)">Sales: ' + fmt(v.sales_balance || 0) + '</div>' +
'<div style="font-size:0.75rem;color:var(--text-light)">Rent: <span style="color:' + ((v.rent_balance || 0) < 0 ? 'var(--danger)' : 'var(--text-light)') + '">' + fmt(v.rent_balance || 0) + '</span></div>' +
'<div style="font-weight:600;color:' + ((v.combined_balance || v.balance) < 0 ? 'var(--danger)' : 'var(--success-light)') + '">' + fmt(v.combined_balance || v.balance) + '</div>' +
```

### 1B. Mobile Card Balance
Find the mobile card balance display (around line 137-138) and apply the same three-line treatment:

```javascript
// OLD:
'<div class="vh-mob-bal" style="color:' + (v.balance < 0 ? 'var(--danger)' : '') + '">' +
fmt(v.balance) +

// NEW:
'<div class="vh-mob-bal">' +
'<div style="font-size:0.7rem;color:var(--text-light)">Sales: ' + fmt(v.sales_balance || 0) + '</div>' +
'<div style="font-size:0.7rem;color:' + ((v.rent_balance || 0) < 0 ? 'var(--danger)' : 'var(--text-light)') + '">Rent: ' + fmt(v.rent_balance || 0) + '</div>' +
'<div style="font-weight:600;color:' + ((v.combined_balance || v.balance) < 0 ? 'var(--danger)' : 'var(--success-light)') + '">' + fmt(v.combined_balance || v.balance) + '</div>' +
```

### 1C. Accordion Detail Balance
Find the big balance display in the accordion detail section (around line 276-277) and show all three:

```javascript
// OLD:
'<p style="font-size:1.75rem;font-family:EB Garamond,serif;color:' + (v.balance < 0 ? 'var(--danger)' : 'var(--success-light)') + ';margin:0.25rem 0">' +
fmt(v.balance) +

// NEW:
'<div style="margin:0.5rem 0">' +
'<div style="font-size:0.85rem;color:var(--text-light);margin-bottom:0.25rem">Sales Balance: <span style="color:var(--gold)">' + fmt(v.sales_balance || 0) + '</span></div>' +
'<div style="font-size:0.85rem;color:var(--text-light);margin-bottom:0.25rem">Rent Balance: <span style="color:' + ((v.rent_balance || 0) < 0 ? 'var(--danger)' : 'var(--gold)') + '">' + fmt(v.rent_balance || 0) + '</span></div>' +
'<p style="font-size:1.75rem;font-family:EB Garamond,serif;color:' + ((v.combined_balance || v.balance) < 0 ? 'var(--danger)' : 'var(--success-light)') + ';margin:0.25rem 0">Combined: ' +
fmt(v.combined_balance || v.balance) +
'</p></div>' +
```

### 1D. Balance Adjust Modal
The `openAdjustModal` call (around line 358) passes `v.balance`. Update it to pass `v.sales_balance || v.balance` since adjustments apply to the sales balance:

```javascript
// OLD:
window.openAdjustModal(id, v.name, v.balance);

// NEW:
window.openAdjustModal(id, v.name, v.sales_balance || v.balance);
```

## Task 2: Rent & Payouts Tab — Vendor Balance Cards

**File:** `frontend/admin/index.html`

Find where the Rent & Payouts tab renders vendor balance cards (the horizontal scrolling card strip). Each card currently shows one balance number. Update to show all three:

In the card rendering, replace the single balance display with:
```html
<div style="font-size:0.75rem;color:var(--text-light)">Sales: $X.XX</div>
<div style="font-size:0.75rem;color:var(--text-light)">Rent: $X.XX</div>
<div style="font-size:1.1rem;font-weight:600;color:COLOR">$COMBINED</div>
```

The data is now available as `card.sales_balance` and `card.rent_balance` in addition to `card.balance`.

Also update the summary stat card for "Total Vendor Balances" to show the breakdown:
- The summary now includes `total_sales_balances` and `total_rent_balances` in addition to `total_vendor_balances`

## Task 3: Vendor Dashboard — Show Breakdown

**File:** `frontend/vendor/dashboard.html`

### 3A. Replace Single Balance Card with Three Cards
Currently there's one card showing "Current Balance" (line 78-82). Replace with three balance cards in the stats grid:

```html
<div class="card">
    <div class="card-title">Sales Balance</div>
    <div class="card-value green" id="sales-balance">—</div>
</div>
<div class="card">
    <div class="card-title">Rent Balance</div>
    <div class="card-value" id="rent-balance">—</div>
</div>
<div class="card">
    <div class="card-title">Combined Balance</div>
    <div class="card-value green" id="balance">—</div>
</div>
```

### 3B. Update JavaScript to Populate All Three
Find the line that sets the balance text (around line 378):

```javascript
// OLD:
document.getElementById("balance").textContent = `$${parseFloat(vendor.current_balance || 0).toFixed(2)}`;

// NEW:
const salesBal = parseFloat(vendor.sales_balance || 0);
const rentBal = parseFloat(vendor.rent_balance || 0);
const combinedBal = parseFloat(vendor.current_balance || 0);

document.getElementById("sales-balance").textContent = `$${salesBal.toFixed(2)}`;

const rentEl = document.getElementById("rent-balance");
rentEl.textContent = `$${rentBal.toFixed(2)}`;
rentEl.className = 'card-value ' + (rentBal < 0 ? 'red' : 'green');

const balEl = document.getElementById("balance");
balEl.textContent = `$${combinedBal.toFixed(2)}`;
balEl.className = 'card-value ' + (combinedBal < 0 ? 'red' : 'green');
```

Make sure the `.red` class exists or use inline style `color: var(--danger)` for negative values.

## Task 4: Cache Busting

After making changes, update the cache-buster query strings on any modified JS files in the HTML that loads them.

In `frontend/admin/index.html`, find the script tags and bump the version:
```html
<script src="/static/js/admin-vendor-dashboard.js?v=20260401c"></script>
```

## Design Notes
- Follow the existing BMM-POS design language: dark background, gold accents, EB Garamond for headings, Roboto for body
- `var(--danger)` = red for negative values
- `var(--success-light)` or `var(--gold)` for positive values
- `var(--text-light)` for muted labels
- Keep `border-radius: 0px` everywhere
- The `fmt()` function already formats numbers as currency — use it for all balance displays

## Testing
1. Log in as admin → Vendor Dashboard tab → verify each vendor row shows Sales, Rent, and Combined balance
2. Expand a vendor accordion → verify the detail shows all three balances
3. Check mobile view → verify mobile cards show all three
4. Click Rent & Payouts tab → verify balance cards show breakdown
5. Log in as a vendor → verify dashboard shows three balance cards
6. Verify negative rent balances show in red
