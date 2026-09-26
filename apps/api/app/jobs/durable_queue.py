from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import DurableJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_idempotency_key(job_type: str, profile_id: int | None, payload: dict) -> str:
    raw = json.dumps(
        {"job_type": job_type, "profile_id": profile_id, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: str,
    payload: dict | None = None,
    profile_id: int | None = None,
    idempotency_key: str | None = None,
    available_at: datetime | None = None,
) -> DurableJob | None:
    payload = payload or {}
    key = idempotency_key or make_idempotency_key(job_type, profile_id, payload)
    existing = await session.execute(
        select(DurableJob).where(DurableJob.idempotency_key == key).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return None

    job = DurableJob(
        job_type=job_type,
        profile_id=profile_id,
        payload_json=json.dumps(payload, ensure_ascii=False),
        idempotency_key=key,
        status="QUEUED",
        available_at=available_at or _utcnow(),
    )
    session.add(job)
    await session.flush()
    return job


async def enqueue_learning_event(
    session: AsyncSession,
    *,
    event_id: int,
    profile_id: int,
) -> DurableJob | None:
    return await enqueue_job(
        session,
        job_type="brand_learning_event",
        profile_id=profile_id,
        payload={"event_id": event_id},
        idempotency_key=f"learning-event:{event_id}",
    )
