from __future__ import annotations

from typing import Any

from app.db.database import SessionLocal
from app.jobs.scheduled_jobs import ScheduledJobs


async def run_scheduled_workload(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "").strip()
    if mode not in {"discovery", "calendar"}:
        raise ValueError("Scheduled durable workload mode must be discovery or calendar.")
    return await ScheduledJobs(SessionLocal).run(mode)


async def run_retention_workload(_payload: dict[str, Any]) -> dict[str, Any]:
    async with SessionLocal() as session:
        result = await ScheduledJobs(SessionLocal).process_retention(session)
        await session.commit()
        return result


def build_scheduled_workload_handlers() -> dict[str, Any]:
    return {
        "scheduled_discovery": run_scheduled_workload,
        "scheduled_calendar": run_scheduled_workload,
        "scheduled_retention": run_retention_workload,
    }
