CREATE TABLE IF NOT EXISTS poynt_payments (
    id SERIAL PRIMARY KEY,
    reference_id VARCHAR(100) UNIQUE,
    amount_cents INTEGER,
    status VARCHAR(20) DEFAULT 'pending',
    poynt_transaction_id VARCHAR(200),
    sale_id INTEGER REFERENCES sales(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_poynt_payments_reference_id ON poynt_payments(reference_id);
CREATE INDEX IF NOT EXISTS idx_poynt_payments_status ON poynt_payments(status);
