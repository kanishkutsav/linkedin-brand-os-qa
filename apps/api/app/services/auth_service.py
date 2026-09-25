from dataclasses import dataclass
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuthSession, AuthUser, UserProfile


@dataclass
class AppUser:
    id: str
    email: str
    role: str
    display_name: str | None = None
    linkedin_url: str | None = None


class AuthService:
    """Supabase/Postgres-backed auth facade.

    The auth_users table is the single source of truth for application access.
    To whitelist a new user, add their normalized email to auth_users with
    is_whitelisted=true and is_active=true. No code change is required.
    """

    @staticmethod
    def normalize_email(value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().lower()

    @staticmethod
    def normalize_linkedin_url(value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().rstrip("/").lower()

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def get_whitelisted_user(
        session: AsyncSession,
        email: str | None,
        *,
        linkedin_url: str | None = None,
        require_linkedin_match: bool = False,
    ) -> AppUser | None:
        normalized_email = AuthService.normalize_email(email)
        if not normalized_email:
            return None

        result = await session.execute(
            select(AuthUser).where(
                AuthUser.email == normalized_email,
                AuthUser.is_active.is_(True),
                AuthUser.is_whitelisted.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None

        # If a LinkedIn URL is stored for an existing user, verify it when the
        # caller explicitly requests identity matching. New whitelist entries
        # only need an email; their LinkedIn identity is learned during OAuth.
        normalized_linkedin_url = AuthService.normalize_linkedin_url(linkedin_url)
        stored_linkedin_url = AuthService.normalize_linkedin_url(user.linkedin_url)
        if require_linkedin_match and stored_linkedin_url:
            if not normalized_linkedin_url or normalized_linkedin_url != stored_linkedin_url:
                return None

        return AppUser(
            id=str(user.id),
            email=user.email,
            role=user.role,
            display_name=user.display_name,
            linkedin_url=user.linkedin_url,
        )

    @staticmethod
    async def validate_linkedin_identity(
        session: AsyncSession,
        email: str | None,
        linkedin_url: str | None,
    ) -> AppUser | None:
        normalized_email = AuthService.normalize_email(email)
        if not normalized_email:
            return None

        result = await session.execute(
            select(AuthUser).where(AuthUser.email == normalized_email)
        )
        user = result.scalar_one_or_none()

        if user is None or not user.is_active or not user.is_whitelisted:
            return None

        normalized_linkedin_url = AuthService.normalize_linkedin_url(linkedin_url)
        stored_linkedin_url = AuthService.normalize_linkedin_url(user.linkedin_url)

        # A stored LinkedIn URL is an optional additional identity check.
        # For new whitelist entries, email alone is sufficient.
        if stored_linkedin_url and normalized_linkedin_url != stored_linkedin_url:
            return None

        if normalized_linkedin_url and not stored_linkedin_url:
            user.linkedin_url = normalized_linkedin_url

        if not user.display_name:
            user.display_name = user.email.split("@", 1)[0]

        await session.commit()
        await session.refresh(user)

        return AppUser(
            id=str(user.id),
            email=user.email,
            role=user.role,
            display_name=user.display_name,
            linkedin_url=user.linkedin_url,
        )

    @staticmethod
    async def get_or_create_profile(session: AsyncSession, user: AppUser) -> UserProfile:
        """Return the profile owned by the authenticated application user.

        Profile IDs intentionally mirror auth_users IDs so every user has a stable,
        server-side ownership boundary without relying on browser state.
        """
        profile_id = int(user.id)
        profile = await session.get(UserProfile, profile_id)
        if profile is None:
            profile = UserProfile(
                id=profile_id,
                display_name=user.display_name or user.email.split("@", 1)[0],
                role=user.role or "user",
            )
            session.add(profile)
            await session.flush()
        elif user.display_name and profile.display_name != user.display_name:
            profile.display_name = user.display_name
        return profile

    @staticmethod
    async def create_session(session: AsyncSession, user: AppUser) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = AuthService.hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        existing = await session.execute(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        current = existing.scalar_one_or_none()
        if current is not None:
            current.expires_at = expires_at
            await session.commit()
            return token

        user_row_result = await session.execute(
            select(AuthUser).where(AuthUser.email == user.email)
        )
        user_row = user_row_result.scalar_one_or_none()
        if user_row is None:
            raise ValueError("Authenticated user is not present in the whitelist.")

        if not user_row.is_active or not user_row.is_whitelisted:
            raise ValueError("Authenticated user is not active or whitelisted.")

        session_row = AuthSession(
            user_id=user_row.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(session_row)
        await session.commit()
        return token

    @staticmethod
    async def get_user_from_token(
        session: AsyncSession,
        token: str | None,
    ) -> AppUser | None:
        if not token:
            return None

        normalized = token.strip()
        if not normalized:
            return None

        token_hash = AuthService.hash_token(normalized)
        result = await session.execute(
            select(AuthSession, AuthUser)
            .join(AuthUser, AuthSession.user_id == AuthUser.id)
            .where(AuthSession.token_hash == token_hash)
            .where(AuthSession.expires_at > datetime.now(timezone.utc))
            .where(AuthUser.is_active.is_(True))
            .where(AuthUser.is_whitelisted.is_(True))
        )
        row = result.first()
        if row is None:
            return None

        session_row, user_row = row
        if session_row is None or user_row is None:
            return None

        return AppUser(
            id=str(user_row.id),
            email=user_row.email,
            role=user_row.role,
            display_name=user_row.display_name,
            linkedin_url=user_row.linkedin_url,
        )
