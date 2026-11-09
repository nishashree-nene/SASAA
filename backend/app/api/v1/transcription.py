"""
SASAA – Transcription Routes
===============================
POST /messages/{id}/transcribe     – trigger Gnani STT transcription (async background)
GET  /messages/{id}/transcription  – retrieve transcript and processing status

ARCHITECTURE:
  The POST endpoint returns HTTP 202 (Accepted) immediately and runs the
  transcription pipeline as a FastAPI BackgroundTask. This avoids blocking
  the request worker during the 5-120 second Gnani API call.

  The background task creates its own database session (AsyncSessionLocal)
  because the request's session is closed after the response is sent.

  The GET endpoint returns the current processing status and, when available,
  the full transcript text with language detection and translation.

  The existing run_transcription_pipeline() in transcription_service.py
  handles the complete pipeline:
    VALIDATING → PROCESSING → TRANSCRIBING → ANALYZING → COMPLETED
  On failure it sets the message status to FAILED with an error message.
"""

import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.transcription_service import run_transcription_pipeline
from app.core.database import AsyncSessionLocal, get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message, MessageAudio, MessageStatus
from app.models.transcript import Transcript
from app.models.user import UserPreferences
from app.schemas.common import SuccessResponse
from app.schemas.transcript import (
    TranscribeRequest,
    TranscriptionStatusResponse,
    TranscriptResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["Transcription"])


# ── Status sets for duplicate-prevention logic ───────────────────────────────
# Messages in these states have an active transcription pipeline running.
# VALIDATING is excluded because the audio upload route sets it after saving
# the file — it means "audio validated, ready for transcription", not
# "transcription is in progress". The POST /transcribe handler sets
# TRANSCRIBING immediately to prevent duplicate triggers.
_IN_PROGRESS_STATUSES = {
    MessageStatus.TRANSCRIBING,
    MessageStatus.PROCESSING,
    MessageStatus.ANALYZING,
}

# Messages in these states have already been transcribed — reject re-trigger.
_COMPLETED_STATUSES = {
    MessageStatus.COMPLETED,
    MessageStatus.NEEDS_VERIFICATION,
}

# Messages in these states can accept a new transcription trigger.
_RETRIGGERABLE_STATUSES = {
    MessageStatus.UPLOADED,
    MessageStatus.FAILED,
}


# ── Ownership helper (self-contained, same pattern as audio.py) ─────────────

async def _get_owned_message_with_audio(
    db: AsyncSession,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Message:
    """
    Fetch a message with its audio relationship eagerly loaded.

    Returns 404 for both 'not found' and 'belongs to another user' so
    that message IDs cannot be used to enumerate other users' data.
    """
    result = await db.execute(
        select(Message)
        .options(selectinload(Message.audio))
        .where(
            Message.id == message_id,
            Message.user_id == user_id,
            Message.deleted_at.is_(None),
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )
    return message


def _resolve_audio_path(audio: MessageAudio) -> Path:
    """
    Resolve the on-disk path of the stored audio file.

    storage_path is stored relative to CWD (backend/) like
    'audio_storage/{user_id}/{message_id}_{filename}'.
    """
    file_path = Path(audio.storage_path)
    if not file_path.is_absolute():
        file_path = file_path.resolve()
    return file_path


# ── POST /messages/{message_id}/transcribe ───────────────────────────────────

@router.post(
    "/messages/{message_id}/transcribe",
    response_model=SuccessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger audio transcription via Gnani STT",
)
async def trigger_transcription(
    message_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    body: TranscribeRequest | None = None,
):
    """
    Start the Gnani speech-to-text transcription pipeline for a message.

    Returns HTTP 202 immediately — the actual transcription runs in the
    background. Poll GET /messages/{id}/transcription to check progress.

    The pipeline transitions through:
      VALIDATING → PROCESSING → TRANSCRIBING → ANALYZING → COMPLETED

    On failure the message status becomes FAILED with an error message.

    Errors:
      404 – Message not found or no audio file attached
      409 – Transcription already completed or already in progress
      503 – Audio file missing from disk storage
    """
    # 1. Verify ownership and load audio
    message = await _get_owned_message_with_audio(db, message_id, current_user.id)

    # 2. Check that audio exists
    audio = message.audio
    if audio is None or audio.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audio file found for this message. Upload audio first.",
        )

    # 3. Prevent duplicate transcription
    #    Check if a transcript already exists in the database
    existing_transcript = await db.execute(
        select(Transcript).where(
            Transcript.message_id == message_id,
            Transcript.deleted_at.is_(None),
        )
    )
    if existing_transcript.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This message has already been transcribed.",
        )

    #    Check if transcription is already in progress
    if message.status in _IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transcription is already in progress (current status: {message.status.value}).",
        )

    if message.status in _COMPLETED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This message has already been transcribed.",
        )

    # 4. Resolve the audio file path on disk
    file_path = _resolve_audio_path(audio)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found on disk. It may have been deleted.",
        )

    # 5. Determine the transcription language
    #    Priority: request body → user preferences → default ta-IN
    language_code = "ta-IN"  # safe default
    if body and body.language_code:
        language_code = body.language_code.strip()
    else:
        # Load user's preferred transcript language
        prefs_result = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == current_user.id)
        )
        prefs = prefs_result.scalar_one_or_none()
        if prefs and prefs.transcript_language:
            language_code = prefs.transcript_language

    # 6. Mark the message as TRANSCRIBING immediately and commit.
    #    This prevents duplicate requests from starting a second pipeline
    #    before the background task has a chance to run.
    message.status = MessageStatus.TRANSCRIBING
    await db.commit()

    # 7. Schedule the transcription pipeline as a background task.
    #    The background task creates its own database session because
    #    the request's session will be closed after the response is sent.
    background_tasks.add_task(
        _run_transcription_background,
        message_id=message_id,
        audio_file_path=str(file_path),
        language_code=language_code,
        mime_type=audio.mime_type,
        user_id=current_user.id,
    )

    logger.info(
        "Transcription triggered",
        message_id=str(message_id),
        language=language_code,
        user_id=str(current_user.id),
    )

    return SuccessResponse(
        success=True,
        message="Transcription started. Poll GET /messages/{id}/transcription for results.",
    )


async def _run_transcription_background(
    message_id: uuid.UUID,
    audio_file_path: str,
    language_code: str,
    mime_type: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """
    Background task: run transcription pipeline, then auto-verify.

    Two separate async sessions are used:
      Session 1 — transcription (committed before session 2 opens)
      Session 2 — verification (opened by _auto_verify_after_transcription)
    This prevents nested-session conflicts on asyncpg.
    """
    log = logger.bind(message_id=str(message_id), language=language_code)
    log.info("Background transcription task started")

    # ── Phase 1: Transcription in its own session ─────────────────────────
    transcript_id = None
    raw_text = None

    async with AsyncSessionLocal() as db:
        try:
            result = await run_transcription_pipeline(
                message_id=message_id,
                audio_file_path=audio_file_path,
                language_code=language_code,
                mime_type=mime_type,
                db=db,
            )

            if result.success:
                log.info(
                    "Background transcription completed",
                    transcript_id=str(result.transcript_id),
                    detected_language=result.detected_language,
                    latency_ms=result.our_latency_ms,
                )
                transcript_id = result.transcript_id
                raw_text = result.raw_text
            else:
                log.error(
                    "Background transcription failed",
                    error_type=result.error_type,
                    error_message=result.error_message,
                )

        except Exception as exc:
            log.error(
                "Background transcription crashed unexpectedly",
                error=str(exc),
                exc_info=True,
            )
            await _safely_fail_message(db, message_id, f"Transcription error: {type(exc).__name__}")
            return  # Don't attempt verification if transcription failed

    # ── Phase 2: Verification in a separate session ────────────────────────
    # The transcription session is now fully closed and committed.
    # Opening a new session here is safe.
    if transcript_id and raw_text and user_id is not None:
        log.info("Running auto-verification (new session)")
        await _auto_verify_after_transcription(
            message_id=message_id,
            transcript_id=transcript_id,
            raw_text=raw_text,
            user_id=user_id,
        )


async def _auto_verify_after_transcription(
    message_id: uuid.UUID,
    transcript_id: uuid.UUID,
    raw_text: str,
    user_id: uuid.UUID,
) -> None:
    """
    Runs verification in its own AsyncSessionLocal scope.
    Called from within _run_transcription_background after the
    transcription session has committed.
    """
    from app.api.v1.verification import _run_verification_background
    logger.info("Auto-verification started", message_id=str(message_id))
    try:
        await _run_verification_background(
            message_id=message_id,
            transcript_id=transcript_id,
            raw_text=raw_text,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "Auto-verification failed — use POST /messages/{id}/verify to retry",
            message_id=str(message_id),
            error=str(exc),
        )


async def _safely_fail_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    error_message: str,
) -> None:
    """
    Last-resort safety net: mark a message as FAILED.
    Used when the background task crashes before the pipeline could
    set the FAILED status itself.
    """
    try:
        result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        message = result.scalar_one_or_none()
        if message and message.status not in {
            MessageStatus.COMPLETED,
            MessageStatus.NEEDS_VERIFICATION,
            MessageStatus.FAILED,
        }:
            message.status = MessageStatus.FAILED
            message.error_message = error_message
            await db.commit()
    except Exception:
        await db.rollback()


# ── GET /messages/{message_id}/transcription ─────────────────────────────────

@router.get(
    "/messages/{message_id}/transcription",
    response_model=TranscriptionStatusResponse,
    summary="Get transcript and processing status",
)
async def get_transcription(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Retrieve the transcription status and, when available, the full transcript.

    Possible responses:
      - status=UPLOADED, has_transcript=False: audio uploaded, transcription not started
      - status=TRANSCRIBING/PROCESSING/VALIDATING/ANALYZING, has_transcript=False: in progress
      - status=COMPLETED, has_transcript=True: transcription done, transcript included
      - status=NEEDS_VERIFICATION, has_transcript=True: done with flagged entities
      - status=FAILED, has_transcript=False: transcription failed, error_message included

    Errors:
      401 – Not authenticated
      404 – Message not found
    """
    # 1. Verify ownership
    message = await _get_owned_message_with_audio(db, message_id, current_user.id)

    # 2. Query for the transcript
    result = await db.execute(
        select(Transcript).where(
            Transcript.message_id == message_id,
            Transcript.deleted_at.is_(None),
        ).order_by(Transcript.created_at.desc())
    )
    transcript = result.scalar_one_or_none()

    # 3. Build the response based on current state
    audio = message.audio
    duration = None
    if audio is not None and audio.duration_seconds is not None:
        duration = float(audio.duration_seconds)

    if transcript is not None:
        # Transcript exists — transcription completed successfully
        return TranscriptionStatusResponse(
            message_id=message_id,
            status=message.status.value,
            has_transcript=True,
            transcript=TranscriptResponse.model_validate(transcript),
            audio_duration_seconds=duration,
            message="Transcription completed successfully.",
        )

    # No transcript yet — describe the current state
    if message.status == MessageStatus.FAILED:
        return TranscriptionStatusResponse(
            message_id=message_id,
            status=message.status.value,
            has_transcript=False,
            audio_duration_seconds=duration,
            error_message=message.error_message or "Transcription failed.",
            message="Transcription failed. You can retry via POST /messages/{id}/transcribe.",
        )

    if message.status in _IN_PROGRESS_STATUSES:
        return TranscriptionStatusResponse(
            message_id=message_id,
            status=message.status.value,
            has_transcript=False,
            audio_duration_seconds=duration,
            message=f"Transcription is in progress (status: {message.status.value}). Please wait.",
        )

    if message.status == MessageStatus.UPLOADED:
        return TranscriptionStatusResponse(
            message_id=message_id,
            status=message.status.value,
            has_transcript=False,
            audio_duration_seconds=duration,
            message="Transcription has not been started. Use POST /messages/{id}/transcribe to start.",
        )

    # Fallback for any other status (e.g. COMPLETED without transcript — shouldn't happen)
    return TranscriptionStatusResponse(
        message_id=message_id,
        status=message.status.value,
        has_transcript=False,
        audio_duration_seconds=duration,
        message=f"Current status: {message.status.value}. No transcript available.",
    )
