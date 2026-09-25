import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.core.config import Settings
from app.jobs.scheduled_jobs import ScheduledJobs
from app.services.agent_scheduler import AgentScheduler


def test_phase2_config_defaults_keep_in_process_scheduler_compatible():
    settings = Settings(_env_file=None)
    assert settings.agent_in_process_schedule_enabled is True
    assert settings.agent_timezone == "Asia/Kolkata"


def test_scheduler_always_starts_for_learning_even_when_daily_schedule_is_disabled():
    source = inspect.getsource(AgentScheduler.start)
    loop = inspect.getsource(AgentScheduler._loop)
    assert "asyncio.create_task(self._loop()" in source
    assert "process_learning" in loop
    assert "agent_in_process_schedule_enabled" in loop


def test_internal_job_key_is_fail_closed():
    source = Path("app/main.py").read_text()
    assert "if not expected or not x_brand_os_job_key" in source
    assert "secrets.compare_digest" in source
    assert 'status_code=401' in source


@pytest.mark.parametrize(
    ("job_name", "expected_path"),
    [
        ("discovery", "/api/internal/scheduled-jobs/discovery"),
        ("calendar", "/api/internal/scheduled-jobs/calendar"),
        ("retention", "/api/internal/scheduled-jobs/retention"),
    ],
)
def test_cron_targets_match_internal_endpoints(job_name, expected_path):
    sql = Path("../../supabase/migrations/20260925_phase2_scheduler.sql").read_text()
    assert expected_path in sql


def test_unknown_scheduled_job_is_rejected():
    jobs = ScheduledJobs(Mock())
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(jobs.run("unknown"))
