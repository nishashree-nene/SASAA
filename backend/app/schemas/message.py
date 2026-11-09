"""
SASAA – Message Pydantic Schemas
===================================
Request and response shapes for /messages endpoints.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.message import MessageStatus, MessagePriority


class CreateMessageRequest(BaseModel):
    """Body for POST /messages — creates a new message record before uploading audio."""
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None


class MessageSummaryResponse(BaseModel):
    """
    Compact message shape for the inbox list.
    Does not include full transcript — keeps the list response small.
    """
    id: uuid.UUID
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    status: MessageStatus
    priority: MessagePriority
    detected_language: Optional[str] = None
    is_read: bool
    is_archived: bool
    # Audio summary (from related MessageAudio)
    duration_seconds: Optional[float] = None
    # Transcript preview (first 100 chars of raw_text)
    transcript_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageDetailResponse(MessageSummaryResponse):
    """
    Full message shape for the Message Analysis screen.
    Extends the summary with full transcript and analysis data.
    """
    # Audio details
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None


class UpdateMessageRequest(BaseModel):
    """Body for PATCH /messages/{id} — mark read, archive, update priority."""
    is_read: Optional[bool] = None
    is_archived: Optional[bool] = None
    priority: Optional[MessagePriority] = None


class DashboardStats(BaseModel):
    """Response for GET /analytics/dashboard — all values from real database counts."""
    total_messages: int
    unread_messages: int
    messages_needing_verification: int
    high_priority_messages: int
    emergency_messages: int
    messages_today: int
    messages_this_week: int
    guardian_active: bool   # True when the backend is running
