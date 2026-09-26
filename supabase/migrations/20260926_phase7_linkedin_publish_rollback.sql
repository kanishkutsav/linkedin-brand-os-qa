-- Phase 7 rollback. Only use this when explicitly reverting Phase 7.
ALTER TABLE approval_requests DROP COLUMN IF EXISTS published_at;
ALTER TABLE approval_requests DROP COLUMN IF EXISTS published_image_urn;
ALTER TABLE approval_requests DROP COLUMN IF EXISTS published_external_id;
ALTER TABLE approval_requests DROP COLUMN IF EXISTS publish_started_at;
DROP TABLE IF EXISTS linkedin_oauth_exchanges;
DROP TABLE IF EXISTS linkedin_oauth_states;
DROP TABLE IF EXISTS linkedin_connections;
