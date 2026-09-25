from __future__ import annotations

from typing import Any

from app.jobs.ai_workload_worker import build_ai_workload_handlers
from app.jobs.brand_learning_worker import build_brand_learning_handlers


def build_durable_job_handlers() -> dict[str, Any]:
    """Return the complete Phase 3 handler registry without starting a worker."""
    handlers = {}
    handlers.update(build_brand_learning_handlers())
    handlers.update(build_ai_workload_handlers())
    return handlers
