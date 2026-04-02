# BMM-POS — Bowenstreet Market Point of Sale
## Master Reference for Claude Code Sessions

---

## 1 · Identity

| field | value |
|-------|-------|
| **Project** | BMM-POS (Bowenstreet Market Mall – Point-of-Sale System) |
| **Location** | 2837 Bowen St, Oshkosh WI 54901 |
| **Concept** | 120-vendor antique / vintage / handcrafted mall |
| **Stack** | Python 3 · FastAPI · PostgreSQL · SQLAlchemy (async) · JWT auth · plain HTML + vanilla JS |
| **AI model** | `google/gemini-2.0-flash-001` via OpenRouter |
| **Payments** | Square (reservations + vendor rent) |
| **Repo** | `https://github.com/crypto2retire/BMM-POS` |

---

## 2 · Environment

| var | purpose | notes |
|-----|---------|-------|
| `DATABASE_URL` | Postgres connection string | auto-set by Replit |
| `OPENROUTER_API_KEY` | AI chat (Gemini Flash via OpenRouter) | in Replit Secrets |
| `ANTHROPIC_API_KEY` | reserved | in Replit Secrets |
| `SQUARE_ACCESS_TOKEN` | Square API auth | in Replit Secrets |
| `SQUARE_APPLICATION_ID` | Square app ID | in Replit Secrets |
| `SQUARE_LOCATION_ID` | Square location | in Replit Secrets |

### Run command
```bash
uvicorn app.main:app --host 0.0.0.0 --port 5000
```

---

## 3 · Credentials (dev / seed)

| role | email | password |
|------|-------|----------|
| admin | `admin@bowenstreetmarket.com` | set via `ADMIN_PASSWORD` env var |
| cashier | `cashier@bowenstreetmarket.com` | set via `CASHIER_PASSWORD` env var |

---

## 4 · Token / Auth Rules

- **Storage:** `sessionStorage.getItem('bmm_token')` — NEVER `localStorage` or `window.name`
- **Login page:** `/vendor/login.html` (shared for all roles)
- **Redirects after login:**
  - `vendor` → `/vendor/dashboard.html`
  - `cashier` → `/pos/index.html`
  - `admin` → `/admin/index.html`
  - `is_vendor` flag → user may choose vendor OR their role destination

---

## 5 · Design Language

| token | value |
|-------|-------|
| `--bg` | `#38383B` |
| `--gold` | `#C9A96E` |
| `--warm-border` | `rgba(201,169,110,0.22)` |
| `--text` | `#F0EDE8` |
| `--surface` | `#44444A` |
| `--surface-2` | `#4e4e54` |
| `--border` | `#555558` |
| navbar bg | `#1e1e20` (darker than `--bg`) |
| border-radius | `0px` everywhere |
| heading font | EB Garamond italic |
| body font | Roboto 300 |

### Design pattern
- Warm editorial / antique aesthetic
- Gold accent borders and hover effects
- Ornamental diamond dividers (`.ornament` class)
- Ledger-style tables with gold header accents
- Dark glass-like form inputs with gold focus glow
- Gradient-enhanced primary buttons

---

## 6 · SKU Format

```
BSM-{vendor_id:04d}-{seq:06d}
```
Example: `BSM-0012-000047`

---

## 7 · Tax Rate

**5% (0.05)** — set in both the JavaScript `TAX_RATE` constant and the display label.

---

## 8 · Project Structure

```
app/
  main.py              ← FastAPI app + lifespan (auto-creates tables/columns)
  database.py          ← async engine + session
  models/
    __init__.py        ← re-exports all models + Base
    vendor.py          ← Vendor, VendorBalance
    item.py            ← Item (with photo_url, tags)
    sale.py            ← Sale, SaleItem
    rent.py            ← RentPayment
    payout.py          ← Payout
    customer.py        ← Customer
    store_setting.py   ← StoreSetting (key/value config)
  schemas/
    vendor.py item.py sale.py rent.py payout.py customer.py
  routers/
    auth.py            ← JWT login, role checks, token refresh
    vendors.py         ← CRUD vendors + is_vendor flag
    items.py           ← CRUD items + photo upload + search
    pos.py             ← POS checkout flow
    sales.py           ← Sales history + returns
    rent.py            ← Rent tracking + Square payments
    payouts.py         ← Vendor payout management
    customers.py       ← Customer loyalty
    storefront.py      ← Public shop API
    ai.py              ← OpenRouter chat (Gemini Flash)
    reports.py         ← Reporting endpoints (daily sales, vendor perf, top items, etc.)
    settings.py        ← Store settings CRUD
frontend/
  pos/
    index.html         ← POS terminal (scanner + cart + checkout)
    register.html      ← Cash register / payment screen
  vendor/
    login.html         ← Shared login (all roles)
    dashboard.html     ← Vendor dashboard
    items.html         ← Vendor inventory management + photo upload
  admin/
    index.html         ← Admin dashboard
    vendors.html       ← Vendor management + directory + edit + password reset
    rent.html          ← Rent management
    customers.html     ← Legacy URL; redirects to vendors.html
    reports.html       ← Reporting suite
    settings.html      ← Store settings panel
  shop/
    index.html         ← Public storefront
  static/
    css/main.css       ← Global styles
    js/assistant-panel.js ← AI chat panel
    llms.txt           ← LLM-friendly site description
    robots.txt         ← Crawler rules
    uploads/items/     ← Item photo uploads
```

---

## 9 · Key Technical Notes

- **bcrypt must stay at 4.0.1** (pinned for compatibility)
- **DB trigger** auto-creates `vendor_balances` row when a vendor is inserted
- **Auto column creation:** `app/main.py` lifespan checks for missing columns and adds them automatically on startup
- **AI assistant panel:** `initAssistantPanel(contextString, { buttonBottom: '...' })` — Admin: `70px`, POS/Vendor: `80px`
- **Photo uploads:** Items support photo upload via `/api/items/{id}/photo` endpoint, stored in `frontend/static/uploads/items/`
- **Vendor `is_vendor` flag:** Cashiers and admins can also have vendor booths; login page shows destination choice

---

## 10 · Phase Completion Log

### Phase 1 — Core System ✅
- FastAPI + PostgreSQL + SQLAlchemy async
- JWT authentication (admin, cashier, vendor roles)
- Full CRUD: vendors, items, sales, rent, payouts, customers
- POS terminal with barcode scanning
- Vendor portal with dashboard + inventory
- Admin panel with all management pages

### Phase 2 — Payments & Polish ✅
- Square integration (rent payments + reservations)
- Public shop page with cart + checkout
- AI assistant (Gemini Flash via OpenRouter)
- Cash register with receipt printing
- Customer loyalty tracking

### Phase 3 — UX Redesign & Features ✅
- Complete dark editorial redesign (all 11 pages)
- Gold accent warm aesthetic
- Ornamental dividers and ledger-style tables
- Tax rate corrected to 5%
- Mobile-responsive navigation
- Reports page (daily sales, vendor performance, top items, hourly, payment methods, balances)
- Settings page (store config, tax, commission, receipt text)
- Vendor management expanded (directory, edit, password reset, is_vendor flag)
- Item photo uploads
- SEO: llms.txt, robots.txt, schema.org markup, OG tags
- Vendor items page with list view, sort, search, pagination

---

## 11 · Current State

**All core features are built and functional.** The system is deployed and running.

### Known items for future work:
- Square webhook integration for real-time payment confirmation
- Email notifications for vendors (balance updates, rent due)
- Barcode label printing
- Inventory alerts (low stock)
- Vendor payout automation
- Advanced analytics dashboards
- Multi-location support
