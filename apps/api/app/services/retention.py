from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import ApprovalRequest, ContentItem, ContentVersion, FeedbackEntry, HistoricalPost, LearningEvent


class RetentionService:
    """Compact raw content while preserving workflow state, hashes and learning memory.

    The retention policy deliberately keeps the latest published content intact.
    Older published content remains represented by lightweight rows and hashes so
    duplicate detection and analytics remain durable, while the raw post body is
    removed from operational/history tables after it has already been learned.
    """

    async def compact(self, session: AsyncSession) -> dict[str, int]:
        published_trimmed = await self._trim_published_history(session)
        workflow_trimmed = await self._trim_old_content_versions(session)
        learning_events_deleted = await self._delete_processed_learning_events(session)
        feedback_payloads_trimmed = await self._trim_old_feedback_payloads(session)
        await session.commit()
        return {
            "published_history_bodies_trimmed": published_trimmed,
            "workflow_bodies_trimmed": workflow_trimmed,
            "processed_learning_events_deleted": learning_events_deleted,
            "old_feedback_payloads_trimmed": feedback_payloads_trimmed,
        }

    async def _trim_published_history(self, session: AsyncSession) -> int:
        pending_result = await session.execute(
            select(LearningEvent.source_id).where(
                LearningEvent.event_type == "CONTENT_PUBLISHED",
                LearningEvent.status != "PROCESSED",
            )
        )
        pending_publish_ids = {str(value) for (value,) in pending_result.all() if value is not None}

        result = await session.execute(
            select(HistoricalPost.id, HistoricalPost.profile_id, HistoricalPost.metadata_json)
            .where(HistoricalPost.source == "brand_os_publish")
            .order_by(HistoricalPost.profile_id.asc(), HistoricalPost.published_at.desc().nullslast(), HistoricalPost.id.desc())
        )
        keep_count: dict[int, int] = {}
        trim_ids: list[int] = []
        for post_id, profile_id, metadata_json in result.all():
            profile_id = int(profile_id)
            current = keep_count.get(profile_id, 0)
            if current < settings.published_post_retention_limit:
                keep_count[profile_id] = current + 1
            else:
                try:
                    approval_id = str(json.loads(metadata_json or "{}").get("approval_id") or "")
                except (TypeError, ValueError):
                    approval_id = ""
                if not approval_id or approval_id in pending_publish_ids:
                    continue
                trim_ids.append(int(post_id))

        for start in range(0, len(trim_ids), 500):
            batch = trim_ids[start:start + 500]
            if batch:
                await session.execute(
                    update(HistoricalPost)
                    .where(HistoricalPost.id.in_(batch))
                    .where(HistoricalPost.body.is_not(None))
                    .values(body=None)
                )
        return len(trim_ids)

    async def _trim_old_content_versions(self, session: AsyncSession) -> int:
        pending_result = await session.execute(
            select(LearningEvent.source_id).where(
                LearningEvent.event_type == "CONTENT_PUBLISHED",
                LearningEvent.status != "PROCESSED",
            )
        )
        pending_publish_ids = {str(value) for (value,) in pending_result.all() if value is not None}

        result = await session.execute(
            select(
                ApprovalRequest.id,
                ApprovalRequest.content_version_id,
                ContentItem.profile_id,
            )
            .join(ContentVersion, ContentVersion.id == ApprovalRequest.content_version_id)
            .join(ContentItem, ContentItem.id == ContentVersion.content_id)
            .where(ApprovalRequest.status == "EXECUTED")
            .order_by(
                ContentItem.profile_id.asc(),
                ApprovalRequest.approved_at.desc().nullslast(),
                ApprovalRequest.id.desc(),
            )
        )
        keep_count: dict[int, int] = {}
        trim_version_ids: list[int] = []
        trim_approval_ids: list[int] = []
        for approval_id, version_id, profile_id in result.all():
            profile_id = int(profile_id)
            current = keep_count.get(profile_id, 0)
            if current < settings.published_post_retention_limit:
                keep_count[profile_id] = current + 1
            else:
                if str(approval_id) in pending_publish_ids:
                    continue
                trim_version_ids.append(int(version_id))
                trim_approval_ids.append(int(approval_id))

        for start in range(0, len(trim_version_ids), 500):
            batch = trim_version_ids[start:start + 500]
            if batch:
                await session.execute(
                    update(ContentVersion)
                    .where(ContentVersion.id.in_(batch))
                    .where(ContentVersion.body != "")
                    .values(body="")
                )
                await session.execute(
                    update(ApprovalRequest)
                    .where(ApprovalRequest.id.in_(trim_approval_ids[start:start + 500]))
                    .where(ApprovalRequest.edited_body.is_not(None))
                    .values(edited_body=None)
                )
        return len(trim_version_ids)

    async def _delete_processed_learning_events(self, session: AsyncSession) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.learning_event_retention_days)
        result = await session.execute(
            delete(LearningEvent).where(
                LearningEvent.status == "PROCESSED",
                LearningEvent.processed_at.is_not(None),
                LearningEvent.processed_at < cutoff,
            )
        )
        return int(result.rowcount or 0)

    async def _trim_old_feedback_payloads(self, session: AsyncSession) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.learning_event_retention_days)
        result = await session.execute(
            update(FeedbackEntry)
            .where(
                FeedbackEntry.created_at < cutoff,
                FeedbackEntry.payload.is_not(None),
            )
            .values(payload=None)
        )
        return int(result.rowcount or 0)
