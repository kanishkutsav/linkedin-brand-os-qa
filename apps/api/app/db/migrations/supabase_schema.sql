-- Sync copy of the Supabase PostgreSQL schema for the API project.
-- This is intentionally aligned with the SQLAlchemy models in app/models/models.py.

CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY REFERENCES auth_users(id),
    display_name VARCHAR(150) NOT NULL DEFAULT 'User',
    professional_title VARCHAR(200),
    industry VARCHAR(200),
    audience VARCHAR(200),
    goals TEXT,
    brand_positioning TEXT,
    tone VARCHAR(200),
    role VARCHAR(50) DEFAULT 'owner',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_memory (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER REFERENCES user_profiles(id) ON DELETE SET NULL,
    tone VARCHAR(200) NOT NULL DEFAULT 'practical',
    sentence_style VARCHAR(200) NOT NULL DEFAULT 'clear',
    vocabulary TEXT,
    preferred_phrases TEXT,
    avoid_phrases TEXT,
    emoji_usage VARCHAR(100),
    humor_style VARCHAR(100),
    technical_depth VARCHAR(100),
    opinion_style VARCHAR(100),
    storytelling_style VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_items (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES user_profiles(id),
    title VARCHAR(200) NOT NULL,
    topic VARCHAR(300) NOT NULL,
    pillar VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'IDEA',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_versions (
    id SERIAL PRIMARY KEY,
    content_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    version_number INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id SERIAL PRIMARY KEY,
    content_version_id INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL DEFAULT 'PUBLISH_POST',
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    approval_hash VARCHAR(64),
    reason TEXT,
    edited_body TEXT,
    expires_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback_entries (
    id SERIAL PRIMARY KEY,
    content_version_id INTEGER,
    approval_id INTEGER,
    action VARCHAR(50) NOT NULL DEFAULT 'APPROVED',
    reason TEXT,
    payload TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    actor VARCHAR(100) NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_flags (
    id SERIAL PRIMARY KEY,
    emergency_stop BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status
    ON approval_requests(status);

CREATE INDEX IF NOT EXISTS idx_approval_requests_expires_at
    ON approval_requests(expires_at);

CREATE INDEX IF NOT EXISTS idx_content_versions_content_id
    ON content_versions(content_id);

CREATE INDEX IF NOT EXISTS idx_voice_memory_profile_id
    ON voice_memory(profile_id);

CREATE INDEX IF NOT EXISTS idx_feedback_entries_approval_id
    ON feedback_entries(approval_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type
    ON audit_logs(event_type);

INSERT INTO system_flags (emergency_stop)
SELECT FALSE
WHERE NOT EXISTS (SELECT 1 FROM system_flags);


CREATE TABLE IF NOT EXISTS brand_memory (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL UNIQUE REFERENCES user_profiles(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'NOT_INITIALIZED',
    version INTEGER NOT NULL DEFAULT 1,
    summary TEXT,
    identity_json TEXT,
    expertise_json TEXT,
    audience_json TEXT,
    themes_json TEXT,
    opinions_json TEXT,
    experiences_json TEXT,
    formats_json TEXT,
    patterns_json TEXT,
    voice_json TEXT,
    source_post_count INTEGER NOT NULL DEFAULT 0,
    initialized_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS historical_posts (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    external_id VARCHAR(255),
    body TEXT,
    content_hash VARCHAR(64) NOT NULL,
    published_at TIMESTAMPTZ,
    source VARCHAR(50) NOT NULL DEFAULT 'user_import',
    metadata_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_historical_posts_profile_hash
    ON historical_posts(profile_id, content_hash);

CREATE INDEX IF NOT EXISTS idx_historical_posts_profile_published
    ON historical_posts(profile_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_brand_memory_status
    ON brand_memory(status);


CREATE TABLE IF NOT EXISTS research_sources (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    topic VARCHAR(300) NOT NULL,
    title VARCHAR(500),
    url TEXT,
    domain VARCHAR(255),
    published_at TIMESTAMPTZ,
    source_type VARCHAR(50) NOT NULL DEFAULT 'web_search',
    evidence_json TEXT,
    search_queries_json TEXT,
    confidence VARCHAR(30) NOT NULL DEFAULT 'medium',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_sources_profile_topic
    ON research_sources(profile_id, topic);

CREATE INDEX IF NOT EXISTS idx_research_sources_created
    ON research_sources(created_at DESC);

CREATE TABLE IF NOT EXISTS content_opportunities (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    title VARCHAR(300) NOT NULL,
    topic VARCHAR(500) NOT NULL,
    angle TEXT NOT NULL,
    pillar VARCHAR(100) NOT NULL,
    format VARCHAR(100),
    objective VARCHAR(300),
    status VARCHAR(40) NOT NULL DEFAULT 'DISCOVERED',
    brand_fit DOUBLE PRECISION NOT NULL DEFAULT 0,
    audience_relevance DOUBLE PRECISION NOT NULL DEFAULT 0,
    timeliness DOUBLE PRECISION NOT NULL DEFAULT 0,
    evidence_strength DOUBLE PRECISION NOT NULL DEFAULT 0,
    novelty DOUBLE PRECISION NOT NULL DEFAULT 0,
    conversation_potential DOUBLE PRECISION NOT NULL DEFAULT 0,
    authenticity DOUBLE PRECISION NOT NULL DEFAULT 0,
    risk DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    rationale TEXT,
    research_source_ids_json TEXT,
    evidence_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_opportunities_profile_status
    ON content_opportunities(profile_id, status);

CREATE INDEX IF NOT EXISTS idx_content_opportunities_score
    ON content_opportunities(total_score DESC);


CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id),
    mode VARCHAR(50) NOT NULL,
    trigger VARCHAR(150) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'RUNNING',
    created_count INTEGER NOT NULL DEFAULT 0,
    details TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_content_items_profile_id
    ON content_items(profile_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id
    ON agent_runs(user_id);
