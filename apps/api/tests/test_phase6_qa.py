from pathlib import Path

from app.core.config import settings
from app.jobs.ai_workload_worker import build_ai_workload_handlers
from app.jobs.durable_handlers import build_durable_job_handlers


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"


def test_phase6_ai_workloads_are_explicitly_opt_in():
    assert settings.durable_ai_workloads_enabled is False
    assert settings.durable_ai_worker_enabled is False


def test_phase6_ai_handler_contract_is_complete():
    assert set(build_ai_workload_handlers()) == {
        "research_discovery",
        "content_improvement",
        "manual_content_generation",
        "approval_regeneration",
    }
    assert {
        "research_discovery",
        "content_improvement",
        "manual_content_generation",
        "approval_regeneration",
    }.issubset(build_durable_job_handlers())


def test_phase6_routes_require_idempotency_when_queued():
    main = (API_ROOT / "app" / "main.py").read_text()
    required_messages = [
        "X-Idempotency-Key is required for queued research.",
        "X-Idempotency-Key is required for queued content improvement.",
        "X-Idempotency-Key is required for queued content generation.",
        "X-Idempotency-Key is required for queued regeneration.",
    ]
    for message in required_messages:
        assert message in main


def test_phase6_worker_uses_lease_fencing():
    worker = (API_ROOT / "app" / "jobs" / "durable_worker.py").read_text()
    service = (API_ROOT / "app" / "services" / "durable_jobs.py").read_text()
    model = (API_ROOT / "app" / "models" / "durable_job.py").read_text()

    assert "job.lease_token" in worker
    assert "lease_token: str" in service
    assert "lease_token" in model


def test_phase6_migration_is_additive_and_rollback_is_scoped():
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "20260926_phase6_durable_job_fencing.sql"
    ).read_text()
    rollback = (
        ROOT
        / "supabase"
        / "migrations"
        / "20260926_phase6_durable_job_fencing_rollback.sql"
    ).read_text()

    assert "alter table public.durable_jobs" in migration
    assert "add column if not exists lease_token" in migration
    assert "drop index if exists public.durable_jobs_lease_token_idx" in rollback
    assert "drop column if exists lease_token" in rollback
    assert "drop table" not in rollback.lower()


def test_phase6_has_explicit_worker_entrypoint():
    entrypoint = (API_ROOT / "app" / "durable_worker_main.py").read_text()
    assert "No durable worker workloads are enabled" in entrypoint
    assert "build_durable_job_handlers" in entrypoint
    assert "allowed_job_types" in entrypoint


def test_phase6_side_effecting_ai_workloads_are_retry_idempotent():
    research = (API_ROOT / "app" / "agents" / "research.py").read_text()
    orchestrator = (API_ROOT / "app" / "agents" / "orchestrator.py").read_text()
    approval = (API_ROOT / "app" / "services" / "approval.py").read_text()
    worker = (API_ROOT / "app" / "jobs" / "durable_worker.py").read_text()

    for source in (research, orchestrator, approval):
        assert 'event_type == "DURABLE_AI_RESULT"' in source
        assert '"DURABLE_AI_RESULT"' in source
        assert '"job_id"' in source
    assert 'payload["_durable_job_id"] = job.id' in worker


def test_phase6_read_runtime_exposes_user_scoped_job_status():
    read_api = (ROOT / "supabase" / "functions" / "read-api" / "index.ts").read_text()
    assert "durableJobRead" in read_api
    assert '.eq("user_id", user.id)' in read_api
    assert 'durable-jobs\\/(\\d+)' in read_api
