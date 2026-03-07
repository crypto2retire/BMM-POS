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

## Application Structure

```
app/
  config.py       — Pydantic settings from env vars
  database.py     — Async SQLAlchemy engine + Base + get_db
  main.py         — FastAPI app, CORS, routes, static files
  models/
    vendor.py     — Vendor, VendorBalance ORM models
    item.py       — Item ORM model
  schemas/
    vendor.py     — VendorCreate, VendorUpdate, VendorResponse, Token
    item.py       — ItemCreate, ItemUpdate, ItemResponse (w/ computed active_price)
  routers/
    auth.py       — Login, logout, get_current_user, require_admin
    vendors.py    — CRUD for vendors (admin-only management)
    items.py      — CRUD for items (vendor self-service + admin)
  services/
    barcode.py    — SKU generation (BSM-XXXX-YYYYYY) + barcode PNG
    labels.py     — PDF label generation (single + batch)
migrations/
  001_initial_schema.sql — All tables, indexes, trigger
scripts/
  seed_dev.py     — Creates admin + 3 vendors + 15 items with sale prices
frontend/
  index.html              — Redirects to login
  static/css/main.css     — Full stylesheet (teal #1A6B5A color scheme)
  static/js/api.js        — JWT fetch wrapper (window.name persistence)
  vendor/
    login.html    — Login page (redirects by role)
    dashboard.html — Vendor stats: balance, items, booth
    items.html    — Item management with add/edit/delete/label
  admin/
    index.html    — Admin dashboard with vendor/item stats
    vendors.html  — Admin vendor management (add/edit/suspend)
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

## Database Tables

- `vendors` — All users (role: vendor/admin)
- `vendor_balances` — Auto-created by trigger on vendor insert
- `items` — Inventory with sale price and date range support
- `sales` — POS transaction headers
- `sale_items` — Line items per sale
- `rent_payments` — Monthly rent tracking
- `payouts` — Vendor payout records

## Authentication

JWT stored in `window.name` (persists across same-tab navigation, cleared on tab close). Not localStorage or sessionStorage. Tokens expire after 8 hours.

## Seed Data (Dev)

Run: `python scripts/seed_dev.py`

| User | Email | Password | Role |
|------|-------|----------|------|
| Admin User | admin@bowenstreetmarket.com | admin123 | admin |
| Sarah Johnson | sarah@email.com | vendor123 | vendor (Booth A-12) |
| Mike Chen | mike@email.com | vendor123 | vendor (Booth B-07) |
| Linda Kowalski | linda@email.com | vendor123 | vendor (Booth C-22) |

## Running the App

The workflow runs: `uvicorn app.main:app --host 0.0.0.0 --port 5000`

- App: `http://0.0.0.0:5000/`
- API Docs: `/docs`
- Login: `/vendor/login.html`

## Key Behaviors

- Vendors can only see/edit their own items
- Admins can manage all vendors and items
- Sale pricing: active_price uses sale_price when today is between sale_start and sale_end
- SKU format: `BSM-{vendor_id:04d}-{sequence:06d}`
- Barcode: 12-digit numeric (auto-generated) or custom (Ricochet imports)
- Vendor suspend = soft delete (status = "suspended")
- Item delete = soft delete (status = "removed")
