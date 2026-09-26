import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.jobs.durable_queue import enqueue_job
from app.jobs.durable_worker import DurableJobWorker
from app.models.base import Base
from app.models.models import DurableJob


@pytest.fixture
async def durable_db(tmp_path):
    db_path = tmp_path / "durable.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_durable_queue_is_idempotent(durable_db):
    async with durable_db() as session:
        first = await enqueue_job(
            session,
            job_type="manual_content_generation",
            profile_id=7,
            payload={"trigger": "test"},
            idempotency_key="same-job",
        )
        second = await enqueue_job(
            session,
            job_type="manual_content_generation",
            profile_id=7,
            payload={"trigger": "test"},
            idempotency_key="same-job",
        )
        await session.commit()
        assert first is not None
        assert second is None

        rows = await session.execute(select(DurableJob))
        assert len(rows.scalars().all()) == 1


@pytest.mark.asyncio
async def test_durable_worker_claims_and_completes_job(durable_db):
    calls = []

    async def handler(session, job, payload):
        calls.append((job.id, payload))
        return {"ok": True}

    async with durable_db() as session:
        await enqueue_job(
            session,
            job_type="test",
            payload={"value": 42},
            idempotency_key="worker-test",
        )
        await session.commit()

    worker = DurableJobWorker(
        durable_db,
        {"test": handler},
        allowed_job_types={"test"},
        poll_interval_seconds=1,
        lease_seconds=60,
        worker_id="qa-worker",
    )
    assert await worker.process_one() is True
    assert calls and calls[0][1] == {"value": 42}

    async with durable_db() as session:
        job = (await session.execute(select(DurableJob))).scalar_one()
        assert job.status == "SUCCEEDED"
        assert job.attempts == 1
        assert job.locked_at is None
        assert job.locked_by is None


@pytest.mark.asyncio
async def test_durable_worker_retries_transient_failure(durable_db):
    async def handler(session, job, payload):
        raise RuntimeError("temporary provider failure")

    async with durable_db() as session:
        await enqueue_job(
            session,
            job_type="test",
            payload={},
            idempotency_key="retry-test",
        )
        await session.commit()

    worker = DurableJobWorker(
        durable_db,
        {"test": handler},
        allowed_job_types={"test"},
        poll_interval_seconds=1,
        lease_seconds=60,
        max_attempts=3,
        worker_id="qa-worker",
    )
    await worker.process_one()

    async with durable_db() as session:
        job = (await session.execute(select(DurableJob))).scalar_one()
        assert job.status == "QUEUED"
        assert job.attempts == 1
        assert "temporary provider failure" in (job.last_error or "")
        assert job.available_at is not None


def test_phase3_6_core_boundaries_are_present():
    root = Path(__file__).resolve().parents[3]
    assert (root / "apps/api/app/services/brand_learning.py").exists()
    assert (root / "apps/api/app/services/retention.py").exists()
    assert (root / "apps/api/app/services/approval.py").exists()
    assert (root / "apps/api/app/jobs/scheduled_jobs.py").exists()
    assert (root / "apps/api/app/jobs/durable_queue.py").exists()
    assert (root / "apps/api/app/jobs/durable_worker.py").exists()
    assert (root / "apps/api/app/jobs/durable_handlers.py").exists()
    assert (root / "apps/api/app/durable_worker_main.py").exists()


def test_phase6_worker_entrypoint_has_explicit_feature_flags():
    source = (Path(__file__).resolve().parents[1] / "app/durable_worker_main.py").read_text()
    assert "durable_learning_worker_enabled" in source
    assert "durable_ai_worker_enabled" in source
    assert "durable_scheduled_worker_enabled" in source
    assert "allowed_job_types" in source


def test_phase6_migration_has_queue_safety_fields():
    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/20260926_phase6_durable_jobs.sql"
    ).read_text()
    for required in (
        "idempotency_key",
        "available_at",
        "locked_at",
        "locked_by",
        "attempts",
        "last_error",
        "completed_at",
    ):
        assert required in migration


def test_phase6_disables_duplicate_in_process_ownership():
    scheduler = (Path(__file__).resolve().parents[1] / "app/services/agent_scheduler.py").read_text()
    assert "not settings.durable_scheduled_worker_enabled" in scheduler
    assert "not settings.durable_learning_worker_enabled" in scheduler


def test_phase6_scheduled_endpoint_supports_durable_queue():
    main = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    assert "enqueue_job(" in main
    assert "scheduled:" in main
    assert "durable_scheduled_worker_enabled" in main


def test_dashboard_counts_remain_independent_of_retention_window():
    approval = (Path(__file__).resolve().parents[1] / "app/services/approval.py").read_text()
    retention = (Path(__file__).resolve().parents[1] / "app/services/retention.py").read_text()
    start = approval.index("def dashboard_counts")
    section = approval[start:start + 5000]
    assert "published_post_retention_limit" not in section
    assert "published_post_retention_limit" in retention


def test_learning_events_enqueue_durable_work():
    learning = (Path(__file__).resolve().parents[1] / "app/services/brand_learning.py").read_text()
    assert "enqueue_learning_event" in learning
    assert "event_id=int(event.id)" in learning
