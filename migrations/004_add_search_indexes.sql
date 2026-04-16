-- Add pg_trgm extension for fast LIKE/ILIKE search on item names
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Create trigram index on item.name for fast substring search
CREATE INDEX IF NOT EXISTS ix_items_name_trgm ON items USING gin (name gin_trgm_ops);

-- Create trigram index on item.sku for fast substring search  
CREATE INDEX IF NOT EXISTS ix_items_sku_trgm ON items USING gin (sku gin_trgm_ops);

-- Create index on items.status for filtered counts
CREATE INDEX IF NOT EXISTS ix_items_status ON items (status);

-- Create composite index on items (vendor_id, status) for vendor-filtered listing
CREATE INDEX IF NOT EXISTS ix_items_vendor_status ON items (vendor_id, status);
