from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


def now():
    return datetime.now(timezone.utc)


class DurableJob(Base):
    """Persistent execution record for Phase 3 background work.

    This table is intentionally generic. Existing application flows continue
    to use their current execution paths until each workload is migrated and
    verified independently.
    """

    __tablename__ = "durable_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="QUEUED")
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fencing token: prevents a stale worker from completing/failing a job after its lease was reclaimed.
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
