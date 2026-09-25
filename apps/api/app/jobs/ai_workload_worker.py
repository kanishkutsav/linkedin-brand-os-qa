from __future__ import annotations

from typing import Any

from app.db.database import SessionLocal
from app.agents.research import ResearchService
from app.services.approval import ApprovalService


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"Missing required durable job field: {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid durable job field: {key}") from exc


async def run_research_discovery(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = _require_int(payload, "profile_id")
    requested_topic = payload.get("requested_topic")
    candidate_limit = int(payload.get("candidate_limit", 8))
    candidate_limit = max(1, min(candidate_limit, 8))

    async with SessionLocal() as session:
        opportunities = await ResearchService(session).research_and_rank(
            profile_id=profile_id,
            requested_topic=str(requested_topic).strip() if requested_topic else None,
            candidate_limit=candidate_limit,
        )

    return {
        "profile_id": profile_id,
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
    }


async def run_approval_regeneration(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = _require_int(payload, "profile_id")
    approval_id = _require_int(payload, "approval_id")
    feedback = payload.get("feedback")

    async with SessionLocal() as session:
        approval = await ApprovalService(session).regenerate(
            approval_id,
            str(feedback).strip() if feedback else None,
            profile_id,
        )

    return {
        "profile_id": profile_id,
        "approval_id": approval_id,
        "status": approval.status,
        "reason": approval.reason,
    }


def build_ai_workload_handlers() -> dict[str, Any]:
    return {
        "research_discovery": run_research_discovery,
        "approval_regeneration": run_approval_regeneration,
    }
