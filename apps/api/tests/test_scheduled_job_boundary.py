import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.jobs.scheduled_jobs import ScheduledJobs
from app.services.agent_scheduler import AgentScheduler


class TestScheduledJobBoundary(unittest.IsolatedAsyncioTestCase):
    def test_scheduler_delegates_to_job_boundary(self):
        scheduler = AgentScheduler(Mock())
        self.assertIsInstance(scheduler.jobs, ScheduledJobs)
        self.assertIsNone(scheduler._task)

    async def test_learning_and_retention_are_delegated(self):
        jobs = ScheduledJobs(Mock())
        session = Mock()

        with patch("app.jobs.scheduled_jobs.BrandLearningService") as learning_cls:
            learning_cls.return_value.process_pending = AsyncMock()
            await jobs.process_learning(session, limit=7)
            learning_cls.return_value.process_pending.assert_awaited_once_with(limit=7)

        with patch("app.jobs.scheduled_jobs.RetentionService") as retention_cls:
            retention_cls.return_value.compact = AsyncMock(return_value={"trimmed": 0})
            result = await jobs.process_retention(session)
            self.assertEqual(result, {"trimmed": 0})
            retention_cls.return_value.compact.assert_awaited_once_with(session)

    async def test_rejects_unknown_scheduled_job(self):
        jobs = ScheduledJobs(Mock())
        with self.assertRaises(ValueError):
            await jobs.run("unknown")


if __name__ == "__main__":
    unittest.main()
