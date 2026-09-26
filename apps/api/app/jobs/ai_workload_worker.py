from __future__ import annotations

from typing import Any

from sqlalchemy import select
import json

from app.models.models import AuditLog

from app.db.database import SessionLocal
from app.agents.orchestrator import AgentOrchestrator
from app.agents.research import ResearchService
from app.services.approval import ApprovalService
from app.services.content_ai import ContentAIService


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
    durable_job_id = _require_int(payload, "_durable_job_id")
    requested_topic = payload.get("requested_topic")
    candidate_limit = int(payload.get("candidate_limit", 8))
    candidate_limit = max(1, min(candidate_limit, 8))

    async with SessionLocal() as session:
        opportunities = await ResearchService(session).research_and_rank(
            profile_id=profile_id,
            requested_topic=str(requested_topic).strip() if requested_topic else None,
            candidate_limit=candidate_limit,
            durable_job_id=durable_job_id,
        )

    return {
        "profile_id": profile_id,
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
    }


async def run_content_improvement(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = _require_int(payload, "profile_id")
    durable_job_id = _require_int(payload, "_durable_job_id")
    async with SessionLocal() as session:
        marker_result = await session.execute(
            select(AuditLog)
            .where(
                AuditLog.event_type == "DURABLE_AI_RESULT",
                AuditLog.actor == "durable-ai-worker",
            )
            .order_by(AuditLog.id.desc())
        )
        for marker in marker_result.scalars():
            try:
                data = json.loads(marker.payload or "{}")
            except json.JSONDecodeError:
                continue
            if data.get("job_id") == durable_job_id and data.get("job_type") == "content_improvement":
                return data.get("result") or {}

        result = await ContentAIService().improve(
            session,
            profile_id=profile_id,
            title=str(payload.get("title") or ""),
            topic=str(payload.get("topic") or ""),
            body=str(payload.get("body") or ""),
            language=str(payload.get("language")) if payload.get("language") else None,
        )
        session.add(
            AuditLog(
                event_type="DURABLE_AI_RESULT",
                actor="durable-ai-worker",
                payload=json.dumps(
                    {"job_id": durable_job_id, "job_type": "content_improvement", "result": result},
                    ensure_ascii=False,
                ),
            )
        )
        await session.commit()
        return result


async def run_manual_content_generation(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = _require_int(payload, "profile_id")
    durable_job_id = _require_int(payload, "_durable_job_id")
    async with SessionLocal() as session:
        return await AgentOrchestrator(session, profile_id).run_manual_content_generation(durable_job_id=durable_job_id)


async def run_approval_regeneration(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = _require_int(payload, "profile_id")
    durable_job_id = _require_int(payload, "_durable_job_id")
    approval_id = _require_int(payload, "approval_id")
    feedback = payload.get("feedback")

    async with SessionLocal() as session:
        approval = await ApprovalService(session).regenerate(
            approval_id,
            str(feedback).strip() if feedback else None,
            profile_id,
            durable_job_id=durable_job_id,
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
        "content_improvement": run_content_improvement,
        "manual_content_generation": run_manual_content_generation,
        "approval_regeneration": run_approval_regeneration,
    }
