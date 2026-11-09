"""
SASAA – FastAPI Dependency Injection
======================================
Dependencies are functions FastAPI runs automatically before a route handler.
They handle cross-cutting concerns like authentication and database sessions.

HOW IT WORKS:
  When a route declares `current_user: User = Depends(get_current_user)`,
  FastAPI calls get_current_user() first. If it raises an HTTPException,
  the route never runs and the client gets a 401 error. If it succeeds,
  the returned User object is passed into the route handler.

  This means authentication logic is written ONCE here, not copied into
  every single route.
"""

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import decode_access_token

# HTTP Bearer scheme – expects: Authorization: Bearer <token>
bearer_scheme = HTTPBearer()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Extract and validate the JWT token from the Authorization header.

    Returns the user's ID (as a string) if the token is valid.
    Raises HTTP 401 if the token is missing, expired, or tampered with.

    This dependency does NOT hit the database — it only validates the token.
    Use get_current_user (below) when you need the full User object.
    """
    token = credentials.credentials

    user_id = decode_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Load the full User record from the database for the authenticated user.

    This is the dependency most protected routes will use.
    Import User model here to avoid circular imports at module load time.

    Raises HTTP 401 if the user no longer exists (e.g. account deleted after
    the token was issued).
    """
    # Import inside function to avoid circular import:
    # models import base, base doesn't import models, dependencies imports models
    from app.models.user import User

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject.",
        )

    result = await db.execute(
        select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or has been deleted.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Like get_current_user but returns None instead of raising 401.
    Used for routes that work for both authenticated and anonymous users
    (e.g. public health check, language list).
    """
    if credentials is None:
        return None

    from app.models.user import User

    token = credentials.credentials
    user_id = decode_access_token(token)

    if not user_id:
        return None

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None

    result = await db.execute(
        select(User).where(User.id == user_uuid, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()
