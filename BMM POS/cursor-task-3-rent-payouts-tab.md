# Cursor Task 3: Add Rent & Payouts Tab to Admin Dashboard

## Overview
Add a new "Rent & Payouts" tab to the admin dashboard (`frontend/admin/index.html`) that shows a combined ledger of all rent payments and vendor payouts. This tab is for verification, searching, and taking action — recording rent payments and processing payouts.

## Backend (ALREADY DONE)
The API endpoint is already created:
- **`GET /api/v1/admin/rent-payout-ledger`** — returns `{ summary, vendor_cards, transactions }`

Response shape:
```json
{
  "summary": {
    "total_rent_owed": 15000.00,
    "rent_collected_this_month": 8500.00,
    "rent_outstanding": 6500.00,
    "total_payouts_processed": 42000.00,
    "total_payouts_pending": 3200.00,
    "total_vendor_balances": 12500.00,
    "month_label": "April 2026"
  },
  "vendor_cards": [
    { "id": 1, "name": "Sarah Johnson", "booth_number": "A-12", "balance": 245.50 }
  ],
  "transactions": [
    {
      "type": "rent",
      "date": "2026-04-01T14:30:00+00:00",
      "vendor_name": "Sarah Johnson",
      "vendor_id": 1,
      "amount": 175.00,
      "method": "check",
      "period": "2026-04",
      "status": "paid",
      "notes": ""
    },
    {
      "type": "payout",
      "date": "2026-04-01T10:00:00+00:00",
      "vendor_name": "Mike Chen",
      "vendor_id": 2,
      "amount": 320.00,
      "method": "check",
      "period": "2026-03",
      "status": "paid",
      "notes": ""
    }
  ]
}
```

## Frontend Task

### 1. Add Tab Navigation
Add a tab bar below the existing period-tabs area in `frontend/admin/index.html`. Two tabs:
- **Dashboard** (default, active) — shows everything currently visible
- **Rent & Payouts** — shows the new section, hides the dashboard content

Tab styling should match the existing `period-tab` class but be visually distinct as a primary navigation (bigger, maybe a gold underline style instead of filled background). Place it RIGHT AFTER the greeting/subtitle and BEFORE the period-tabs.

```html
<div class="main-tabs" style="display:flex;gap:0;margin-bottom:1.25rem;border-bottom:2px solid var(--border)">
    <button class="main-tab active" onclick="switchMainTab('dashboard',this)">Dashboard</button>
    <button class="main-tab" onclick="switchMainTab('rent-payouts',this)">Rent & Payouts</button>
</div>
```

CSS for main-tabs:
```css
.main-tab {
    padding: 0.65rem 1.5rem;
    font-size: 0.88rem;
    font-family: 'EB Garamond', Georgia, serif;
    font-weight: 500;
    color: var(--text-light);
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    cursor: pointer;
    transition: all 0.2s;
    margin-bottom: -2px;
}
.main-tab.active {
    color: var(--gold);
    border-bottom-color: var(--gold);
}
.main-tab:hover:not(.active) { color: var(--text); }
```

### 2. Wrap existing dashboard content
Wrap ALL existing dashboard content (period-tabs through the end of all current sections) in:
```html
<div id="tab-dashboard">
    <!-- all existing content -->
</div>
```

### 3. Create Rent & Payouts section
Add a new section AFTER `tab-dashboard`:
```html
<div id="tab-rent-payouts" style="display:none">
    <!-- Content described below -->
</div>
```

### 4. Rent & Payouts section content

#### 4a. Summary stat cards (6 cards)
Use the same `store-summary` / `sum-card` classes:
- **Total Rent Owed** (this month) — `sum-value white`
- **Rent Collected** (this month) — `sum-value green`
- **Rent Outstanding** — `sum-value` (gold, default)
- **Payouts Processed** — `sum-value green`
- **Payouts Pending** — `sum-value white`
- **Total Vendor Balances** — `sum-value` (gold)

Show the `month_label` as a subtitle above the cards.

#### 4b. Scrollable vendor balance cards
Horizontal scrollable row of small cards, one per vendor:
```html
<div style="display:flex;gap:0.65rem;overflow-x:auto;padding:0.5rem 0;margin-bottom:1.25rem">
    <!-- for each vendor_card -->
    <div style="min-width:140px;background:var(--surface);border:1px solid var(--border);padding:0.75rem;flex-shrink:0">
        <div style="font-size:0.65rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em">A-12</div>
        <div style="font-family:'EB Garamond',serif;font-size:0.95rem;color:var(--text);margin-top:0.15rem">Sarah Johnson</div>
        <div style="font-family:'EB Garamond',serif;font-size:1.25rem;color:var(--gold);margin-top:0.25rem">$245.50</div>
    </div>
</div>
```
- Negative balances should display in red (`var(--danger)`)
- Zero balances in `var(--text-light)`
- Positive balances in `var(--gold)`

#### 4c. Search/filter bar
```html
<div style="display:flex;flex-wrap:wrap;gap:0.65rem;margin-bottom:1rem;align-items:center">
    <input type="search" id="rp-search" placeholder="Search vendor name..." style="..." oninput="filterRPLedger()">
    <select id="rp-type-filter" onchange="filterRPLedger()">
        <option value="all">All Types</option>
        <option value="rent">Rent Payments</option>
        <option value="payout">Payouts</option>
    </select>
    <input type="month" id="rp-period-filter" onchange="filterRPLedger()">
    <input type="number" id="rp-amount-filter" step="0.01" placeholder="Amount..." oninput="filterRPLedger()">
</div>
```
All inputs should use the dark BMM style: `background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.55rem 0.75rem;font-size:0.88rem`.

#### 4d. Combined transaction table
```html
<div class="card" style="padding:0;overflow:hidden">
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Vendor</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Method</th>
                    <th>Period</th>
                    <th>Status</th>
                    <th>Notes</th>
                </tr>
            </thead>
            <tbody id="rp-ledger-tbody"></tbody>
        </table>
    </div>
</div>
```

Row rendering rules:
- **Type column**: Show "Rent" with a subtle colored badge (green background) or "Payout" (blue/gold background)
- **Amount**: Format as currency `$X,XXX.XX`
- **Date**: Format as `MMM DD, YYYY` (e.g., "Apr 01, 2026")
- **Period**: Format as `Mon YYYY` (e.g., "Apr 2026")
- **Status**: Color-coded — "paid" = green, "pending" = gold/amber, "outstanding" = red
- **Method**: Capitalize first letter

#### 4e. Action buttons
Below the search bar, add two action buttons:
```html
<div style="display:flex;gap:0.65rem;margin-bottom:1rem">
    <button class="process-btn" onclick="openRentModalFromLedger()">Record Rent Payment</button>
    <button class="process-btn" onclick="window.confirmProcessPayoutsHub()">Process Payouts</button>
</div>
```

The "Record Rent Payment" button should open the EXISTING rent modal (`rent-modal-overlay`) that is already in the page. The `openRentModalFromLedger()` function should:
1. Show a vendor selection dropdown (populated from vendor_cards data) before opening the rent modal
2. Set the selected vendor and open the existing modal

For "Process Payouts", reuse the existing `confirmProcessPayoutsHub()` function.

### 5. Tab switching JavaScript

```javascript
function switchMainTab(tab, btn) {
    document.querySelectorAll('.main-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-dashboard').style.display = tab === 'dashboard' ? '' : 'none';
    document.getElementById('tab-rent-payouts').style.display = tab === 'rent-payouts' ? '' : 'none';
    if (tab === 'rent-payouts') loadRPLedger();
}
```

### 6. Data loading JavaScript

```javascript
var _rpData = null;

async function loadRPLedger() {
    try {
        var res = await fetch('/api/v1/admin/rent-payout-ledger', {
            headers: { 'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token') }
        });
        if (!res.ok) throw new Error('Failed to load');
        _rpData = await res.json();
        renderRPSummary();
        renderRPVendorCards();
        renderRPTable();
    } catch (e) {
        console.error('Ledger load error:', e);
    }
}

function renderRPSummary() {
    var s = _rpData.summary;
    // Update the 6 summary card values
    document.getElementById('rp-rent-owed').textContent = '$' + s.total_rent_owed.toLocaleString('en-US', {minimumFractionDigits:2});
    // ... etc for all 6 cards
}

function renderRPVendorCards() {
    var container = document.getElementById('rp-vendor-cards');
    container.innerHTML = '';
    _rpData.vendor_cards.forEach(function(v) {
        var color = v.balance > 0 ? 'var(--gold)' : v.balance < 0 ? 'var(--danger)' : 'var(--text-light)';
        container.innerHTML += '...card HTML...';
    });
}

function renderRPTable() {
    var tbody = document.getElementById('rp-ledger-tbody');
    var search = (document.getElementById('rp-search').value || '').toLowerCase();
    var typeFilter = document.getElementById('rp-type-filter').value;
    var periodFilter = document.getElementById('rp-period-filter').value;
    var amountFilter = document.getElementById('rp-amount-filter').value;

    var filtered = _rpData.transactions.filter(function(t) {
        if (search && t.vendor_name.toLowerCase().indexOf(search) < 0) return false;
        if (typeFilter !== 'all' && t.type !== typeFilter) return false;
        if (periodFilter && t.period !== periodFilter) return false;
        if (amountFilter && Math.abs(t.amount - parseFloat(amountFilter)) > 0.01) return false;
        return true;
    });

    tbody.innerHTML = '';
    filtered.forEach(function(t) {
        // Render each row with proper formatting
    });
}

function filterRPLedger() {
    if (_rpData) renderRPTable();
}
```

### 7. "Record Rent Payment" from ledger
Add a small vendor-picker that appears when clicking "Record Rent Payment" from the ledger tab. This can be a simple dropdown overlay or prepend a vendor select to the existing rent modal. The simplest approach:

Create a small inline select before the rent modal opens:
```javascript
function openRentModalFromLedger() {
    // Show a quick vendor picker modal
    var cards = _rpData.vendor_cards;
    var html = '<select id="rp-pick-vendor" style="...">' +
        '<option value="">— Select vendor —</option>';
    cards.forEach(function(v) {
        html += '<option value="' + v.id + '">' + v.name + ' (' + v.booth_number + ')</option>';
    });
    html += '</select>';
    // Show this in a small overlay, then on selection call the existing openRentModalHub(vendorId, vendorName, monthlyRent)
}
```

Or simpler: add a vendor dropdown at the top of the existing rent modal that only appears when opened from the ledger tab.

## Design Rules (MUST FOLLOW)
- `border-radius: 0px` everywhere (no rounded corners)
- Colors: `--bg: #38383B`, `--gold: #C9A96E`, `--text: #F0EDE8`, `--surface: #44444A`, `--border: #555558`
- Heading font: `EB Garamond` italic
- Body font: `Roboto 300`
- Token: `sessionStorage.getItem('bmm_token')` — NEVER localStorage
- All form inputs: dark glass style matching existing inputs

## Files to modify
1. `frontend/admin/index.html` — Add tab nav, wrap dashboard content, add rent-payouts section HTML
2. `frontend/static/js/admin-vendor-dashboard.js` — Add tab switching, ledger loading, rendering, and filtering functions (OR add inline `<script>` in index.html if cleaner)

## Files NOT to modify
- `app/routers/admin.py` — endpoint already created
- Do NOT change nav links or other pages

## Testing checklist
- [ ] Dashboard tab shows all existing content (no regressions)
- [ ] Rent & Payouts tab loads transaction data on click
- [ ] Summary cards show correct numbers
- [ ] Vendor balance cards scroll horizontally
- [ ] Search by vendor name filters table
- [ ] Type filter (All/Rent/Payout) works
- [ ] Period filter works
- [ ] Amount filter works
- [ ] "Record Rent Payment" opens the existing rent modal with vendor selection
- [ ] "Process Payouts" opens existing payout confirmation
- [ ] Mobile responsive — cards stack, table scrolls horizontally
