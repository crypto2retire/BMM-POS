# BMM-POS — Bowenstreet Market Point of Sale System

## Overview

A full-featured point-of-sale and vendor management system for a vendor mall with up to 120 vendors. Built with Python FastAPI, PostgreSQL, and vanilla JavaScript.

## Tech Stack

- **Backend**: Python FastAPI with SQLAlchemy async ORM
- **Database**: Replit built-in PostgreSQL (via `DATABASE_URL`)
- **Auth**: JWT (python-jose) + bcrypt (passlib)
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
  schemas/
    vendor.py     — VendorCreate, VendorUpdate, VendorResponse, Token
    item.py       — ItemCreate, ItemUpdate, ItemResponse (w/ computed active_price)
    sale.py       — SaleCreate, SaleResponse, CartItem, SaleItemResponse, Poynt schemas
  routers/
    auth.py       — Login, get_current_user, require_admin, require_cashier_or_admin
    vendors.py    — CRUD for vendors (admin-only management)
    items.py      — CRUD for items (vendor self-service + admin)
    sales.py      — POS checkout, sale history
    pos.py        — Poynt terminal charge + status polling endpoints
  services/
    barcode.py    — SKU generation (BSM-XXXX-YYYYYY) + barcode PNG
    labels.py     — PDF label generation (single + batch)
    poynt.py      — GoDaddy Poynt Cloud API (RSA JWT + order/transaction calls)
migrations/
  001_initial_schema.sql — All tables, indexes, trigger
scripts/
  seed_dev.py     — Creates admin + cashier + 3 vendors + 15 items with sale prices
frontend/
  index.html              — Redirects to login
  static/css/main.css     — Full stylesheet (teal #1A6B5A, print @media for receipts)
  static/js/api.js        — JWT fetch wrapper (window.name persistence)
  vendor/
    login.html    — Login page (redirects by role: admin→/admin, cashier→/pos, vendor→/vendor)
    dashboard.html — Vendor stats: balance, items, booth
    items.html    — Item management with add/edit/delete/label
  admin/
    index.html    — Admin dashboard with vendor/item stats + POS Terminal nav link
    vendors.html  — Admin vendor management (add/edit/suspend) with cashier role option
  pos/
    index.html    — Full employee POS terminal (barcode scanner, cart, cash/card payments, receipt)
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
| POST | /sales/ | Auth | Create sale (checkout) |
| GET | /sales/ | Auth | List sales (admin/cashier=all, vendor=own) |
| GET | /sales/{id} | Auth | Get single sale |
| POST | /pos/poynt/charge | Cashier/Admin | Initiate Poynt terminal charge |
| GET | /pos/poynt/status/{id} | Cashier/Admin | Poll Poynt transaction status |

## Database Tables

- `vendors` — All users (role: vendor/cashier/admin)
- `vendor_balances` — Auto-created by DB trigger on vendor insert
- `items` — Inventory with sale price and date range support
- `sales` — POS transaction headers (subtotal, tax, total, payment_method, cash_tendered, change_given)
- `sale_items` — Line items per sale (linked to item + vendor)
- `rent_payments` — Monthly rent tracking
- `payouts` — Vendor payout records

## Authentication & Roles

JWT stored in `window.name` (persists across same-tab navigation, cleared on tab close). Not localStorage or sessionStorage. Tokens expire after 8 hours.

| Role | Access |
|------|--------|
| vendor | Own items, own dashboard, own sale history |
| cashier | POS terminal only (scan, checkout, view sales) |
| admin | Everything — all vendors, items, sales, plus POS |

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

## Key Behaviors

- Vendors can only see/edit their own items
- Admins can manage all vendors and items
- Cashiers can operate POS but cannot manage vendors/items
- Sale pricing: active_price uses sale_price when today is between sale_start and sale_end
- On sale completion: inventory is decremented, vendor balances are credited
- SKU format: `BSM-{vendor_id:04d}-{sequence:06d}`
- Barcode: 12-digit numeric (auto-generated) or custom
- Vendor suspend = soft delete (status = "suspended")
- Item delete = soft delete (status = "removed")
- DB trigger auto-creates `vendor_balances` row on vendor insert (do NOT insert manually)
