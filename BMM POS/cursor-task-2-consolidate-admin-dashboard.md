# Task 2: Consolidate Admin Dashboard — Vendors + Rent + Payouts in One View

## Goal
Merge the Vendor list, Rent management, and Payout operations into the admin dashboard (`/admin/index.html`). Each vendor row expands into an accordion showing their balance, rent status, payout info, and quick actions. Remove the separate Rent page and Payouts page from navigation. The separate Vendors page (`/admin/vendors.html`) is also absorbed — its edit form becomes a modal accessible from the accordion.

## Design Language (MUST follow)
- `--bg: #38383B`, `--gold: #C9A96E`, `--surface: #44444A`, `--text: #F0EDE8`
- `border-radius: 0px` everywhere
- Heading font: EB Garamond italic
- Body font: Roboto 300
- Gold accent borders, warm-border hover effects
- Ledger-style tables, dark glass-like inputs with gold focus glow
- Status badges: green for paid/current, yellow for due/pending, red for overdue/shortfall

---

## Part A: New Backend Endpoint

### Create `GET /api/v1/admin/vendor-overview` in `app/routers/admin.py`

This endpoint returns ALL vendor data needed for the consolidated view in a single API call. It combines data from vendors, vendor_balances, rent_payments, and payouts.

```python
@router.get("/vendor-overview")
async def vendor_overview(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """All vendor data for consolidated admin dashboard."""
    from datetime import date
    from decimal import Decimal

    today = date.today()
    current_period = date(today.year, today.month, 1)
    period_label = current_period.strftime("%B %Y")

    # Get all active vendors
    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    # Batch-load all balances
    bal_result = await db.execute(select(VendorBalance.vendor_id, VendorBalance.balance))
    balance_map = {row.vendor_id: float(row.balance or 0) for row in bal_result.all()}

    # Batch-load current month rent payments
    rent_result = await db.execute(
        select(RentPayment).where(RentPayment.period_month == current_period)
    )
    rent_map = {}
    for rp in rent_result.scalars().all():
        rent_map[rp.vendor_id] = {
            "paid": rp.status == "paid",
            "method": rp.method,
            "amount": float(rp.amount),
            "date": rp.created_at.strftime("%m/%d/%Y") if rp.created_at else None,
        }

    # Batch-load last rent payment per vendor (for history display)
    from sqlalchemy import func as sqlfunc
    last_rent_result = await db.execute(
        select(
            RentPayment.vendor_id,
            sqlfunc.max(RentPayment.created_at).label("last_date"),
        )
        .where(RentPayment.status == "paid")
        .group_by(RentPayment.vendor_id)
    )
    last_rent_map = {row.vendor_id: row.last_date for row in last_rent_result.all()}

    # Batch-load current month payouts
    payout_result = await db.execute(
        select(Payout).where(Payout.period_month == current_period)
    )
    payout_map = {}
    for p in payout_result.scalars().all():
        payout_map[p.vendor_id] = {
            "gross_sales": float(p.gross_sales),
            "rent_deducted": float(p.rent_deducted),
            "net_payout": float(p.net_payout),
            "status": p.status,
        }

    # Check if payouts already processed this month
    already_processed = len(payout_map) > 0

    # Build response
    rows = []
    totals = {"gross": 0, "rent_due": 0, "rent_collected": 0, "net": 0, "shortfalls": 0}

    for v in vendors:
        balance = balance_map.get(v.id, 0)
        rent = float(v.monthly_rent or 0)
        rent_info = rent_map.get(v.id, None)
        rent_paid = rent_info is not None and rent_info["paid"]
        last_rent_date = last_rent_map.get(v.id)
        payout_info = payout_map.get(v.id)

        # Rent status logic
        if rent <= 0:
            rent_status = "none"
        elif rent_paid:
            rent_status = "current"
        else:
            # Check if overdue (past the 1st of the month by 15+ days)
            if today.day > 15:
                rent_status = "overdue"
            else:
                rent_status = "due"

        # Payout preview calculation
        rent_to_deduct = 0 if rent_paid else rent
        if balance >= rent_to_deduct:
            net_payout = round(balance - rent_to_deduct, 2)
            shortfall = 0
        else:
            net_payout = 0
            shortfall = round(rent_to_deduct - balance, 2)

        totals["gross"] += balance
        totals["rent_due"] += rent if not rent_paid else 0
        totals["rent_collected"] += rent_info["amount"] if rent_info and rent_paid else 0
        totals["net"] += net_payout
        totals["shortfalls"] += shortfall

        rows.append({
            "id": v.id,
            "name": v.name,
            "email": v.email or "",
            "phone": v.phone or "",
            "booth_number": v.booth_number or "—",
            "monthly_rent": rent,
            "balance": round(balance, 2),
            "rent_status": rent_status,
            "rent_paid": rent_paid,
            "rent_paid_method": rent_info["method"] if rent_info else None,
            "rent_paid_date": rent_info["date"] if rent_info else None,
            "rent_flagged": v.rent_flagged,
            "last_rent_date": last_rent_date.strftime("%m/%d/%Y") if last_rent_date else None,
            "payout_preview": {
                "gross": round(balance, 2),
                "rent_deducted": round(rent_to_deduct, 2),
                "net": net_payout,
                "shortfall": shortfall,
            },
            "payout_processed": payout_info is not None,
            "payout_method": v.payout_method or "—",
            "zelle_handle": v.zelle_handle or "",
            "commission_rate": float(v.commission_rate or 0),
            "role": v.role,
            "status": v.status,
            "notes": v.notes or "",
        })

    return {
        "period": period_label,
        "already_processed": already_processed,
        "totals": {
            "gross_sales": round(totals["gross"], 2),
            "rent_due": round(totals["rent_due"], 2),
            "rent_collected": round(totals["rent_collected"], 2),
            "net_payouts": round(totals["net"], 2),
            "shortfalls": round(totals["shortfalls"], 2),
            "vendor_count": len(rows),
        },
        "vendors": rows,
    }
```

Make sure to import `RentPayment` and `Payout` at the top of admin.py if not already imported.

---

## Part B: Redesign Admin Dashboard Frontend

### Rewrite `/frontend/admin/index.html`

The page layout should be (top to bottom):

1. **Navbar** (same as current, but updated links — see Part C)
2. **Greeting + Period label**
3. **Summary stat cards row** — 6 cards:
   - Total Sales (gross vendor balances)
   - Rent Collected
   - Rent Due
   - Net Payouts
   - Shortfalls
   - Active Vendors
4. **Action bar** — 3 buttons:
   - "Process Payouts" (green, with confirmation modal)
   - "Send Rent Reminders" (yellow/warning)
   - "Send Weekly Reports" (green outline)
   - Show "Already Processed" badge if payouts done this month
5. **Search bar** — Filter vendors by name or booth
6. **Vendor list** — Each vendor is a clickable row that expands into an accordion panel

### Vendor List Row (collapsed)
Each row shows:
| Name | Booth | Balance | Rent Status | Payout Method |
- Balance shown in green with `$XX.XX` format
- Rent Status shown as badge: CURRENT (green) / DUE (yellow) / OVERDUE (red) / NONE (gray)
- Chevron arrow on right indicates expandable
- 🚩 flag icon if `rent_flagged` is true

### Vendor Accordion Panel (expanded)
When a vendor row is clicked, it expands to show 3 sections side by side (on desktop) or stacked (on mobile):

**Section 1: Balance & Payout**
- Current Balance: `$XX.XX` (large green number)
- Payout Preview:
  - Gross Sales: $XX.XX
  - Rent Deduction: -$XX.XX (red)
  - Net Payout: $XX.XX (green, bold)
  - Or "Shortfall: $XX.XX" in red if insufficient
- Payout Method: Zelle / Check / etc.
- Zelle Handle (if applicable)
- **"Adjust Balance" button** → opens existing adjust balance modal

**Section 2: Rent**
- Monthly Rent: `$XXX.XX/mo`
- This Month: PAID badge with method + date, or DUE/OVERDUE badge
- Last Payment: date
- **"Record Rent Payment" button** → opens rent payment modal (same as rent.html modal with cash/check/zelle/card options)
- **"Flag" / "Unflag" button** for rent flagging

**Section 3: Edit Vendor**
- **"Edit Vendor" button** → opens modal with full edit form:
  - Name, Email, Phone, Booth Number
  - Monthly Rent, Commission Rate
  - Payout Method (dropdown: Zelle, Check, Cash, Other)
  - Zelle Handle (shown when Zelle selected)
  - Status (Active, Suspended, Archived)
  - Notes
  - Save / Cancel buttons
- **"View Items" link** → navigates to `/vendor/items.html?vendor_id={id}`

### Mobile Layout
On screens < 768px:
- Vendor list shows as cards instead of table rows
- Each card shows name, booth, balance, rent badge
- Tap to expand shows sections stacked vertically
- Stat cards become 2-column grid
- Action buttons stack full-width

### Modals Needed

**1. Record Rent Payment Modal** (port from rent.html):
- Vendor name display
- Amount field (pre-filled with monthly rent)
- Payment method dropdown: Cash, Check, Zelle, Card (Terminal)
- Period selector (month input, defaults to current month)
- Notes field (optional)
- Card (Terminal) option: shows info message about presenting card on terminal, initiates charge via `POST /api/v1/admin/vendors/{id}/rent-charge-card`, polls `/api/v1/admin/rent-charge-status/{orderId}` for result
- Cash/Check/Zelle: posts to `POST /api/v1/admin/vendors/{id}/record-rent`
- After success: refresh the vendor data

**2. Adjust Balance Modal** (already exists on current admin/index.html):
- Keep as-is — credit/debit dropdown, amount, reason
- Posts to `POST /api/v1/vendors/{id}/balance/adjust`

**3. Edit Vendor Modal** (port from vendors.html):
- Full vendor edit form
- Posts to `PUT /api/v1/vendors/{id}`
- After save: refresh vendor data

**4. Process Payouts Confirmation Modal** (port from payouts.html):
- Warning text about processing payouts and resetting balances
- Posts to `POST /api/v1/admin/process-payouts`
- Shows result count

**5. Balance History Modal** (already exists on current admin/index.html):
- Keep as-is — shows balance adjustment history
- Gets from `GET /api/v1/vendors/{id}/balance/history`

### JavaScript Structure

```javascript
// Main data load
async function loadDashboard() {
    var data = await apiGet('/api/v1/admin/vendor-overview');
    // Store globally for filtering
    window._vendorData = data;
    renderStats(data.totals, data.period, data.already_processed);
    renderVendorList(data.vendors);
}

// Render summary stats
function renderStats(totals, period, alreadyProcessed) { ... }

// Render vendor rows with accordion
function renderVendorList(vendors) { ... }

// Toggle accordion for a vendor
function toggleVendor(vendorId) {
    // Collapse any other open accordion
    // Expand this vendor's detail panel
}

// Filter vendors by search input
function filterVendors() {
    var q = document.getElementById('search-input').value.toLowerCase();
    var filtered = window._vendorData.vendors.filter(v =>
        v.name.toLowerCase().includes(q) || v.booth_number.toLowerCase().includes(q)
    );
    renderVendorList(filtered);
}

// Rent payment modal
function openRentModal(vendorId) { ... }
function submitRentPayment() { ... }
function onPayMethodChange() { ... } // show/hide card terminal info

// Card terminal charge flow
async function chargeCardForRent(vendorId) { ... }

// Adjust balance modal
function openAdjustModal(vendorId, name, balance) { ... }
function submitAdjustment() { ... }

// Edit vendor modal
function openEditModal(vendorId) { ... }
function submitEditVendor() { ... }

// Process payouts
function confirmProcessPayouts() { ... }
async function doProcessPayouts() { ... }

// Send rent reminders
async function sendRentReminders() { ... }

// Send weekly reports
async function sendWeeklyReports() { ... }

// Refresh after any action
async function refreshData() { await loadDashboard(); }
```

### API Endpoints Used
- `GET /api/v1/admin/vendor-overview` — main data load (new endpoint)
- `POST /api/v1/admin/vendors/{id}/record-rent` — record rent payment
- `POST /api/v1/admin/vendors/{id}/rent-charge-card` — initiate card charge
- `GET /api/v1/admin/rent-charge-status/{orderId}` — poll card payment
- `POST /api/v1/admin/vendors/{id}/flag` — toggle rent flag
- `POST /api/v1/vendors/{id}/balance/adjust` — adjust balance
- `GET /api/v1/vendors/{id}/balance/history` — balance history
- `PUT /api/v1/vendors/{id}` — update vendor
- `POST /api/v1/admin/process-payouts` — process all payouts
- `POST /api/v1/admin/send-rent-reminders` — send rent reminders
- `POST /api/v1/admin/send-weekly-reports` — send weekly reports

### Sections to REMOVE from current admin/index.html
- **Online Orders section** — keep this, it stays
- **Employees section** — keep this, it stays
- **Data Import section** — keep this, it stays
- **Old "All Vendors" table** — REPLACE with the new accordion vendor list
- **Old vendor cards** — REPLACE
- **Dashboard stats from /admin/reports/dashboard** — REPLACE with vendor-overview stats

### Sections to KEEP on current admin/index.html
- Online Orders section
- Employees section (Add Employee button + table)
- Data Import section (CSV uploads)
- Clear Test Data / Reset buttons

---

## Part C: Update Navigation

### On ALL admin pages, update the navbar links:

**Remove these links:**
- Rent (`/admin/rent.html`)
- Payouts (`/admin/payouts.html`)

**Remove from the mobile bottom nav too** (the `<nav class="admin-bottom-nav">` at the bottom).

**Final nav should be:**
- Dashboard (active on index.html)
- Vendors → redirect to Dashboard (or remove entirely since dashboard now has vendors)
- Items
- Verify
- Studio
- Reports
- EOD Reports
- Settings
- POS Terminal
- Logout

Actually, since Dashboard now IS the vendor management page, the nav simplifies to:
- **Dashboard** (`/admin/index.html`) — vendors + rent + payouts + overview
- **Items** (`/vendor/items.html`)
- **Verify** (`/admin/inventory-verify.html`)
- **Studio** (`/admin/studio.html`)
- **Reports** (`/admin/reports.html`)
- **EOD Reports** (`/admin/eod-reports.html`)
- **Settings** (`/admin/settings.html`)
- **POS Terminal** (`/pos/index.html`)
- **Logout**

Update the nav in these files:
- `frontend/admin/index.html`
- `frontend/admin/reports.html`
- `frontend/admin/settings.html`
- `frontend/admin/studio.html`
- `frontend/admin/inventory-verify.html`
- `frontend/admin/eod-reports.html`
- `frontend/admin/vendors.html` (if kept as redirect)
- `frontend/admin/customers.html`
- `frontend/admin/payouts.html` (can add redirect to dashboard)

Also update the **mobile bottom nav** on all pages to:
```html
<nav class="admin-bottom-nav">
    <a href="/admin/index.html"><span class="nav-icon">&#127968;</span>Dashboard</a>
    <a href="/vendor/items.html"><span class="nav-icon">&#127991;&#65039;</span>Items</a>
    <a href="/admin/reports.html"><span class="nav-icon">&#128202;</span>Reports</a>
    <a href="/admin/settings.html"><span class="nav-icon">&#9881;&#65039;</span>Settings</a>
    <a href="/pos/index.html"><span class="nav-icon">&#128421;&#65039;</span>POS</a>
</nav>
```

---

## Part D: Redirect Old Pages

### `frontend/admin/rent.html` — Add redirect at top of script
```javascript
// Redirect to consolidated dashboard
window.location.href = '/admin/index.html';
```
Or simpler: replace entire file content with a redirect page.

### `frontend/admin/payouts.html` — Same redirect
```javascript
window.location.href = '/admin/index.html';
```

### `frontend/admin/vendors.html` — Same redirect
```javascript
window.location.href = '/admin/index.html';
```

---

## Important Notes

- Do NOT delete the old rent.html, payouts.html, or vendors.html files — just add redirects. The API endpoints they used still need to work (they're used by the new dashboard too).
- The rent payment card terminal flow must be ported exactly — it uses the Poynt terminal for in-person card payments. Vendors paying through the vendor portal use Square (that's a separate flow in vendor/dashboard.html, don't touch it).
- All modals should match the existing design language: dark background overlay, `--bg` modal body, gold headings, dark glass inputs.
- This page will be data-heavy with 120+ vendors. Make sure the accordion only renders the expanded content for the currently open vendor (don't render all 120 detail panels at once).
- The `initAssistantPanel(contextString, { buttonBottom: '70px' })` call at the bottom of the admin page should remain.
