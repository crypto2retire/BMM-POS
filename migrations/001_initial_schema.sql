CREATE TABLE IF NOT EXISTS vendors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    booth_number VARCHAR(20),
    monthly_rent NUMERIC(10,2) NOT NULL DEFAULT 0,
    rent_due_day INTEGER NOT NULL DEFAULT 27,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'vendor',
    payout_method VARCHAR(20) DEFAULT 'check',
    zelle_handle VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendor_balances (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER UNIQUE NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    balance NUMERIC(10,2) NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    sku VARCHAR(100) UNIQUE NOT NULL,
    barcode VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    price NUMERIC(10,2) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    photo_urls TEXT[],
    is_online BOOLEAN NOT NULL DEFAULT FALSE,
    is_tax_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    sale_price NUMERIC(10,2),
    sale_start DATE,
    sale_end DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    cashier_id INTEGER REFERENCES vendors(id),
    subtotal NUMERIC(10,2) NOT NULL,
    tax_rate NUMERIC(5,4) NOT NULL DEFAULT 0.0550,
    tax_amount NUMERIC(10,2) NOT NULL,
    total NUMERIC(10,2) NOT NULL,
    payment_method VARCHAR(20) NOT NULL,
    cash_tendered NUMERIC(10,2),
    change_given NUMERIC(10,2),
    card_transaction_id VARCHAR(255),
    receipt_email VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sale_items (
    id SERIAL PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(10,2) NOT NULL,
    line_total NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS rent_payments (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    amount NUMERIC(10,2) NOT NULL,
    period_month DATE NOT NULL,
    method VARCHAR(20) NOT NULL DEFAULT 'balance',
    status VARCHAR(20) NOT NULL DEFAULT 'paid',
    notes TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payouts (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    period_month DATE NOT NULL,
    gross_sales NUMERIC(10,2) NOT NULL DEFAULT 0,
    rent_deducted NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_payout NUMERIC(10,2) NOT NULL DEFAULT 0,
    payout_method VARCHAR(20),
    zelle_handle VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    paid_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_items_vendor_id ON items(vendor_id);
CREATE INDEX IF NOT EXISTS idx_items_barcode ON items(barcode);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale_id ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_vendor_id ON sale_items(vendor_id);
CREATE INDEX IF NOT EXISTS idx_sales_created_at ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_rent_payments_vendor_period ON rent_payments(vendor_id, period_month);
CREATE INDEX IF NOT EXISTS idx_payouts_vendor_period ON payouts(vendor_id, period_month);

CREATE OR REPLACE FUNCTION create_vendor_balance()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO vendor_balances (vendor_id, balance)
    VALUES (NEW.id, 0)
    ON CONFLICT (vendor_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_create_vendor_balance ON vendors;
CREATE TRIGGER trigger_create_vendor_balance
    AFTER INSERT ON vendors
    FOR EACH ROW
    EXECUTE FUNCTION create_vendor_balance();
