import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.jobs.durable_worker import DurableJobWorker
from app.jobs.ai_workload_worker import build_ai_workload_handlers
from app.jobs.durable_handlers import build_durable_job_handlers
from app.models.base import Base
from app.models.durable_job import DurableJob
from app.models.models import AuthUser, LearningEvent
from app.services.durable_jobs import DurableJobService, utcnow
from app.services.brand_learning import BrandLearningService
from app.core.config import settings


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_is_idempotent(session_factory):
    service = DurableJobService(session_factory)

    first, created = await service.enqueue(
        job_type="test",
        idempotency_key="same-key",
        payload={"value": 1},
    )
    second, created_again = await service.enqueue(
        job_type="test",
        idempotency_key="same-key",
        payload={"value": 2},
    )

    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert json.loads(second.payload_json or "{}") == {"value": 1}


@pytest.mark.asyncio
async def test_claim_complete_lifecycle(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="test",
        idempotency_key="lifecycle",
        payload={"user": 7},
    )

    claimed = await service.claim_next()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "RUNNING"
    assert claimed.attempts == 1
    assert claimed.lease_token

    completed = await service.complete(
        claimed.id,
        lease_token=claimed.lease_token or "",
        result={"ok": True},
    )
    assert completed.status == "SUCCEEDED"
    assert completed.finished_at is not None
    assert json.loads(completed.result_json or "{}") == {"ok": True}

    assert await service.claim_next() is None


@pytest.mark.asyncio
async def test_failure_requeues_then_eventually_becomes_terminal(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="test",
        idempotency_key="retryable",
        max_attempts=2,
    )

    claimed = await service.claim_next()
    assert claimed is not None

    retrying = await service.fail(
        claimed.id,
        lease_token=claimed.lease_token or "",
        error="temporary provider failure",
        retry_delay_seconds=0,
    )
    assert retrying.status == "QUEUED"
    assert retrying.last_error == "temporary provider failure"

    claimed_again = await service.claim_next()
    assert claimed_again is not None
    assert claimed_again.attempts == 2

    failed = await service.fail(
        claimed_again.id,
        lease_token=claimed_again.lease_token or "",
        error="permanent failure",
        retry_delay_seconds=0,
    )
    assert failed.status == "FAILED"
    assert failed.finished_at is not None


@pytest.mark.asyncio
async def test_expired_running_lease_is_reclaimed(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="test",
        idempotency_key="expired-lease",
        max_attempts=3,
    )

    claimed = await service.claim_next()
    assert claimed is not None

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        stored.status = "RUNNING"
        stored.locked_at = utcnow() - timedelta(seconds=601)
        await session.commit()

    reclaimed = await service.claim_next(lease_seconds=600)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.status == "RUNNING"
    assert reclaimed.attempts == 2


@pytest.mark.asyncio
async def test_stale_worker_cannot_complete_after_lease_reclaim(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="fenced",
        idempotency_key="fenced-stale-worker",
        max_attempts=3,
    )

    first = await service.claim_next()
    assert first is not None
    stale_token = first.lease_token
    assert stale_token

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        stored.locked_at = utcnow() - timedelta(seconds=601)
        await session.commit()

    second = await service.claim_next(lease_seconds=600)
    assert second is not None
    assert second.id == job.id
    assert second.lease_token
    assert second.lease_token != stale_token

    with pytest.raises(ValueError, match="lease is no longer valid"):
        await service.complete(
            job.id,
            lease_token=stale_token,
            result={"stale": True},
        )

    completed = await service.complete(
        job.id,
        lease_token=second.lease_token,
        result={"stale": False},
    )
    assert completed.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_worker_dispatches_handler_and_records_result(session_factory):
    seen = []

    async def handler(payload):
        seen.append(payload)
        return {"processed": payload["value"]}

    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="unit-test",
        idempotency_key="worker-success",
        payload={"value": 42},
    )

    worker = DurableJobWorker(
        session_factory,
        {"unit-test": handler},
        poll_interval_seconds=1,
        lease_seconds=600,
    )

    assert await worker.run_once() is True
    assert seen[0]["value"] == 42
    assert seen[0]["_durable_job_id"] == job.id

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        assert stored.status == "SUCCEEDED"
        assert json.loads(stored.result_json or "{}") == {"processed": 42}


@pytest.mark.asyncio
async def test_worker_retries_handler_failure_with_bounded_backoff(session_factory):
    async def handler(_payload):
        raise RuntimeError("provider unavailable")

    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="unit-test-failure",
        idempotency_key="worker-failure",
        max_attempts=2,
    )

    worker = DurableJobWorker(
        session_factory,
        {"unit-test-failure": handler},
        poll_interval_seconds=1,
        lease_seconds=600,
    )

    assert await worker.run_once() is True

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        assert stored.status == "QUEUED"
        assert stored.attempts == 1
        assert "RuntimeError: provider unavailable" in (stored.last_error or "")
        stored.available_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once() is True

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        assert stored.status == "FAILED"
        assert stored.attempts == 2


@pytest.mark.asyncio
async def test_worker_rejects_unknown_job_type_without_crashing(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(
        job_type="unknown-type",
        idempotency_key="unknown-handler",
    )

    worker = DurableJobWorker(session_factory, {}, poll_interval_seconds=1)

    assert await worker.run_once() is True

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        assert stored.status == "FAILED"
        assert "No handler registered" in (stored.last_error or "")


@pytest.mark.asyncio
async def test_ai_workload_handlers_validate_payloads():
    handlers = build_ai_workload_handlers()
    assert set(handlers) == {"research_discovery", "content_improvement", "manual_content_generation", "approval_regeneration"}

    with pytest.raises(ValueError, match="profile_id"):
        await handlers["research_discovery"]({})

    with pytest.raises(ValueError, match="approval_id"):
        await handlers["approval_regeneration"]({"profile_id": 1, "_durable_job_id": 1})


def test_phase3c_ai_workloads_are_opt_in():
    assert settings.durable_ai_workloads_enabled is False
    assert settings.durable_ai_worker_enabled is False
    assert settings.durable_scheduled_jobs_enabled is False
    assert settings.durable_scheduled_worker_enabled is False


def test_complete_phase3_handler_registry():
    handlers = build_durable_job_handlers()
    assert set(handlers) == {
        "brand_learning_event",
        "research_discovery",
        "content_improvement",
        "manual_content_generation",
        "approval_regeneration",
        "scheduled_discovery",
        "scheduled_calendar",
        "scheduled_retention",
    }


def test_phase3_migration_is_non_destructive_to_existing_tables():
    from pathlib import Path

    sql = Path(__file__).resolve().parents[3] / "supabase/migrations/20260926_phase3_durable_jobs.sql"
    text = sql.read_text()

    assert "create table if not exists public.durable_jobs" in text
    assert "references public.auth_users(id) on delete cascade" in text
    assert "idempotency_key text not null unique" in text
    assert "status in ('QUEUED','RUNNING','SUCCEEDED','FAILED')" in text
    assert "drop table" not in text.lower()


def test_phase3_worker_is_not_started_by_fastapi():
    from pathlib import Path

    main = Path("app/main.py").read_text()
    assert "DurableJobWorker" not in main
    assert "from app.jobs.durable_worker import" not in main


@pytest.mark.asyncio
async def test_learning_event_enqueues_one_durable_job_when_enabled(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "durable_learning_enqueue_enabled", True)
    # Use the same SQLAlchemy session for event + durable job so enqueue is
    # atomic with the learning event transaction.
    async with session_factory() as session:
        service = BrandLearningService(session)
        event_id = await service.record_event(
            profile_id=1,
            event_type="USER_THOUGHT",
            source_type="manual_thought",
            source_id="thought-1",
            content="A durable learning test event.",
        )
        await session.commit()

        assert event_id is not None

        result = await session.execute(
            select(DurableJob).where(
                DurableJob.idempotency_key == f"learning-event:{event_id}"
            )
        )
        job = result.scalar_one()
        assert job.job_type == "brand_learning_event"
        assert job.status == "QUEUED"
        assert json.loads(job.payload_json or "{}") == {
            "learning_event_id": event_id,
            "profile_id": 1,
        }


@pytest.mark.asyncio
async def test_learning_worker_processing_is_profile_scoped(session_factory):
    async with session_factory() as session:
        session.add_all([
            LearningEvent(
                profile_id=1,
                event_type="USER_THOUGHT",
                source_type="manual_thought",
                source_id="profile-1-event",
                content="Profile one event",
                metadata_json="{}",
                status="PENDING",
            ),
            LearningEvent(
                profile_id=2,
                event_type="USER_THOUGHT",
                source_type="manual_thought",
                source_id="profile-2-event",
                content="Profile two event",
                metadata_json="{}",
                status="PENDING",
            ),
        ])
        await session.commit()

        result = await session.execute(
            select(LearningEvent).order_by(LearningEvent.id.asc())
        )
        events = list(result.scalars().all())
        second_id = events[1].id

        processed = await BrandLearningService(session).process_pending(
            limit=1,
            event_ids=[second_id],
            profile_id=1,
        )
        assert processed == 0

        refreshed_second = await session.get(LearningEvent, second_id)
        assert refreshed_second is not None
        assert refreshed_second.status == "PENDING"


@pytest.mark.asyncio
async def test_learning_processing_failure_records_retry_state(session_factory, monkeypatch):
    async def failing_embed(_self, _texts):
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(BrandLearningService, "_embed_documents", failing_embed)

    async with session_factory() as session:
        event = LearningEvent(
            profile_id=1,
            event_type="USER_THOUGHT",
            source_type="manual_thought",
            source_id="retry-event",
            content="Retryable learning event",
            metadata_json="{}",
            status="PENDING",
        )
        session.add(event)
        await session.commit()
        event_id = event.id

        processed = await BrandLearningService(session).process_pending(
            limit=1,
            event_ids=[event_id],
            profile_id=1,
        )
        assert processed == 0

        refreshed = await session.get(LearningEvent, event_id)
        assert refreshed is not None
        assert refreshed.status == "PENDING"
        assert refreshed.attempts == 1
        assert refreshed.last_error == "embedding provider unavailable"


def test_learning_worker_handler_passes_profile_scope():
    from pathlib import Path

    source = Path("app/jobs/brand_learning_worker.py").read_text()
    assert "event_ids=[event_id]" in source
    assert "profile_id=profile_id" in source


@pytest.mark.asyncio
async def test_learning_event_does_not_enqueue_job_by_default(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "durable_learning_enqueue_enabled", False)
    async with session_factory() as session:
        event_id = await BrandLearningService(session).record_event(
            profile_id=1,
            event_type="USER_THOUGHT",
            source_type="manual_thought",
            source_id="thought-default",
            content="Existing learning path remains unchanged.",
        )
        await session.commit()

        result = await session.execute(
            select(DurableJob).where(
                DurableJob.idempotency_key == f"learning-event:{event_id}"
            )
        )
        assert result.scalar_one_or_none() is None

# Phase 3 QA: regression suite remains intentionally production-disconnected.


@pytest.mark.asyncio
async def test_exhausted_running_lease_becomes_terminal_failure(session_factory):
    service = DurableJobService(session_factory)
    job, _ = await service.enqueue(job_type="lease-terminal", idempotency_key="lease-terminal", max_attempts=1)
    claimed = await service.claim_next()
    assert claimed is not None
    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        stored.locked_at = utcnow() - timedelta(seconds=601)
        await session.commit()

    assert await service.claim_next(lease_seconds=600) is None

    async with session_factory() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored is not None
        assert stored.status == "FAILED"
        assert stored.finished_at is not None

# Phase 3 QA: lease recovery regression included.

# Phase 3 QA: stale exhausted leases are terminal.

# Final Phase 3 QA trigger.
