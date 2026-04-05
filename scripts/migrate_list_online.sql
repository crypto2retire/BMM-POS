-- Migration: rename list_online → is_online
-- Run this once on the production database when upgrading from
-- the old schema (which used list_online) to the current schema
-- (which uses is_online).
--
-- Scenario A: only list_online exists (clean rename)
--   ALTER TABLE items RENAME COLUMN list_online TO is_online;
--
-- Scenario B: both columns exist (list_online has data, is_online is all-false)
--   UPDATE items SET is_online = list_online;
--   ALTER TABLE items DROP COLUMN list_online;
--
-- Run the query below first to see which scenario you are in:

SELECT
    COUNT(*) FILTER (WHERE column_name = 'list_online') AS has_list_online,
    COUNT(*) FILTER (WHERE column_name = 'is_online')   AS has_is_online
FROM information_schema.columns
WHERE table_name = 'items';

-- Then run the appropriate block:

-- ── SCENARIO A: only list_online exists ─────────────────────────
-- ALTER TABLE items RENAME COLUMN list_online TO is_online;

-- ── SCENARIO B: both columns exist ──────────────────────────────
-- UPDATE items SET is_online = list_online;
-- ALTER TABLE items DROP COLUMN list_online;

-- Verify after running:
SELECT COUNT(*) FROM items WHERE is_online = true AND status = 'active';
