"""
SASAA – Audio Routes
======================
POST /messages/{id}/audio             – upload audio file
GET  /messages/{id}/audio             – stream/download audio for playback
POST /messages/{id}/recording-complete – signal that recording is done

Security rules enforced:
  - Every request must be authenticated (get_current_user)
  - The message must belong to the authenticated user (ownership check)
  - A 404 is returned for both "not found" and "not owned" so an
    attacker cannot enumerate other users' message IDs
  - Only one audio file per message (409 on duplicate upload)
  - File paths are never returned to the client — only the audio bytes
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.audio_service import ACCEPTED_MIME_TYPES, AudioValidationError, save_uploaded_audio
from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message, MessageAudio, MessageStatus
from app.schemas.common import SuccessResponse

router = APIRouter(tags=["Audio"])


# ── Ownership helper ─────────────────────────────────────────────────────────
# Defined locally (not imported from messages.py) to keep audio.py self-contained
# and avoid a cross-module dependency that could cause import-order issues.

async def _get_owned_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    load_audio: bool = True,
) -> Message:
    """
    Fetch a message only if it belongs to the current user and is not deleted.

    Returns 404 for both 'not found' and 'belongs to someone else' so that
    message IDs cannot be used to enumerate other users' data.

    Args:
        load_audio: If True, eagerly load the MessageAudio relationship
                    so it can be accessed without an extra query.
    """
    stmt = select(Message).where(
        Message.id == message_id,
        Message.user_id == user_id,
        Message.deleted_at.is_(None),
    )
    if load_audio:
        stmt = stmt.options(selectinload(Message.audio))

    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )
    return message


# ── POST /messages/{message_id}/audio ────────────────────────────────────────

@router.post(
    "/messages/{message_id}/audio",
    response_model=SuccessResponse,
    summary="Upload an audio file for a message",
)
async def upload_audio(
    message_id: uuid.UUID,
    audio_file: UploadFile = File(
        ...,
        description="Audio file: OGG, MP3, WAV, M4A, MP4, WebM, AAC, FLAC",
    ),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Upload an audio file for a message.

    Accepted formats: OGG, MP3, WAV, M4A, MP4, WebM, AAC, FLAC
    Maximum size: MAX_AUDIO_SIZE_MB from .env (default 50 MB)

    After upload:
      - The message status becomes VALIDATING
      - The audio file is stored on disk under audio_storage/{user_id}/
      - A MessageAudio record is created with file metadata
      - Transcription can be triggered separately via POST /messages/{id}/transcribe

    Errors:
      404 – Message not found (or does not belong to you)
      409 – An audio file has already been uploaded for this message
      415 – Unsupported audio format
      422 – Empty or oversized file
    """
    # 1. Verify message exists and belongs to the user
    message = await _get_owned_message(db, message_id, current_user.id, load_audio=True)

    # 2. Reject duplicate uploads — one audio file per message
    if message.audio is not None and message.audio.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An audio file has already been uploaded for this message.",
        )

    # 3. Save and validate the uploaded file
    try:
        metadata = await save_uploaded_audio(
            upload=audio_file,
            user_id=str(current_user.id),
            message_id=str(message_id),
        )
    except AudioValidationError as exc:
        # Format not supported or file too large — return 415
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=exc.user_message,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the audio file. Please try again.",
        )

    # 4. Create the MessageAudio database record
    audio_record = MessageAudio(
        message_id=message_id,
        original_filename=metadata.original_filename,
        storage_path=metadata.storage_path,
        mime_type=metadata.mime_type,
        file_size_bytes=metadata.file_size_bytes,
        duration_seconds=metadata.duration_seconds,
    )
    db.add(audio_record)

    # 5. Advance the message to VALIDATING status
    message.status = MessageStatus.VALIDATING

    await db.commit()

    return SuccessResponse(
        success=True,
        message="Audio uploaded successfully. You can now trigger transcription.",
    )


# ── GET /messages/{message_id}/audio ─────────────────────────────────────────

@router.get(
    "/messages/{message_id}/audio",
    summary="Stream audio for playback",
    responses={
        200: {"content": {"audio/*": {}}},
        404: {"description": "Message or audio file not found"},
    },
)
async def get_audio(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Stream the original audio file for playback in the browser.

    Returns the file with the correct Content-Type header (audio/ogg,
    audio/mpeg, audio/wav, etc.) so the browser's <audio> element can
    play it directly.

    Uses FileResponse which supports HTTP Range requests, allowing
    the client to seek within the audio without downloading the entire file.

    Only the message owner can access their audio files.

    Errors:
      401 – Not authenticated
      404 – Message not found, no audio attached, or file missing from disk
    """
    # 1. Verify message exists and belongs to the user
    message = await _get_owned_message(db, message_id, current_user.id, load_audio=True)

    # 2. Check that audio metadata exists
    audio = message.audio
    if audio is None or audio.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audio file found for this message.",
        )

    # 3. Resolve the file path on disk
    #    storage_path is stored as a path relative to CWD (backend/) like
    #    "audio_storage/{user_id}/{message_id}_{filename}"
    file_path = Path(audio.storage_path)
    if not file_path.is_absolute():
        # Resolve relative to current working directory (backend/ when
        # running via uvicorn from the backend/ folder)
        file_path = file_path.resolve()

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found on disk. It may have been deleted.",
        )

    # 4. Return the file with the correct MIME type for browser playback
    #    content_disposition_type="inline" tells the browser to play the
    #    audio inline rather than downloading it as an attachment.
    return FileResponse(
        path=str(file_path),
        media_type=audio.mime_type,
        filename=audio.original_filename,
        content_disposition_type="inline",
    )


# ── POST /messages/{message_id}/recording-complete ───────────────────────────

@router.post(
    "/messages/{message_id}/recording-complete",
    response_model=SuccessResponse,
    summary="Signal that a live recording has finished",
)
async def recording_complete(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Signal that a live recording has finished and is ready for transcription.
    Used by the Android app after stopping the microphone.

    In the current MVP, audio is uploaded directly via POST /messages/{id}/audio.
    This endpoint is reserved for the future real-time recording flow where
    audio chunks are streamed during recording and this call marks the end.
    """
    # Verify ownership even for this stub — don't accept arbitrary IDs
    await _get_owned_message(db, message_id, current_user.id, load_audio=False)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Recording-complete flow is reserved for the Android live recording feature.",
    )
