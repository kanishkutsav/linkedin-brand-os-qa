-- E2E hardening: publication idempotency and per-profile dedupe constraints.

ALTER TABLE public.approval_requests
  ADD COLUMN IF NOT EXISTS publish_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS published_external_id VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_memory_profile_id
  ON public.voice_memory(profile_id)
  WHERE profile_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_historical_posts_profile_content_hash
  ON public.historical_posts(profile_id, content_hash);

CREATE INDEX IF NOT EXISTS idx_linkedin_oauth_exchanges_user_id
  ON public.linkedin_oauth_exchanges(user_id);
