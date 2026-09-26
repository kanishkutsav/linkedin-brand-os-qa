from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator
from app.jobs.durable_queue import enqueue_job
from app.jobs.scheduled_jobs import ScheduledJobs
from app.models.models import DurableJob
from app.services.approval import ApprovalService
from app.services.brand_learning import BrandLearningService


async def _learning(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    processed = await BrandLearningService(session).process_pending(limit=10)
    return {"processed_events": processed}


async def _research_discovery(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    result = await AgentOrchestrator(session, int(job.profile_id)).run_discovery(
        trigger=payload.get("trigger", "durable_research_discovery")
    )
    return result


async def _content_improvement(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    result = await AgentOrchestrator(session, int(job.profile_id)).run_event(
        "content_improvement", payload
    )
    return result


async def _manual_content(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    return await AgentOrchestrator(session, int(job.profile_id)).run_manual_content_generation(
        trigger=payload.get("trigger", "durable_manual_content_generation")
    )


async def _approval_regeneration(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    approval = await ApprovalService(session).regenerate(
        int(payload["approval_id"]),
        feedback=payload.get("feedback"),
        profile_id=int(job.profile_id),
    )
    return {"approval_id": approval.id, "status": approval.status}


async def _scheduled(session: AsyncSession, job: DurableJob, payload: dict) -> dict:
    mode = payload.get("mode")
    if mode in {"discovery", "calendar"}:
        return await ScheduledJobs(session.bind).run(mode)
    if mode == "retention":
        return await ScheduledJobs(session.bind).process_retention(session)
    raise ValueError(f"Unsupported durable scheduled mode: {mode}")


def build_durable_job_handlers() -> dict[str, Any]:
    return {
        "brand_learning_event": _learning,
        "research_discovery": _research_discovery,
        "content_improvement": _content_improvement,
        "manual_content_generation": _manual_content,
        "approval_regeneration": _approval_regeneration,
        "scheduled_discovery": _scheduled,
        "scheduled_calendar": _scheduled,
        "scheduled_retention": _scheduled,
    }
