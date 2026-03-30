# BMM-POS — Bowenstreet Market Point of Sale System

## Overview

BMM-POS is a comprehensive point-of-sale and vendor management system designed for multi-vendor malls accommodating up to 120 vendors. It streamlines sales, inventory, vendor payouts, and includes features for managing studio classes and gift cards. The system aims to provide an efficient and scalable solution for multi-vendor retail environments, enhancing operational efficiency and improving vendor satisfaction. Key capabilities include a full POS terminal, extensive vendor and item management with barcode/label generation, sales tracking, studio class booking, an in-house gift card system, and robust administrative tools for bulk imports, rent tracking, payout processing, and customizable settings. It also features a public storefront with an AI assistant and vendor booth showcases.

## User Preferences

I prefer iterative development with clear communication on major changes. Please prioritize functional correctness and security. When making architectural decisions, favor simplicity and maintainability. For frontend tasks, stick to vanilla JavaScript and avoid external frameworks.

## System Architecture

The system is built on a Python FastAPI backend with PostgreSQL for data persistence and a vanilla JavaScript frontend.

### UI/UX Decisions

The frontend adheres to Bowenstreet Market branding, using a dark (`#38383B`) and accent (`#A8A6A1`) color scheme with EB Garamond for headings and Roboto for body text. All design elements feature 0px radius. The UI is fully mobile-first responsive, adapting layouts for various screen sizes (375px/390px/768px/1024px) with considerations for touch targets and input readability. Special print styles are implemented for thermal-printer-compatible receipts (80mm width). Admin pages use consistent mobile patterns including a hamburger navigation dropdown, a `admin-bottom-nav` with 5 key links, and mobile card views for data tables below 767px.

### Technical Implementations

- **Backend**: Python FastAPI with SQLAlchemy for asynchronous ORM operations.
- **Authentication**: JWT tokens (python-jose) for API access, bcrypt for password hashing. Tokens are stored in `sessionStorage` and expire after 8 hours.
- **Frontend**: Plain HTML and vanilla JavaScript for high performance and minimal dependencies.
- **Timezone Handling**: All timestamps are stored in UTC in PostgreSQL and converted to Central Time (America/Chicago) for display.
- **Barcode & Label Generation**: `python-barcode` for Code 128 barcodes; `ReportLab` for PDF labels in various configurable sizes (10 formats). SKU format: `BSM-{vendor_id:04d}-{sequence:06d}`.
- **Role-Based Access Control**: Differentiated access for `vendor`, `cashier`, `admin` roles, including a "booth mode" for vendor-admins/cashiers.
- **Soft Deletion**: Vendors and items are soft-deleted by updating their `status` field.
- **Photo Uploads**: Item and studio class images are handled as multipart uploads, stored as static files, with paths referenced in the database. Ricochet storefront images scraped and imported for 196 items (522 images) via `scripts/scrape_ricochet_images.py` and `scripts/import_scraped_images.py`, matched by the `sku` field.
- **Image Persistence**: Product images are stored as binary data in the `item_images` PostgreSQL table (not just filesystem), served via `/api/v1/items/{id}/image`. This ensures images persist across Railway deploys. The `store-images-to-db` endpoint handles bulk import, skipping logo placeholders (218508 bytes) and using real product photos.
- **Dynamic Category Images**: Homepage "What You'll Find" section loads a random in-stock item with a photo from each category group via `GET /api/v1/storefront/category-images`. Categories map display names (Handmade, Vintage & Antique, etc.) to actual DB categories.
- **Data Sync Images**: `POST /api/v1/data-sync/apply-scraped-images` endpoint for applying Ricochet image mappings to any environment's database (admin password protected). `POST /api/v1/data-sync/store-images-to-db` persists scraped images into PostgreSQL `item_images` table.
- **Void/Reverse Transactions**: Supports comprehensive voiding of sales, reversing quantities, vendor balances, and gift card debits, with audit trails.
- **Admin Balance Adjustments**: Admins can credit/debit vendor balances with a full audit trail.
- **Batch Label Printing**: Items track a `label_printed` flag, with UI elements to select unprinted items and support vendor-specific label preferences (standard/Dymo).
- **Online Order Ready-for-Pickup Notifications**: Automated email notifications for customers when their online orders are ready for pickup.
- **Storefront Security**: Public storefront endpoints use UUIDs for reservations, rate limiting on critical payment endpoints, and robust input validation. Login brute-force protection is implemented.
- **AI Assistant**: Both public-facing (customer support, item search, class registration) and vendor-facing (customizable name) AI assistants using OpenRouter for tool-calling capabilities.
- **Data Reset**: An admin-only feature to reset all transactional and vendor data while preserving core settings and admin/cashier accounts.
- **Password Reset Flow**: Self-service forgot-password via email (JWT-based reset tokens, 60-min expiry), reset-password page, and change-password endpoint for logged-in users. Reset emails sent via Gmail API integration.

### Feature Specifications

- **POS Terminal**: Supports barcode scanning, cart management, multiple payment types (cash, card via Poynt, gift card), split payments, receipt generation, and order suspension/lookup.
- **Vendor Management**: CRUD operations for vendors, vendor-specific dashboards, and balance adjustment capabilities for admins.
- **Item Management**: CRUD for items, including automatic SKU/barcode generation, PDF label printing, and batch label printing tools.
- **Sales Management**: Records sales, manages inventory, and credits vendor balances, supporting consignment.
- **Studio Class Management**: CRUD for classes, public calendar, online registration, and image uploads.
- **Gift Card System**: In-house gift cards with barcode, balance tracking, and transaction history.
- **Bulk CSV Import**: Admin-only CSV upload for vendors and inventory, with deduplication and secure password generation.
- **Rent Tracking**: Monthly rent tracking, payment recording, and overdue flagging for vendors. Integrates rent deduction into payout processing.
- **Payout Processing**: Admin interface for previewing and processing vendor payouts, automatically deducting rent and sending email notifications.
- **Admin Settings Panel**: Comprehensive, tabbed settings page for store details, taxes, POS, features (toggleable modules), user roles, labels, and customizable email notifications.
- **Email Notifications**: Gmail API integration for branded HTML email templates for various events (payouts, orders, rent reminders), with customizable content via admin settings.
- **Vendor Booth Showcase**: Vendors can create public booth profiles with photos, video, description, and AI-assisted content, displayed on a public "Booths" page.
- **Vendor Landing Pages**: An add-on premium feature providing dedicated vendor pages (`/v/{slug}`) with extended content, contact info, social links, SEO, and full searchable inventory display with category filtering, sorting, and pagination.
- **Vendor Inventory Pages**: Standalone vendor inventory pages (`/shop/vendor/{id}`) for vendors without landing pages, showing full inventory with search, category filters, sorting, and pagination. Linked from booth cards and booth modal on the Booths page.

## External Dependencies

- **Database**: PostgreSQL
- **Payment Gateway (Card)**: GoDaddy Poynt Cloud API
- **Payment Gateway (Rent)**: Square Checkout API
- **PDF Generation**: ReportLab
- **Barcode Generation**: python-barcode
- **Authentication**: python-jose (for JWTs)
- **Password Hashing**: bcrypt
- **Email Service**: Gmail API (via Replit connector)
- **AI/LLM**: OpenRouter (for AI assistants)
- **Secrets Management**: Replit Secrets (for `SECRET_KEY`, `POYNT_*`, `SQUARE_*`, `ADMIN_PASSWORD`, `CASHIER_PASSWORD`)