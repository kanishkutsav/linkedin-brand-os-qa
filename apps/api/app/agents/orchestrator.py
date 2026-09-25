from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.strategy import ContentStrategyService
from app.agents.voice import VoiceProfileBuilder
from app.agents.research import ResearchService
from app.guards.guardrails import normalize_human_style, run_content_guards
from app.models.models import (
    AuditLog,
    ContentItem,
    ContentVersion,
    FeedbackEntry,
    HistoricalPost,
    UserProfile,
    VoiceMemory,
)
from app.services.approval import ApprovalService
from app.services.brand_intelligence import BrandIntelligenceService
from app.services.gemini_service import ModelRouterService


class AgentOrchestrator:
    """Approval-first content pipeline.

    Gemini may research at a high level, select an angle and draft content.
    It cannot publish, comment, like, DM, connect or otherwise act externally.
    """

    def __init__(self, session: AsyncSession, profile_id: int):
        self.session = session
        self.profile_id = int(profile_id)

    async def _profile(self) -> UserProfile:
        profile = await self.session.get(UserProfile, self.profile_id)
        if profile is None:
            profile = UserProfile(
                id=self.profile_id,
                display_name="User",
                role="owner",
            )
            self.session.add(profile)
            await self.session.flush()
        return profile

    async def _voice(self) -> dict:
        profile = await self._profile()
        memory = (await self.session.execute(
            select(VoiceMemory).where(VoiceMemory.profile_id == profile.id).limit(1)
        )).scalar_one_or_none()
        if memory is not None:
            return {
                "tone": memory.tone,
                "sentence_style": memory.sentence_style,
                "vocabulary": memory.vocabulary,
                "preferred_phrases": memory.preferred_phrases,
                "avoid_phrases": memory.avoid_phrases,
                "emoji_usage": memory.emoji_usage,
                "humor_style": memory.humor_style,
                "technical_depth": memory.technical_depth,
                "opinion_style": memory.opinion_style,
                "storytelling_style": memory.storytelling_style,
            }

        result = await self.session.execute(
            select(ContentVersion.body)
            .join(FeedbackEntry, FeedbackEntry.content_version_id == ContentVersion.id)
            .join(ContentItem, ContentItem.id == ContentVersion.content_id)
            .where(
                FeedbackEntry.action == "APPROVED",
                ContentItem.profile_id == self.profile_id,
            )
            .order_by(FeedbackEntry.created_at.desc())
            .limit(10)
        )
        examples = [row[0] for row in result.all()]
        return VoiceProfileBuilder().learn(examples)

    async def _is_duplicate_topic(self, topic: str) -> bool:
        result = await self.session.execute(
            select(ContentItem).where(
                ContentItem.profile_id == self.profile_id,
                ContentItem.topic == topic,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _is_duplicate_body(self, body: str) -> bool:
        digest = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()
        version_result = await self.session.execute(
            select(ContentVersion.id)
            .join(ContentItem, ContentItem.id == ContentVersion.content_id)
            .where(
                ContentItem.profile_id == self.profile_id,
                ContentVersion.content_hash == digest,
            )
            .limit(1)
        )
        if version_result.scalar_one_or_none() is not None:
            return True

        historical_result = await self.session.execute(
            select(HistoricalPost.id).where(
                HistoricalPost.profile_id == self.profile_id,
                HistoricalPost.content_hash == digest,
            ).limit(1)
        )
        return historical_result.scalar_one_or_none() is not None

    async def _generate_with_gemini(
        self,
        *,
        profile: UserProfile,
        title: str,
        topic: str,
        pillar: str,
        objective: str,
        evidence: list[dict] | None = None,
        feedback: str | None = None,
        current_draft: str | None = None,
        brand_context: dict | None = None,
    ) -> dict:
        service = ModelRouterService()
        if brand_context is None:
            brand_context = await BrandIntelligenceService(self.session).generation_context(profile.id, query=f"{topic} {objective}".strip())
        return await service.create_post(
            profile={
                "name": profile.display_name,
                "title": profile.professional_title,
                "industry": profile.industry,
                "experience_years": profile.experience_years,
                "tone": profile.tone,
                "brand_intelligence": brand_context,
            },
            topic=topic,
            pillar=pillar,
            objective=objective,
            evidence=evidence or [],
            voice=await self._voice(),
            feedback=feedback,
            current_draft=current_draft,
        )

    async def _create_candidate(
        self,
        *,
        title: str,
        topic: str,
        pillar: str,
        objective: str,
        trigger: str,
        evidence: list[dict] | None = None,
    ) -> int | None:
        if await self._is_duplicate_topic(topic):
            return None

        profile = await self._profile()
        # Do not produce generic drafts. Every autonomous draft must be grounded
        # in the user's initialized Brand DNA and historical content.
        brand_context = await BrandIntelligenceService(self.session).generation_context(profile.id, query=f"{topic} {objective}".strip())

        generated = await self._generate_with_gemini(
            profile=profile,
            title=title,
            topic=topic,
            pillar=pillar,
            objective=objective,
            evidence=evidence or [],
            brand_context=brand_context,
        )

        if generated:
            final_title = str(generated.get("title") or title)[:200]
            body = str(generated.get("body") or "").strip()
            angle = str(generated.get("angle") or "").strip()
            claims = generated.get("claims") or []
            confidence = str(generated.get("confidence") or "medium")
        else:
            final_title = title
            angle = "Focus on the practical tradeoffs behind the topic."
            claims = []
            confidence = "low"
            body = (
                f"{title}\n\n"
                f"A practical way to think about {topic.lower()} is to start with the "
                f"business problem, make the workflow explicit, and separate assumptions "
                f"from evidence.\n\n"
                f"Three questions are useful:\n"
                f"1. What is the actual bottleneck?\n"
                f"2. Which part can be standardized or automated safely?\n"
                f"3. What should remain under human review?\n\n"
                f"The useful takeaway is not to automate everything. It is to design a "
                f"system where automation handles repeatable work and people retain "
                f"control over decisions that carry meaningful risk."
            )

        if not body:
            raise ValueError("Gemini did not produce a usable draft.")

        guard = run_content_guards(body)
        if guard.passed and await self._is_duplicate_body(body):
            return None

        item = ContentItem(
            profile_id=profile.id,
            title=final_title,
            topic=topic,
            pillar=pillar,
            status="AWAITING_APPROVAL" if guard.passed else "EDIT_REQUIRED",
        )
        self.session.add(item)
        await self.session.flush()

        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        version = ContentVersion(
            content_id=item.id,
            body=body,
            content_hash=digest,
            version_number=1,
        )
        self.session.add(version)
        await self.session.flush()

        metadata = {
            "trigger": trigger,
            "objective": objective,
            "angle": angle,
            "claims": claims,
            "confidence": confidence,
            "generator": "openrouter_groq_router" if generated else "deterministic_fallback",
        }

        if guard.passed:
            approval = await ApprovalService(self.session).request(version)
            self.session.add(
                AuditLog(
                    event_type="AGENT_CANDIDATE_CREATED",
                    actor="agent-orchestrator",
                    payload=json.dumps(
                        {
                            "approval": approval.id,
                            "content": item.id,
                            "topic": topic,
                            "metadata": metadata,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        else:
            self.session.add(
                AuditLog(
                    event_type="AGENT_CANDIDATE_BLOCKED",
                    actor="agent-orchestrator",
                    payload=json.dumps(
                        {
                            "content": item.id,
                            "topic": topic,
                            "issues": guard.issues,
                            "metadata": metadata,
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        await self.session.commit()
        return item.id

    async def run_discovery(self, trigger: str = "scheduled_daily") -> dict:
        profile = await self._profile()
        opportunities = await ResearchService(self.session).research_and_rank(profile_id=profile.id, candidate_limit=8)

        created: list[int] = []
        selected = opportunities[:3]
        for opportunity in selected:
            evidence = [{
                "claim": opportunity.get("evidence", {}).get("summary", ""),
                "why_now": opportunity.get("evidence", {}).get("why_now", ""),
                "sources": opportunity.get("sources", []),
            }]
            item_id = await self._create_candidate(
                title=opportunity["title"],
                topic=opportunity["topic"],
                pillar=opportunity["pillar"],
                objective=opportunity["objective"],
                trigger=trigger,
                evidence=evidence,
            )
            if item_id is not None:
                created.append(item_id)

        return {
            "mode": "discovery",
            "trigger": trigger,
            "opportunities_found": len(opportunities),
            "selected_opportunities": selected,
            "created_content_ids": created,
            "created_count": len(created),
        }

    async def run_calendar(self, trigger: str = "scheduled_calendar") -> dict:
        profile = await self._profile()
        opportunities = await ResearchService(self.session).research_and_rank(profile_id=profile.id, candidate_limit=6)

        created: list[int] = []
        for opportunity in opportunities[:2]:
            evidence = [{
                "claim": opportunity.get("evidence", {}).get("summary", ""),
                "why_now": opportunity.get("evidence", {}).get("why_now", ""),
                "sources": opportunity.get("sources", []),
            }]
            item_id = await self._create_candidate(
                title=opportunity["title"],
                topic=opportunity["topic"],
                pillar=opportunity["pillar"],
                objective=opportunity["objective"],
                trigger=trigger,
                evidence=evidence,
            )
            if item_id is not None:
                created.append(item_id)

        return {
            "mode": "calendar",
            "trigger": trigger,
            "opportunities_found": len(opportunities),
            "created_content_ids": created,
            "created_count": len(created),
        }

    async def run_manual_content_generation(self, trigger: str = "manual_generate_content") -> dict:
        """Generate a fresh draft without making live research a prerequisite.

        Manual content generation is intentionally independent from the live
        research feed. Research can enrich opportunities, but a user clicking
        Generate Content should still receive a draft from their Brand DNA
        when the public-news feed or research provider is unavailable.
        """
        profile = await self._profile()
        brand = BrandIntelligenceService(self.session)
        positioning = profile.professional_title or profile.industry or "professional expertise"
        context = await brand.generation_context(profile.id, query=f"{positioning} fresh practical perspective".strip())
        historical = await brand.get_posts(profile.id, limit=5)

        # Build a deterministic, brand-grounded topic seed from persisted
        # positioning and recent source posts. The LLM then turns it into the
        # actual post; no unsupported personal facts are introduced.
        positioning = profile.professional_title or profile.industry or "professional expertise"
        recent_topics = []
        for post in historical:
            text = (post.body or "").strip().replace("\n", " ")
            if text:
                recent_topics.append(text[:220])

        topic = f"{positioning}, a fresh practical perspective"
        title = "A practical perspective from your work"
        avoid_text = "; ".join(recent_topics[:8]) or "No prior post topics are available."
        objective = (
            "Generate a fresh LinkedIn post grounded in the user's Brand DNA and distinct from saved historical posts. "
            "Avoid repeating the following recent post excerpts or angles: " + avoid_text
        )

        generated = await self._generate_with_gemini(
            profile=profile,
            title=title,
            topic=topic,
            pillar="Professional insights",
            objective=objective,
            evidence=[],
            feedback=None,
            brand_context=context,
        )

        if not generated:
            raise ValueError("The configured content model did not return a usable draft.")

        final_title = str(generated.get("title") or title)[:200]
        body = normalize_human_style(str(generated.get("body") or ""))
        if not body:
            raise ValueError("The configured content model did not return a usable draft.")

        guard = run_content_guards(body)
        duplicate_blocked = guard.passed and await self._is_duplicate_body(body)
        if duplicate_blocked:
            return {
                "mode": "manual_content",
                "trigger": trigger,
                "created_content_ids": [],
                "created_count": 0,
                "approval_queued": False,
                "blocked_by_guardrails": False,
                "duplicate_blocked": True,
            }

        item = ContentItem(
            profile_id=profile.id,
            title=final_title,
            topic=topic[:500],
            pillar="Professional insights",
            status="AWAITING_APPROVAL" if guard.passed else "EDIT_REQUIRED",
        )
        self.session.add(item)
        await self.session.flush()

        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        version = ContentVersion(
            content_id=item.id,
            body=body,
            content_hash=digest,
            version_number=1,
        )
        self.session.add(version)
        await self.session.flush()

        metadata = {
            "trigger": trigger,
            "objective": objective,
            "angle": generated.get("angle") or "",
            "claims": generated.get("claims") or [],
            "confidence": generated.get("confidence") or "medium",
            "generator": "openrouter_groq_router",
            "research_dependency": False,
            "blocked_by_guardrails": not guard.passed,
        }

        approval_queued = False
        if guard.passed:
            approval = await ApprovalService(self.session).request(version)
            approval_queued = True
            self.session.add(
                AuditLog(
                    event_type="AGENT_CANDIDATE_CREATED",
                    actor="agent-orchestrator",
                    payload=json.dumps(
                        {"approval": approval.id, "content": item.id, "topic": topic, "metadata": metadata},
                        ensure_ascii=False,
                    ),
                )
            )
        else:
            self.session.add(
                AuditLog(
                    event_type="AGENT_CANDIDATE_BLOCKED",
                    actor="agent-orchestrator",
                    payload=json.dumps(
                        {"content": item.id, "topic": topic, "issues": guard.issues, "metadata": metadata},
                        ensure_ascii=False,
                    ),
                )
            )

        await self.session.commit()
        return {
            "mode": "manual_content",
            "trigger": trigger,
            "created_content_ids": [item.id],
            "created_count": 1,
            "content_id": item.id,
            "title": final_title,
            "approval_queued": approval_queued,
            "blocked_by_guardrails": not guard.passed,
        }

    async def run_event(self, event_type: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        profile = await self._profile()
        requested_topic = str(payload.get("topic") or "").strip() or None

        opportunities = await ResearchService(self.session).research_and_rank(
            profile_id=profile.id,
            requested_topic=requested_topic,
            candidate_limit=5,
        )
        selected = opportunities[0] if opportunities else None
        if selected is None:
            raise ValueError("Research did not find a sufficiently relevant, evidence-backed opportunity.")

        evidence = [{
            "claim": selected.get("evidence", {}).get("summary", ""),
            "why_now": selected.get("evidence", {}).get("why_now", ""),
            "sources": selected.get("sources", []),
        }]
        item_id = await self._create_candidate(
            title=selected["title"],
            topic=selected["topic"],
            pillar=selected["pillar"],
            objective=selected["objective"],
            trigger=f"event:{event_type}",
            evidence=evidence,
        )
        return {
            "mode": "event",
            "event_type": event_type,
            "selected_opportunity": selected,
            "created_content_ids": [item_id] if item_id else [],
            "created_count": 1 if item_id else 0,
        }
