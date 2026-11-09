"""
SASAA – Transcript Pydantic Schemas
=====================================
Request and response shapes for the transcription endpoints.

TranscribeRequest         – optional body for POST /transcribe (language override)
TranscriptResponse         – the stored transcript data returned by GET /transcription
TranscriptionStatusResponse – unified response covering all processing states:
                                in-progress, completed, failed, not-started
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TranscribeRequest(BaseModel):
    """Optional body for POST /messages/{id}/transcribe."""
    language_code: Optional[str] = Field(
        None,
        description="BCP-47 language code e.g. ta-IN, en-IN. "
                    "Defaults to user preference or ta-IN if not set.",
    )


class TranscriptResponse(BaseModel):
    """
    The full transcript record from the database.

    raw_text is the immutable original text returned by Gnani STT.
    It is never modified after creation — user corrections are
    stored separately in TranscriptVersion rows.
    """
    id: uuid.UUID
    message_id: uuid.UUID
    raw_text: str
    detected_language: Optional[str] = None
    provider_confidence: Optional[float] = None
    processing_latency_ms: Optional[int] = None
    english_translation: Optional[str] = None
    translation_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TranscriptionStatusResponse(BaseModel):
    """
    Unified response for GET /messages/{id}/transcription.

    Covers every possible state:
      - Transcription not started (status=UPLOADED/VALIDATING, has_transcript=False)
      - Transcription in progress (status=TRANSCRIBING/PROCESSING/ANALYZING, has_transcript=False)
      - Transcription completed (status=COMPLETED, has_transcript=True, transcript=...)
      - Transcription failed (status=FAILED, has_transcript=False, error_message=...)
      - Needs verification (status=NEEDS_VERIFICATION, has_transcript=True, transcript=...)

    The frontend uses `status` to decide what to display and `has_transcript`
    to know whether transcript data is available.
    """
    message_id: uuid.UUID
    status: str                          # MessageStatus value as string
    has_transcript: bool
    transcript: Optional[TranscriptResponse] = None
    audio_duration_seconds: Optional[float] = None
    error_message: Optional[str] = None   # Populated when status=FAILED
    message: Optional[str] = None        # Human-readable status description
