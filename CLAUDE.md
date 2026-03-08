# BMM-POS — Bowenstreet Market Point of Sale
## Master Reference for Claude Code Sessions

---

## 🏪 Business Overview

**Bowenstreet Market**
- Address: 2837 Bowen St, Oshkosh, WI 54901
- Website: bowenstreetmarket.com (Wix-hosted)
- 120+ vendors selling handcrafted, vintage, and antique goods
- 70 vendors receiving monthly payouts
- Replacing: Ricochet POS (bowenstreet.ricoconsign.com) — $159–$199/month
- Payment terminal: GoDaddy Poynt (no per-swipe fee)

---

## 🖥️ Live Server

| Item | Value |
|------|-------|
| **Server IP** | 138.68.239.233 |
| **Live URL** | http://138.68.239.233/vendor/login.html |
| **Provider** | DigitalOcean droplet |
| **OS** | Ubuntu 24.04 |
| **Web server** | Nginx |
| **App path** | /var/www/bmm-pos |
| **Service name** | bmm-pos |
| **Python** | 3.12.3 |
| **DB** | PostgreSQL 16 |
| **DB name** | bmm_pos |
| **DB user** | bmm_user |

---

## 🚀 Deployment Workflow

### Making Changes (do this every time)

**Step 1 — In Replit Shell, push changes to GitHub:**
```bash
git add -A
git commit -m "describe what changed"
git push origin main
```

**Step 2 — In SSH session, deploy to live server:**
```bash
deploy
```
(This runs: `cd /var/www/bmm-pos && git pull origin main && systemctl restart bmm-pos && echo Done`)

**Step 3 — If new database columns were added, run the migration:**
```bash
sudo -u postgres psql -d bmm_pos -c "ALTER TABLE items ADD COLUMN IF NOT EXISTS column_name TYPE DEFAULT value;"
```

---

## 🔧 SSH Quick Reference

**Connect to server:**
```bash
ssh root@138.68.239.233
```

**Common commands:**
```bash
# Deploy latest code
deploy

# Check app status
systemctl status bmm-pos

# Restart app
systemctl restart bmm-pos

# View live logs (last 50 lines)
journalctl -u bmm-pos -n 50 --no-pager

# Follow logs in real time
journalctl -u bmm-pos -f

# Check Nginx
nginx -t
systemctl reload nginx
```

---

## 🗄️ Database Quick Reference

**Connect to database:**
```bash
sudo -u postgres psql -d bmm_pos
```

**Useful queries:**
```sql
-- List all vendors
SELECT id, name, email, role, status, monthly_rent FROM vendors ORDER BY id;

-- Check vendor balances
SELECT v.name, vb.balance FROM vendors v JOIN vendor_balances vb ON v.id = vb.vendor_id;

-- Count items by status
SELECT status, count(*) FROM items GROUP BY status;

-- Grant permissions (run if permission errors appear)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bmm_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bmm_user;
```

**Run a migration file:**
```bash
sudo -u postgres psql -d bmm_pos -f /var/www/bmm-pos/migrations/001_initial_schema.sql
```

---

## 👤 Test Accounts

> ⚠️ These are TEST accounts. Delete all before go-live.

| Name | Email | Password | Role |
|------|-------|----------|------|
| Admin | admin@bowenstreetmarket.com | admin123 | admin |
| Cashier | cashier@bowenstreetmarket.com | cashier123 | cashier |
| Sarah Johnson | sarah@email.com | vendor123 | vendor |
| Mike Chen | mike@email.com | vendor123 | vendor |
| Linda Kowalski | linda@email.com | vendor123 | vendor |
| Nora | nora@email.com | vendor123 | admin |
| Sammy | sammy@email.com | vendor123 | admin |
| Ashley | ashley@email.com | vendor123 | admin |
| Anne | anne@email.com | vendor123 | admin |
| Paula | paula@email.com | vendor123 | vendor |

**Login redirects by role:**
- admin → /admin/index.html
- cashier → /pos/index.html
- vendor → /vendor/dashboard.html

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) |
| Database | PostgreSQL (asyncpg + SQLAlchemy async) |
| Frontend | Plain HTML + Vanilla JS (no frameworks) |
| Auth | JWT via python-jose, bcrypt passwords |
| Barcodes | python-barcode (Code 128) |
| Labels — PDF | ReportLab (2.25×1.25" Zebra) |
| Labels — Dymo | Dymo LabelWriter 450 (XML via local web service) |
| Receipt printer | Star TSP100III (thermal, 80mm, browser print) |
| AI assistant | OpenRouter → google/gemini-2.0-flash |
| Payments | GoDaddy Poynt Payment Bridge (stubbed, Phase 4) |
| Payouts | Zelle manual (Phase 1), ACH planned (Phase 2) |
| Hosting | DigitalOcean droplet |
| Web server | Nginx + SSL |
| GitHub repo | https://github.com/crypto2retire/BMM-POS |

---

## 📁 Project Structure

```
/var/www/bmm-pos/          ← Live server path
app/
  config.py                ← Settings (pydantic-settings)
  database.py              ← Async SQLAlchemy engine
  main.py                  ← FastAPI app, all routers wired
  models/
    vendor.py              ← Vendor, VendorBalance ORM
    item.py                ← Item ORM
    sale.py                ← Sale, SaleItem ORM
    rent.py                ← RentPayment ORM
    payout.py              ← Payout ORM
  schemas/
    vendor.py              ← Pydantic schemas
    item.py                ← Includes active_price computed field
    sale.py                ← CartItem, SaleCreate, SaleResponse
    assistant.py           ← AssistantChatRequest/Response
  routers/
    auth.py                ← POST /api/v1/auth/login, JWT
    vendors.py             ← CRUD vendors
    items.py               ← CRUD items, barcode lookup, labels
    sales.py               ← Sale history
    pos.py                 ← Checkout, barcode/search endpoints
    assistant.py           ← AI chat, tool calling
  services/
    barcode.py             ← generate_sku(), generate_barcode_image()
    labels.py              ← PDF labels, Dymo XML
migrations/
  001_initial_schema.sql   ← Full 8-table schema
  002_add_label_style.sql  ← label_style column
scripts/
  seed_dev.py              ← Seeds all test accounts and items
frontend/
  static/
    css/main.css           ← Bowenstreet brand styles
    js/
      api.js               ← JWT fetch wrapper (sessionStorage)
      assistant-panel.js   ← Shared AI assistant panel
  vendor/
    login.html             ← All roles log in here
    dashboard.html         ← Vendor dashboard (mobile-friendly)
    items.html             ← Item management (mobile-friendly)
  admin/
    index.html             ← Admin dashboard
    vendors.html           ← Vendor management
    customers.html         ← Customer/vendor lookup (cashier access)
  pos/
    index.html             ← POS register (mobile + camera scan)
```

---

## 🗃️ Database Schema (8 Tables)

| Table | Key Fields |
|-------|-----------|
| vendors | id, name, email, password_hash, role, booth_number, monthly_rent, payout_method, zelle_handle, status |
| vendor_balances | vendor_id (unique), balance |
| items | id, vendor_id, sku, barcode, name, price, sale_price, sale_start, sale_end, status, label_style |
| sales | id, cashier_id, subtotal, tax_rate, tax_amount, total, payment_method |
| sale_items | sale_id, item_id, vendor_id, quantity, unit_price, line_total |
| rent_payments | vendor_id, amount, period_month, status |
| payouts | vendor_id, period_month, gross_sales, rent_deducted, net_payout, status |
| payout_batches | (batch tracking for payout runs) |

**Key rules:**
- Tax rate: 5.5% (Winnebago County WI) — check is_tax_exempt per item
- SKU format: BSM-{vendor_id:04d}-{sequence:06d}
- Barcodes: Code 128, compatible with existing Ricochet barcodes
- Sale prices activate/deactivate automatically by sale_start and sale_end dates
- DB trigger auto-creates vendor_balance row on vendor insert
- Soft deletes: items set to status='removed', vendors set to status='suspended'

---

## 🔌 API Endpoints

**Auth**
- POST /api/v1/auth/login — OAuth2 form (username=email, password)
- POST /api/v1/auth/logout

**Vendors** (admin only for write)
- GET/POST /api/v1/vendors/
- GET/PUT/DELETE /api/v1/vendors/{id}

**Items**
- GET/POST /api/v1/items/
- GET /api/v1/items/barcode/{barcode} — POS barcode lookup
- GET/PUT/DELETE /api/v1/items/{id}
- GET /api/v1/items/{id}/label — PDF label
- GET /api/v1/items/{id}/dymo-label — Dymo XML

**POS**
- GET /api/v1/pos/search?q= — search items by name/barcode
- GET /api/v1/pos/barcode/{barcode} — exact barcode lookup
- POST /api/v1/pos/sale — checkout
- POST /api/v1/pos/payment-callback — Poynt webhook (stub)

**Sales**
- GET /api/v1/sales/
- GET /api/v1/sales/{id}
- GET /api/v1/sales/summary/today

**Assistant**
- POST /api/v1/assistant/chat — AI chat with tool calling

**Docs:** http://138.68.239.233/docs

---

## 💰 Business Rules

**Rent:**
- Deducted from vendor balance on the 27th of each month
- Field: vendors.rent_due_day (default 27)

**Payouts:**
- Processed on the 1st of each month
- Method: Zelle (manual, ~15 min for 70 vendors)
- System generates ready-to-send list
- ACH direct deposit planned for Phase 2

**Vendor roles:**
- vendor — own items/dashboard only
- cashier — POS + read vendors + full item management
- admin — everything

---

## 🤖 AI Assistant

- Provider: OpenRouter
- Model: google/gemini-2.0-flash
- API key: OPENROUTER_API_KEY (in .env)
- Available on: all pages (vendor, admin, POS)
- Capabilities: add/edit/archive items via chat, photo analysis, description writing, SEO descriptions
- Tool calling: add_item, edit_item, archive_item, list_items, get_item

---

## 📋 Build Phases

| Phase | Status | Scope |
|-------|--------|-------|
| 1 | ✅ Complete | Vendors, items, barcodes, labels, auth |
| 2 | ✅ Complete | POS register, checkout, vendor balance updates |
| 3 | ✅ Complete | Receipt printing, Dymo labels, mobile UI, AI assistant, cashier permissions |
| 4 | 🔲 Pending | GoDaddy Poynt card payment integration |
| 5 | 🔲 Pending | Auto rent deduction (27th), auto payout list (1st), email notifications |
| 6 | 🔲 Pending | Tax reports, Wix website item listings |
| 7 | 🔲 Pending | Side-by-side testing with Ricochet, staff training, cutover |

---

## ⚠️ Known Migration Notes

When deploying new code that adds database columns, always run the ALTER TABLE manually on the server:

```bash
# Example — adding a new column
sudo -u postgres psql -d bmm_pos -c "ALTER TABLE table_name ADD COLUMN IF NOT EXISTS column_name TYPE DEFAULT value;"
```

**Columns added after initial schema:**
- items.label_style VARCHAR(20) DEFAULT 'standard' — added manually March 2026

---

## 🔐 Environment Variables (.env)

```
DATABASE_URL=postgresql+asyncpg://bmm_user:BmmPos2024Secure@localhost/bmm_pos
SECRET_KEY=bowenstreet-production-secret-2024
TAX_RATE=0.055
STORE_NAME=Bowenstreet Market
OPENROUTER_API_KEY=your-key-here
```

---

## 🎨 Brand

- Primary background: #38383B (dark charcoal)
- Accent: #A8A6A1 (warm gray)
- Surface/card: #44444A
- Text: white on dark, #374151 on light
- Border radius: 0px (square corners throughout)
- Headings: EB Garamond
- Body: Roboto
- Buttons: uppercase, tracked labels
