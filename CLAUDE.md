# BMM-POS — Bowenstreet Market Point of Sale
## Master Reference for Claude Code Sessions

---

## 🏪 Business Overview

**Bowenstreet Market**
- Address: 2837 Bowen St, Oshkosh, WI 54901
- Website: bowenstreetmarket.com (Wix-hosted, marketing only)
- Online shop: https://www.bowenstreetmm.com/shop/ (self-hosted, this system)
- 120+ vendors selling handcrafted, vintage, and antique goods
- 70 vendors receiving monthly payouts
- Replacing: Ricochet POS (bowenstreet.ricoconsign.com) — $159–$199/month
- Payment terminal: GoDaddy Poynt (no per-swipe fee, in-store)
- Online payments: Square

---

## 🖥️ Live Server

| Item | Value |
|------|-------|
| **Domain** | https://www.bowenstreetmm.com |
| **Server IP** | 138.68.239.233 |
| **Provider** | DigitalOcean droplet |
| **OS** | Ubuntu 24.04 |
| **Web server** | Nginx + SSL (Let's Encrypt, auto-renewing) |
| **App path** | /var/www/bmm-pos |
| **Service name** | bmm-pos |
| **Python** | 3.12.3 |
| **DB** | PostgreSQL 16 |
| **DB name** | bmm_pos |
| **DB user** | bmm_user |
| **DB password** | BmmPos2024Secure |
| **GitHub** | https://github.com/crypto2retire/BMM-POS |

---

## 🚀 Deployment Workflow

**Step 1 — On Mac (Claude Code), push to GitHub:**
```bash
git add -A
git commit -m "describe what changed"
git push origin main
```

**Step 2 — In SSH session, deploy:**
```bash
deploy
```
(Runs: `cd /var/www/bmm-pos && git pull origin main && systemctl restart bmm-pos && echo Done`)

**Step 3 — If new database columns were added:**
```bash
sudo -u postgres psql -d bmm_pos -c "ALTER TABLE table_name ADD COLUMN IF NOT EXISTS column_name TYPE DEFAULT value;"
```

---

## 🔧 SSH Quick Reference
```bash
# Connect
ssh root@138.68.239.233

# Deploy latest code
deploy

# Check app status
systemctl status bmm-pos

# Restart app
systemctl restart bmm-pos

# View logs (last 50 lines)
journalctl -u bmm-pos -n 50 --no-pager

# Follow logs live
journalctl -u bmm-pos -f

# Check Nginx
nginx -t && systemctl reload nginx
```

---

## 🗄️ Database Quick Reference
```bash
# Connect
sudo -u postgres psql -d bmm_pos
```
```sql
-- List all vendors
SELECT id, name, email, role, is_vendor, status, monthly_rent FROM vendors ORDER BY id;

-- Check vendor balances
SELECT v.name, vb.balance FROM vendors v JOIN vendor_balances vb ON v.id = vb.vendor_id;

-- Count items by status
SELECT status, count(*) FROM items GROUP BY status;

-- Fix permissions (run after adding new tables)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bmm_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bmm_user;
```

---

## 👤 Test Accounts (DELETE BEFORE GO-LIVE)

| Name | Email | Password | Role |
|------|-------|----------|------|
| Admin | admin@bowenstreetmarket.com | admin123 | admin |
| Cashier | cashier@bowenstreetmarket.com | cashier123 | cashier |
| Sarah Johnson | sarah@email.com | vendor123 | vendor |
| Mike Chen | mike@email.com | vendor123 | vendor |
| Linda Kowalski | linda@email.com | vendor123 | vendor |
| Paula | paula@email.com | vendor123 | vendor |
| Nora | nora@email.com | vendor123 | admin |
| Sammy | sammy@email.com | vendor123 | admin |
| Ashley | ashley@email.com | vendor123 | admin |
| Anne | anne@email.com | vendor123 | admin |

**Login redirects:**
- admin (no booth) → /admin/index.html
- cashier (no booth) → /pos/index.html
- admin or cashier with is_vendor=true → choice screen (Dashboard or My Booth)
- vendor → /vendor/dashboard.html

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) |
| Database | PostgreSQL (asyncpg + SQLAlchemy async) |
| Frontend | Plain HTML + Vanilla JS |
| Auth | JWT via python-jose, bcrypt passwords |
| Barcodes | python-barcode (Code 128) |
| Labels — PDF | ReportLab (2.25×1.25" Zebra) |
| Labels — Dymo | Dymo LabelWriter 450 (XML via local web service) |
| Receipt printer | Star TSP100III (thermal, 80mm, browser print) |
| AI assistant | OpenRouter → google/gemini-2.0-flash |
| Online payments | Square (shop purchases + vendor rent) |
| In-store payments | GoDaddy Poynt terminal (Phase 4) |
| Payouts | Zelle manual (Phase 1), ACH planned (Phase 2) |
| Image processing | Pillow (resize to max 800px, saved as JPG) |
| Hosting | DigitalOcean droplet |
| Web server | Nginx + SSL |

---

## 📁 Project Structure
```
/var/www/bmm-pos/
app/
  config.py
  database.py
  main.py                    ← All routers registered here
  models/
    vendor.py                ← Vendor, VendorBalance ORM
    item.py                  ← Item ORM (includes image_path)
    sale.py                  ← Sale, SaleItem ORM
    rent.py                  ← RentPayment ORM
    payout.py                ← Payout ORM
    reservation.py           ← Reservation ORM
    store_setting.py         ← StoreSettings ORM
  schemas/
    vendor.py
    item.py
    sale.py
    assistant.py
  routers/
    auth.py                  ← POST /api/v1/auth/login, JWT
    vendors.py               ← CRUD + reset-password endpoint
    items.py                 ← CRUD, barcode, labels, image upload
    sales.py
    pos.py                   ← Checkout, barcode/search
    assistant.py             ← AI chat, tool calling
    storefront.py            ← Public shop API
    admin.py                 ← Rent status, vendor flagging
    rent.py                  ← Vendor rent payment via Square
    settings.py              ← Store settings
    reports.py               ← All report endpoints
  services/
    barcode.py
    labels.py
    square.py
    poynt.py
migrations/
  001_initial_schema.sql
  002_add_label_style.sql
scripts/
  seed_dev.py
frontend/
  static/
    css/main.css             ← Full design system (parchment/gold/charcoal)
    js/api.js
    js/assistant-panel.js
    uploads/items/           ← Item photos stored here (gitignored content)
    llms.txt                 ← LLM SEO file served at /llms.txt
    robots.txt               ← Served at /robots.txt
  vendor/
    login.html               ← All roles log in here
    dashboard.html
    items.html               ← Grid/list toggle, photo upload, search/sort/pagination
  admin/
    index.html
    vendors.html             ← Full vendor management + edit + password reset
    rent.html
    reports.html             ← 5-tab reporting suite
    settings.html            ← Store settings panel
  pos/
    index.html
    register.html
  shop/
    index.html               ← Public shop, sort/filter/view toggle, Square checkout
```

---

## 🗃️ Database Schema (Key Tables)

| Table | Key Fields |
|-------|-----------|
| vendors | id, name, email, password_hash, role, is_vendor, booth_number, monthly_rent, payout_method, zelle_handle, notes, rent_flagged, status |
| vendor_balances | vendor_id (unique), balance |
| items | id, vendor_id, sku, barcode, name, price, sale_price, sale_start, sale_end, status, label_style, image_path, is_online, description |
| sales | id, cashier_id, subtotal, tax_rate, tax_amount, total, payment_method |
| sale_items | sale_id, item_id, vendor_id, quantity, unit_price, line_total |
| rent_payments | vendor_id, amount, period_month, status, square_payment_id, method |
| payouts | vendor_id, period_month, gross_sales, rent_deducted, net_payout, status |
| reservations | id, item_id, customer_name, customer_phone, square_payment_id, amount_paid, status, created_at |
| store_settings | key (PK), value, updated_at |

**Key rules:**
- Tax rate: 5% (Wisconsin state only, no Winnebago County tax)
- SKU format: BSM-{vendor_id:04d}-{sequence:06d}
- Barcodes: Code 128, compatible with existing Ricochet barcodes
- Sale prices activate/deactivate automatically by sale_start/sale_end dates
- DB trigger auto-creates vendor_balance row on vendor insert
- Soft deletes: items → status='removed', vendors → status='suspended'
- Item photos: stored at /static/uploads/items/{item_id}.jpg, max 800px

---

## 🔌 API Endpoints

**Auth**
- POST /api/v1/auth/login

**Vendors** (admin only for write)
- GET/POST /api/v1/vendors/
- GET/PUT/DELETE /api/v1/vendors/{id}
- POST /api/v1/vendors/{id}/reset-password

**Items**
- GET/POST /api/v1/items/
- GET/PUT/DELETE /api/v1/items/{id}
- GET /api/v1/items/barcode/{barcode}
- GET /api/v1/items/{id}/label
- GET /api/v1/items/{id}/dymo-label
- POST /api/v1/items/{id}/upload-image

**POS**
- GET /api/v1/pos/search?q=
- GET /api/v1/pos/barcode/{barcode}
- POST /api/v1/pos/sale
- POST /api/v1/pos/payment-callback

**Sales**
- GET /api/v1/sales/
- GET /api/v1/sales/{id}
- GET /api/v1/sales/summary/today

**Admin**
- GET /api/v1/admin/rent-status
- POST /api/v1/admin/vendors/{id}/flag

**Storefront (public)**
- GET /api/v1/storefront/items
- POST /api/v1/storefront/create-payment
- POST /api/v1/storefront/payment-confirmed
- POST /api/v1/storefront/reserve

**Rent**
- POST /api/v1/vendor/pay-rent
- POST /api/v1/vendor/rent-confirmed

**Settings**
- GET /api/v1/admin/settings
- POST /api/v1/admin/settings

**Reports**
- GET /api/v1/admin/reports/sales?start=&end=
- GET /api/v1/admin/reports/vendors?start=&end=
- GET /api/v1/admin/reports/rent?month=
- GET /api/v1/admin/reports/payouts
- GET /api/v1/admin/reports/reservations
- POST /api/v1/admin/reports/reservations/{id}/pickup

**Assistant**
- POST /api/v1/assistant/chat

**Static / SEO**
- GET /llms.txt
- GET /robots.txt
- GET /sitemap.xml

**Docs:** https://www.bowenstreetmm.com/docs

---

## 💰 Business Rules

**Rent:** Deducted on the 27th of each month. Vendors pay via Square link or manually.

**Payouts:** Processed on the 1st. Zelle manual (~15 min for 70 vendors). ACH planned Phase 2.

**Vendor roles:**
- vendor — own items/dashboard only
- cashier — POS + full item management
- admin — everything
- is_vendor flag — any role can also have a booth (shows choice screen at login)

**Online shop:** All sales final. Items held 48 hours for in-store pickup. Square processes payment.

---

## 🤖 AI Assistant

- Provider: OpenRouter → google/gemini-2.0-flash
- Available on: all pages
- Capabilities: add/edit/archive items via chat, photo analysis, description writing

---

## 🎨 Brand / Design System

- Background: `#2A2825` (deep charcoal)
- Surface/card: parchment `#F5F0E8` / cream `#EDE8DC`
- Accent: aged gold `#C9A84C`
- Danger/alert: muted rust `#8B4A3C`
- Headings: EB Garamond
- Body: Crimson Pro
- Monospace (SKUs, numbers): JetBrains Mono
- No rounded corners anywhere (square edges throughout)
- Buttons: thin border, uppercase tracked labels, hover fill
- Tables: ledger-style, alternating warm tones

---

## 📋 Build Phases

| Phase | Status | Scope |
|-------|--------|-------|
| 1 | ✅ Complete | Vendors, items, barcodes, labels, auth |
| 2 | ✅ Complete | POS register, checkout, vendor balance updates |
| 3 | ✅ Complete | Receipt printing, Dymo labels, mobile UI, AI assistant |
| 3.5 | ✅ Complete | Public shop at /shop with Square payments |
| 3.6 | ✅ Complete | Rent dashboard, vendor flags, vendor rent via Square |
| 3.7 | ✅ Complete | Admin settings panel, full reporting suite (5 tabs) |
| 3.8 | ✅ Complete | Full UX redesign — parchment/gold aesthetic, SEO, LLM SEO |
| 3.9 | ✅ Complete | Item photo uploads, vendor list view, shop sort/filter/views |
| 3.10 | ✅ Complete | Vendor directory merged into Vendors, full edit + password reset |
| 3.11 | ✅ Complete | Primary role + is_vendor flag, login choice screen |
| 4 | 🔲 Pending | GoDaddy Poynt in-store card payment integration |
| 5 | 🔲 Pending | Auto rent deduction (27th), auto payout list (1st), email notifications |
| 6 | 🔲 Pending | Tax reports |
| 7 | 🔲 Pending | Side-by-side testing with Ricochet, staff training, cutover |

---

## ⚠️ Migration Notes

Always run ALTER TABLE manually on the server when adding new columns. `bmm_user` does not have ALTER TABLE ownership — use `sudo -u postgres psql`.

**Columns added after initial schema:**
- items.label_style VARCHAR(20) DEFAULT 'standard'
- items.image_path VARCHAR(500)
- items.is_online BOOLEAN DEFAULT false
- items.description TEXT
- vendors.rent_flagged BOOLEAN DEFAULT false
- vendors.is_vendor BOOLEAN DEFAULT false
- vendors.notes TEXT
- rent_payments.square_payment_id VARCHAR(200)
- rent_payments.method VARCHAR(50) DEFAULT 'manual'

**Tables added after initial schema:**
- reservations
- store_settings

---

## 🔐 Environment Variables (.env)
```
DATABASE_URL=postgresql+asyncpg://bmm_user:BmmPos2024Secure@localhost/bmm_pos
SECRET_KEY=bowenstreet-production-secret-2024
TAX_RATE=0.05
STORE_NAME=Bowenstreet Market
OPENROUTER_API_KEY=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
SQUARE_APPLICATION_ID=sq0idp-ZSYtZmlW1n7goEtDWTl9Tg
SQUARE_LOCATION_ID=G2KJFVAEVK3BZ
SQUARE_ACCESS_TOKEN=[stored on server only — regenerate at developer.squareup.com if needed]
```
