"""
SASAA – Transcription Service
================================
Orchestrates the complete audio processing pipeline:

  Audio File
      ↓
  Language Validation     (is this language supported by Gnani?)
      ↓
  Audio Preparation       (format conversion if needed)
      ↓
  Gnani STT API Call      (async HTTP, retry logic, error handling)
      ↓
  Result Storage          (immutable transcript row in database)
      ↓
  Language Fallback       (text-based detection if Gnani didn't return language)
      ↓
  English Translation     (optional, stored separately from original)
      ↓
  TranscriptionResult     (returned to the caller / background worker)

This service is what the audio route handler calls after saving an audio file.
It is also what the background worker calls for reprocessing.

CORE RULE ENFORCED HERE:
  raw_text in the Transcript table is set ONCE from gnani_result.transcript
  and NEVER updated. All subsequent changes go to TranscriptVersion rows.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.audio_service import prepare_for_gnani
from app.ai.gnani_client import GnaniError, GnaniTranscriptResult, transcribe_audio
from app.ai.language_service import (
    detect_language_from_text,
    is_stt_supported,
    translate_to_english,
    validate_language_code,
)
from app.models.message import Message, MessageStatus
from app.models.transcript import Transcript

logger = structlog.get_logger(__name__)


@dataclass
class TranscriptionResult:
    """
    The outcome of running the full transcription pipeline on one message.

    success=True means a raw_text is available in the database.
    success=False means the message status is FAILED with an error_message.
    """
    success: bool
    message_id: uuid.UUID
    transcript_id: Optional[uuid.UUID] = None
    raw_text: Optional[str] = None
    detected_language: Optional[str] = None
    our_latency_ms: Optional[int] = None
    gnani_latency_ms: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None


async def run_transcription_pipeline(
    message_id: uuid.UUID,
    audio_file_path: str,
    language_code: str,
    mime_type: str,
    db: AsyncSession,
) -> TranscriptionResult:
    """
    Run the full transcription pipeline for a message.

    This function:
      1. Updates message status as it moves through each stage
      2. Calls Gnani STT
      3. Stores the immutable transcript
      4. Stores the translation
      5. Updates the message status to COMPLETED or FAILED

    Args:
        message_id:       UUID of the message to transcribe
        audio_file_path:  Absolute path to the saved audio file
        language_code:    BCP-47 code for the transcription language
        mime_type:        MIME type of the audio file
        db:               AsyncSession for database operations

    Returns:
        TranscriptionResult describing the outcome
    """
    log = logger.bind(message_id=str(message_id), language=language_code)
    log.info("Starting transcription pipeline")

    # ── Step 1: Validate language ──────────────────────────────────────────
    await _update_message_status(db, message_id, MessageStatus.VALIDATING)

    is_valid, validation_msg = validate_language_code(language_code)
    if not is_valid:
        log.warning("Unsupported language", reason=validation_msg)
        await _fail_message(db, message_id, validation_msg)
        return TranscriptionResult(
            success=False,
            message_id=message_id,
            error_type="UNSUPPORTED_LANGUAGE",
            error_message=validation_msg,
        )

    # ── Step 2: Prepare audio for Gnani ───────────────────────────────────
    await _update_message_status(db, message_id, MessageStatus.PROCESSING)

    try:
        send_path, send_mime = await prepare_for_gnani(audio_file_path)
        log.info("Audio prepared", send_path=send_path, send_mime=send_mime)
    except Exception as e:
        error_msg = f"Audio preparation failed: {str(e)}"
        log.error("Audio preparation error", error=str(e))
        await _fail_message(db, message_id, error_msg)
        return TranscriptionResult(
            success=False,
            message_id=message_id,
            error_type="AUDIO_PREPARATION_FAILED",
            error_message=error_msg,
        )

    # ── Step 3: Call Gnani STT ─────────────────────────────────────────────
    await _update_message_status(db, message_id, MessageStatus.TRANSCRIBING)

    gnani_result = await transcribe_audio(
        audio_file_path=send_path,
        language_code=language_code,
        mime_type=send_mime,
    )

    if isinstance(gnani_result, GnaniError):
        log.error(
            "Gnani transcription failed",
            error_type=gnani_result.error_type,
            message=gnani_result.message,
        )
        await _fail_message(db, message_id, gnani_result.message)
        return TranscriptionResult(
            success=False,
            message_id=message_id,
            error_type=gnani_result.error_type,
            error_message=gnani_result.message,
        )

    # ── Step 4: Store immutable transcript ────────────────────────────────
    await _update_message_status(db, message_id, MessageStatus.ANALYZING)

    # Determine the language to store
    detected_language = (
        gnani_result.detected_language_code
        or await detect_language_from_text(gnani_result.transcript)
        or language_code   # final fallback: the language we requested
    )

    # Create the immutable transcript record
    # raw_text is set here and NEVER modified again
    transcript = Transcript(
        message_id=message_id,
        raw_text=gnani_result.transcript,            # IMMUTABLE from this point
        detected_language=detected_language,
        provider_confidence=None,                    # Gnani v3 doesn't return confidence
        processing_latency_ms=gnani_result.our_latency_ms,
        provider_response=gnani_result.raw_response, # stored for debugging
    )
    db.add(transcript)
    await db.flush()  # Get the transcript ID without committing yet

    log.info(
        "Transcript stored",
        transcript_id=str(transcript.id),
        language=detected_language,
        text_length=len(gnani_result.transcript),
    )

    # ── Step 5: Store English translation (optional) ───────────────────────
    if detected_language != "en-IN":
        log.info("Translating to English...")
        english_text = await translate_to_english(gnani_result.transcript)
        if english_text:
            transcript.english_translation = english_text
            transcript.translation_source = "google_translate"
            log.info("English translation stored", length=len(english_text))
        else:
            log.warning("English translation failed or unavailable")

    # ── Step 6: Update message with detected language and COMPLETED status ─
    await _update_message_after_transcription(
        db, message_id, detected_language, MessageStatus.COMPLETED
    )

    await db.commit()

    log.info(
        "Transcription pipeline completed",
        transcript_id=str(transcript.id),
        our_latency_ms=gnani_result.our_latency_ms,
        gnani_latency_ms=gnani_result.end_to_end_latency,
    )

    return TranscriptionResult(
        success=True,
        message_id=message_id,
        transcript_id=transcript.id,
        raw_text=gnani_result.transcript,
        detected_language=detected_language,
        our_latency_ms=gnani_result.our_latency_ms,
        gnani_latency_ms=gnani_result.end_to_end_latency,
    )


# ── Database helpers ─────────────────────────────────────────────────────────

async def _update_message_status(
    db: AsyncSession,
    message_id: uuid.UUID,
    new_status: MessageStatus,
) -> None:
    """Update the message status and commit. Called at each pipeline stage."""
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    message = result.scalar_one_or_none()
    if message:
        message.status = new_status
        await db.flush()


async def _fail_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    error_message: str,
) -> None:
    """Set message status to FAILED with an error description."""
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    message = result.scalar_one_or_none()
    if message:
        message.status = MessageStatus.FAILED
        message.error_message = error_message
        await db.commit()


async def _update_message_after_transcription(
    db: AsyncSession,
    message_id: uuid.UUID,
    detected_language: str,
    final_status: MessageStatus,
) -> None:
    """Update message with detected language and final status after transcription."""
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    message = result.scalar_one_or_none()
    if message:
        message.detected_language = detected_language
        message.status = final_status
        await db.flush()
