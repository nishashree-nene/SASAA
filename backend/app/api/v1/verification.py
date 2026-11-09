"""
SASAA – Verification Routes
==============================
POST /messages/{id}/verify        – run the verification engine
GET  /messages/{id}/verification  – get verification results and entities
POST /messages/{id}/corrections   – save user corrections as a new TranscriptVersion

Security:
  - Every endpoint verifies message ownership
  - Ownership check returns 404 for both not-found and not-owned (no info leak)
  - Corrections never modify the immutable raw_text — only add new versions

Immutability rule:
  Transcript.raw_text is set once by the transcription pipeline and NEVER updated.
  User corrections are stored in TranscriptVersion rows with version_number 1, 2, …
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal, get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message, MessagePriority, MessageStatus
from app.models.transcript import (
    ExtractedEntity, EntityType, Transcript, TranscriptVersion,
    VerificationResult, VerificationStatus,
)
from app.schemas.common import SuccessResponse
from app.schemas.verification import (
    CorrectionRequest,
    CorrectionResponse,
    ExtractedEntityResponse,
    VerificationResultResponse,
)
from app.services.alert_service import create_alerts_from_verification, derive_message_priority
from app.verification.verification_engine import run_verification

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["Verification"])


# ── Ownership helper ──────────────────────────────────────────────────────────

async def _get_owned_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Message:
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
            Message.deleted_at.is_(None),
        )
    )
    msg = result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    return msg


async def _get_active_transcript(
    db: AsyncSession,
    message_id: uuid.UUID,
) -> Transcript | None:
    result = await db.execute(
        select(Transcript).where(
            Transcript.message_id == message_id,
            Transcript.deleted_at.is_(None),
        ).order_by(Transcript.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


# ── POST /messages/{message_id}/verify ───────────────────────────────────────

@router.post(
    "/messages/{message_id}/verify",
    response_model=SuccessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run the verification engine on a completed transcript",
)
async def run_verification_route(
    message_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Trigger entity extraction and risk assessment on a completed transcript.

    Returns HTTP 202 immediately — verification runs in the background.
    Poll GET /messages/{id}/verification for results.

    The pipeline:
      COMPLETED → ANALYZING → COMPLETED (or NEEDS_VERIFICATION)

    Errors:
      404 – Message not found
      404 – No transcript exists (transcription must run first)
      409 – Verification already completed for this message
      409 – Another verification is in progress
    """
    msg = await _get_owned_message(db, message_id, current_user.id)

    # Must have a transcript
    transcript = await _get_active_transcript(db, message_id)
    if transcript is None:
        raise HTTPException(
            status_code=404,
            detail="No transcript found. Run transcription first via POST /messages/{id}/transcribe.",
        )

    # Prevent re-running if verification already completed
    # (check both entities AND verified_at to handle 0-entity results)
    existing = await db.execute(
        select(ExtractedEntity.id).where(
            ExtractedEntity.transcript_id == transcript.id,
            ExtractedEntity.deleted_at.is_(None),
        ).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Verification has already been run for this message.",
        )
    if transcript.verified_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Verification has already been run for this message (0 entities found).",
        )

    # Only run on completed transcripts
    if msg.status not in {
        MessageStatus.COMPLETED, MessageStatus.NEEDS_VERIFICATION, MessageStatus.FAILED
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Message is not ready for verification (status: {msg.status.value}). "
                   "Wait for transcription to complete.",
        )

    # Mark as analyzing immediately
    msg.status = MessageStatus.ANALYZING
    await db.commit()

    background_tasks.add_task(
        _run_verification_background,
        message_id=message_id,
        transcript_id=transcript.id,
        raw_text=transcript.raw_text,
        user_id=current_user.id,
    )

    return SuccessResponse(
        success=True,
        message="Verification started. Poll GET /messages/{id}/verification for results.",
    )


async def _run_verification_background(
    message_id: uuid.UUID,
    transcript_id: uuid.UUID,
    raw_text: str,
    user_id: uuid.UUID,
) -> None:
    """
    Background task: run verification engine, persist results, create alerts.
    Creates its own database session (separate from the transcription session).
    Sets verified_at on the transcript so the GET endpoint knows verification ran.
    """
    from datetime import datetime, timezone as _tz

    log = logger.bind(message_id=str(message_id))
    log.info("Verification background task started")

    async with AsyncSessionLocal() as db:
        try:
            # ── Step 1: Run engine (synchronous/CPU) in a thread ──────────
            loop = asyncio.get_event_loop()
            entities, summary = await loop.run_in_executor(
                None, run_verification, raw_text
            )
            log.info(
                "Verification engine completed",
                total=summary.total_entities,
                flagged=summary.flagged_count,
                critical=summary.critical_risk_count,
            )

            # ── Step 2: Mark transcript as verified (even with 0 entities) ─
            tr_result = await db.execute(
                select(Transcript).where(Transcript.id == transcript_id)
            )
            tr_obj = tr_result.scalar_one_or_none()
            if tr_obj:
                tr_obj.verified_at = datetime.now(_tz.utc)
                await db.flush()

            # ── Step 3: Persist entities and verification results ──────────
            for scored in entities:
                entity = ExtractedEntity(
                    transcript_id=transcript_id,
                    entity_type=scored.entity_type,
                    raw_value=scored.raw_value[:5000],
                    normalized_value=(scored.normalized_value or "")[:1000] or None,
                    suggested_interpretation=(scored.suggested_interpretation or "")[:1000] or None,
                    has_ambiguity=scored.has_ambiguity,
                    ambiguity_reason=(scored.ambiguity_reason or "")[:2000] or None,
                    extraction_confidence=scored.extraction_confidence,
                    char_start=scored.char_start,
                    char_end=scored.char_end,
                )
                db.add(entity)
                await db.flush()  # get entity.id

                vr = VerificationResult(
                    entity_id=entity.id,
                    verification_status=scored.verification_status,
                    risk_level=scored.risk_level,
                    evidence=scored.evidence,
                    reason=(scored.reason or "")[:2000] or None,
                )
                db.add(vr)

            await db.flush()

            # ── Step 4: Create alerts ──────────────────────────────────────
            await create_alerts_from_verification(
                db=db,
                message_id=message_id,
                user_id=user_id,
                entities=entities,
                summary=summary,
            )

            # ── Step 5: Update message status and priority ─────────────────
            msg_result = await db.execute(
                select(Message).where(Message.id == message_id)
            )
            msg = msg_result.scalar_one_or_none()
            if msg:
                msg.status = (
                    MessageStatus.NEEDS_VERIFICATION
                    if summary.message_needs_verification
                    else MessageStatus.COMPLETED
                )
                msg.priority = derive_message_priority(summary)

            await db.commit()
            log.info(
                "Verification persisted",
                entities_saved=len(entities),
                final_status=msg.status.value if msg else "unknown",
            )

        except Exception as exc:
            log.error("Verification background task failed", error=str(exc), exc_info=True)
            await db.rollback()
            # Safety: restore COMPLETED so message is not stuck in ANALYZING
            try:
                async with AsyncSessionLocal() as db2:
                    r = await db2.execute(select(Message).where(Message.id == message_id))
                    m = r.scalar_one_or_none()
                    if m and m.status == MessageStatus.ANALYZING:
                        m.status = MessageStatus.COMPLETED
                        m.error_message = f"Verification failed: {type(exc).__name__}"
                        await db2.commit()
            except Exception:
                pass


# ── GET /messages/{message_id}/verification ──────────────────────────────────

@router.get(
    "/messages/{message_id}/verification",
    response_model=VerificationResultResponse,
    summary="Get extracted entities and verification results",
)
async def get_verification_results(
    message_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return all extracted entities for this message with their risk assessments.

    Each entity includes:
      - entity_type (PHONE_NUMBER, AMOUNT, TIME, DATE, NEGATION, …)
      - raw_value (exact text from transcript)
      - normalized_value (cleaned representation)
      - has_ambiguity + ambiguity_reason
      - verification_status (FLAGGED, NEEDS_REVIEW, VERIFIED, …)
      - risk_level (CRITICAL, HIGH, MEDIUM, LOW)
      - reason (plain-language explanation)
      - user_decision (ACCEPTED / REJECTED / EDITED, if set)
    """
    msg = await _get_owned_message(db, message_id, current_user.id)
    transcript = await _get_active_transcript(db, message_id)

    if transcript is None:
        return VerificationResultResponse(
            message_id=message_id,
            status=msg.status.value,
            has_results=False,
            message="No transcript found. Run transcription first.",
        )

    # Load entities with their verification results
    entity_result = await db.execute(
        select(ExtractedEntity)
        .options(selectinload(ExtractedEntity.verification_result))
        .where(
            ExtractedEntity.transcript_id == transcript.id,
            ExtractedEntity.deleted_at.is_(None),
        )
        .order_by(ExtractedEntity.char_start.asc().nullslast())
    )
    entities = entity_result.scalars().all()

    if not entities:
        if msg.status == MessageStatus.ANALYZING:
            return VerificationResultResponse(
                message_id=message_id,
                status=msg.status.value,
                has_results=False,
                message="Verification is in progress. Please wait.",
            )
        # Check if verification has run (even with 0 results)
        if transcript.verified_at is not None:
            return VerificationResultResponse(
                message_id=message_id,
                status=msg.status.value,
                has_results=True,   # ran, found nothing — that's a valid result
                entities=[],
                total_entities=0,
                flagged_count=0,
                needs_review_count=0,
                verified_count=0,
                critical_risk_count=0,
                high_risk_count=0,
                message="Verification complete. No critical entities detected in this transcript.",
            )
        return VerificationResultResponse(
            message_id=message_id,
            status=msg.status.value,
            has_results=False,
            message=(
                "Verification has not been run yet. Use POST /messages/{id}/verify to start."
                if msg.status in {MessageStatus.COMPLETED, MessageStatus.NEEDS_VERIFICATION}
                else f"Message status: {msg.status.value}. Transcription must complete first."
            ),
        )

    # Build response items
    items: list[ExtractedEntityResponse] = []
    flagged = needs_review = verified = critical = high = 0

    for ent in entities:
        vr = ent.verification_result
        item = ExtractedEntityResponse(
            id=ent.id,
            entity_type=ent.entity_type.value,
            raw_value=ent.raw_value,
            normalized_value=ent.normalized_value,
            suggested_interpretation=ent.suggested_interpretation,
            has_ambiguity=ent.has_ambiguity,
            ambiguity_reason=ent.ambiguity_reason,
            extraction_confidence=ent.extraction_confidence,
            char_start=ent.char_start,
            char_end=ent.char_end,
            verification_status=vr.verification_status.value if vr else None,
            risk_level=vr.risk_level.value if vr and vr.risk_level else None,
            reason=vr.reason if vr else None,
            evidence=vr.evidence if vr else None,
            user_decision=vr.user_decision if vr else None,
            user_correction=vr.user_correction if vr else None,
            user_decided_at=vr.user_decided_at if vr else None,
        )
        items.append(item)
        if vr:
            if vr.verification_status == VerificationStatus.FLAGGED:
                flagged += 1
            elif vr.verification_status == VerificationStatus.NEEDS_REVIEW:
                needs_review += 1
            elif vr.verification_status == VerificationStatus.VERIFIED:
                verified += 1
            from app.models.transcript import RiskLevel
            if vr.risk_level == RiskLevel.CRITICAL:
                critical += 1
            elif vr.risk_level == RiskLevel.HIGH:
                high += 1

    return VerificationResultResponse(
        message_id=message_id,
        status=msg.status.value,
        has_results=True,
        entities=items,
        total_entities=len(items),
        flagged_count=flagged,
        needs_review_count=needs_review,
        verified_count=verified,
        critical_risk_count=critical,
        high_risk_count=high,
        message=f"Found {len(items)} entities. {flagged} flagged, {needs_review} needing review.",
    )


# ── POST /messages/{message_id}/corrections ──────────────────────────────────

@router.post(
    "/messages/{message_id}/corrections",
    response_model=CorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a user correction as a new transcript version",
)
async def save_corrections(
    message_id: uuid.UUID,
    body: Annotated[CorrectionRequest, Body(
        openapi_examples={
            "basic": {
                "summary": "Simple text correction",
                "value": {
                    "corrected_text": "Transfer fifty rupees, not fifteen rupees.",
                    "change_summary": "Corrected amount from transcript mishearing",
                },
            },
            "with_entity_corrections": {
                "summary": "Correction with structured entity list",
                "value": {
                    "corrected_text": "Transfer fifty rupees, not fifteen rupees.",
                    "change_summary": "Fixed amounts",
                    "corrections": [
                        {
                            "entity_id": "uuid-of-entity",
                            "original": "fity",
                            "corrected": "fifty",
                            "action": "EDITED",
                        }
                    ],
                },
            },
        }
    )],
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Save a user correction as a new TranscriptVersion.

    IMMUTABILITY GUARANTEE:
    The original Transcript.raw_text is NEVER modified. Corrections
    are stored as separate TranscriptVersion rows with an incrementing
    version_number. The user can always view the original.

    Each POST creates one new version. Version numbers start at 1.

    Errors:
      404 – Message not found
      404 – No transcript to correct
    """
    await _get_owned_message(db, message_id, current_user.id)

    transcript = await _get_active_transcript(db, message_id)
    if transcript is None:
        raise HTTPException(
            status_code=404,
            detail="No transcript found. Transcription must complete before corrections can be saved.",
        )

    # Determine next version number
    existing_versions = await db.execute(
        select(TranscriptVersion.version_number)
        .where(TranscriptVersion.transcript_id == transcript.id)
        .order_by(TranscriptVersion.version_number.desc())
        .limit(1)
    )
    last_version = existing_versions.scalar_one_or_none()
    next_version = (last_version or 0) + 1

    # Create the new version — raw_text on transcript is UNTOUCHED
    version = TranscriptVersion(
        transcript_id=transcript.id,
        created_by_user_id=current_user.id,
        version_number=next_version,
        corrected_text=body.corrected_text,
        change_summary=body.change_summary,
        corrections=body.corrections,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    logger.info(
        "Transcript correction saved",
        message_id=str(message_id),
        transcript_id=str(transcript.id),
        version_number=next_version,
        user_id=str(current_user.id),
    )

    return CorrectionResponse(
        id=version.id,
        transcript_id=version.transcript_id,
        version_number=version.version_number,
        corrected_text=version.corrected_text,
        change_summary=version.change_summary,
        created_at=version.created_at,
    )
