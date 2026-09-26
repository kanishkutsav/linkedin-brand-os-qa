from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Boolean, Integer, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .base import Base


def now(): return datetime.now(timezone.utc)


class AuthUser(Base):
    __tablename__ = "auth_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(150), default="User")
    professional_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class VoiceMemory(Base):
    __tablename__ = "voice_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), unique=True, index=True, nullable=True)
    tone: Mapped[str] = mapped_column(String(200), default="practical")
    sentence_style: Mapped[str] = mapped_column(String(200), default="clear")
    vocabulary: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_phrases: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_phrases: Mapped[str | None] = mapped_column(Text, nullable=True)
    emoji_usage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    humor_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    technical_depth: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opinion_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storytelling_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ContentItem(Base):
    __tablename__ = "content_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(300))
    pillar: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="IDEA")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ContentVersion(Base):
    __tablename__ = "content_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_version_id: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(50), default="PUBLISH_POST")
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_image_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50), default="APPROVED")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(100))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(50), index=True)
    trigger: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrandMemory(Base):
    __tablename__ = "brand_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="NOT_INITIALIZED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    expertise_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    themes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    opinions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    experiences_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    formats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    patterns_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_post_count: Mapped[int] = mapped_column(Integer, default=0)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class HistoricalPost(Base):
    __tablename__ = "historical_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="user_import")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LinkedInConnection(Base):
    __tablename__ = "linkedin_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), unique=True, index=True, nullable=False)
    member_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linkedin_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class LinkedInOAuthState(Base):
    __tablename__ = "linkedin_oauth_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LinkedInOAuthExchange(Base):
    __tablename__ = "linkedin_oauth_exchanges"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id"), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SystemFlag(Base):
    __tablename__ = "system_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)


class ResearchSource(Base):
    __tablename__ = "research_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), default="web_search")
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_queries_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(30), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ContentOpportunity(Base):
    __tablename__ = "content_opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str] = mapped_column(String(500))
    angle: Mapped[str] = mapped_column(Text)
    pillar: Mapped[str] = mapped_column(String(100))
    format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    objective: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="DISCOVERED")
    brand_fit: Mapped[float] = mapped_column(Float, default=0)
    audience_relevance: Mapped[float] = mapped_column(Float, default=0)
    timeliness: Mapped[float] = mapped_column(Float, default=0)
    evidence_strength: Mapped[float] = mapped_column(Float, default=0)
    novelty: Mapped[float] = mapped_column(Float, default=0)
    conversation_potential: Mapped[float] = mapped_column(Float, default=0)
    authenticity: Mapped[float] = mapped_column(Float, default=0)
    risk: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_source_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    source_type: Mapped[str] = mapped_column(String(60))
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LearningMemory(Base):
    __tablename__ = "learning_memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    memory_key: Mapped[str] = mapped_column(String(180))
    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20), default="medium")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class DurableJob(Base):
    __tablename__ = "durable_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
