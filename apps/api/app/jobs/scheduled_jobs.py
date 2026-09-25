from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.orchestrator import AgentOrchestrator
from app.models.models import AgentRun, BrandMemory, UserProfile
from app.services.brand_learning import BrandLearningService
from app.services.retention import RetentionService


class ScheduledJobs:
    """Business operations invoked by a scheduler.

    No timing or task-lifecycle concerns belong here. Keeping these operations
    behind a small job boundary lets the same work be called by the current
    in-process scheduler and, later, by durable scheduled execution.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def run(self, mode: str) -> dict:
        if mode not in {"discovery", "calendar"}:
            raise ValueError(f"Unsupported scheduled job: {mode}")

        tz = ZoneInfo("Asia/Kolkata")
        today = datetime.now(tz).date()
        day_start = datetime.combine(today, time.min, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        summary = {"mode": mode, "profiles": 0, "skipped": 0, "succeeded": 0, "failed": 0}

        async with self.session_factory() as session:
            # pg_cron retries are safe even if an earlier invocation is still running.
            # The transaction-scoped advisory lock serializes each scheduled mode.
            bind = session.bind
            if bind is not None and bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                    {"lock_key": f"brand-os-scheduled:{mode}"},
                )

            result = await session.execute(
                select(UserProfile.id)
                .join(BrandMemory, BrandMemory.profile_id == UserProfile.id)
                .where(BrandMemory.status == "READY")
            )
            profile_ids = [int(row[0]) for row in result.all()]

            for profile_id in profile_ids:
                summary["profiles"] += 1
                existing = await session.execute(
                    select(AgentRun).where(
                        AgentRun.user_id == profile_id,
                        AgentRun.mode == mode,
                        AgentRun.trigger == f"scheduled:{mode}",
                        AgentRun.started_at >= day_start,
                        AgentRun.started_at < day_end,
                        AgentRun.status.in_(["RUNNING", "SUCCEEDED"]),
                    ).order_by(AgentRun.started_at.desc()).limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    summary["skipped"] += 1
                    continue

                run = AgentRun(
                    user_id=profile_id,
                    mode=mode,
                    trigger=f"scheduled:{mode}",
                    status="RUNNING",
                )
                session.add(run)
                await session.flush()
                try:
                    orchestrator = AgentOrchestrator(session, profile_id)
                    if mode == "calendar":
                        run_result = await orchestrator.run_calendar()
                    else:
                        run_result = await orchestrator.run_discovery()
                    run.status = "SUCCEEDED"
                    run.created_count = run_result["created_count"]
                    run.details = str(run_result)
                    summary["succeeded"] += 1
                except Exception as exc:
                    run.status = "FAILED"
                    run.details = str(exc)
                    summary["failed"] += 1
                finally:
                    run.finished_at = datetime.now(ZoneInfo("UTC"))
                    await session.commit()

        return summary

    async def process_learning(self, session: AsyncSession, *, limit: int = 10) -> None:
        await BrandLearningService(session).process_pending(limit=limit)

    async def process_retention(self, session: AsyncSession):
        return await RetentionService().compact(session)
