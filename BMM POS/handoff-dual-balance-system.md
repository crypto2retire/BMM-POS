# Handoff Summary: Dual-Balance System
**Date:** April 1, 2026
**Project:** BMM-POS (Bowenstreet Market Point of Sale)

---

## What Was Done This Session

### 1. Removed Zelle as Payout Option (DEPLOYED)
- Forced all vendors to `payout_method = 'check'` — no other payout options
- Removed zelle from all UI dropdowns, edit modals, CSV templates, email templates, AI assistant prompt, and seed data
- Startup migration catches vendors still set to 'zelle' and flips them to 'check'
- **Files changed:** `app/main.py`, `app/routers/admin.py`, `app/routers/assistant.py`, `app/services/email_templates.py`, `frontend/admin/index.html`, `frontend/admin/vendors.html`, `frontend/admin/rent.html`, `frontend/static/js/admin-vendor-dashboard.js`, `scripts/seed_dev.py`, `migrations/001_initial_schema.sql`

### 2. Clarified Rent vs Payout Payment Methods (DEPLOYED)
- **Vendor payouts:** Check only
- **Rent payments:** Cash, check, card (Poynt at register), or card (Square via vendor portal)
- Rent payment dropdown: `cash`, `check`, `card`, `square`

### 3. Added Rent & Payouts Tab to Admin Dashboard (DEPLOYED via Cursor)
- Combined ledger with summary stat cards, vendor balance strip, searchable transaction table
- Backend API: `GET /api/v1/admin/rent-payout-ledger`
- Cursor Task 3 file was used to implement the frontend

### 4. Negative Balance Display Fix (DEPLOYED)
- Balances now show red (`var(--danger)`) when negative in table rows, accordion details, and mobile cards

### 5. Vendor Sales History in Accordion (DEPLOYED)
- Last 50 sales per vendor load when accordion is expanded
- Fetches from `/api/v1/sales/?vendor_id=X&limit=50`

### 6. Dual-Balance System Backend (NOT YET PUSHED)
This is the big one. All backend changes are complete but **not yet committed or pushed**.

---

## Dual-Balance System — How It Works

### The Problem (Ricochet)
The old system combined rent and sales into one balance. This made it impossible for vendors to prepay rent, hard to answer vendor questions about their balance, and any extra rent paid would just get processed as a payout at month end.

### The Solution — Two Separate Balances

| Column | What It Tracks | Goes Up When | Goes Down When |
|--------|---------------|--------------|----------------|
| `balance` (sales) | Accumulated POS sales | Items sell through POS | Payout is processed (resets to $0) |
| `rent_balance` | Prepaid rent credit | Vendor pays rent | Monthly rent is deducted during payout processing |

**Combined balance** = `balance + rent_balance` — this is what shows on the dashboard as the main number.

### Prepaid Rent Example
- Vendor pays $600 for 3 months → `rent_balance = $600`
- Month 1 payout: deduct $200 from rent_balance → `rent_balance = $400`
- Month 2 payout: deduct $200 → `rent_balance = $200`
- Month 3 payout: deduct $200 → `rent_balance = $0`
- No sales balance is touched during this time

### Payout Processing Flow
1. Deduct monthly rent from `rent_balance` (can go negative)
2. If `rent_balance` is negative and there are sales, transfer from `balance` to cover the deficit
3. Remaining `balance` = payout amount (paid by check)
4. `balance` resets to $0
5. `rent_balance` carries forward (negative = vendor owes rent)

### Example — Vendor with $500 sales, $0 rent_balance, $200 rent
1. `rent_balance` = $0 - $200 = **-$200**
2. Transfer $200 from sales to cover → `rent_balance` = $0, `balance` = $300
3. Net payout = **$300** by check
4. `balance` resets to $0, `rent_balance` stays $0

### Example — Vendor with $100 sales, $0 rent_balance, $200 rent
1. `rent_balance` = $0 - $200 = **-$200**
2. Transfer $100 from sales → `rent_balance` = -$100, `balance` = $0
3. Net payout = **$0** (nothing to pay)
4. `balance` resets to $0, `rent_balance` = **-$100** (carries forward)

---

## Files Changed (Not Yet Pushed)

### `app/models/vendor.py`
- Added `rent_balance` column to `VendorBalance` model: `Numeric(10, 2), default=Decimal("0.00")`

### `app/main.py` — Three New Startup Migrations
1. **ALTER TABLE** adds `rent_balance` column if it doesn't exist
2. **Backfill** ensures all vendors have a `vendor_balances` row (including `rent_balance`)
3. **One-time migration** credits `rent_balance` from today's rent payments where `rent_balance` is still 0 and payment method is not 'balance' (catches rent already recorded today before the code was deployed)

Also updated: the payout_method migration now forces ALL vendors to 'check' (not just NULL ones).

### `app/routers/admin.py`
- **`POST /record-rent`** (~line 367): Now credits `rent_balance` when rent is paid
- **`POST /process-payouts`** (~line 565): Completely rewritten with dual-balance logic (rent from rent_balance → sales cover deficit → remaining sales = payout → balances reset)
- **`GET /vendor-overview`** (~line 53): Now returns `sales_balance`, `rent_balance`, and `combined_balance` for each vendor (in addition to `balance` which is now the combined number)
- **`GET /rent-payout-ledger`** (~line 892): Vendor cards now include `sales_balance` and `rent_balance`; summary includes `total_sales_balances` and `total_rent_balances`

### `app/routers/vendors.py`
- **`GET /vendors/`** (list): Returns `sales_balance`, `rent_balance`, `current_balance` (combined) for each vendor
- **`GET /vendors/{id}`** (single): Same three-balance return
- **`GET /vendors/{id}/balance`**: Returns `balance` (sales), `rent_balance`, and `combined_balance`

### `app/schemas/vendor.py`
- **`VendorResponse`**: Added `sales_balance` and `rent_balance` fields
- **`VendorBalanceResponse`**: Added `rent_balance` and `combined_balance` fields

---

## What Still Needs to Happen

### Step 1: Fix Git (Your Terminal)
A stale worktree is blocking git commands. Run this first:
```bash
cd ~/path-to/BMM-POS
rm -rf .git/worktrees/laughing-rubin
```

### Step 2: Commit & Push Backend (Your Terminal)
```bash
git add app/models/vendor.py app/main.py app/routers/admin.py app/routers/vendors.py app/schemas/vendor.py
git commit -m "Implement dual-balance system: separate sales and rent balances"
git push
```
Railway will auto-deploy. The startup migrations will create the `rent_balance` column and migrate today's rent payments.

### Step 3: Frontend Updates (Cursor)
Use **Cursor Task 4** file: `cursor-task-4-dual-balance-frontend.md`

This tells Cursor to update:
- **Admin vendor dashboard JS** — Show sales/rent/combined in table rows, mobile cards, and accordion details
- **Rent & Payouts tab** — Vendor balance cards show all three numbers; summary includes breakdown
- **Vendor dashboard HTML** — Replace single "Current Balance" card with three cards (Sales Balance, Rent Balance, Combined Balance)
- **Cache busting** — Bump query strings on modified JS files

### Step 4: Verify After Deploy
- [ ] Check Railway logs — confirm `rent_balance` column was created
- [ ] Check Railway logs — confirm rent payment migration ran (should see "Migrated X rent payments to rent_balance")
- [ ] Log in as admin → Vendor Dashboard → verify three balance numbers per vendor
- [ ] Log in as admin → Rent & Payouts tab → verify balance cards show breakdown
- [ ] Log in as vendor → Dashboard → verify three balance cards
- [ ] Record a test rent payment → verify rent_balance increases
- [ ] Verify negative balances show in red

---

## Still Pending from Previous Sessions
- Receipt timezone display fix
- Railway cron job manual setup
- Lisa's consignment items
- Square webhook integration
- Email notifications for vendors
- Barcode label printing
- Inventory alerts (low stock)
