from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.durable_job import DurableJob


TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}
CLAIMABLE_STATUSES = {"QUEUED", "RUNNING"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DurableJobService:
    """Small persistence boundary for durable job lifecycle operations.

    The service deliberately does not know how a job is executed. That keeps
    domain workloads isolated from queue mechanics and lets Phase 3 migrate
    one workload at a time without changing user-facing behavior.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        available_at: datetime | None = None,
    ) -> tuple[DurableJob, bool]:
        if not job_type.strip():
            raise ValueError("job_type is required")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        async with self.session_factory() as session:
            existing = await session.execute(
                select(DurableJob).where(
                    DurableJob.idempotency_key == idempotency_key
                )
            )
            job = existing.scalar_one_or_none()
            if job is not None:
                return job, False

            job = DurableJob(
                user_id=user_id,
                job_type=job_type.strip(),
                status="QUEUED",
                idempotency_key=idempotency_key,
                payload_json=json.dumps(payload or {}, separators=(",", ":"), sort_keys=True),
                max_attempts=max_attempts,
                available_at=available_at or utcnow(),
            )
            session.add(job)
            try:
                await session.commit()
            except IntegrityError:
                # Another worker may have won the same idempotency key between
                # the read above and this insert. Treat the unique constraint
                # as the durable winner instead of surfacing a duplicate error.
                await session.rollback()
                existing = await session.execute(
                    select(DurableJob).where(
                        DurableJob.idempotency_key == idempotency_key
                    )
                )
                job = existing.scalar_one_or_none()
                if job is None:
                    raise
                return job, False
            await session.refresh(job)
            return job, True

    async def claim_next(
        self,
        *,
        job_type: str | None = None,
        job_types: list[str] | None = None,
        lease_seconds: int = 600,
    ) -> DurableJob | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

        now = utcnow()
        lease_cutoff = now - timedelta(seconds=lease_seconds)

        async with self.session_factory() as session:
            # A crashed worker leaves RUNNING behind. Once its lease expires,
            # make it claimable again, but only while retry budget remains.
            stale = await session.execute(
                select(DurableJob).where(
                    DurableJob.status == "RUNNING",
                    DurableJob.locked_at.is_not(None),
                    DurableJob.locked_at < lease_cutoff,
                )
            )
            for job in stale.scalars().all():
                job.locked_at = None
                if job.attempts >= job.max_attempts:
                    job.status = "FAILED"
                    job.finished_at = now
                    job.last_error = job.last_error or "Worker lease expired after the retry budget was exhausted."
                else:
                    job.status = "QUEUED"
                    job.available_at = now

            await session.flush()

            query = (
                select(DurableJob)
                .where(
                    DurableJob.status == "QUEUED",
                    DurableJob.available_at <= now,
                    DurableJob.attempts < DurableJob.max_attempts,
                )
                .order_by(DurableJob.available_at.asc(), DurableJob.id.asc())
                .limit(1)
            )
            if job_type and job_types:
                raise ValueError("Pass either job_type or job_types, not both")
            if job_type:
                query = query.where(DurableJob.job_type == job_type)
            elif job_types:
                query = query.where(DurableJob.job_type.in_(job_types))

            # PostgreSQL workers skip rows claimed by another worker. SQLite
            # ignores FOR UPDATE, but remains useful for deterministic QA.
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)

            result = await session.execute(query)
            job = result.scalar_one_or_none()
            if job is None:
                await session.commit()
                return None

            job.status = "RUNNING"
            job.attempts += 1
            job.locked_at = now
            job.updated_at = now
            await session.commit()
            await session.refresh(job)
            return job

    async def complete(
        self,
        job_id: int,
        *,
        result: dict[str, Any] | None = None,
    ) -> DurableJob:
        async with self.session_factory() as session:
            job = await session.get(DurableJob, job_id)
            if job is None:
                raise ValueError(f"Unknown durable job: {job_id}")
            if job.status != "RUNNING":
                raise ValueError(f"Job {job_id} is not RUNNING")

            now = utcnow()
            job.status = "SUCCEEDED"
            job.result_json = json.dumps(result or {}, separators=(",", ":"), sort_keys=True)
            job.last_error = None
            job.locked_at = None
            job.finished_at = now
            job.updated_at = now
            await session.commit()
            await session.refresh(job)
            return job

    async def fail(
        self,
        job_id: int,
        *,
        error: str,
        retry_delay_seconds: int = 60,
        retryable: bool = True,
    ) -> DurableJob:
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")

        async with self.session_factory() as session:
            job = await session.get(DurableJob, job_id)
            if job is None:
                raise ValueError(f"Unknown durable job: {job_id}")
            if job.status != "RUNNING":
                raise ValueError(f"Job {job_id} is not RUNNING")

            now = utcnow()
            job.last_error = (error or "Unknown job failure")[:10000]
            job.locked_at = None
            job.updated_at = now

            if retryable and job.attempts < job.max_attempts:
                job.status = "QUEUED"
                job.available_at = now + timedelta(seconds=retry_delay_seconds)
            else:
                job.status = "FAILED"
                job.finished_at = now

            await session.commit()
            await session.refresh(job)
            return job
