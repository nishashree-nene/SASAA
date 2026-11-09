"""
SASAA – User Pydantic Schemas
================================
Request and response shapes for /users endpoints.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserProfileResponse(BaseModel):
    """The user's display profile — safe to return to clients."""
    id: uuid.UUID
    email: EmailStr
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    profile_picture_url: Optional[str] = None
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}  # Allows ORM → Pydantic conversion


class UpdateProfileRequest(BaseModel):
    """Body for PATCH /users/me"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=20)
    profile_picture_url: Optional[str] = None


class UserPreferencesResponse(BaseModel):
    """Returns the user's current preferences."""
    interface_language: str
    transcript_language: str
    auto_translate: bool
    theme: str
    notify_new_message: bool
    notify_high_priority: bool
    notify_emergency: bool
    notify_suspicious: bool
    notify_email: bool
    audio_retention_days: Optional[int] = None

    model_config = {"from_attributes": True}


class UpdatePreferencesRequest(BaseModel):
    """Body for PATCH /users/preferences — all fields optional."""
    interface_language: Optional[str] = None
    transcript_language: Optional[str] = None
    auto_translate: Optional[bool] = None
    theme: Optional[str] = None
    notify_new_message: Optional[bool] = None
    notify_high_priority: Optional[bool] = None
    notify_emergency: Optional[bool] = None
    notify_suspicious: Optional[bool] = None
    notify_email: Optional[bool] = None
    audio_retention_days: Optional[int] = None
