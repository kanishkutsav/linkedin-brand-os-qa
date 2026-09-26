from __future__ import annotations

import asyncio

from app.core.config import settings
from app.db.database import SessionLocal
from app.jobs.durable_handlers import build_durable_job_handlers
from app.jobs.durable_worker import DurableJobWorker


def allowed_job_types() -> set[str]:
    allowed: set[str] = set()
    if settings.durable_learning_worker_enabled:
        allowed.add("brand_learning_event")
    if settings.durable_ai_worker_enabled:
        allowed.update({
            "research_discovery",
            "content_improvement",
            "manual_content_generation",
            "approval_regeneration",
        })
    if settings.durable_scheduled_worker_enabled:
        allowed.update({
            "scheduled_discovery",
            "scheduled_calendar",
            "scheduled_retention",
        })
    return allowed


async def main() -> None:
    if not any((
        settings.durable_learning_worker_enabled,
        settings.durable_ai_worker_enabled,
        settings.durable_scheduled_worker_enabled,
    )):
        raise RuntimeError(
            "No durable worker is enabled. Set an explicit durable_*_worker_enabled flag before starting the worker."
        )

    worker = DurableJobWorker(
        SessionLocal,
        build_durable_job_handlers(),
        allowed_job_types=allowed_job_types(),
        poll_interval_seconds=settings.durable_worker_poll_seconds,
        lease_seconds=settings.durable_worker_lease_seconds,
        max_attempts=settings.durable_worker_max_attempts,
    )
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
