import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, File, UploadFile, Header
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.research import ResearchService
from app.agents.orchestrator import AgentOrchestrator
from app.agents.strategy import ContentStrategyService
from app.agents.voice import VoiceProfileBuilder
from app.auth import require_roles
from app.core.config import settings
from app.db.database import engine, get_session, SessionLocal
from app.services.agent_scheduler import AgentScheduler
from app.jobs.scheduled_jobs import ScheduledJobs
from app.jobs.durable_queue import enqueue_job
from app.services.brand_intelligence import BrandIntelligenceService
from app.services.brand_learning import BrandLearningService
from app.guards.guardrails import normalize_human_style, run_content_guards
from app.integrations.linkedin import OfficialLinkedInAdapter
from app.models.base import Base
from app.models.models import ApprovalRequest, ContentItem, ContentVersion, HistoricalPost, LinkedInConnection, UserProfile, VoiceMemory, AgentRun, AuthSession
from app.services.approval import ApprovalService
from app.services.auth_service import AppUser, AuthService
from app.services.linkedin_oauth import build_authorization_url, exchange_code, handle_callback
from app.services.linkedin_analytics import LinkedInAnalyticsService
from app.services.gemini_service import ModelRouterService

logger = logging.getLogger(__name__)


def _resolve_sqlite_path() -> str | None:
    database_url = settings.database_url
    if not database_url.startswith("sqlite"):
        return None

    normalized = database_url.replace("sqlite+aiosqlite:///", "", 1).replace("sqlite:///", "", 1)
    normalized = normalized.replace("sqlite://", "", 1)
    if not normalized:
        return None
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith(".\\"):
        normalized = normalized[2:]
    return os.path.abspath(normalized)


def _database_needs_reset() -> bool:
    absolute_path = _resolve_sqlite_path()
    if absolute_path is None or not os.path.exists(absolute_path):
        return False

    required_tables = {
        "user_profiles",
        "voice_memory",
        "content_items",
        "content_versions",
        "approval_requests",
        "feedback_entries",
        "audit_logs",
        "system_flags",
    }

    try:
        with sqlite3.connect(absolute_path) as conn:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            return not required_tables.issubset(existing)
    except sqlite3.Error:
        return False


agent_scheduler = AgentScheduler(SessionLocal)


@asynccontextmanager
async def lifespan(app: FastAPI):
    absolute_path = _resolve_sqlite_path()
    if _database_needs_reset() and absolute_path and os.path.exists(absolute_path):
        os.remove(absolute_path)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(lambda sync_conn: {
            column["name"] for column in inspect(sync_conn).get_columns("user_profiles")
        })
        if "experience_years" not in columns:
            await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN experience_years FLOAT"))

        approval_columns = await conn.run_sync(lambda sync_conn: {
            column["name"] for column in inspect(sync_conn).get_columns("approval_requests")
        })
        if "published_image_urn" not in approval_columns:
            await conn.execute(text("ALTER TABLE approval_requests ADD COLUMN published_image_urn VARCHAR(255)"))

        # Drop the retired self-declared audience, goals and positioning fields.
        # They are no longer part of Brand DNA and must not remain as an
        # alternative source of user context.
        retired_columns = {
            "audience",
            "goals",
            "brand_positioning",
        }
        for column_name in retired_columns.intersection(columns):
            try:
                await conn.execute(text(f'ALTER TABLE user_profiles DROP COLUMN "{column_name}"'))
            except Exception:
                # Older SQLite builds may not support DROP COLUMN. The ORM
                # schema and application queries already ignore these fields,
                # so a deployment on such a database remains isolated and safe.
                logger.warning("Could not drop retired user_profiles.%s", column_name)

        brand_memory_columns = await conn.run_sync(lambda sync_conn: {
            column["name"] for column in inspect(sync_conn).get_columns("brand_memory")
        })
        if "audience_json" in brand_memory_columns:
            try:
                await conn.execute(text('ALTER TABLE brand_memory DROP COLUMN "audience_json"'))
            except Exception:
                logger.warning("Could not drop retired brand_memory.audience_json")
    # Vercel functions are ephemeral. Supabase Cron owns scheduled execution
    # in the Vercel deployment, so never start an in-process scheduler there.
    vercel_runtime = os.getenv("VERCEL", "").lower() == "1"
    if settings.agent_in_process_schedule_enabled and not vercel_runtime:
        agent_scheduler.start()
    yield
    if settings.agent_in_process_schedule_enabled and not vercel_runtime:
        await agent_scheduler.stop()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    topic: str
    pillar: str = "Expertise"
    body: str


class ImproveContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    topic: str = ""
    body: str
    language: str | None = None


class StrategyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = None
    sources: list[dict[str, str]] = Field(default_factory=list)


class LearningThoughtRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    topic: str | None = None
    title: str | None = None


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_examples: list[str]


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = "User"
    professional_title: str
    industry: str
    tone: str
    experience_years: float = Field(ge=0, le=100)


class BrandOnboardingPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    published_at: str | None = None
    external_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class BrandOnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = "User"
    professional_title: str
    industry: str
    tone: str
    experience_years: float = Field(ge=0, le=100)
    posts: list[BrandOnboardingPost] = Field(default_factory=list)


class ApprovalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edited_body: str
    reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class LinkedInExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    oauth_nonce: str | None = None


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "external_actions": "approval_required",
        "agent_enabled": settings.agent_enabled,
        "agent_modes": ["daily_discovery", "event_driven", "scheduled_calendar"],
    }


@app.get("/health/ready")
async def readiness() -> dict[str, object]:
    """Dependency-aware readiness probe for controlled Render fallback/cutover."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "ok",
            "environment": settings.environment,
        }
    except Exception:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Service dependencies are not ready")


@app.get("/api/auth/linkedin/start")
async def linkedin_oauth_start(
    browser_nonce: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if browser_nonce and len(browser_nonce) > 200:
        raise HTTPException(status_code=400, detail="Invalid OAuth browser nonce.")
    url, state = await build_authorization_url(session, browser_nonce=browser_nonce)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key="brand_os_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=bool(settings.environment == "production"),
        samesite="lax",
        path="/api",
    )
    return response


@app.get("/api/auth/linkedin/callback")
async def linkedin_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if error:
        response = RedirectResponse(
            url=f"{(settings.frontend_url or 'http://localhost:3000').rstrip('/')}/?linkedin_error=authorization_denied",
            status_code=302,
        )
        response.delete_cookie("brand_os_oauth_state", path="/api")
        return response
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing LinkedIn OAuth code or state.")

    expected_state = request.cookies.get("brand_os_oauth_state") if request else None
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid LinkedIn OAuth state.")

    browser_nonce = state.split(".", 1)[0] if "." in state else None
    exchange = await handle_callback(session, code, state)
    frontend = (settings.frontend_url or "http://localhost:3000").rstrip("/")
    nonce_suffix = f"&oauth_nonce={browser_nonce}" if browser_nonce else ""
    response = RedirectResponse(url=f"{frontend}/?linkedin_code={exchange}{nonce_suffix}", status_code=302)
    # Keep the short-lived state cookie until the browser exchanges the one-time
    # code. This lets the server bind the exchange to the browser that started OAuth.
    return response


@app.post("/api/auth/linkedin/exchange")
async def linkedin_oauth_exchange(
    request: Request,
    req: LinkedInExchangeRequest,
    session: AsyncSession = Depends(get_session),
):
    browser_nonce = request.cookies.get("brand_os_oauth_state", "").split(".", 1)[0]
    if not browser_nonce:
        raise HTTPException(status_code=400, detail="LinkedIn exchange is not bound to the initiating browser.")
    # The frontend sends the nonce it received in the callback URL. The cookie
    # contains the exact state generated for the same browser.
    oauth_nonce = req.oauth_nonce
    if not oauth_nonce or oauth_nonce != browser_nonce:
        raise HTTPException(status_code=400, detail="LinkedIn exchange browser verification failed.")
    result = await exchange_code(session, req.code)
    response = JSONResponse(result)
    response.delete_cookie("brand_os_oauth_state", path="/api")
    return response


@app.get("/api/linkedin/status")
async def linkedin_status(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    session: AsyncSession = Depends(get_session),
):
    user = await AuthService.get_user_from_token(session, credentials.credentials if credentials else None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await session.execute(
        select(LinkedInConnection).where(LinkedInConnection.user_id == int(user.id))
    )
    connection = result.scalar_one_or_none()
    return {
        "connected": connection is not None,
        "name": connection.linkedin_name if connection else None,
        "email": connection.linkedin_email if connection else None,
        "expires_at": connection.token_expires_at if connection else None,
    }


@app.post("/api/auth/linkedin/login")
async def linkedin_login_legacy():
    raise HTTPException(
        status_code=410,
        detail="Legacy LinkedIn login is disabled. Use the official LinkedIn OAuth flow.",
    )


@app.get("/api/auth/me")
async def auth_me(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    session: AsyncSession = Depends(get_session),
):
    token = credentials.credentials if credentials else None
    if token is None:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    user = await AuthService.get_user_from_token(session, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
        "linkedin_url": user.linkedin_url,
    }


@app.post("/api/auth/logout")
async def auth_logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    session: AsyncSession = Depends(get_session),
):
    token = credentials.credentials if credentials else None
    if token:
        token_hash = AuthService.hash_token(token)
        result = await session.execute(select(AuthSession).where(AuthSession.token_hash == token_hash))
        session_row = result.scalar_one_or_none()
        if session_row is not None:
            await session.delete(session_row)
            await session.commit()
    return {"success": True}

@app.get("/api/profile")
async def get_profile(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    profile = await AuthService.get_or_create_profile(session, current_user)
    await session.commit()
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "professional_title": profile.professional_title,
        "industry": profile.industry,
        "experience_years": profile.experience_years,
        "tone": profile.tone,
        "role": profile.role or "owner",
    }


@app.post("/api/profile")
async def upsert_profile_legacy():
    raise HTTPException(
        status_code=410,
        detail="Use the Brand DNA setup to enter your professional title, industry, desired tone and years of experience.",
    )


@app.get("/api/brand/status")
async def brand_status(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    service = BrandIntelligenceService(session)
    profile = await AuthService.get_or_create_profile(session, current_user)
    await session.commit()
    memory = await service.get_memory(profile.id)
    posts = await service.get_posts(profile.id, limit=100)
    profile_complete = bool(
        profile.professional_title and profile.professional_title.strip()
        and profile.industry and profile.industry.strip()
        and profile.tone and profile.tone.strip()
        and profile.experience_years is not None
    )
    brand_ready = bool(memory and memory.status == "READY" and profile_complete)
    return {
        "status": "READY" if brand_ready else ("NEEDS_INPUT" if memory else "NOT_INITIALIZED"),
        "ready": brand_ready,
        "source_post_count": memory.source_post_count if memory else len(posts),
        "current_post_count": len(posts),
        "summary": memory.summary if memory else None,
        "continuous_learning": True,
        "historical_import_optional": True,
        "last_updated": memory.updated_at if memory else None,
        "profile": {
            "display_name": profile.display_name if profile else "User",
            "professional_title": profile.professional_title if profile else None,
            "industry": profile.industry if profile else None,
            "experience_years": profile.experience_years if profile else None,
            "tone": profile.tone if profile else None,
        },
        "source_posts": [
            {"id": post.id, "body": post.body, "published_at": post.published_at, "source": post.source}
            for post in posts
            if post.source == "user_import"
        ][:10],
    }


@app.get("/api/brand/memory")
async def brand_memory(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    service = BrandIntelligenceService(session)
    profile = await AuthService.get_or_create_profile(session, current_user)
    return service.serialize(await service.get_memory(profile.id))


@app.get("/api/brand/source-posts")
async def brand_source_posts(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    profile = await AuthService.get_or_create_profile(session, current_user)
    result = await session.execute(
        select(HistoricalPost)
        .where(HistoricalPost.profile_id == int(profile.id), HistoricalPost.source == "user_import")
        .order_by(HistoricalPost.created_at.asc())
        .limit(10)
    )
    return {"posts": [
        {"id": post.id, "body": post.body, "published_at": post.published_at, "source": post.source}
        for post in result.scalars().all()
    ]}


@app.post("/api/brand/onboard")
async def brand_onboard(
    req: BrandOnboardingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "user")),
):

    if len(req.posts) < 3:
        raise HTTPException(status_code=400, detail="At least 3 previous posts are required to build Brand Intelligence.")
    if len(req.posts) > 10:
        raise HTTPException(status_code=400, detail="You can import a maximum of 10 previous posts.")
    if any(not post.body.strip() for post in req.posts):
        raise HTTPException(status_code=400, detail="Every imported post must contain content.")

    profile = await AuthService.get_or_create_profile(session, current_user)

    # Brand DNA is fully user-controlled. LinkedIn is used only for account
    # connection and publishing, never as the source of Brand DNA profile fields.
    profile.display_name = req.display_name.strip()[:150] or current_user.display_name or profile.display_name or "User"
    profile.professional_title = req.professional_title.strip()[:200]
    profile.industry = req.industry.strip()[:200]
    profile.experience_years = float(req.experience_years)
    profile.tone = req.tone.strip()[:200]
    profile.role = profile.role or current_user.role or "user"
    await session.commit()

    # The editable 3–10 source posts are a current snapshot. Replace only the
    # user-imported set on refresh; keep Brand OS published posts as durable evidence.
    await session.execute(
        delete(HistoricalPost).where(
            HistoricalPost.profile_id == int(profile.id),
            HistoricalPost.source == "user_import",
        )
    )
    await session.commit()

    service = BrandIntelligenceService(session)
    import_result = await service.import_posts(
        [
            {
                "body": post.body,
                "published_at": post.published_at,
                "external_id": post.external_id,
                "metadata": post.metadata,
                "source": "user_import",
            }
            for post in req.posts
        ],
        profile_id=profile.id,
    )
    try:
        memory = await service.analyze(profile.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Brand onboarding analysis failed: %s", exc)
        raise HTTPException(status_code=502, detail="Brand analysis failed. Neither configured LLM provider returned a usable analysis. Please try again; your imported posts were saved.") from exc

    return {"import": import_result, "brand_memory": memory}


@app.post("/api/brand/initialize")
async def brand_initialize_legacy():
    raise HTTPException(
        status_code=410,
        detail="Automatic Brand DNA initialization is disabled. Enter your Brand DNA details and use the onboarding form.",
    )


@app.post("/api/brand/rebuild")
async def rebuild_brand(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "user")),
):
    profile = await AuthService.get_or_create_profile(session, current_user)
    service = BrandIntelligenceService(session)
    try:
        return await service.analyze(profile.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Brand analysis failed. Check the configured LLM providers and try again.") from exc


@app.get("/api/dashboard/approvals")
async def dashboard_approvals(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    approval_service = ApprovalService(session)
    approvals = await approval_service.list_dashboard(int(current_user.id))
    counts = await approval_service.dashboard_counts(int(current_user.id))
    records = []
    for item in approvals:
        version = await session.get(ContentVersion, item.content_version_id)
        content_item = await session.get(ContentItem, version.content_id) if version else None
        records.append(
            {
                "id": item.id,
                "status": item.status,
                "action_type": item.action_type,
                "reason": item.reason,
                "content": version.body if version else "",
                "title": content_item.title if content_item else "",
                "topic": content_item.topic if content_item else "",
                "approved_at": item.approved_at,
                "created_at": item.created_at,
            }
        )
    return {"pending_approvals": records, "counts": counts}


@app.get("/api/agent/status")
async def agent_status(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.user_id == int(current_user.id))
        .order_by(AgentRun.started_at.desc())
        .limit(10)
    )
    runs = result.scalars().all()
    return {
        "enabled": settings.agent_enabled,
        "modes": {
            "daily_discovery": settings.agent_daily_discovery_enabled,
            "event_driven": True,
            "scheduled_calendar": settings.agent_calendar_enabled,
        },
        "recent_runs": [
            {
                "id": run.id,
                "mode": run.mode,
                "trigger": run.trigger,
                "status": run.status,
                "created_count": run.created_count,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "details": run.details,
            }
            for run in runs
        ],
    }


class AgentEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    payload: dict[str, object] = Field(default_factory=dict)


async def _require_scheduled_job_key(x_brand_os_job_key: str | None = Header(default=None)) -> None:
    expected = settings.scheduled_job_key
    if not expected or not x_brand_os_job_key or not secrets.compare_digest(x_brand_os_job_key, expected):
        raise HTTPException(status_code=401, detail="Invalid scheduled job credentials.")


async def _run_scheduled_job_background(job_name: str) -> None:
    jobs = ScheduledJobs(SessionLocal)
    if job_name in {"discovery", "calendar"}:
        try:
            result = await jobs.run(job_name)
            logger.info("Scheduled %s job completed: %s", job_name, result)
        except Exception:
            logger.exception("Scheduled %s job failed.", job_name)
        return

    async with SessionLocal() as session:
        try:
            result = await jobs.process_retention(session)
            await session.commit()
            logger.info("Scheduled retention job completed: %s", result)
        except Exception:
            await session.rollback()
            logger.exception("Scheduled retention job failed.")




_scheduled_background_tasks: set[asyncio.Task] = set()


def _dispatch_scheduled_job(job_name: str) -> None:
    task = asyncio.create_task(_run_scheduled_job_background(job_name))
    _scheduled_background_tasks.add(task)
    task.add_done_callback(_scheduled_background_tasks.discard)


@app.post("/api/internal/scheduled-jobs/{job_name}")
async def run_scheduled_job(
    job_name: str,
    _: None = Depends(_require_scheduled_job_key),
):
    jobs = ScheduledJobs(SessionLocal)
    if job_name not in {"discovery", "calendar", "retention", "learning"}:
        raise HTTPException(status_code=404, detail="Unknown scheduled job.")

    if job_name == "learning":
        if settings.durable_learning_worker_enabled:
            local_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
            async with SessionLocal() as session:
                job = await enqueue_job(
                    session,
                    job_type="brand_learning_event",
                    payload={"scheduled_date": local_date},
                    idempotency_key=f"scheduled:learning:{local_date}",
                )
                await session.commit()
            return {
                "ok": True,
                "job": job_name,
                "accepted": True,
                "queued": True,
                "job_id": job.id if job else None,
            }

        async with SessionLocal() as session:
            try:
                processed = await jobs.process_learning(session, limit=50)
                await session.commit()
                logger.info("Scheduled learning job completed: processed=%s", processed)
            except Exception:
                await session.rollback()
                logger.exception("Scheduled learning job failed.")
        return

    if settings.durable_scheduled_worker_enabled:
        local_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        async with SessionLocal() as session:
            job = await enqueue_job(
                session,
                job_type=f"scheduled_{job_name}",
                payload={"mode": job_name, "scheduled_date": local_date},
                idempotency_key=f"scheduled:{job_name}:{local_date}",
            )
            await session.commit()
        return {
            "ok": True,
            "job": job_name,
            "accepted": True,
            "queued": True,
            "job_id": job.id if job else None,
        }

    # Safe fallback while the durable worker is disabled. Supabase pg_net gets
    # a fast response while the existing AgentRun/idempotency guards protect
    # the actual scheduled work.
    _dispatch_scheduled_job(job_name)
    return {"ok": True, "job": job_name, "accepted": True, "queued": False}

@app.post("/api/agent/events")
async def trigger_agent_event(
    req: AgentEventRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "user")),
):
    run = AgentRun(user_id=int(current_user.id), mode="event", trigger=f"event:{req.event_type}", status="RUNNING")
    session.add(run)
    await session.flush()
    try:
        orchestrator = AgentOrchestrator(session, int(current_user.id))
        if req.event_type == "manual_generate_content":
            result = await orchestrator.run_manual_content_generation()
        else:
            result = await orchestrator.run_event(req.event_type, req.payload)
        run.status = "SUCCEEDED"
        run.created_count = result["created_count"]
        run.details = str(result)
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return result | {"run_id": run.id}
    except Exception as exc:
        run.status = "FAILED"
        run.details = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=500, detail="Agent event processing failed") from exc


@app.post("/api/strategy/recommend")
async def recommend_strategy(
    req: StrategyRequest,
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    return ContentStrategyService().recommend(req.focus)


@app.post("/api/research/discover")
async def research_discover(
    req: ResearchRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    try:
        opportunities = await ResearchService(session).research_and_rank(
            profile_id=int(current_user.id),
            requested_topic=req.topic,
            candidate_limit=8,
        )
        return {"opportunities": opportunities}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Live research failed: %s", exc)
        raise HTTPException(status_code=502, detail="Live research failed. The public source feed or configured LLM provider was unavailable. Please try again.") from exc


@app.get("/api/research/opportunities")
async def research_opportunities(
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    return {"opportunities": await ResearchService(session).list_opportunities(int(current_user.id), 20)}


@app.post("/api/research/evidence")
async def build_research_evidence(
    req: ResearchRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    return ResearchService(session).build_evidence_pack(
        req.topic or "",
        req.sources,
    )


@app.post("/api/learning/thought")
async def save_learning_thought(req: LearningThoughtRequest, session: AsyncSession = Depends(get_session), current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user"))):
    content = (req.content or "").strip()
    if len(content) < 10:
        raise HTTPException(status_code=400, detail="Write a little more so Brand OS has a useful idea to learn from.")
    if len(content) > 20000:
        raise HTTPException(status_code=400, detail="Thoughts are limited to 20,000 characters.")
    profile = await AuthService.get_or_create_profile(session, current_user)
    event_id = await BrandLearningService(session).record_event(
        profile_id=profile.id,
        event_type="USER_THOUGHT",
        source_type="manual_thought",
        content=content,
        metadata={"topic": (req.topic or "").strip()[:300], "title": (req.title or "").strip()[:200]},
    )
    await session.commit()
    return {"saved": True, "event_id": event_id}


@app.get("/api/learning/status")
async def learning_status(session: AsyncSession = Depends(get_session), current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user"))):
    profile = await AuthService.get_or_create_profile(session, current_user)
    return await BrandLearningService(session).summary(profile.id)


@app.post("/api/voice/profile")
async def build_voice_profile(
    req: VoiceRequest,
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    return VoiceProfileBuilder().learn(req.approved_examples)


@app.post("/api/content/improve")
async def improve_content(
    req: ImproveContentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    if not req.body.strip():
        raise HTTPException(status_code=400, detail="Enter a draft before asking Brand OS to improve it.")
    profile = await AuthService.get_or_create_profile(session, current_user)
    if profile is None:
        raise HTTPException(status_code=400, detail="Complete Brand DNA setup first.")
    if (
        not profile.professional_title
        or not profile.industry
        or not profile.tone
        or profile.experience_years is None
    ):
        raise HTTPException(status_code=400, detail="Complete Professional Title, Industry, Desired Tone and Years of Experience before improving content.")

    brand_service = BrandIntelligenceService(session)
    memory = await brand_service.get_memory(profile.id)
    if memory is None or memory.status != "READY":
        raise HTTPException(status_code=400, detail="Complete Brand Intelligence setup first.")

    # Polishing stays fast and uses the saved Brand DNA plus relevant learning memory.
    brand_context = await brand_service.generation_context(
        profile.id,
        query=f"{req.title} {req.topic}".strip(),
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
        "user_language": req.language,
        "title": req.title,
        "topic": req.topic,
        "draft": req.body,
    }, ensure_ascii=False)

    try:
        improved = await ModelRouterService().generate_json(system, prompt, max_output_tokens=1000)
    except Exception as exc:
        logger.exception("Content improvement failed: %s", exc)
        raise HTTPException(status_code=502, detail="Content improvement failed. Please try again.") from exc

    body = normalize_human_style(str(improved.get("body") or ""))
    if not body:
        raise HTTPException(status_code=502, detail="The configured LLM provider returned an empty polished draft.")
    guard = run_content_guards(body)
    return {
        "title": str(improved.get("title") or req.title).strip(),
        "topic": str(improved.get("topic") or req.topic).strip(),
        "body": body,
        "changes": improved.get("changes") or [],
        "claims": improved.get("claims") or [],
        "guard": guard.__dict__,
    }


@app.get("/api/analytics/overview")
async def analytics_overview(
    session: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    async def count(query):
        return len((await session.execute(query)).scalars().all())

    pipeline = {
        "historical_posts": await count(select(HistoricalPost.id).where(HistoricalPost.profile_id == int(current_user.id))),
        "content_items": await count(select(ContentItem.id).where(ContentItem.profile_id == int(current_user.id))),
        "pending_approval": await count(select(ApprovalRequest.id).join(ContentVersion, ContentVersion.id == ApprovalRequest.content_version_id).join(ContentItem, ContentItem.id == ContentVersion.content_id).where(ContentItem.profile_id == int(current_user.id), ApprovalRequest.status.in_(["PENDING", "EDITED", "REGENERATED"]))),
        "approved": await count(select(ApprovalRequest.id).join(ContentVersion, ContentVersion.id == ApprovalRequest.content_version_id).join(ContentItem, ContentItem.id == ContentVersion.content_id).where(ContentItem.profile_id == int(current_user.id), ApprovalRequest.status == "APPROVED")),
        "published_via_brand_os": await count(select(ApprovalRequest.id).join(ContentVersion, ContentVersion.id == ApprovalRequest.content_version_id).join(ContentItem, ContentItem.id == ContentVersion.content_id).where(ContentItem.profile_id == int(current_user.id), ApprovalRequest.status == "EXECUTED")),
    }

    user = await AuthService.get_user_from_token(session, credentials.credentials if credentials else None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    connection_result = await session.execute(
        select(LinkedInConnection).where(LinkedInConnection.user_id == int(user.id))
    )
    connection = connection_result.scalar_one_or_none()

    if connection is None:
        return {
            "pipeline": pipeline,
            "linkedin_performance": {
                "available": False,
                "authorization_required": True,
                "message": "Connect LinkedIn first. Analytics requires the official Community Management member analytics permissions.",
            },
        }

    if connection.token_expires_at and connection.token_expires_at <= datetime.now(timezone.utc):
        return {
            "pipeline": pipeline,
            "linkedin_performance": {
                "available": False,
                "authorization_required": True,
                "message": "Your LinkedIn connection has expired. Reconnect after analytics permissions are enabled.",
            },
        }

    try:
        linkedin_performance = await LinkedInAnalyticsService(connection.access_token).fetch(days=30)
    except Exception as exc:
        detail = str(exc)
        if "HTTP 401" in detail or "HTTP 403" in detail:
            linkedin_performance = {
                "available": False,
                "authorization_required": True,
                "message": "LinkedIn analytics access is not enabled for this connection yet. The app needs r_member_postAnalytics, and r_member_profileAnalytics if follower trends are enabled. After LinkedIn grants the permissions, reconnect the account so the new consent is included.",
            }
        else:
            logger.exception("LinkedIn analytics failed: %s", exc)
            linkedin_performance = {
                "available": False,
                "authorization_required": False,
                "message": "LinkedIn analytics is temporarily unavailable. Refresh the Analytics section and try again.",
            }

    return {"pipeline": pipeline, "linkedin_performance": linkedin_performance}


@app.post("/api/content/drafts")
async def create_draft(
    req: DraftRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "owner", "reviewer", "user")),
):
    profile = await AuthService.get_or_create_profile(session, current_user)
    if (
        not profile.professional_title
        or not profile.industry
        or not profile.tone
        or profile.experience_years is None
    ):
        raise HTTPException(status_code=400, detail="Complete Professional Title, Industry, Desired Tone and Years of Experience before creating content.")
    brand_memory = await BrandIntelligenceService(session).get_memory(profile.id)
    if brand_memory is None or brand_memory.status != "READY":
        raise HTTPException(status_code=400, detail="Complete Brand DNA setup before creating content.")

    guard = run_content_guards(req.body)
    digest = hashlib.sha256(req.body.strip().encode("utf-8")).hexdigest()
    existing_content = await session.execute(
        select(ContentVersion.id)
        .join(ContentItem, ContentItem.id == ContentVersion.content_id)
        .where(
            ContentItem.profile_id == profile.id,
            ContentVersion.content_hash == digest,
        )
        .limit(1)
    )
    if existing_content.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This exact content already exists in your brand memory.")

    existing_historical = await session.execute(
        select(HistoricalPost.id).where(
            HistoricalPost.profile_id == profile.id,
            HistoricalPost.content_hash == digest,
        ).limit(1)
    )
    if existing_historical.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="This exact content already exists in your brand memory.")

    item = ContentItem(
        profile_id=profile.id,
        title=req.title,
        topic=req.topic,
        pillar=req.pillar,
        status="AWAITING_APPROVAL" if guard.passed else "EDIT_REQUIRED",
    )
    session.add(item)
    await session.flush()

    digest = hashlib.sha256(req.body.encode("utf-8")).hexdigest()
    version = ContentVersion(content_id=item.id, body=req.body, content_hash=digest)
    session.add(version)
    await session.commit()
    await session.refresh(version)

    await BrandLearningService(session).record_event(
        profile_id=profile.id,
        event_type="CONTENT_DRAFT",
        source_type="manual_content",
        source_id=version.id,
        content=req.body,
        metadata={"title": req.title, "topic": req.topic, "guard_passed": guard.passed},
    )
    await session.commit()

    approval = None
    if guard.passed:
        approval = await ApprovalService(session).request(version)

    return {
        "content_id": item.id,
        "version_id": version.id,
        "guard": guard.__dict__,
        "approval_id": approval.id if approval else None,
    }


@app.post("/api/approvals/{approval_id}/approve")
async def approve(
    approval_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    try:
        approval = await ApprovalService(session).approve(approval_id, int(current_user.id))
        return {
            "id": approval.id,
            "status": approval.status,
            "approval_hash": approval.approval_hash,
            "approved_at": approval.approved_at,
            "message": "Approved. The content is now locked and ready for execution.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/approvals/{approval_id}/execute")
async def execute_approval(
    approval_id: int,
    image: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    try:
        connection_result = await session.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == int(current_user.id))
        )
        connection = connection_result.scalar_one_or_none()
        if connection is None:
            raise ValueError("Connect your LinkedIn account before executing the post.")
        if connection.token_expires_at and connection.token_expires_at <= datetime.now(timezone.utc):
            raise ValueError("Your LinkedIn connection has expired. Reconnect LinkedIn before executing the post.")

        image_bytes = None
        image_mime = None
        if image is not None:
            image_mime = (image.content_type or "").lower()
            if image_mime not in {"image/jpeg", "image/png", "image/gif"}:
                raise ValueError("Only JPEG or PNG images are supported.")
            image_bytes = await image.read()
            if not image_bytes:
                raise ValueError("The selected image is empty.")
            if len(image_bytes) > 4 * 1024 * 1024:
                raise ValueError("Image must be 4 MB or smaller.")

        publish_adapter = OfficialLinkedInAdapter(connection.access_token, connection.member_sub)
        publish_result = await ApprovalService(session).execute(
            approval_id,
            publish_adapter,
            int(current_user.id),
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        # Return a durable publication confirmation so the UI can render
        # success without inferring it from a transient HTTP response.
        result = await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        saved_approval = result.scalar_one_or_none()
        return {
            "id": approval_id,
            "status": "EXECUTED" if publish_result.success else "APPROVED",
            "published": publish_result.success,
            "external_id": publish_result.external_id,
            "image_urn": getattr(publish_result, "image_urn", None),
            "published_at": saved_approval.published_at if saved_approval else None,
            "message": publish_result.message,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/approvals/{approval_id}/publication")
async def publication_confirmation(
    approval_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    """Return the durable publication result for a user-owned approval."""
    result = await session.execute(
        select(ApprovalRequest)
        .join(ContentVersion, ContentVersion.id == ApprovalRequest.content_version_id)
        .join(ContentItem, ContentItem.id == ContentVersion.content_id)
        .where(
            ApprovalRequest.id == approval_id,
            ContentItem.profile_id == int(current_user.id),
        )
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {
        "id": approval.id,
        "status": approval.status,
        "published": approval.status == "EXECUTED",
        "external_id": approval.published_external_id,
        "image_urn": approval.published_image_urn,
        "published_at": approval.published_at,
        "message": (
            "Published to LinkedIn."
            if approval.status == "EXECUTED"
            else "This post has not been published to LinkedIn."
        ),
    }


@app.post("/api/approvals/{approval_id}/edit")
async def edit_approval(
    approval_id: int,
    req: ApprovalEditRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    try:
        approval = await ApprovalService(session).edit(approval_id, req.edited_body, req.reason, int(current_user.id))
        return {
            "id": approval.id,
            "status": approval.status,
            "reason": approval.reason,
            "edited_body": approval.edited_body,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/approvals/{approval_id}/reject")
async def reject_approval(
    approval_id: int,
    req: ApprovalDecisionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    try:
        approval = await ApprovalService(session).reject(approval_id, req.reason, int(current_user.id))
        return {
            "id": approval.id,
            "status": approval.status,
            "reason": approval.reason,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/approvals/{approval_id}/regenerate")
async def regenerate_approval(
    approval_id: int,
    req: ApprovalDecisionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: AppUser = Depends(require_roles("admin", "reviewer", "owner", "user")),
):
    try:
        approval = await ApprovalService(session).regenerate(approval_id, req.reason, int(current_user.id))
        return {
            "id": approval.id,
            "status": approval.status,
            "reason": approval.reason,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc