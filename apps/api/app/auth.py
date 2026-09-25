from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_session
from app.services.auth_service import AppUser, AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_user(request: Request, credentials: HTTPAuthorizationCredentials | None, session: AsyncSession) -> AppUser | None:
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
        user = await AuthService.get_user_from_token(session, token)
        if user:
            return user

    header_role = request.headers.get("x-user-role")
    if header_role and not settings.is_production:
        normalized = header_role.strip().lower()
        if normalized in {"owner", "admin", "reviewer", "user"}:
            return AppUser(id=normalized, email=f"{normalized}@local.test", role=normalized)

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            user = await AuthService.get_user_from_token(session, token)
            if user:
                return user

    return None


def require_roles(*allowed_roles: str):
    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        session: AsyncSession = Depends(get_session),
    ) -> AppUser:
        user = await _resolve_user(request, credentials, session)

        if user is None:
            if settings.is_production:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return AppUser(id="owner", email="owner@local.test", role="owner")

        role = user.role.lower()
        if role not in {"owner", "admin", "reviewer", "user"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions",
            )

        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions",
            )

        return user

    return dependency
