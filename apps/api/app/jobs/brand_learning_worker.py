from __future__ import annotations

from typing import Any

from app.db.database import SessionLocal
from app.services.brand_learning import BrandLearningService


async def process_brand_learning_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_id = int(payload["learning_event_id"])
    profile_id = int(payload["profile_id"])

    async with SessionLocal() as session:
        processed = await BrandLearningService(session).process_pending(
            limit=1,
            event_ids=[event_id],
            profile_id=profile_id,
        )

    return {
        "learning_event_id": event_id,
        "profile_id": profile_id,
        "processed": processed,
    }


def build_brand_learning_handlers() -> dict[str, Any]:
    return {"brand_learning_event": process_brand_learning_event}
