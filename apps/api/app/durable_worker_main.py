from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings
from app.db.database import SessionLocal, engine
from app.jobs.durable_handlers import build_durable_job_handlers
from app.jobs.durable_worker import DurableJobWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    learning_types = {"brand_learning_event"} if settings.durable_learning_worker_enabled else set()
    ai_types = {
        "research_discovery",
        "content_improvement",
        "manual_content_generation",
        "approval_regeneration",
    } if settings.durable_ai_worker_enabled else set()
    scheduled_types = {
        "scheduled_discovery",
        "scheduled_calendar",
        "scheduled_retention",
    } if settings.durable_scheduled_worker_enabled else set()
    allowed = learning_types | ai_types | scheduled_types

    if not allowed:
        logger.info("No durable worker workloads are enabled. Exiting.")
        await engine.dispose()
        return

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    worker = DurableJobWorker(
        SessionLocal,
        build_durable_job_handlers(),
        allowed_job_types=allowed,
        poll_interval_seconds=settings.durable_worker_poll_seconds,
        lease_seconds=settings.durable_worker_lease_seconds,
    )
    logger.info("Durable worker started for job types: %s", sorted(allowed))
    try:
        await worker.run_forever(stop_event)
    finally:
        await engine.dispose()
        logger.info("Durable worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
