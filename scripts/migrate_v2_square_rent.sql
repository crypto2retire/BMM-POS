-- Migration v2: Square payments + rent flagging
-- Run this once on production to add the new tables and columns.

-- 1. reservations table (for Square-paid shop reservations)
CREATE TABLE IF NOT EXISTS reservations (
  id                SERIAL PRIMARY KEY,
  item_id           INTEGER REFERENCES items(id),
  customer_name     VARCHAR(200),
  customer_phone    VARCHAR(50),
  square_payment_id VARCHAR(200),
  amount_paid       NUMERIC(10,2),
  status            VARCHAR(20) NOT NULL DEFAULT 'pending',
  created_at        TIMESTAMP DEFAULT NOW()
);

-- 2. rent_flagged column on vendors (30+ days overdue flag)
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS rent_flagged BOOLEAN NOT NULL DEFAULT false;

-- Verify
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name IN ('reservations','vendors') AND column_name IN ('rent_flagged','id','status')
ORDER BY table_name, column_name;
