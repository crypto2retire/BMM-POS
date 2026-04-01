# Task 3: Add Rent & Payouts Tab to Admin Dashboard

## Goal
Add a second top-level tab to the admin dashboard (`/admin/index.html`) called "Rent & Payouts". This tab shows a combined ledger of all rent payments and vendor payouts with summary stats, vendor balance cards, search/filtering, and action buttons. The existing dashboard content becomes the "Dashboard" tab.

## Design Language (MUST follow)
- `--bg: #38383B`, `--gold: #C9A96E`, `--surface: #44444A`, `--text: #F0EDE8`, `--border: #555558`
- `border-radius: 0px` everywhere — NO rounded corners
- Heading font: `EB Garamond` italic
- Body font: `Roboto 300`
- Gold accent borders, warm-border hover effects
- Status badges: green for paid/current, gold/amber for pending, red for overdue/outstanding
- Auth token: `sessionStorage.getItem('bmm_token')` — NEVER localStorage

## Backend (ALREADY DONE — do NOT modify)
The API endpoint already exists:

**`GET /api/v1/admin/rent-payout-ledger`**

Returns:
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

---

## Part A: Add Tab Navigation to index.html

### Step 1: Add CSS for main tabs
Add this CSS inside the existing `<style>` block in `frontend/admin/index.html`:

```css
.main-tabs {
    display: flex;
    gap: 0;
    margin-bottom: 1.25rem;
    border-bottom: 2px solid var(--border);
}
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

.rp-vendor-cards-row {
    display: flex;
    gap: 0.65rem;
    overflow-x: auto;
    padding: 0.5rem 0;
    margin-bottom: 1.25rem;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}
.rp-vendor-card {
    min-width: 140px;
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 0.75rem;
    flex-shrink: 0;
    transition: border-color 0.2s;
}
.rp-vendor-card:hover { border-color: var(--warm-border); }

.rp-type-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    font-size: 0.7rem;
    font-family: 'Roboto', sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
}
.rp-type-badge.rent {
    background: color-mix(in srgb, var(--success) 15%, transparent);
    color: var(--success-light);
    border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
}
.rp-type-badge.payout {
    background: color-mix(in srgb, var(--gold) 15%, transparent);
    color: var(--gold);
    border: 1px solid color-mix(in srgb, var(--gold) 30%, transparent);
}

.rp-status-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    font-size: 0.7rem;
    font-family: 'Roboto', sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.rp-status-badge.paid, .rp-status-badge.completed { color: var(--success-light); }
.rp-status-badge.pending { color: var(--gold); }
.rp-status-badge.outstanding, .rp-status-badge.overdue { color: var(--danger); }

.rp-filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.65rem;
    margin-bottom: 1rem;
    align-items: center;
}
.rp-filter-bar input, .rp-filter-bar select {
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.55rem 0.75rem;
    font-size: 0.88rem;
    font-family: 'Roboto', sans-serif;
    box-sizing: border-box;
}
.rp-filter-bar input:focus, .rp-filter-bar select:focus {
    border-color: var(--gold);
    outline: none;
    box-shadow: 0 0 0 2px var(--gold-glow);
}

.rp-action-bar {
    display: flex;
    gap: 0.65rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
}
```

### Step 2: Add tab buttons in the HTML body
Find this line in the HTML body:
```html
<div class="period-tabs">
```

Add this BEFORE it:
```html
<div class="main-tabs">
    <button class="main-tab active" onclick="switchMainTab('dashboard',this)">Dashboard</button>
    <button class="main-tab" onclick="switchMainTab('rent-payouts',this)">Rent & Payouts</button>
</div>
```

### Step 3: Wrap existing dashboard content
Wrap EVERYTHING from `<div class="period-tabs">` through the end of all existing sections (period-tabs, store-summary, ornament, vendor-hub-section, dash-row charts, online orders, employees, data import) in a wrapper div:

```html
<div id="tab-dashboard">
    <!-- ALL existing dashboard content goes here -->
</div>
```

Do NOT include the greeting, subtitle, or main-tabs in this wrapper — only the content that should hide when switching tabs.

### Step 4: Add the Rent & Payouts tab section
Add this AFTER the closing `</div>` of `tab-dashboard`:

```html
<div id="tab-rent-payouts" style="display:none">

    <div style="font-family:'EB Garamond',serif;font-style:italic;font-size:0.95rem;color:var(--text-light);margin-bottom:1rem" id="rp-month-label"></div>

    <!-- Summary stat cards -->
    <div class="store-summary" id="rp-summary-cards">
        <div class="sum-card"><div class="sum-label">Rent Owed (this month)</div><div class="sum-value white" id="rp-rent-owed">&mdash;</div></div>
        <div class="sum-card"><div class="sum-label">Rent Collected</div><div class="sum-value green" id="rp-rent-collected">&mdash;</div></div>
        <div class="sum-card"><div class="sum-label">Rent Outstanding</div><div class="sum-value" id="rp-rent-outstanding">&mdash;</div></div>
        <div class="sum-card"><div class="sum-label">Payouts Processed</div><div class="sum-value green" id="rp-payouts-processed">&mdash;</div></div>
        <div class="sum-card"><div class="sum-label">Payouts Pending</div><div class="sum-value white" id="rp-payouts-pending">&mdash;</div></div>
        <div class="sum-card"><div class="sum-label">Total Vendor Balances</div><div class="sum-value" id="rp-total-balances">&mdash;</div></div>
    </div>

    <div class="ornament">&loz;</div>

    <!-- Scrollable vendor balance cards -->
    <h3 style="font-family:'EB Garamond',serif;font-size:1.1rem;font-weight:500;color:var(--text);margin-bottom:0.5rem;font-style:italic">Vendor Balances</h3>
    <div class="rp-vendor-cards-row" id="rp-vendor-cards"></div>

    <div class="ornament">&loz;</div>

    <!-- Action buttons -->
    <div class="rp-action-bar">
        <button type="button" class="process-btn" onclick="openRentFromLedger()" style="background:color-mix(in srgb, var(--success-light) 12%, transparent);color:var(--success-light);border:1px solid color-mix(in srgb, var(--success-light) 30%, transparent);padding:0.55rem 1.2rem;font-size:0.78rem;cursor:pointer;font-family:'Roboto',sans-serif;text-transform:uppercase;letter-spacing:0.06em;min-height:44px">Record Rent Payment</button>
        <button type="button" class="process-btn" onclick="window.confirmProcessPayoutsHub()" style="background:color-mix(in srgb, var(--gold) 12%, transparent);color:var(--gold);border:1px solid color-mix(in srgb, var(--gold) 30%, transparent);padding:0.55rem 1.2rem;font-size:0.78rem;cursor:pointer;font-family:'Roboto',sans-serif;text-transform:uppercase;letter-spacing:0.06em;min-height:44px">Process Payouts</button>
    </div>

    <!-- Search and filter bar -->
    <div class="rp-filter-bar">
        <input type="search" id="rp-search" placeholder="Search vendor name..." oninput="filterRPLedger()" style="flex:1;min-width:180px;max-width:280px">
        <select id="rp-type-filter" onchange="filterRPLedger()">
            <option value="all">All Types</option>
            <option value="rent">Rent Payments</option>
            <option value="payout">Payouts</option>
        </select>
        <input type="month" id="rp-period-filter" onchange="filterRPLedger()">
        <input type="number" id="rp-amount-filter" step="0.01" placeholder="Amount..." oninput="filterRPLedger()" style="width:120px">
    </div>

    <!-- Combined transaction table -->
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

</div>
```

### Step 5: Vendor picker modal for recording rent from ledger
Add this modal HTML after the existing rent-modal-overlay:

```html
<div class="modal-overlay" id="rp-vendor-picker-overlay" style="display:none;position:fixed;inset:0;background:color-mix(in srgb, black 78%, transparent);z-index:1001;align-items:center;justify-content:center;padding:1rem" onclick="if(event.target===this)this.style.display='none'">
    <div style="background:var(--surface);border:1px solid var(--warm-border);padding:1.75rem;width:100%;max-width:380px;color:var(--text)" onclick="event.stopPropagation()">
        <h2 style="font-family:'EB Garamond',serif;font-size:1.35rem;font-weight:500;margin-bottom:1rem;color:var(--gold);font-style:italic">Select Vendor</h2>
        <select id="rp-pick-vendor" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:0.55rem 0.7rem;font-size:0.875rem;box-sizing:border-box;margin-bottom:1rem">
            <option value="">— Select vendor —</option>
        </select>
        <div style="display:flex;gap:0.5rem">
            <button type="button" onclick="document.getElementById('rp-vendor-picker-overlay').style.display='none'" style="flex:1;padding:0.7rem;background:var(--surface-2);color:var(--text-light);border:1px solid var(--border);cursor:pointer;font-size:0.78rem;font-family:'Roboto',sans-serif;text-transform:uppercase;letter-spacing:0.06em">Cancel</button>
            <button type="button" onclick="confirmVendorPick()" style="flex:1;padding:0.7rem;background:var(--gold);color:var(--charcoal-deep);border:none;cursor:pointer;font-size:0.78rem;font-family:'Roboto',sans-serif;text-transform:uppercase;letter-spacing:0.06em">Continue</button>
        </div>
    </div>
</div>
```

---

## Part B: JavaScript

Add this JavaScript. You can add it as a new `<script>` block at the end of the page, or add the functions to the existing inline script. Do NOT put this in a separate .js file — keep it inline in index.html.

```javascript
/* ─── Main Tab Switching ─── */
function switchMainTab(tab, btn) {
    document.querySelectorAll('.main-tab').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('tab-dashboard').style.display = tab === 'dashboard' ? '' : 'none';
    document.getElementById('tab-rent-payouts').style.display = tab === 'rent-payouts' ? '' : 'none';
    if (tab === 'rent-payouts' && !_rpData) loadRPLedger();
}

/* ─── Rent & Payouts Ledger ─── */
var _rpData = null;

function rpFmt(n) {
    return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function rpDateFmt(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
}

function rpPeriodFmt(p) {
    if (!p) return '—';
    var parts = p.split('-');
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return months[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
}

async function loadRPLedger() {
    try {
        var res = await fetch('/api/v1/admin/rent-payout-ledger', {
            headers: { 'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token') }
        });
        if (!res.ok) throw new Error('Failed to load ledger');
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
    document.getElementById('rp-month-label').textContent = s.month_label;
    document.getElementById('rp-rent-owed').textContent = rpFmt(s.total_rent_owed);
    document.getElementById('rp-rent-collected').textContent = rpFmt(s.rent_collected_this_month);
    document.getElementById('rp-rent-outstanding').textContent = rpFmt(s.rent_outstanding);
    document.getElementById('rp-payouts-processed').textContent = rpFmt(s.total_payouts_processed);
    document.getElementById('rp-payouts-pending').textContent = rpFmt(s.total_payouts_pending);
    document.getElementById('rp-total-balances').textContent = rpFmt(s.total_vendor_balances);
}

function renderRPVendorCards() {
    var container = document.getElementById('rp-vendor-cards');
    container.innerHTML = '';
    _rpData.vendor_cards.forEach(function(v) {
        var color = v.balance > 0 ? 'var(--gold)' : v.balance < 0 ? 'var(--danger)' : 'var(--text-light)';
        var card = document.createElement('div');
        card.className = 'rp-vendor-card';
        card.innerHTML =
            '<div style="font-size:0.65rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em">' + (v.booth_number || '—') + '</div>' +
            '<div style="font-family:\'EB Garamond\',serif;font-size:0.95rem;color:var(--text);margin-top:0.15rem">' + v.name + '</div>' +
            '<div style="font-family:\'EB Garamond\',serif;font-size:1.25rem;color:' + color + ';margin-top:0.25rem">' + rpFmt(v.balance) + '</div>';
        container.appendChild(card);
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
        if (amountFilter) {
            var target = parseFloat(amountFilter);
            if (!isNaN(target) && Math.abs(t.amount - target) > 0.50) return false;
        }
        return true;
    });

    tbody.innerHTML = '';
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-light);padding:2rem">No transactions found</td></tr>';
        return;
    }

    filtered.forEach(function(t) {
        var tr = document.createElement('tr');
        var typeBadge = '<span class="rp-type-badge ' + t.type + '">' + (t.type === 'rent' ? 'Rent' : 'Payout') + '</span>';
        var statusBadge = '<span class="rp-status-badge ' + t.status + '">' + t.status + '</span>';
        var method = t.method ? t.method.charAt(0).toUpperCase() + t.method.slice(1) : '—';

        tr.innerHTML =
            '<td>' + rpDateFmt(t.date) + '</td>' +
            '<td>' + t.vendor_name + '</td>' +
            '<td>' + typeBadge + '</td>' +
            '<td>' + rpFmt(t.amount) + '</td>' +
            '<td>' + method + '</td>' +
            '<td>' + rpPeriodFmt(t.period) + '</td>' +
            '<td>' + statusBadge + '</td>' +
            '<td style="font-size:0.82rem;color:var(--text-light)">' + (t.notes || '') + '</td>';
        tbody.appendChild(tr);
    });
}

function filterRPLedger() {
    if (_rpData) renderRPTable();
}

/* ─── Vendor Picker for Recording Rent from Ledger Tab ─── */
function openRentFromLedger() {
    if (!_rpData || !_rpData.vendor_cards) return;
    var sel = document.getElementById('rp-pick-vendor');
    sel.innerHTML = '<option value="">— Select vendor —</option>';
    _rpData.vendor_cards.forEach(function(v) {
        var opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.name + ' (' + (v.booth_number || '—') + ')';
        sel.appendChild(opt);
    });
    document.getElementById('rp-vendor-picker-overlay').style.display = 'flex';
}

function confirmVendorPick() {
    var sel = document.getElementById('rp-pick-vendor');
    var vid = sel.value;
    if (!vid) return;
    document.getElementById('rp-vendor-picker-overlay').style.display = 'none';

    // Find the vendor in the data and open the existing rent modal
    var vendor = _rpData.vendor_cards.find(function(v) { return v.id == vid; });
    if (vendor && typeof window.openRentModalHub === 'function') {
        // openRentModalHub expects (vendorId, vendorName, monthlyRent)
        // monthlyRent may not be in vendor_cards — pass 0 and let the modal show the field
        window.openRentModalHub(vendor.id, vendor.name, 0);
    }
}
```

---

## Part C: Files to Modify

1. **`frontend/admin/index.html`** — All HTML and JS changes described above

## Files NOT to Modify
- `app/routers/admin.py` — endpoint already exists, do NOT change
- `frontend/static/js/admin-vendor-dashboard.js` — do NOT change
- No new files needed

---

## Testing Checklist
- [ ] "Dashboard" tab is active by default — shows all existing content unchanged
- [ ] Clicking "Rent & Payouts" hides dashboard, shows new section
- [ ] Clicking "Dashboard" hides rent-payouts, shows dashboard
- [ ] Summary stat cards populate with correct numbers from API
- [ ] Vendor balance cards display horizontally, scroll when many vendors
- [ ] Positive balances show in gold, negative in red, zero in gray
- [ ] Transaction table loads all rent payments and payouts sorted by date desc
- [ ] Type badges show "Rent" (green) and "Payout" (gold)
- [ ] Status badges are color-coded (paid=green, pending=gold, outstanding=red)
- [ ] Search by vendor name filters the table in real time
- [ ] Type dropdown filters to rent-only or payout-only
- [ ] Period filter (month picker) filters by period column
- [ ] Amount filter narrows results
- [ ] "Record Rent Payment" opens vendor picker, then existing rent modal
- [ ] "Process Payouts" triggers existing payout confirmation flow
- [ ] Mobile responsive: cards scroll, table has horizontal scroll, filters wrap
- [ ] No regressions on existing dashboard functionality
