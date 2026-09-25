from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.guards.guardrails import normalize_human_style, run_content_guards
from app.models.models import VoiceMemory
from app.services.brand_intelligence import BrandIntelligenceService
from app.services.gemini_service import ModelRouterService


class ContentAIService:
    """AI-heavy content operations behind a reusable synchronous boundary.

    Routes may call these methods directly during the compatibility period, while
    durable workers can call the same methods without duplicating business logic.
    """

    async def improve(
        self,
        session: AsyncSession,
        *,
        profile_id: int,
        title: str,
        topic: str,
        body: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        if not body.strip():
            raise ValueError("Enter a draft before asking Brand OS to improve it.")

        brand_service = BrandIntelligenceService(session)
        memory = await brand_service.get_memory(profile_id)
        if memory is None or memory.status != "READY":
            raise ValueError("Complete Brand Intelligence setup first.")

        profile = await session.get(__import__("app.models.models", fromlist=["UserProfile"]).UserProfile, profile_id)
        if profile is None:
            raise ValueError("Complete Brand DNA setup first.")
        if (
            not profile.professional_title
            or not profile.industry
            or not profile.tone
            or profile.experience_years is None
        ):
            raise ValueError("Complete Professional Title, Industry, Desired Tone and Years of Experience before improving content.")

        brand_context = await brand_service.generation_context(
            profile.id,
            query=f"{title} {topic}".strip(),
        )
        voice_result = await session.execute(
            select(VoiceMemory).where(VoiceMemory.profile_id == profile.id).limit(1)
        )
        voice = voice_result.scalar_one_or_none()
        voice_context = {
            "tone": voice.tone if voice else profile.tone,
            "sentence_style": voice.sentence_style if voice else "clear and grounded",
            "preferred_phrases": voice.preferred_phrases if voice else "",
            "avoid_phrases": voice.avoid_phrases if voice else "",
            "technical_depth": voice.technical_depth if voice else "moderate",
        }

        system = """You are the polishing editor inside a human-controlled LinkedIn personal-brand product.
Improve the user's own draft without changing what they mean.

Rules:
- Preserve the user's facts, intent, language and personal claims. Never invent experience, metrics, credentials, clients or opinions.
- If the draft is in Hindi, Hinglish or another language, keep that language unless a change is necessary for clarity.
- Improve hook, structure, readability, specificity and professional tone.
- Remove filler, generic AI language and repetition.
- Do not make the post sound artificially corporate.
- Do not add unsupported facts.
- Never use em dashes, en dashes or semicolons.
- Prefer ordinary human wording, natural sentence lengths and concrete language.
- Avoid polished corporate filler, generic AI hooks and phrases that sound machine-written.
- Return JSON only:
{"title":"","topic":"","body":"","changes":[""],"claims":[{"text":"","support":"user_draft"}]}
"""
        prompt = json.dumps({
            "profile": {
                "title": profile.professional_title,
                "industry": profile.industry,
                "experience_years": profile.experience_years,
                "tone": profile.tone,
            },
            "brand_intelligence": brand_context,
            "voice": voice_context,
            "user_language": language,
            "title": title,
            "topic": topic,
            "draft": body,
        }, ensure_ascii=False)

        improved = await ModelRouterService().generate_json(
            system, prompt, max_output_tokens=1000
        )
        body_out = normalize_human_style(str(improved.get("body") or ""))
        if not body_out:
            raise ValueError("The configured LLM provider returned an empty polished draft.")
        guard = run_content_guards(body_out)
        return {
            "title": str(improved.get("title") or title).strip(),
            "topic": str(improved.get("topic") or topic).strip(),
            "body": body_out,
            "changes": improved.get("changes") or [],
            "claims": improved.get("claims") or [],
            "guard": guard.__dict__,
        }
