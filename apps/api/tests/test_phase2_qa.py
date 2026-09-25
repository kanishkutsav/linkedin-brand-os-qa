import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.jobs.scheduled_jobs import ScheduledJobs
from app.services.agent_scheduler import AgentScheduler
from app.main import app


def test_phase2_config_defaults_keep_in_process_scheduler_compatible():
    settings = Settings(_env_file=None)
    assert settings.agent_in_process_schedule_enabled is True
    assert settings.agent_timezone == "Asia/Kolkata"


def test_scheduler_stays_alive_for_learning_when_daily_schedule_is_disabled():
    source = inspect.getsource(AgentScheduler._loop)
    assert "process_learning" in source
    assert "agent_in_process_schedule_enabled" in source
    assert "process_retention" in source


@pytest.mark.asyncio
async def test_scheduler_skips_daily_work_but_continues_learning_when_external_schedule_owns_daily_jobs():
    scheduler = AgentScheduler(Mock())
    scheduler.jobs.process_learning = AsyncMock()
    scheduler.jobs.run = AsyncMock()
    scheduler.jobs.process_retention = AsyncMock()

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=Mock())
    session.__aexit__ = AsyncMock(return_value=None)
    scheduler.session_factory = MagicMock(return_value=session)

    with patch("app.services.agent_scheduler.settings.agent_in_process_schedule_enabled", False),          patch("app.services.agent_scheduler.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await scheduler._loop()

    scheduler.jobs.process_learning.assert_awaited_once()
    scheduler.jobs.run.assert_not_awaited()
    scheduler.jobs.process_retention.assert_not_awaited()


def test_internal_job_key_is_fail_closed():
    source = Path("app/main.py").read_text()
    assert "if not expected or not x_brand_os_job_key" in source
    assert "secrets.compare_digest" in source
    assert "status_code=401" in source


def test_internal_scheduler_endpoint_dispatches_long_running_jobs_in_background():
    source = Path("app/main.py").read_text()
    assert "background_tasks: BackgroundTasks" in source
    assert "background_tasks.add_task(_run_scheduled_job_background, job_name)" in source
    assert '"accepted": True' in source


def test_internal_scheduler_endpoint_rejects_missing_and_wrong_keys():
    client = TestClient(app)
    assert client.post("/api/internal/scheduled-jobs/discovery").status_code == 401
    assert client.post(
        "/api/internal/scheduled-jobs/discovery",
        headers={"X-Brand-OS-Job-Key": "wrong-key"},
    ).status_code == 401


def test_internal_scheduler_endpoint_rejects_unknown_jobs():
    client = TestClient(app)
    response = client.post(
        "/api/internal/scheduled-jobs/not-a-real-job",
        headers={"X-Brand-OS-Job-Key": "qa-test-key"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("job_name", "expected_path"),
    [
        ("discovery", "/api/internal/scheduled-jobs/discovery"),
        ("calendar", "/api/internal/scheduled-jobs/calendar"),
        ("retention", "/api/internal/scheduled-jobs/retention"),
    ],
)
def test_cron_targets_match_internal_endpoints(job_name, expected_path):
    repo_root = Path(__file__).resolve().parents[3]
    sql = (repo_root / "supabase/migrations/20260925_phase2_scheduler.sql").read_text()
    assert expected_path in sql


def test_cron_schedules_are_09_00_09_15_and_10_00_ist_in_utc():
    sql = Path("../../supabase/migrations/20260925_phase2_scheduler.sql")
    if not sql.exists():
        sql = Path(__file__).resolve().parents[3] / "supabase/migrations/20260925_phase2_scheduler.sql"
    text = sql.read_text()
    assert "'30 3 * * *'" in text
    assert "'45 3 * * *'" in text
    assert "'0 4 * * *'" in text


def test_cron_uses_vault_secrets_and_shared_header():
    repo_root = Path(__file__).resolve().parents[3]
    sql = (repo_root / "supabase/migrations/20260925_phase2_scheduler.sql").read_text()
    assert "brand_os_render_url" in sql
    assert "brand_os_job_key" in sql
    assert "X-Brand-OS-Job-Key" in sql
    assert "vault.decrypted_secrets" in sql


def test_scheduled_jobs_have_postgres_advisory_lock_and_daily_idempotency_guard():
    source = Path("app/jobs/scheduled_jobs.py").read_text()
    assert "pg_advisory_xact_lock" in source
    assert 'AgentRun.status.in_(["RUNNING", "SUCCEEDED"])' in source
    assert "AgentRun.started_at >= day_start" in source
    assert "AgentRun.started_at < day_end" in source
    assert 'trigger=f"scheduled:{mode}"' in source


def test_dashboard_counts_are_not_derived_from_retention_window():
    approval = Path("app/services/approval.py").read_text()
    retention = Path("app/services/retention.py").read_text()
    assert "def dashboard_counts" in approval
    assert "func.count(ApprovalRequest.id)" in approval
    assert "published_post_retention_limit" not in approval[approval.index("def dashboard_counts"):approval.index("def dashboard_counts")+5000]
    assert "published_post_retention_limit" in retention


def test_rollback_contains_all_three_cron_jobs():
    repo_root = Path(__file__).resolve().parents[3]
    rollback = (repo_root / "supabase/migrations/20260925_phase2_scheduler_rollback.sql").read_text()
    assert "brand-os-daily-discovery" in rollback
    assert "brand-os-calendar-generation" in rollback
    assert "brand-os-daily-retention" in rollback


def test_unknown_scheduled_job_is_rejected():
    jobs = ScheduledJobs(Mock())
    with pytest.raises(ValueError):
        asyncio.run(jobs.run("unknown"))


@pytest.mark.parametrize("job_name", ["discovery", "calendar"])
def test_valid_daily_job_delegates_to_scheduled_jobs(job_name):
    client = TestClient(app)
    mocked = Mock()
    mocked.run = AsyncMock(return_value={"mode": job_name, "profiles": 0, "skipped": 0, "succeeded": 0, "failed": 0})
    with patch("app.main.ScheduledJobs", return_value=mocked):
        response = client.post(
            f"/api/internal/scheduled-jobs/{job_name}",
            headers={"X-Brand-OS-Job-Key": "qa-test-key"},
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mocked.run.assert_awaited_once_with(job_name)
