from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import BrandMemory, HistoricalPost, UserProfile, VoiceMemory
from app.services.gemini_service import ModelRouterService
from app.services.brand_learning import BrandLearningService


def _json(value) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


class BrandIntelligenceService:
    """Builds durable brand memory from user-controlled profile data and posts.

    This service never scrapes LinkedIn. Historical content is accepted only from
    an explicit user import or an officially authorized API integration.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_memory(self, profile_id: int) -> BrandMemory | None:
        result = await self.session.execute(
            select(BrandMemory).where(BrandMemory.profile_id == profile_id)
        )
        return result.scalar_one_or_none()

    async def get_posts(self, profile_id: int, limit: int = 20) -> list[HistoricalPost]:
        result = await self.session.execute(
            select(HistoricalPost)
            .where(
                HistoricalPost.profile_id == profile_id,
                HistoricalPost.body.is_not(None),
                HistoricalPost.body != "",
            )
            .order_by(HistoricalPost.published_at.desc().nullslast(), HistoricalPost.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())

    async def import_posts(self, posts: list[dict], profile_id: int) -> dict:
        created = 0
        skipped = 0

        for raw in posts:
            body = str(raw.get("body") or raw.get("text") or "").strip()
            if not body:
                skipped += 1
                continue

            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            existing = await self.session.execute(
                select(HistoricalPost).where(
                    HistoricalPost.profile_id == profile_id,
                    HistoricalPost.content_hash == digest,
                )
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            self.session.add(
                HistoricalPost(
                    profile_id=profile_id,
                    external_id=str(raw.get("external_id") or raw.get("id") or "") or None,
                    body=body,
                    content_hash=digest,
                    published_at=_parse_datetime(raw.get("published_at") or raw.get("publishedAt")),
                    source=str(raw.get("source") or "user_import")[:50],
                    metadata_json=json.dumps(raw.get("metadata") or {}, ensure_ascii=False),
                )
            )
            created += 1

        await self.session.commit()
        return {"created": created, "skipped": skipped, "total": created + skipped}

    async def analyze(self, profile_id: int) -> dict:
        profile = await self.session.get(UserProfile, profile_id)
        if profile is None:
            raise ValueError("Complete your profile before building Brand DNA.")

        posts = await self.get_posts(profile_id, limit=10)
        count_result = await self.session.execute(
            select(func.count(HistoricalPost.id)).where(HistoricalPost.profile_id == profile_id)
        )
        total_post_count = int(count_result.scalar_one() or 0)

        service = ModelRouterService()
        examples = [
            {
                "id": post.id,
                "published_at": post.published_at.isoformat() if post.published_at else None,
                "body": post.body[:3500],
            }
            for post in posts
        ]

        system = """You are the Brand Intelligence analyst for a professional LinkedIn personal-brand system.
Analyze ONLY the supplied profile fields and the user's own historical posts.

Rules:
- Never invent credentials, employers, clients, achievements, metrics, opinions or experiences.
- Separate direct evidence from reasonable patterns inferred from the posts.
- Treat repeated themes as patterns, not proof of expertise.
- Do not infer sensitive personal traits.
- Do not copy sentences from the historical posts into the memory summary.
- Historical posts are optional bootstrap evidence, not a prerequisite.
- If there are no historical posts, infer only from supplied profile fields and leave post-derived patterns empty or low confidence.
- The memory will be used to guide future writing, so be concrete and operational.
- Return JSON only.

Return:
{
  "summary": "short brand DNA summary",
  "identity": {"role": [], "industry": []},
  "expertise": [{"area": "", "evidence": "profile|post_pattern", "confidence": "high|medium|low"}],
  "themes": [{"theme": "", "frequency": "high|medium|low", "examples": []}],
  "opinions": [{"view": "", "evidence": "post_pattern", "confidence": "high|medium|low"}],
  "experiences": [{"signal": "", "evidence": "post_pattern", "confidence": "high|medium|low"}],
  "formats": [{"format": "", "observed": true, "notes": ""}],
  "patterns": {"hook_style": "", "structure": "", "paragraph_style": "", "cta_style": "", "length": "", "emoji_usage": "", "hashtag_usage": ""},
  "voice": {"tone": "", "sentence_style": "", "technical_depth": "", "storytelling": "", "preferred_phrases": [], "avoid_phrases": []}
}"""

        prompt = json.dumps(
            {
                "profile": {
                    "display_name": profile.display_name,
                    "professional_title": profile.professional_title,
                    "industry": profile.industry,
                    "experience_years": profile.experience_years,
                    "tone": profile.tone,
                },
                "historical_posts": examples,
                "post_count": total_post_count,
                "analysis_limit": 10,
                "historical_posts_are_optional": True,
            },
            ensure_ascii=False,
        )
        analysis = await service.generate_json(system, prompt, max_output_tokens=3600)

        memory = await self.get_memory(profile_id)
        if memory is None:
            memory = BrandMemory(profile_id=profile_id)
            self.session.add(memory)

        memory.status = "READY"
        memory.version = (memory.version or 0) + 1 if memory.initialized_at else 1
        memory.summary = str(analysis.get("summary") or "").strip()
        memory.identity_json = _json(analysis.get("identity"))
        memory.expertise_json = _json(analysis.get("expertise"))
        memory.themes_json = _json(analysis.get("themes"))
        memory.opinions_json = _json(analysis.get("opinions"))
        memory.experiences_json = _json(analysis.get("experiences"))
        memory.formats_json = _json(analysis.get("formats"))
        memory.patterns_json = _json(analysis.get("patterns"))
        memory.voice_json = _json(analysis.get("voice"))
        memory.source_post_count = total_post_count
        memory.initialized_at = datetime.now(timezone.utc)

        voice_data = analysis.get("voice") or {}
        # Desired tone is explicitly supplied by the user and remains the source of truth.
        if profile.tone:
            voice_data = {**voice_data, "tone": profile.tone}
        voice_result = await self.session.execute(select(VoiceMemory).where(VoiceMemory.profile_id == profile_id).limit(1))
        voice = voice_result.scalar_one_or_none()
        if voice is None:
            voice = VoiceMemory(profile_id=profile_id)
            self.session.add(voice)
        voice.tone = str(voice_data.get("tone") or profile.tone or "practical")
        voice.sentence_style = str(voice_data.get("sentence_style") or "clear and concise")
        voice.vocabulary = _json(voice_data.get("preferred_phrases"))
        voice.preferred_phrases = _json(voice_data.get("preferred_phrases"))
        voice.avoid_phrases = _json(voice_data.get("avoid_phrases"))
        voice.emoji_usage = str((analysis.get("patterns") or {}).get("emoji_usage") or "limited")
        voice.technical_depth = str(voice_data.get("technical_depth") or "moderate")
        voice.opinion_style = "grounded in observed content"
        voice.storytelling_style = str(voice_data.get("storytelling") or "concrete")

        await self.session.commit()
        await self.session.refresh(memory)
        return self.serialize(memory)

    def serialize(self, memory: BrandMemory | None) -> dict:
        if memory is None:
            return {"status": "NOT_INITIALIZED", "source_post_count": 0}
        return {
            "id": memory.id,
            "status": memory.status,
            "version": memory.version,
            "summary": memory.summary,
            "identity": json.loads(memory.identity_json or "[]"),
            "expertise": json.loads(memory.expertise_json or "[]"),
            "themes": json.loads(memory.themes_json or "[]"),
            "opinions": json.loads(memory.opinions_json or "[]"),
            "experiences": json.loads(memory.experiences_json or "[]"),
            "formats": json.loads(memory.formats_json or "[]"),
            "patterns": json.loads(memory.patterns_json or "{}"),
            "voice": json.loads(memory.voice_json or "{}"),
            "source_post_count": memory.source_post_count,
            "initialized_at": memory.initialized_at.isoformat() if memory.initialized_at else None,
            "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        }

    async def generation_context(self, profile_id: int, query: str | None = None) -> dict:
        memory = await self.get_memory(profile_id)
        if memory is None or memory.status != "READY":
            raise ValueError("Brand Intelligence is not initialized. Complete the Brand DNA setup first.")
        profile = await self.session.get(UserProfile, profile_id)
        if profile is None:
            raise ValueError("Complete the Brand DNA setup first.")
        if (
            not profile.professional_title
            or not profile.industry
            or not profile.tone
            or profile.experience_years is None
        ):
            raise ValueError("Complete Professional Title, Industry, Desired Tone and Years of Experience before generating content.")

        count_result = await self.session.execute(
            select(func.count(HistoricalPost.id)).where(HistoricalPost.profile_id == profile_id)
        )
        current_post_count = int(count_result.scalar_one() or 0)

        # Do not silently re-run Brand Intelligence during every content request.
        # Refreshing Brand DNA is an explicit user action. This keeps generation fast
        # and prevents a hidden second LLM call from blocking the editor.
        posts = await self.get_posts(profile_id, limit=5)
        learning_context = await BrandLearningService(self.session).context(
            profile_id,
            query=query,
            memory_limit=10,
            event_limit=6,
            semantic_limit=8,
        )
        return {
            "brand_memory": self.serialize(memory),
            "learning_memory": learning_context,
            "historical_examples": [
                {
                    "published_at": p.published_at.isoformat() if p.published_at else None,
                    "source": p.source,
                    "body": p.body[:1400],
                }
                for p in posts
            ],
            "memory_state": {
                "historical_post_count": current_post_count,
                "last_analyzed_post_count": memory.source_post_count if memory else 0,
                "continuously_updated": True,
            },
        }
