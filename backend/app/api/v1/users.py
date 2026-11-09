"""
SASAA - User Profile Routes
=============================
GET    /users/me             – get current user profile
PATCH  /users/me             – update profile
DELETE /users/me             – soft-delete account
GET    /users/preferences    – get user preferences
PATCH  /users/preferences    – update preferences
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.user import (
    UpdatePreferencesRequest,
    UpdateProfileRequest,
    UserPreferencesResponse,
    UserProfileResponse,
)
from app.services.user_service import (
    get_user_with_profile,
    update_user_preferences,
    update_user_profile,
)

router = APIRouter(prefix="/users", tags=["Users"])


def _build_profile_response(user: User) -> UserProfileResponse:
    """
    Build a UserProfileResponse from a User with its profile loaded.

    UserProfileResponse exposes fields from BOTH the User table (id, email,
    is_verified, created_at) AND the UserProfile table (full_name, phone_number,
    profile_picture_url). SQLAlchemy won't auto-join these, so we do it here.
    """
    profile = user.profile
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=profile.full_name if profile else None,
        phone_number=profile.phone_number if profile else None,
        profile_picture_url=profile.profile_picture_url if profile else None,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


# ── GET /users/me ─────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return the authenticated user's profile.

    Requires: Authorization: Bearer <access_token>
    """
    # Re-fetch with profile eagerly loaded (get_current_user only loads User)
    user = await get_user_with_profile(db, current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return _build_profile_response(user)


# ── PATCH /users/me ───────────────────────────────────────────────────────────

@router.patch(
    "/me",
    response_model=UserProfileResponse,
    summary="Update current user profile",
)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Update the authenticated user's display profile.

    Only fields included in the request body are updated.
    Omitted fields are left unchanged.
    """
    user = await get_user_with_profile(db, current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    updated = await update_user_profile(
        db=db,
        user=user,
        full_name=body.full_name,
        phone_number=body.phone_number,
        profile_picture_url=body.profile_picture_url,
    )
    return _build_profile_response(updated)


# ── DELETE /users/me ──────────────────────────────────────────────────────────

@router.delete(
    "/me",
    response_model=SuccessResponse,
    summary="Delete your account",
)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Soft-delete the authenticated user's account.

    Sets deleted_at to now. The user can no longer log in.
    Data is retained according to the audio retention policy.
    Full data deletion can be requested via the privacy settings (Phase 8).
    """
    current_user.deleted_at = datetime.now(timezone.utc)
    current_user.is_active = False
    await db.commit()

    return SuccessResponse(
        success=True,
        message="Your account has been deleted. Your data will be removed according to retention policy.",
    )


# ── GET /users/preferences ────────────────────────────────────────────────────

@router.get(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Get user preferences",
)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the authenticated user's current application preferences."""
    user = await get_user_with_profile(db, current_user.id)
    if user is None or user.preferences is None:
        raise HTTPException(status_code=404, detail="Preferences not found.")

    return UserPreferencesResponse.model_validate(user.preferences)


# ── PATCH /users/preferences ──────────────────────────────────────────────────

@router.patch(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Update user preferences",
)
async def patch_preferences(
    body: UpdatePreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Update one or more preference fields.

    Only include the fields you want to change.
    Omitted fields are left at their current values.
    """
    user = await get_user_with_profile(db, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    updates = body.model_dump(exclude_none=True)
    prefs = await update_user_preferences(db=db, user=user, updates=updates)
    return UserPreferencesResponse.model_validate(prefs)
