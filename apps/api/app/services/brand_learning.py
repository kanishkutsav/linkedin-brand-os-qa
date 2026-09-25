from __future__ import annotations

import json
from datetime import datetime, timezone
import math
from typing import Any

from google import genai
from google.genai import types
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import LearningEvent, LearningMemory
from app.services.gemini_service import ModelRouterService
from app.models.models import UserProfile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


class BrandLearningService:
    """User-isolated long-term learning layer.

    Raw learning events are durable evidence. Structured memories are distilled
    observations. Neither silently changes Brand DNA. Learning work is queued
    and processed asynchronously by the existing scheduler.
    """

    EMBEDDING_MODEL = settings.learning_embedding_model
    EMBEDDING_DIMENSIONS = 768

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_event(
        self,
        *,
        profile_id: int,
        event_type: str,
        source_type: str,
        content: str,
        source_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        content = (content or "").strip()
        if not content:
            return None

        normalized_source_id = str(source_id) if source_id is not None else None
        if normalized_source_id:
            existing = await self.session.execute(
                select(LearningEvent.id).where(
                    LearningEvent.profile_id == profile_id,
                    LearningEvent.source_type == source_type,
                    LearningEvent.source_id == normalized_source_id,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return None

        event = LearningEvent(
            profile_id=profile_id,
            event_type=event_type[:60],
            source_type=source_type[:60],
            source_id=normalized_source_id,
            content=content[:20000],
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            status="PENDING",
        )
        self.session.add(event)
        await self.session.flush()
        return event.id

    async def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not settings.gemini_api_key or not texts:
            return []
        client = genai.Client(api_key=settings.gemini_api_key)
        result = await client.aio.models.embed_content(
            model=self.EMBEDDING_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self.EMBEDDING_DIMENSIONS,
            ),
        )
        return [list(getattr(item, "values", None) or []) for item in (result.embeddings or [])]

    async def _embed_query(self, query: str) -> list[float]:
        if not settings.gemini_api_key or not query.strip():
            return []
        client = genai.Client(api_key=settings.gemini_api_key)
        result = await client.aio.models.embed_content(
            model=self.EMBEDDING_MODEL,
            contents=query[:4000],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self.EMBEDDING_DIMENSIONS,
            ),
        )
        embeddings = result.embeddings or []
        return list(getattr(embeddings[0], "values", None) or []) if embeddings else []

    async def process_pending(self, limit: int = 10) -> int:
        result = await self.session.execute(
            select(LearningEvent)
            .where(LearningEvent.status == "PENDING")
            .order_by(LearningEvent.created_at.asc())
            .limit(max(1, min(limit, 50)))
            .with_for_update(skip_locked=True)
        )
        events = list(result.scalars().all())
        if not events:
            return 0

        processed = 0
        by_profile: dict[int, list[LearningEvent]] = {}
        for event in events:
            by_profile.setdefault(int(event.profile_id), []).append(event)

        for profile_id, profile_events in by_profile.items():
            try:
                embeddings = await self._embed_documents(
                    [f"event: {e.event_type} | source: {e.source_type} | text: {e.content[:6000]}" for e in profile_events]
                )
                if embeddings and len(embeddings) == len(profile_events):
                    for event, embedding in zip(profile_events, embeddings):
                        if len(embedding) == self.EMBEDDING_DIMENSIONS:
                            event.embedding = embedding

                extraction_prompt = json.dumps(
                    {
                        "events": [
                            {
                                "id": e.id,
                                "event_type": e.event_type,
                                "source_type": e.source_type,
                                "content": e.content[:8000],
                                "metadata": json.loads(e.metadata_json or "{}"),
                            }
                            for e in profile_events
                        ]
                    },
                    ensure_ascii=False,
                )
                system = """You are the private learning analyst for one user's personal brand.
Extract durable observations from the supplied user-owned events.

Rules:
- Never invent facts or infer sensitive traits.
- A research action is evidence of interest, not proof of belief.
- A draft is weaker evidence than an approved/published final post.
- Repeated behavior can increase confidence, but do not turn one-off behavior into a permanent preference.
- Do not rewrite Brand DNA. Produce observations only.
- Keep memories operational for future writing and research.
- Return JSON only.

Return:
{"memories":[
  {"memory_key":"","memory_type":"interest|writing_preference|topic|viewpoint|format_preference|avoidance|behavior",
   "content":"","confidence":"high|medium|low","importance":0.0,
   "evidence_event_ids":[0]}
]}"""

                extracted = await ModelRouterService().generate_json(
                    system,
                    extraction_prompt,
                    max_output_tokens=1800,
                )
                memories = extracted.get("memories") or []
                memory_texts: list[str] = []
                memory_rows: list[dict[str, Any]] = []

                for raw in memories[:20]:
                    key = str(raw.get("memory_key") or "").strip().lower()[:180]
                    content = str(raw.get("content") or "").strip()
                    if not key or not content:
                        continue
                    confidence = str(raw.get("confidence") or "medium").lower()
                    if confidence not in {"high", "medium", "low"}:
                        confidence = "medium"
                    try:
                        importance = max(0.05, min(1.0, float(raw.get("importance", 0.5))))
                    except (TypeError, ValueError):
                        importance = 0.5
                    memory_texts.append(content[:4000])
                    memory_rows.append(
                        {
                            "key": key,
                            "type": str(raw.get("memory_type") or "behavior")[:50],
                            "content": content[:5000],
                            "confidence": confidence,
                            "importance": importance,
                            "evidence": raw.get("evidence_event_ids") or [],
                        }
                    )

                memory_embeddings = await self._embed_documents(memory_texts)
                for index, row in enumerate(memory_rows):
                    existing = await self.session.execute(
                        select(LearningMemory).where(
                            LearningMemory.profile_id == profile_id,
                            LearningMemory.memory_key == row["key"],
                        ).limit(1)
                    )
                    memory = existing.scalar_one_or_none()
                    if memory is None:
                        memory = LearningMemory(
                            profile_id=profile_id,
                            memory_key=row["key"],
                            memory_type=row["type"],
                            content=row["content"],
                            confidence=row["confidence"],
                            importance=row["importance"],
                            source_count=1,
                            metadata_json=json.dumps({"evidence_event_ids": row["evidence"]}, ensure_ascii=False),
                        )
                        self.session.add(memory)
                    else:
                        memory.content = row["content"]
                        memory.memory_type = row["type"]
                        memory.confidence = row["confidence"]
                        memory.importance = max(float(memory.importance or 0), row["importance"])
                        memory.source_count = int(memory.source_count or 0) + 1
                        memory.metadata_json = json.dumps({"evidence_event_ids": row["evidence"]}, ensure_ascii=False)
                        memory.last_observed_at = _utcnow()
                        memory.updated_at = _utcnow()
                    if index < len(memory_embeddings) and len(memory_embeddings[index]) == self.EMBEDDING_DIMENSIONS:
                        memory.embedding = memory_embeddings[index]

                for event in profile_events:
                    event.status = "PROCESSED"
                    event.processed_at = _utcnow()
                    event.attempts = int(event.attempts or 0) + 1
                    event.last_error = None
                await self.session.commit()
                processed += len(profile_events)
            except Exception as exc:
                await self.session.rollback()
                for event in profile_events:
                    event.attempts = int(event.attempts or 0) + 1
                    event.last_error = str(exc)[:1000]
                    if event.attempts >= 3:
                        event.status = "FAILED"
                await self.session.commit()

        return processed

    async def context(
        self,
        profile_id: int,
        *,
        query: str | None = None,
        memory_limit: int = 10,
        event_limit: int = 6,
        semantic_limit: int = 8,
    ) -> dict:
        memories_result = await self.session.execute(
            select(LearningMemory)
            .where(LearningMemory.profile_id == profile_id)
            .order_by(LearningMemory.updated_at.desc())
            .limit(max(10, min(memory_limit * 3, 60)))
        )
        memories = list(memories_result.scalars().all())
        now = _utcnow()
        def memory_rank(item: LearningMemory) -> float:
            age_days = max(0.0, (now - (item.updated_at or now)).total_seconds() / 86400)
            recency = 0.5 + 0.5 * math.exp(-age_days / 180.0)
            return float(item.importance or 0.5) * recency
        memories.sort(key=memory_rank, reverse=True)
        memories = memories[:max(1, min(memory_limit, 20))]

        recent_result = await self.session.execute(
            select(LearningEvent)
            .where(
                LearningEvent.profile_id == profile_id,
                LearningEvent.status.in_(["PENDING", "PROCESSED"]),
            )
            .order_by(LearningEvent.created_at.desc())
            .limit(max(1, min(event_limit, 12)))
        )
        recent_events = list(recent_result.scalars().all())

        semantic_events: list[dict] = []
        semantic_memories: list[dict] = []
        if query and query.strip():
            try:
                embedding = await self._embed_query(query)
            except Exception:
                embedding = []
            if len(embedding) == self.EMBEDDING_DIMENSIONS:
                literal = _vector_literal(embedding)
                event_rows = await self.session.execute(
                    text("""
                        select id, event_type, source_type, source_id, content, metadata_json, created_at, similarity
                        from public.match_learning_events(
                            :profile_id,
                            cast(:embedding as extensions.vector(768)),
                            :threshold,
                            :count
                        )
                    """),
                    {
                        "profile_id": profile_id,
                        "embedding": literal,
                        "threshold": 0.42,
                        "count": semantic_limit,
                    },
                )
                semantic_events = [dict(row._mapping) for row in event_rows.all()]

                memory_rows = await self.session.execute(
                    text("""
                        select id, memory_key, memory_type, content, confidence, importance, source_count, metadata_json, updated_at, similarity
                        from public.match_learning_memories(
                            :profile_id,
                            cast(:embedding as extensions.vector(768)),
                            :threshold,
                            :count
                        )
                    """),
                    {
                        "profile_id": profile_id,
                        "embedding": literal,
                        "threshold": 0.42,
                        "count": semantic_limit,
                    },
                )
                semantic_memories = [dict(row._mapping) for row in memory_rows.all()]

        return {
            "memories": [
                {
                    "type": m.memory_type,
                    "content": m.content,
                    "confidence": m.confidence,
                    "importance": round(float(m.importance or 0), 2),
                    "source_count": m.source_count,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                }
                for m in memories
            ],
            "recent_events": [
                {
                    "event_type": e.event_type,
                    "source_type": e.source_type,
                    "content": e.content[:1400],
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in recent_events
            ],
            "semantic_matches": {
                "memories": semantic_memories,
                "events": semantic_events,
            },
        }

    async def summary(self, profile_id: int) -> dict:
        pending = await self.session.execute(
            select(LearningEvent.id).where(
                LearningEvent.profile_id == profile_id,
                LearningEvent.status == "PENDING",
            )
        )
        memories = await self.session.execute(
            select(LearningMemory.id).where(LearningMemory.profile_id == profile_id)
        )
        return {
            "pending_events": len(pending.scalars().all()),
            "memory_count": len(memories.scalars().all()),
        }
