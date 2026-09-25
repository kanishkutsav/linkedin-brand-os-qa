-- Keep only the latest published post bodies as raw operational/history data.
-- Older published content remains represented by hashes/metadata and in the
-- learning layer, so duplicate detection and analytics remain durable.

ALTER TABLE historical_posts
    ALTER COLUMN body DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_historical_posts_profile_source_published
    ON historical_posts(profile_id, source, published_at DESC);

-- The scheduler performs the profile-aware 10-post compaction. This migration
-- only makes the schema capable of storing a compacted row.
