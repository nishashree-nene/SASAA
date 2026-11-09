"""
SASAA – Voicemail API Routes
================================
GET  /voicemails                    – inbox with pagination/filters
GET  /voicemails/{id}               – single voicemail detail
GET  /voicemails/{id}/audio         – authenticated audio playback
GET  /voicemails/{id}/transcript    – transcript + segments
GET  /voicemails/{id}/report        – detailed accuracy report
POST /voicemails/{id}/reprocess     – manually retry failed processing
POST /voicemails/{id}/corrections   – save corrected transcript version
"""

import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message
from app.models.transcript import (
    Transcript, TranscriptSegment, TranscriptVersion, VerificationStatus
)
from app.models.voicemail import (
    Voicemail, VoicemailProcessingStatus, VoicemailRecording, VoicemailReport
)
from app.schemas.common import PaginatedResponse, SuccessResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/voicemails", tags=["Voicemails"])


# ── Ownership helper ─────────────────────────────────────────────────────────

async def _get_owned_voicemail(
    db: AsyncSession,
    voicemail_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Voicemail:
    result = await db.execute(
        select(Voicemail)
        .options(selectinload(Voicemail.recording))
        .where(
            Voicemail.id == voicemail_id,
            Voicemail.user_id == user_id,
            Voicemail.deleted_at.is_(None),
        )
    )
    vm = result.scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=404, detail="Voicemail not found.")
    return vm


# ── GET /voicemails ──────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedResponse)
async def list_voicemails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    processing_status: Optional[str] = Query(None),
    is_read: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return the authenticated user's voicemail inbox, newest first.

    Filters: processing_status, is_read
    Search: matches caller_number (partial)
    """
    filters = [
        Voicemail.user_id == current_user.id,
        Voicemail.deleted_at.is_(None),
    ]
    if processing_status:
        try:
            filters.append(
                Voicemail.processing_status == VoicemailProcessingStatus(processing_status.upper())
            )
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid processing_status: {processing_status}")
    if is_read is not None:
        filters.append(Voicemail.is_read == is_read)
    if search:
        filters.append(Voicemail.caller_number.ilike(f"%{search}%"))

    total_result = await db.execute(
        select(func.count(Voicemail.id)).where(*filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Voicemail)
        .options(selectinload(Voicemail.recording))
        .where(*filters)
        .order_by(Voicemail.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    voicemails = result.scalars().all()

    total_pages = math.ceil(total / page_size) if total else 0

    items = [_serialize_voicemail(vm) for vm in voicemails]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total > 0,
    )


# ── GET /voicemails/{id} ─────────────────────────────────────────────────────

@router.get("/{voicemail_id}")
async def get_voicemail(
    voicemail_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return full voicemail detail including recording metadata."""
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    # Mark as read
    if not vm.is_read:
        vm.is_read = True
        await db.commit()

    return _serialize_voicemail(vm, detail=True)


# ── GET /voicemails/{id}/audio ───────────────────────────────────────────────

@router.get("/{voicemail_id}/audio")
async def stream_voicemail_audio(
    voicemail_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Stream the voicemail recording for authenticated playback.
    Returns FileResponse — supports HTTP Range requests for seeking.
    """
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    recording = vm.recording
    if not recording or not recording.storage_key:
        raise HTTPException(
            status_code=404,
            detail="Audio file not yet available. Processing may be in progress.",
        )

    file_path = Path(recording.storage_key)
    if not file_path.is_absolute():
        file_path = file_path.resolve()

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Audio file not found on disk. It may have been deleted.",
        )

    return FileResponse(
        path=str(file_path),
        media_type=recording.mime_type or "audio/mpeg",
        filename=file_path.name,
        content_disposition_type="inline",
    )


# ── GET /voicemails/{id}/transcript ─────────────────────────────────────────

@router.get("/{voicemail_id}/transcript")
async def get_voicemail_transcript(
    voicemail_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the transcript, segments, and correction versions."""
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    if not vm.message_id:
        return {
            "voicemail_id": str(voicemail_id),
            "processing_status": vm.processing_status.value,
            "has_transcript": False,
            "message": (
                "Transcription has not started yet. "
                f"Processing status: {vm.processing_status.value}"
            ),
        }

    transcript_result = await db.execute(
        select(Transcript)
        .options(
            selectinload(Transcript.segments),
            selectinload(Transcript.versions),
            selectinload(Transcript.entities),
        )
        .where(
            Transcript.message_id == vm.message_id,
            Transcript.deleted_at.is_(None),
        )
        .order_by(Transcript.created_at.desc())
        .limit(1)
    )
    transcript = transcript_result.scalar_one_or_none()

    if not transcript:
        return {
            "voicemail_id": str(voicemail_id),
            "processing_status": vm.processing_status.value,
            "has_transcript": False,
            "message": "Transcription is in progress or has failed.",
        }

    segments = sorted(
        transcript.segments or [],
        key=lambda s: (s.start_ms or 0),
    )

    versions = sorted(
        transcript.versions or [],
        key=lambda v: v.version_number,
    )

    return {
        "voicemail_id": str(voicemail_id),
        "processing_status": vm.processing_status.value,
        "has_transcript": True,
        "transcript": {
            "id": str(transcript.id),
            "raw_text": transcript.raw_text,
            "detected_language": transcript.detected_language,
            "english_translation": transcript.english_translation,
            "translation_source": transcript.translation_source,
            "processing_latency_ms": transcript.processing_latency_ms,
            "verified_at": transcript.verified_at.isoformat() if transcript.verified_at else None,
            "created_at": transcript.created_at.isoformat(),
        },
        "segments": [
            {
                "id": str(s.id),
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
                "speech_confidence": s.speech_confidence,
                "review_status": s.review_status,
            }
            for s in segments
        ],
        "versions": [
            {
                "id": str(v.id),
                "version_number": v.version_number,
                "corrected_text": v.corrected_text,
                "change_summary": v.change_summary,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
        "entity_count": len(transcript.entities or []),
    }


# ── GET /voicemails/{id}/report ──────────────────────────────────────────────

@router.get("/{voicemail_id}/report")
async def get_voicemail_report(
    voicemail_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the detailed accuracy report for this voicemail."""
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    report_result = await db.execute(
        select(VoicemailReport).where(VoicemailReport.voicemail_id == voicemail_id)
    )
    report = report_result.scalar_one_or_none()

    if not report:
        # Try to generate it if transcription is complete
        if vm.processing_status == VoicemailProcessingStatus.COMPLETED:
            from app.services.voicemail_service import generate_voicemail_report
            await generate_voicemail_report(voicemail_id)
            # Re-fetch
            report_result2 = await db.execute(
                select(VoicemailReport).where(VoicemailReport.voicemail_id == voicemail_id)
            )
            report = report_result2.scalar_one_or_none()

    if not report:
        return {
            "voicemail_id": str(voicemail_id),
            "has_report": False,
            "processing_status": vm.processing_status.value,
            "message": "Report not yet available. Processing may be in progress.",
        }

    return {
        "voicemail_id": str(voicemail_id),
        "has_report": True,
        "overall_status": report.overall_status,
        "total_entities": report.total_entities,
        "flagged_entities": report.flagged_entities,
        "critical_risk_count": report.critical_risk_count,
        "has_negation_risk": report.has_negation_risk,
        "has_financial_risk": report.has_financial_risk,
        "speech_confidence": report.speech_confidence,
        "speech_confidence_note": (
            "Not available" if report.speech_confidence is None
            else f"{report.speech_confidence:.1%}"
        ),
        "findings": report.findings_json,
        "generated_at": report.generated_at.isoformat(),
    }


# ── POST /voicemails/{id}/reprocess ─────────────────────────────────────────

@router.post("/{voicemail_id}/reprocess", response_model=SuccessResponse)
async def reprocess_voicemail(
    voicemail_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Manually retry processing a voicemail that failed.
    Only allowed when processing_status is FAILED.
    """
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    if vm.processing_status not in {
        VoicemailProcessingStatus.FAILED,
        VoicemailProcessingStatus.QUEUED,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot reprocess voicemail in status '{vm.processing_status.value}'. "
                "Only FAILED or QUEUED voicemails can be reprocessed."
            ),
        )

    vm.processing_status = VoicemailProcessingStatus.QUEUED
    vm.error_message = None
    await db.commit()

    from app.services.voicemail_service import process_voicemail_recording
    background_tasks.add_task(process_voicemail_recording, voicemail_id)

    return SuccessResponse(
        success=True,
        message="Reprocessing started. The voicemail will be retranscribed.",
    )


# ── POST /voicemails/{id}/corrections ───────────────────────────────────────

@router.post("/{voicemail_id}/corrections", status_code=status.HTTP_201_CREATED)
async def save_voicemail_correction(
    voicemail_id: uuid.UUID,
    body: Annotated[dict, Body(
        openapi_examples={
            "basic": {
                "summary": "Correct transcript text",
                "value": {
                    "corrected_text": "Transfer fifty rupees, not fifteen rupees.",
                    "change_summary": "Corrected amount from transcript mishearing",
                },
            }
        }
    )],
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Save a user correction as a new TranscriptVersion.
    The original raw_text is NEVER modified.
    """
    vm = await _get_owned_voicemail(db, voicemail_id, current_user.id)

    if not vm.message_id:
        raise HTTPException(
            status_code=404,
            detail="No transcript found for this voicemail.",
        )

    transcript_result = await db.execute(
        select(Transcript)
        .where(
            Transcript.message_id == vm.message_id,
            Transcript.deleted_at.is_(None),
        )
        .order_by(Transcript.created_at.desc())
        .limit(1)
    )
    transcript = transcript_result.scalar_one_or_none()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found.")

    corrected_text = body.get("corrected_text", "").strip()
    if not corrected_text:
        raise HTTPException(status_code=422, detail="corrected_text is required and must not be empty.")

    # Get next version number
    last_version_result = await db.execute(
        select(TranscriptVersion.version_number)
        .where(TranscriptVersion.transcript_id == transcript.id)
        .order_by(TranscriptVersion.version_number.desc())
        .limit(1)
    )
    last_v = last_version_result.scalar_one_or_none()
    next_version = (last_v or 0) + 1

    version = TranscriptVersion(
        transcript_id=transcript.id,
        created_by_user_id=current_user.id,
        version_number=next_version,
        corrected_text=corrected_text,
        change_summary=body.get("change_summary"),
        corrections=body.get("corrections"),
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    return {
        "id": str(version.id),
        "transcript_id": str(version.transcript_id),
        "voicemail_id": str(voicemail_id),
        "version_number": version.version_number,
        "corrected_text": version.corrected_text,
        "change_summary": version.change_summary,
        "created_at": version.created_at.isoformat(),
    }


# ── Serializer ───────────────────────────────────────────────────────────────

def _serialize_voicemail(vm: Voicemail, detail: bool = False) -> dict:
    rec = vm.recording
    base = {
        "id": str(vm.id),
        "user_id": str(vm.user_id),
        "message_id": str(vm.message_id) if vm.message_id else None,
        "provider": vm.provider.value,
        "caller_number": vm.caller_number,
        "called_number": vm.called_number,
        "forward_reason": vm.forward_reason.value,
        "call_status": vm.call_status.value,
        "processing_status": vm.processing_status.value,
        "duration_seconds": vm.duration_seconds,
        "is_read": vm.is_read,
        "error_message": vm.error_message if detail else None,
        "created_at": vm.created_at.isoformat(),
        "updated_at": vm.updated_at.isoformat(),
        "recording": {
            "has_audio": bool(rec and rec.storage_key),
            "duration_seconds": rec.duration_seconds if rec else None,
            "size_bytes": rec.size_bytes if rec else None,
            "mime_type": rec.mime_type if rec else None,
        } if rec else {"has_audio": False},
    }
    return base
