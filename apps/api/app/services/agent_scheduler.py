from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.jobs.scheduled_jobs import ScheduledJobs


class AgentScheduler:
    """Timing/runtime adapter for scheduled background jobs.

    This class owns only the in-process timing loop. The actual scheduled work
    lives in ScheduledJobs so it can later be invoked by Supabase Cron, a
    worker, or another durable job runner without changing business behavior.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.jobs = ScheduledJobs(session_factory)
        self._task: asyncio.Task | None = None
        self._last_discovery_date: str | None = None
        self._last_calendar_date: str | None = None
        self._last_retention_date: str | None = None

    def start(self) -> None:
        if settings.agent_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="agent-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        tz = ZoneInfo(settings.agent_timezone)
        while True:
            now = datetime.now(tz)
            if settings.agent_in_process_schedule_enabled and settings.agent_daily_discovery_enabled:
                if (
                    now.hour == settings.agent_daily_discovery_hour
                    and now.minute == settings.agent_daily_discovery_minute
                    and self._last_discovery_date != now.date().isoformat()
                ):
                    await self.jobs.run("discovery")
                    self._last_discovery_date = now.date().isoformat()

            if settings.agent_in_process_schedule_enabled and settings.agent_calendar_enabled:
                if (
                    now.hour == settings.agent_calendar_hour
                    and now.minute == settings.agent_calendar_minute
                    and self._last_calendar_date != now.date().isoformat()
                ):
                    await self.jobs.run("calendar")
                    self._last_calendar_date = now.date().isoformat()

            async with self.session_factory() as learning_session:
                try:
                    await self.jobs.process_learning(learning_session, limit=10)
                except Exception as exc:
                    print(f"Brand learning cycle skipped: {exc}")

                if settings.agent_in_process_schedule_enabled and self._last_retention_date != now.date().isoformat():
                    try:
                        retention = await self.jobs.process_retention(learning_session)
                        print(f"Brand OS retention cycle completed: {retention}")
                        self._last_retention_date = now.date().isoformat()
                    except Exception as exc:
                        await learning_session.rollback()
                        print(f"Brand OS retention cycle skipped: {exc}")

            await asyncio.sleep(30)
