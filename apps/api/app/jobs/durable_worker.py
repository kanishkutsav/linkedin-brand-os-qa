from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.durable_jobs import DurableJobService

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class DurableJobWorker:
    """Polling worker for Phase 3 durable workloads.

    The worker is a separate execution process. FastAPI never starts it, so
    web-request lifecycle and long-running AI work remain isolated.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, JobHandler],
        *,
        allowed_job_types: set[str] | None = None,
        poll_interval_seconds: int = 5,
        lease_seconds: int = 600,
    ):
        if poll_interval_seconds < 1:
            raise ValueError("poll_interval_seconds must be at least 1")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.jobs = DurableJobService(session_factory)
        self.handlers = handlers
        self.allowed_job_types = allowed_job_types
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds

    async def run_once(self) -> bool:
        job = await self.jobs.claim_next(
            job_types=sorted(self.allowed_job_types) if self.allowed_job_types else None,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return False

        handler = self.handlers.get(job.job_type)
        if handler is None:
            await self.jobs.fail(
                job.id,
                lease_token=job.lease_token or "",
                error=f"No handler registered for job type: {job.job_type}",
                retry_delay_seconds=0,
                retryable=False,
            )
            return True

        try:
            payload = json.loads(job.payload_json or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Durable job payload must be a JSON object")
            payload["_durable_job_id"] = job.id
            result = await handler(payload)
            await self.jobs.complete(job.id, lease_token=job.lease_token or "", result=result or {})
            logger.info("Durable job %s (%s) completed", job.id, job.job_type)
        except Exception as exc:
            delay = min(3600, 2 ** max(job.attempts - 1, 0) * 60)
            await self.jobs.fail(
                job.id,
                lease_token=job.lease_token or "",
                error=f"{type(exc).__name__}: {exc}",
                retry_delay_seconds=delay,
            )
            logger.exception(
                "Durable job %s (%s) failed; retry delay=%ss",
                job.id,
                job.job_type,
                delay,
            )
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.poll_interval_seconds)
