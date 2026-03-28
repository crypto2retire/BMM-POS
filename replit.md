# BMM-POS — Bowenstreet Market Point of Sale System

## Overview

BMM-POS is a comprehensive point-of-sale and vendor management system designed for vendor malls accommodating up to 120 vendors. It streamlines sales, inventory, vendor payouts, and includes features for managing studio classes and gift cards. The system aims to provide an efficient and scalable solution for multi-vendor retail environments, enhancing operational efficiency and improving vendor satisfaction.

## User Preferences

I prefer iterative development with clear communication on major changes. Please prioritize functional correctness and security. When making architectural decisions, favor simplicity and maintainability. For frontend tasks, stick to vanilla JavaScript and avoid external frameworks.

## System Architecture

The system is built on a Python FastAPI backend with PostgreSQL for data persistence and a vanilla JavaScript frontend.

### UI/UX Decisions

The frontend design adheres to Bowenstreet Market branding with a dark (`#38383B`) and accent (`#A8A6A1`) color scheme, using EB Garamond for headings and Roboto for body text. All design elements feature 0px radius. The UI is fully mobile-first responsive, adapting layouts for various screen sizes (375px/390px/768px/1024px) with considerations for touch targets and input readability. Special print styles are implemented for thermal-printer-compatible receipts (80mm width).

### Technical Implementations

- **Backend**: Python FastAPI leverages SQLAlchemy for asynchronous ORM operations.
- **Authentication**: JWT tokens (python-jose) secure API access, with bcrypt for password hashing. Tokens are stored in `sessionStorage` and expire after 8 hours.
- **Frontend**: Plain HTML and vanilla JavaScript are used, minimizing external dependencies and ensuring high performance.
- **Timezone Handling**: All timestamps are stored in UTC in PostgreSQL and converted to Central Time (America/Chicago) for display and reporting using `zoneinfo.ZoneInfo`.
- **Barcode & Label Generation**: `python-barcode` generates Code 128 barcodes, and `ReportLab` creates 2.25 × 1.25 inch Zebra-compatible PDF labels.
- **SKU Generation**: A standardized SKU format `BSM-{vendor_id:04d}-{sequence:06d}` is used for items.
- **Role-Based Access Control**: Differentiated access based on roles: `vendor`, `cashier`, `admin`.
- **is_vendor Booth Mode**: Admins/cashiers who are also vendors can access a "booth mode" to manage their own inventory.
- **Soft Deletion**: Vendors and items are soft-deleted by updating their `status` field.
- **Photo Uploads**: Item and studio class images are handled as multipart uploads and stored as static files, with paths referenced in the database.

### Feature Specifications

- **POS Terminal**: Supports barcode scanning, cart management, cash and card payments (via Poynt API), gift card management (activate, load, redeem), split payments (all combinations: cash+card, gc+cash, gc+card, gc+cash+card), receipt generation, and **void/reverse transactions**. Includes features like suspend/hold orders, receipt lookup, and online order management. Split payments store `gift_card_amount` and `gift_card_barcode` on the Sale model. Void sales: `POST /api/v1/pos/sale/{id}/void` reverses item quantities, vendor balances, and gift card debits; marks sale with `is_voided`, `voided_at`, `voided_by`, `void_reason`. EOD report excludes voided sales from totals and shows voided count/total separately.
- **Vendor Management**: CRUD operations for vendors (admin-only management), with vendor-specific dashboards displaying balance and item statistics. **Admin Balance Adjustments**: Admins can credit or debit vendor balances via `/api/v1/vendors/{id}/balance/adjust` with full audit trail (`balance_adjustments` table). History viewable at `/api/v1/vendors/{id}/balance/history`. Admin UI has Adjust and History buttons on each vendor row in the All Vendors table.
- **Item Management**: CRUD operations for items, including automatic SKU/barcode generation and PDF label printing. Vendors can only manage their own items. **Batch Label Printing**: Items track `label_printed` flag — set to `true` when any label (PDF, Dymo, batch) is generated. "Select Unprinted" button selects all active items without labels, gold "X items need labels" banner shows when unprinted items exist, and "NEEDS LABEL" badge appears on item cards/rows. After printing, items auto-reload to reflect updated status. **Vendor Label Preference**: Each vendor has a `label_preference` (standard/dymo) stored on their profile, settable via dropdown on the items page or `PATCH /api/v1/vendors/me/label-preference`. New items default to the vendor's chosen label type. **Print Window Navigation**: Label print windows include a navigation toolbar with "Back to Items" link, role-appropriate dashboard link (Admin Dashboard / POS Terminal / Dashboard), and "Close Window" button. Toolbar hides during print via `@media print`.
- **Sales Management**: Records sales, tracks inventory decrement, and credits vendor balances. Supports consignment items with configurable rates.
- **Studio Class Management**: CRUD for studio classes, public class calendar, online registration, and image uploads.
- **Gift Card System**: In-house gift cards with barcode, balance tracking, and transaction history.
- **Bulk CSV Import**: Admin-only CSV upload for vendors and inventory items (`/api/v1/bulk-import/vendors`, `/api/v1/bulk-import/inventory`). Includes vendor deduplication by email, auto-generated secure passwords, per-row savepoints, and a clear-test-data endpoint (blocked when sales exist). Admin UI in the Data Import section of `/admin/index.html` with template downloads.
- **Rent Tracking**: Monthly rent tracking for vendors, including payment methods and overdue flagging.

## External Dependencies

- **Database**: PostgreSQL (via Replit's `DATABASE_URL`).
- **Payment Gateway (Card)**: GoDaddy Poynt Cloud API (requires `POYNT_APP_ID`, `POYNT_PRIVATE_KEY`, `POYNT_BUSINESS_ID`, `POYNT_STORE_ID`).
- **Payment Gateway (Rent)**: Square Checkout API (for vendor rent payments).
- **PDF Generation**: ReportLab (for item labels).
- **Barcode Generation**: python-barcode (for Code 128 barcodes).
- **Authentication**: `python-jose` (for JWT handling).
- **Password Hashing**: `bcrypt`.