CREATE TABLE IF NOT EXISTS durable_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(80) NOT NULL,
    profile_id BIGINT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ NULL,
    locked_by VARCHAR(255) NULL,
    last_error TEXT NULL,
    result_json TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_durable_jobs_claim
    ON durable_jobs(status, available_at, created_at);

CREATE INDEX IF NOT EXISTS idx_durable_jobs_profile
    ON durable_jobs(profile_id, created_at);
