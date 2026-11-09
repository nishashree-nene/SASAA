"""SASAA message inbox routes.

All message queries are scoped to the authenticated owner. Deletion is soft:
rows and their related audio/transcript records remain available for retention
and audit purposes.
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message, MessagePriority, MessageStatus
from app.models.transcript import Transcript
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.message import (
    CreateMessageRequest,
    MessageDetailResponse,
    MessageSummaryResponse,
    UpdateMessageRequest,
)

router = APIRouter(prefix="/messages", tags=["Messages"])


def _latest_transcript(message: Message) -> Optional[Transcript]:
    """Return the newest non-deleted transcript attached to a message."""
    active_transcripts = [
        transcript
        for transcript in (message.transcripts or [])
        if transcript.deleted_at is None
    ]
    if not active_transcripts:
        return None
    return max(
        active_transcripts,
        key=lambda transcript: (
            transcript.created_at or datetime.min.replace(tzinfo=timezone.utc),
            str(transcript.id),
        ),
    )


def _message_response(message: Message, *, detail: bool = False):
    """Map ORM relationships into the API's flattened Pydantic response."""
    audio = message.audio
    if audio is not None and audio.deleted_at is not None:
        audio = None

    transcript = _latest_transcript(message)
    payload = {
        "id": message.id,
        "caller_name": message.caller_name,
        "caller_phone": message.caller_phone,
        "status": message.status,
        "priority": message.priority,
        "detected_language": message.detected_language,
        "is_read": message.is_read,
        "is_archived": message.is_archived,
        "duration_seconds": (
            float(audio.duration_seconds)
            if audio is not None and audio.duration_seconds is not None
            else None
        ),
        "transcript_preview": transcript.raw_text[:100] if transcript else None,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }

    if detail:
        payload.update(
            {
                "original_filename": audio.original_filename if audio else None,
                "mime_type": audio.mime_type if audio else None,
                "file_size_bytes": audio.file_size_bytes if audio else None,
                "error_message": message.error_message,
            }
        )
        return MessageDetailResponse(**payload)

    return MessageSummaryResponse(**payload)


async def _get_owned_message(
    db: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID
) -> Message:
    """Fetch an active message only when it belongs to the current user."""
    statement = (
        select(Message)
        .where(
            Message.id == message_id,
            Message.user_id == user_id,
            Message.deleted_at.is_(None),
        )
        .options(
            selectinload(Message.audio),
            selectinload(Message.transcripts),
        )
    )
    result = await db.execute(statement)
    message = result.scalar_one_or_none()
    if message is None:
        # Same response for missing and another user's ID; avoids leaking records.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )
    return message


@router.get("", response_model=PaginatedResponse[MessageSummaryResponse])
async def list_messages(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search transcript text"),
    status: Optional[MessageStatus] = Query(None),
    priority: Optional[MessagePriority] = Query(None),
    language: Optional[str] = Query(None, description="Detected language, e.g. ta-IN"),
    is_read: Optional[bool] = Query(None),
    is_archived: bool = Query(False, description="Filter by archived state"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the authenticated user's inbox, newest messages first."""
    filters = [
        Message.user_id == current_user.id,
        Message.deleted_at.is_(None),
        Message.is_archived == is_archived,
    ]

    if status is not None:
        filters.append(Message.status == status)
    if priority is not None:
        filters.append(Message.priority == priority)
    if language:
        filters.append(Message.detected_language == language.strip())
    if is_read is not None:
        filters.append(Message.is_read == is_read)
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        matching_transcript = (
            select(Transcript.id)
            .where(
                Transcript.message_id == Message.id,
                Transcript.deleted_at.is_(None),
                Transcript.raw_text.ilike(search_pattern),
            )
            .exists()
        )
        filters.append(
            or_(
                Message.caller_name.ilike(search_pattern),
                Message.caller_phone.ilike(search_pattern),
                matching_transcript,
            )
        )

    count_result = await db.execute(
        select(func.count(Message.id)).where(*filters)
    )
    total = count_result.scalar_one()

    statement = (
        select(Message)
        .where(*filters)
        .options(
            selectinload(Message.audio),
            selectinload(Message.transcripts),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(statement)
    messages = result.scalars().all()

    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedResponse[MessageSummaryResponse](
        items=[_message_response(message) for message in messages],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total > 0,
    )


@router.post(
    "", response_model=MessageDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_message(
    body: CreateMessageRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Create an UPLOADED message record; audio is attached by the audio route."""
    message = Message(
        user_id=current_user.id,
        caller_name=body.caller_name,
        caller_phone=body.caller_phone,
        status=MessageStatus.UPLOADED,
        priority=MessagePriority.NORMAL,
        is_read=False,
        is_archived=False,
    )
    db.add(message)
    await db.commit()
    # Reload with eager relationships so response mapping never triggers
    # an unsupported implicit async lazy-load.
    message = await _get_owned_message(db, message.id, current_user.id)
    return _message_response(message, detail=True)


@router.get("/{message_id}", response_model=MessageDetailResponse)
async def get_message(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return message details, including audio metadata and transcript preview."""
    message = await _get_owned_message(db, message_id, current_user.id)
    return _message_response(message, detail=True)


@router.patch("/{message_id}", response_model=MessageDetailResponse)
async def update_message(
    message_id: uuid.UUID,
    body: UpdateMessageRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update read state, archive state, and/or priority."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one field to update.",
        )
    if any(value is None for value in updates.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Update fields cannot be null.",
        )

    message = await _get_owned_message(db, message_id, current_user.id)
    for field, value in updates.items():
        setattr(message, field, value)

    await db.commit()
    await db.refresh(message)
    # Re-load relationships because refresh() refreshes scalar columns only.
    message = await _get_owned_message(db, message_id, current_user.id)
    return _message_response(message, detail=True)


@router.delete("/{message_id}", response_model=SuccessResponse)
async def delete_message(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Soft-delete a message; keep related audio and transcript data for retention."""
    message = await _get_owned_message(db, message_id, current_user.id)
    message.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return SuccessResponse(message="Message deleted successfully.")
