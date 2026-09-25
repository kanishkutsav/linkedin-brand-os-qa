import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.jobs.durable_worker import DurableJobWorker
from app.models.base import Base
from app.models.durable_job import DurableJob
from app.models.models import AuthUser
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

    completed = await service.complete(
        claimed.id,
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
    assert seen == [{"value": 42}]

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
        assert stored.status == "QUEUED"
        assert "No handler registered" in (stored.last_error or "")


def test_phase3_migration_is_non_destructive_to_existing_tables():
    from pathlib import Path

    sql = Path(__file__).resolve().parents[3] / "supabase/migrations/20260926_phase3_durable_jobs.sql"
    text = sql.read_text()

    assert "create table if not exists public.durable_jobs" in text
    assert "references public.auth_users(id) on delete cascade" in text
    assert "idempotency_key text not null unique" in text
    assert "status in ('QUEUED','RUNNING','SUCCEEDED','FAILED')" in text
    assert "drop table" not in text.lower()


def test_phase3_worker_is_not_started_by_fastapi_yet():
    from pathlib import Path

    main = Path("app/main.py").read_text()
    assert "DurableJobWorker" not in main
    assert "DurableJobService" not in main


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
