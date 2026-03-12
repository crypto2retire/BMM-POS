# BMM-POS — Bowenstreet Market Point of Sale System

## Overview

A full-featured point-of-sale and vendor management system for a vendor mall with up to 120 vendors. Built with Python FastAPI, PostgreSQL, and vanilla JavaScript.

## Tech Stack

- **Backend**: Python FastAPI with SQLAlchemy async ORM
- **Database**: Replit built-in PostgreSQL (via `DATABASE_URL`)
- **Auth**: JWT (python-jose) + bcrypt (direct, not passlib)
- **Frontend**: Plain HTML + vanilla JavaScript (no frameworks)
- **PDF labels**: ReportLab (2.25 × 1.25 inch Zebra-compatible)
- **Barcodes**: python-barcode (Code 128)
- **Card payments**: GoDaddy Poynt Cloud API (RSA JWT auth)

## Application Structure

```
app/
  config.py       — Pydantic settings from env vars (tax_rate, JWT secret, etc.)
  database.py     — Async SQLAlchemy engine + Base + get_db
  main.py         — FastAPI app, CORS, routes, static files
  models/
    vendor.py     — Vendor, VendorBalance ORM models
    item.py       — Item ORM model
    sale.py       — Sale, SaleItem ORM models
    rent.py       — RentPayment ORM model
    payout.py     — Payout ORM model
    studio_class.py — StudioClass ORM model (classes/workshops)
  schemas/
    vendor.py     — VendorCreate, VendorUpdate, VendorResponse, Token
    item.py       — ItemCreate, ItemUpdate, ItemResponse (w/ computed active_price)
    sale.py       — SaleCreate, SaleResponse, CartItem, SaleItemResponse, Poynt schemas
    studio_class.py — StudioClassCreate, StudioClassUpdate, StudioClassResponse
  routers/
    auth.py       — Login, get_current_user, require_admin, require_cashier_or_admin
    vendors.py    — CRUD for vendors (admin-only management)
    items.py      — CRUD for items (vendor self-service + admin)
    sales.py      — POS checkout, sale history
    pos.py        — Poynt terminal charge + status polling endpoints
    rent.py       — Vendor rent payment via Square (POST /vendor/pay-rent, /vendor/rent-confirmed)
    admin.py      — Admin rent status (GET /admin/rent-status) + vendor flag toggle
    studio.py     — Studio class CRUD (GET/POST/PUT/DELETE /studio/classes)
  services/
    barcode.py    — SKU generation (BSM-XXXX-YYYYYY) + barcode PNG
    labels.py     — PDF label generation (single + batch)
    poynt.py      — GoDaddy Poynt Cloud API (RSA JWT + order/transaction calls)
    square.py     — Square Checkout API helper (create_payment_link)
migrations/
  001_initial_schema.sql — All tables, indexes, trigger
scripts/
  seed_dev.py     — Creates admin + cashier + 3 vendors + 15 items with sale prices
frontend/
  index.html              — SEO landing page (schema.org, OG tags, keyword-rich)
  static/css/main.css     — Full stylesheet (Bowenstreet Market brand: dark #38383B, accent #A8A6A1, EB Garamond headings, Roboto body, 0px radius, print @media for receipts)
  static/images/logo.webp  — Official Bowenstreet Market logo (white emblem)
  static/images/favicon.webp — Favicon
  static/js/api.js        — JWT fetch wrapper (sessionStorage persistence)
  static/js/change-password.js — Shared password change modal (all roles)
  vendor/
    login.html    — Login page (redirects by role; shows choice screen for is_vendor admins/cashiers)
    dashboard.html — Vendor stats: balance, items, booth + Pay Rent with Card section
    items.html    — Item management with add/edit/delete/label (booth mode scopes to own items)
  admin/
    index.html    — Admin dashboard with vendor/item stats + Rent link
    vendors.html  — Admin vendor management (add/edit/suspend); shows 🚩 for flagged vendors
    rent.html     — Rent status dashboard: all vendors, CURRENT/DUE/OVERDUE badges, flag/unflag buttons
    studio.html   — Studio class calendar (calendar/list view, add/edit/delete classes)
  studio/
    index.html    — Public studio class calendar with class cards and detail overlay
  shop/
    index.html    — Public storefront: browse items, "Pay & Reserve" → Square checkout
  pos/
    index.html    — Full employee POS terminal (barcode scanner, cart, cash/card payments, receipt)
    register.html — Cash register: two-column layout, item search, cart, cash/card checkout
```

## API Routes

All routes prefixed with `/api/v1/`:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/login | — | OAuth2 login → JWT |
| POST | /auth/logout | — | Stateless logout |
| GET | /vendors/ | Admin | List all vendors |
| POST | /vendors/ | Admin | Create vendor |
| GET | /vendors/{id} | Self/Admin | Get vendor |
| PUT | /vendors/{id} | Self/Admin | Update vendor |
| DELETE | /vendors/{id} | Admin | Suspend vendor |
| GET | /items/ | Auth | List items (vendors see own only) |
| POST | /items/ | Auth | Create item (auto-SKU/barcode) |
| GET | /items/barcode/{bc} | Auth | POS barcode lookup |
| GET | /items/{id} | Auth | Get item |
| PUT | /items/{id} | Auth | Update item |
| DELETE | /items/{id} | Auth | Soft-delete item |
| GET | /items/{id}/label | Auth | PDF label download |
| POST | /items/labels/batch | Auth | Batch PDF labels (body: {item_ids}) |
| POST | /sales/ | Auth | Create sale (checkout) |
| GET | /sales/ | Auth | List sales (admin/cashier=all, vendor=own) |
| GET | /sales/summary/today | Admin/Cashier | Today's sale count, revenue, tax |
| GET | /sales/{id} | Auth | Get single sale |
| POST | /pos/sale | Admin/Cashier | Cash register checkout (per-item tax exempt support) |
| POST | /pos/payment-callback | Auth | Placeholder payment webhook |
| POST | /pos/poynt/charge | Cashier/Admin | Initiate Poynt terminal charge |
| GET | /pos/poynt/status/{id} | Cashier/Admin | Poll Poynt transaction status |

| GET | /studio/classes | Public | List published classes (query: start, end, category) |
| GET | /studio/classes/{id} | Public | Get single class details |
| POST | /studio/classes | Admin | Create studio class |
| PUT | /studio/classes/{id} | Admin | Update studio class |
| DELETE | /studio/classes/{id} | Admin | Delete studio class |
| GET | /studio/categories | Public | List distinct class categories |

## Database Tables

- `vendors` — All users (role: vendor/cashier/admin)
- `vendor_balances` — Auto-created by DB trigger on vendor insert
- `items` — Inventory with sale price and date range support
- `sales` — POS transaction headers (subtotal, tax, total, payment_method, cash_tendered, change_given)
- `sale_items` — Line items per sale (linked to item + vendor)
- `studio_classes` — Studio class schedule (title, instructor, date, time, capacity, enrolled, price, category, location)
- `rent_payments` — Monthly rent tracking (method: "square" for online payments)
- `reservations` — Square-paid shop reservations (status: pending → confirmed)
- `payouts` — Vendor payout records
- `vendors.rent_flagged` — Boolean flag for vendors 30+ days overdue on rent

## Authentication & Roles

JWT stored in `sessionStorage` under key `bmm_token` (persists across same-tab navigation, cleared on tab close). Tokens expire after 8 hours.

| Role | Access |
|------|--------|
| vendor | Own items, own dashboard, own sale history |
| cashier | POS terminal only (scan, checkout, view sales) |
| admin | Everything — all vendors, items, sales, plus POS |

### is_vendor Booth Mode

Admins and cashiers with `is_vendor=true` AND a `booth_number` set see a choice screen at login: "Admin Dashboard" or "My Booth". Choosing "My Booth" sets `sessionStorage['bmm_booth_mode']='1'` and navigates to the vendor dashboard. In booth mode:
- Items page shows only their own items (filtered by vendor_id)
- Vendor filter bar is hidden
- Bottom nav and vendor-style nav are shown
- Page title shows "My Items" instead of "Item Management"
- JWT includes `is_vendor`, `booth_number`, and `name` claims

## POS Terminal Features

- Barcode scanner input (USB HID keyboard mode — auto-focused, Enter to add)
- Cart management with quantity controls, remove, clear
- Sale price awareness (uses active_price at time of sale)
- Cash payment with change calculation, quick-amount buttons ($20/$50/$100)
- Card payment via GoDaddy Poynt Cloud API (terminal charge + 2s polling)
- Receipt modal with thermal-printer-compatible print layout (80mm @media print)
- Auth-protected — cashier or admin role required

## Poynt Configuration (optional)

Set these env vars to enable card payments. Without them, cash-only mode works fine:
- `POYNT_APP_ID` — Developer app ID from Poynt Developer Portal
- `POYNT_PRIVATE_KEY` — PEM-encoded RSA private key
- `POYNT_BUSINESS_ID` — Merchant's Poynt business UUID
- `POYNT_STORE_ID` — Store UUID

## Seed Data (Dev)

Run: `python scripts/seed_dev.py`

| User | Email | Password | Role |
|------|-------|----------|------|
| Admin User | admin@bowenstreetmarket.com | admin123 | admin |
| Jane Doe | cashier@bowenstreetmarket.com | cashier123 | cashier |
| Sarah Johnson | sarah@email.com | vendor123 | vendor (Booth A-12) |
| Mike Chen | mike@email.com | vendor123 | vendor (Booth B-07) |
| Linda Kowalski | linda@email.com | vendor123 | vendor (Booth C-22) |

## Running the App

The workflow runs: `uvicorn app.main:app --host 0.0.0.0 --port 5000`

- App: `http://0.0.0.0:5000/`
- API Docs: `/docs`
- Login: `/vendor/login.html`
- POS Terminal: `/pos/index.html`

## Mobile Responsive Design

All vendor pages are fully mobile-first responsive (375px/390px/768px/1024px):
- **vendor/login.html** — full-width card on mobile, 48px button, keyboard-safe padding
- **vendor/dashboard.html** — stats grid (2-col mobile, 4-col desktop); Recent Items switches from table to item cards on mobile; prominent "Add New Item" CTA; fixed bottom nav bar (🏠 Home / 🏷️ Items / 🚪 Logout)
- **vendor/items.html** — always renders item cards grid (1-col mobile → 2-col tablet → 3-col desktop); form modal is full-screen slide-up on mobile; photo upload with `accept="image/*" capture="environment"` (opens camera on phones); hamburger nav on mobile
- Inputs are `font-size: 16px` minimum on mobile (prevents iOS auto-zoom)
- All tap targets ≥ 44px height
- Bottom nav hidden for admin/cashier roles (not needed on those pages)

## Photo Upload

Item photos are stored in `frontend/static/images/items/` and served as static files.
- `POST /api/v1/items/{id}/photo` — multipart upload, appends to `photo_urls` array
- `DELETE /api/v1/items/{id}/photo?photo_url=...` — removes a photo from the array and deletes the file
- Inline per-card photo upload button on items page (opens camera/gallery)
- Photo thumbnail shown in item card top-left corner

## POS Features

- **Suspend/Hold Order**: Cart can be held (⏸ Hold button) and resumed later via green Resume button. Held orders stored in sessionStorage.
- **Receipt Lookup**: "Receipts" button in POS navbar opens search by sale # or date. Can view and reprint old receipts.
- **Online Orders**: "Orders" button in POS navbar shows pending/completed reservations from the shop. New order badge notification (polls every 30s). Can mark orders as picked up.
- **Receipt**: Includes BMM logo at top, optimized for 72mm thermal paper width. Right-side cutoff fixed.

## Key Behaviors

- Vendors can only see/edit their own items
- Admins can manage all vendors and items
- Cashiers can read vendors list (read-only), manage items, access Vendor Directory
- Sale pricing: active_price uses sale_price when today is between sale_start and sale_end
- On sale completion: inventory is decremented, vendor balances are credited
- Consignment items: `is_consignment=true` + `consignment_rate` (decimal, e.g. 0.40 = 40% store keeps). On sale, vendor balance credited with (line_total - consignment_amount). Sale items track `is_consignment`, `consignment_rate`, `consignment_amount`
- SKU format: `BSM-{vendor_id:04d}-{sequence:06d}`
- Barcode: 12-digit numeric (auto-generated) or custom
- Vendor suspend = soft delete (status = "suspended")
- Item delete = soft delete (status = "removed")
- DB trigger auto-creates `vendor_balances` row on vendor insert (do NOT insert manually)
