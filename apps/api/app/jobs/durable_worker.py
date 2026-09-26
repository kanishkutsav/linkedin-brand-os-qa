from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.models import DurableJob

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, DurableJob, dict], Awaitable[dict | None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DurableJobWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, Handler],
        *,
        allowed_job_types: set[str],
        poll_interval_seconds: int = 5,
        lease_seconds: int = 300,
        max_attempts: int = 5,
        worker_id: str | None = None,
    ):
        self.session_factory = session_factory
        self.handlers = handlers
        self.allowed_job_types = allowed_job_types
        self.poll_interval_seconds = max(1, poll_interval_seconds)
        self.lease_seconds = max(30, lease_seconds)
        self.max_attempts = max(1, max_attempts)
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"

    async def claim_one(self) -> DurableJob | None:
        async with self.session_factory() as session:
            now = _utcnow()
            stale_before = now - timedelta(seconds=self.lease_seconds)
            result = await session.execute(
                select(DurableJob)
                .where(
                    DurableJob.job_type.in_(self.allowed_job_types),
                    or_(
                        (DurableJob.status == "QUEUED") & (DurableJob.available_at <= now),
                        (DurableJob.status == "RUNNING") & (DurableJob.locked_at < stale_before),
                    ),
                )
                .order_by(DurableJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "RUNNING"
            job.attempts = int(job.attempts or 0) + 1
            job.locked_at = now
            job.locked_by = self.worker_id
            await session.commit()
            return job

    async def process_one(self) -> bool:
        job = await self.claim_one()
        if job is None:
            return False

        handler = self.handlers.get(job.job_type)
        if handler is None or job.job_type not in self.allowed_job_types:
            await self._fail(job.id, f"No handler enabled for job type {job.job_type}", retryable=False)
            return True

        try:
            payload = json.loads(job.payload_json or "{}")
            async with self.session_factory() as session:
                result = await handler(session, job, payload)
                await session.commit()
            await self._complete(job.id, result)
        except Exception as exc:
            logger.exception("Durable job %s failed", job.id)
            await self._fail(job.id, str(exc)[:2000], retryable=True)
        return True

    async def _complete(self, job_id: int, result: dict | None) -> None:
        async with self.session_factory() as session:
            job = await session.get(DurableJob, job_id)
            if job is None:
                return
            job.status = "SUCCEEDED"
            job.result_json = json.dumps(result or {}, ensure_ascii=False)
            job.completed_at = _utcnow()
            job.locked_at = None
            job.locked_by = None
            await session.commit()

    async def _fail(self, job_id: int, error: str, *, retryable: bool) -> None:
        async with self.session_factory() as session:
            job = await session.get(DurableJob, job_id)
            if job is None:
                return
            if retryable and int(job.attempts or 0) < self.max_attempts:
                delay = min(300, 2 ** max(0, int(job.attempts or 1) - 1) * 5)
                job.status = "QUEUED"
                job.available_at = _utcnow() + timedelta(seconds=delay)
            else:
                job.status = "FAILED"
                job.completed_at = _utcnow()
            job.last_error = error[:2000]
            job.locked_at = None
            job.locked_by = None
            await session.commit()

    async def run_forever(self) -> None:
        while True:
            try:
                processed = await self.process_one()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Durable worker polling cycle failed")
                await asyncio.sleep(self.poll_interval_seconds)
