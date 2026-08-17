from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings


class AuthenticatedUser(BaseModel):
    id: UUID
    email: str | None = None
    role: str | None = None
    user_metadata: dict[str, Any] = Field(default_factory=dict)
    app_metadata: dict[str, Any] = Field(default_factory=dict)
    access_token: str = Field(exclude=True, repr=False)


bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized(detail: str = "Invalid or expired access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def validate_access_token(token: str, settings: Settings) -> AuthenticatedUser:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication is not configured on the backend",
        )

    endpoint = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": settings.supabase_anon_key.get_secret_value(),
        "Authorization": f"Bearer {token}",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(endpoint, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication service is unavailable",
        ) from exc

    if response.status_code != status.HTTP_200_OK:
        raise unauthorized()

    try:
        user = AuthenticatedUser.model_validate(
            {**response.json(), "access_token": token},
        )
        return user
    except (ValueError, TypeError) as exc:
        raise unauthorized() from exc


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Authentication required")

    return await validate_access_token(credentials.credentials, settings)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
