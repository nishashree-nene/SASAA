"""
SASAA – Voicemail Service
===========================
Business logic for the missed-call voicemail pipeline.

Lifecycle:
  received → recording → recorded → queued
  → transcribing → verifying → ready_for_review

Failure states:
  recording_failed | transcription_failed | verification_failed | processing_failed

Each step is idempotent — safe to retry after a crash.
The service does NOT block the webhook response: all heavy work
(download, transcription, verification) runs in background tasks.
"""

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.message import Message, MessageAudio, MessagePriority, MessageStatus
from app.models.voicemail import (
    ForwardReason,
    JobStatus,
    JobType,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    ProcessingJob,
    TelephonyEvent,
    TelephonyProvider,
    Voicemail,
    VoicemailCallStatus,
    VoicemailProcessingStatus,
    VoicemailRecording,
    VoicemailReport,
)
from app.telephony.provider_base import InboundCallEvent, RecordingInfo

logger = structlog.get_logger(__name__)


# ── Idempotency ───────────────────────────────────────────────────────────────

async def record_telephony_event(
    db: AsyncSession,
    provider: TelephonyProvider,
    provider_event_id: str,
    event_type: str,
    payload_hash: Optional[str] = None,
) -> tuple[bool, Optional[uuid.UUID]]:
    """
    Record a webhook event for idempotency checking.

    Returns (is_duplicate, voicemail_id).
    is_duplicate=True means this event was already processed.
    """
    existing = await db.execute(
        select(TelephonyEvent).where(
            TelephonyEvent.provider == provider,
            TelephonyEvent.provider_event_id == provider_event_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        logger.info(
            "Duplicate telephony event — skipping",
            provider=provider.value,
            event_id=provider_event_id,
        )
        return True, row.voicemail_id

    event = TelephonyEvent(
        provider=provider,
        provider_event_id=provider_event_id,
        event_type=event_type,
        received_at=datetime.now(timezone.utc),
        payload_hash=payload_hash,
    )
    db.add(event)
    await db.flush()
    return False, None


async def link_event_to_voicemail(
    db: AsyncSession,
    provider: TelephonyProvider,
    provider_event_id: str,
    voicemail_id: uuid.UUID,
) -> None:
    """Set voicemail_id on a previously inserted telephony event."""
    result = await db.execute(
        select(TelephonyEvent).where(
            TelephonyEvent.provider == provider,
            TelephonyEvent.provider_event_id == provider_event_id,
        )
    )
    event = result.scalar_one_or_none()
    if event:
        event.voicemail_id = voicemail_id


# ── Voicemail creation ────────────────────────────────────────────────────────

async def get_or_create_voicemail(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider: TelephonyProvider,
    event: InboundCallEvent,
) -> tuple[Voicemail, bool]:
    """
    Get an existing voicemail for this call or create a new one.

    Returns (voicemail, created_new).
    Uses the (provider, provider_call_id) unique constraint for idempotency.
    """
    existing = await db.execute(
        select(Voicemail).where(
            Voicemail.provider == provider,
            Voicemail.provider_call_id == event.provider_call_id,
        )
    )
    voicemail = existing.scalar_one_or_none()
    if voicemail:
        return voicemail, False

    reason_map = {
        "busy": ForwardReason.BUSY,
        "no_answer": ForwardReason.NO_ANSWER,
        "unreachable": ForwardReason.UNREACHABLE,
        "rejected": ForwardReason.REJECTED,
    }
    forward_reason = reason_map.get(event.forward_reason, ForwardReason.UNKNOWN)

    voicemail = Voicemail(
        user_id=user_id,
        provider=provider,
        provider_call_id=event.provider_call_id,
        caller_number=event.caller_number or None,
        called_number=event.called_number or None,
        forward_reason=forward_reason,
        call_status=VoicemailCallStatus.RECEIVED,
        processing_status=VoicemailProcessingStatus.QUEUED,
        call_started_at=datetime.now(timezone.utc),
        is_read=False,
    )
    db.add(voicemail)
    await db.flush()

    logger.info(
        "Voicemail created",
        voicemail_id=str(voicemail.id),
        caller=event.caller_number,
        provider=provider.value,
    )
    return voicemail, True


async def mark_voicemail_recording(
    db: AsyncSession,
    voicemail: Voicemail,
    recording_info: Optional[RecordingInfo] = None,
) -> None:
    """Update voicemail status when a recording is available."""
    voicemail.call_status = (
        VoicemailCallStatus.RECORDED if recording_info
        else VoicemailCallStatus.RECORDING
    )
    voicemail.call_ended_at = datetime.now(timezone.utc)

    if recording_info:
        # Store recording metadata
        rec = VoicemailRecording(
            voicemail_id=voicemail.id,
            provider_recording_url=recording_info.provider_recording_url,
            provider_recording_id=recording_info.provider_recording_id,
            mime_type=recording_info.mime_type,
            duration_seconds=recording_info.duration_seconds,
        )
        db.add(rec)

        if voicemail.call_started_at and recording_info.duration_seconds:
            voicemail.duration_seconds = int(recording_info.duration_seconds)

    await db.flush()


async def create_processing_job(
    db: AsyncSession,
    voicemail_id: uuid.UUID,
    job_type: JobType,
    payload: Optional[dict] = None,
    max_attempts: int = 3,
) -> ProcessingJob:
    """Create a processing job for this voicemail."""
    job = ProcessingJob(
        voicemail_id=voicemail_id,
        job_type=job_type,
        status=JobStatus.PENDING,
        attempts=0,
        max_attempts=max_attempts,
        payload=payload or {},
    )
    db.add(job)
    await db.flush()
    return job


# ── Background processing ─────────────────────────────────────────────────────

async def process_voicemail_recording(voicemail_id: uuid.UUID) -> None:
    """
    Background task: download recording → create message → trigger transcription.


    Uses SEPARATE database sessions for each step to avoid expired-object
    issues after commits. Each step is idempotent — safe to retry after a crash.
    """
    log = logger.bind(voicemail_id=str(voicemail_id))
    log.info("Processing voicemail recording")

    # ── Step 1: Load voicemail + recording metadata ────────────────────────
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Voicemail)
            .options(selectinload(Voicemail.recording))
            .where(Voicemail.id == voicemail_id)
        )
        voicemail = result.scalar_one_or_none()
        if not voicemail:
            log.error("Voicemail not found in background task")
            return

        recording = voicemail.recording
        # Capture all values we need BEFORE any commit (objects expire after commit)
        vm_user_id = voicemail.user_id
        vm_caller_number = voicemail.caller_number
        vm_message_id = voicemail.message_id
        rec_provider_url = recording.provider_recording_url if recording else None
        rec_storage_key = recording.storage_key if recording else None
        rec_mime_type = recording.mime_type if recording else None
        rec_size_bytes = recording.size_bytes if recording else None
        rec_duration = recording.duration_seconds if recording else None

    # ── Step 2: Download recording if URL available and not yet downloaded ───
    if rec_provider_url and not rec_storage_key:
        log.info("Downloading recording", url=rec_provider_url[:80])

        # Mark as DOWNLOADING in its own session
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Voicemail).where(Voicemail.id == voicemail_id))
            vm = r.scalar_one_or_none()
            if vm:
                vm.processing_status = VoicemailProcessingStatus.DOWNLOADING
            await db.commit()

        try:
            storage_path = _make_storage_path(str(vm_user_id), str(voicemail_id))

            from app.telephony.registry import get_provider
            provider = get_provider()

            size, mime = await provider.download_recording(
                rec_provider_url,
                str(storage_path),
            )

            checksum = _sha256_file(storage_path)
            log.info("Recording downloaded", size=size, mime=mime, checksum=checksum[:16])

            # Save recording metadata in its own session
            async with AsyncSessionLocal() as db:
                r2 = await db.execute(
                    select(VoicemailRecording)
                    .where(VoicemailRecording.voicemail_id == voicemail_id)
                )
                rec2 = r2.scalar_one_or_none()
                if rec2:
                    rec2.storage_key = str(storage_path)
                    rec2.size_bytes = size
                    rec2.mime_type = mime
                    rec2.checksum_sha256 = checksum
                    retention_days = 90
                    rec2.retention_until = datetime.now(timezone.utc) + timedelta(days=retention_days)
                await db.commit()

            # Update local variables for next step
            rec_storage_key = str(storage_path)
            rec_mime_type = mime
            rec_size_bytes = size

        except Exception as exc:
            log.error("Recording download failed", error=str(exc))
            async with AsyncSessionLocal() as db_err:
                r = await db_err.execute(select(Voicemail).where(Voicemail.id == voicemail_id))
                vm = r.scalar_one_or_none()
                if vm:
                    vm.processing_status = VoicemailProcessingStatus.FAILED
                    vm.error_message = f"Recording download failed: {str(exc)[:500]}"
                await db_err.commit()
            return

    elif not rec_storage_key:
        log.warning("No recording available yet — deferring processing")
        return

    # ── Step 3: Create the messages record (if not already created) ────────
    if vm_message_id:
        log.info("Voicemail already has message_id — skipping message creation")
    elif not rec_storage_key:
        log.warning("Cannot create message: no recording storage_key")
        return
    else:
        log.info("Creating message record for voicemail")
        async with AsyncSessionLocal() as db:
            message = Message(
                user_id=vm_user_id,
                caller_name=None,
                caller_phone=vm_caller_number,
                status=MessageStatus.UPLOADED,
                priority=MessagePriority.NORMAL,
                is_read=False,
                is_archived=False,
            )
            db.add(message)
            await db.flush()

            audio_record = MessageAudio(
                message_id=message.id,
                original_filename=Path(rec_storage_key).name,
                storage_path=rec_storage_key,
                mime_type=rec_mime_type or "audio/mpeg",
                file_size_bytes=rec_size_bytes or 0,
                duration_seconds=rec_duration,
            )
            db.add(audio_record)

            # Link voicemail to message
            r = await db.execute(select(Voicemail).where(Voicemail.id == voicemail_id))
            vm = r.scalar_one_or_none()
            if vm:
                vm.message_id = message.id
                vm.processing_status = VoicemailProcessingStatus.TRANSCRIBING

            await db.commit()
            vm_message_id = message.id
            log.info("Message record created", message_id=str(message.id))

    # ── Step 4: Trigger transcription pipeline ──────────────────────────────
    if vm_message_id and rec_storage_key:
        log.info("Triggering transcription", message_id=str(vm_message_id))

        # Mark voicemail as transcribing
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Voicemail).where(Voicemail.id == voicemail_id))
            vm = r.scalar_one_or_none()
            if vm:
                vm.processing_status = VoicemailProcessingStatus.TRANSCRIBING
            await db.commit()

        # Reuse the existing transcription background task
        from app.api.v1.transcription import _run_transcription_background
        await _run_transcription_background(
            message_id=vm_message_id,
            audio_file_path=rec_storage_key,
            language_code="ta-IN",
            mime_type=rec_mime_type or "audio/mpeg",
            user_id=vm_user_id,
        )

    # ── Step 5: Mark voicemail complete ─────────────────────────────────────
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Voicemail).where(Voicemail.id == voicemail_id))
        vm = r.scalar_one_or_none()
        if vm:
            vm.processing_status = VoicemailProcessingStatus.COMPLETED
        await db.commit()

    log.info("Voicemail processing complete")

    # ── Step 6: Send notification ───────────────────────────────────────────
    await _send_voicemail_notification(voicemail_id, str(vm_user_id))

    # ── Step 7: Generate voicemail report ──────────────────────────────────
    # Give the verification engine a moment to complete
    await asyncio.sleep(3)
    await generate_voicemail_report(voicemail_id)


# ── Notification ──────────────────────────────────────────────────────────────

async def _send_voicemail_notification(voicemail_id: uuid.UUID, user_id: str) -> None:
    """
    Create in-app notification delivery record.
    Actual push delivery (FCM/web push) fires when the NotificationDelivery
    record exists and the worker processes it.
    """
    try:
        async with AsyncSessionLocal() as db:
            delivery = NotificationDelivery(
                user_id=uuid.UUID(user_id),
                voicemail_id=voicemail_id,
                channel=NotificationChannel.PUSH_ANDROID,
                status=NotificationDeliveryStatus.PENDING,
                event_type="new_voicemail",
            )
            db.add(delivery)
            try:
                await db.commit()
                logger.info("Notification queued", voicemail_id=str(voicemail_id))
            except Exception:
                await db.rollback()
                logger.info(
                    "Notification already exists (duplicate) — skipping",
                    voicemail_id=str(voicemail_id),
                )
    except Exception as exc:
        logger.warning("Failed to queue notification", error=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_storage_path(user_id: str, voicemail_id: str) -> Path:
    """Return the absolute path where the voicemail recording should be stored."""
    base = Path(settings.audio_storage_path)
    dest_dir = base / user_id / "voicemails"
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"{voicemail_id}.mp3"


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Voicemail report generation ───────────────────────────────────────────────

async def generate_voicemail_report(voicemail_id: uuid.UUID) -> None:
    """
    Generate the detailed accuracy report for a voicemail after
    transcription and verification are complete.
    """
    log = logger.bind(voicemail_id=str(voicemail_id))

    async with AsyncSessionLocal() as db:
        try:
            # Load voicemail and its linked message
            result = await db.execute(
                select(Voicemail).where(Voicemail.id == voicemail_id)
            )
            voicemail = result.scalar_one_or_none()
            if not voicemail or not voicemail.message_id:
                log.warning("Cannot generate report: no linked message")
                return

            # Load verification results via the message
            from app.models.transcript import ExtractedEntity, Transcript, VerificationResult
            from app.models.transcript import RiskLevel, VerificationStatus

            transcript_result = await db.execute(
                select(Transcript)
                .options(selectinload(Transcript.entities))
                .where(
                    Transcript.message_id == voicemail.message_id,
                    Transcript.deleted_at.is_(None),
                )
                .order_by(Transcript.created_at.desc())
                .limit(1)
            )
            transcript = transcript_result.scalar_one_or_none()

            if not transcript:
                log.info("No transcript yet — report deferred")
                return

            entities = transcript.entities or []

            # Load verification results for each entity
            entity_ids = [e.id for e in entities]
            vr_result = await db.execute(
                select(VerificationResult).where(
                    VerificationResult.entity_id.in_(entity_ids)
                )
            )
            vr_map = {vr.entity_id: vr for vr in vr_result.scalars()}

            # Build findings
            flagged = sum(
                1 for e in entities
                if vr_map.get(e.id) and vr_map[e.id].verification_status == VerificationStatus.FLAGGED
            )
            critical = sum(
                1 for e in entities
                if vr_map.get(e.id) and vr_map[e.id].risk_level == RiskLevel.CRITICAL
            )
            has_negation = any(e.entity_type.value == "NEGATION" for e in entities)
            has_financial = any(e.entity_type.value == "AMOUNT" for e in entities)

            overall = (
                "high_risk" if critical > 0 or flagged > 2
                else "needs_review" if flagged > 0 or len(entities) > 0
                else "clean"
            )

            findings = {
                "transcript": {
                    "raw_text": transcript.raw_text,
                    "detected_language": transcript.detected_language,
                    "english_translation": transcript.english_translation,
                },
                "entities": [
                    {
                        "id": str(e.id),
                        "entity_type": e.entity_type.value,
                        "raw_value": e.raw_value,
                        "normalized_value": e.normalized_value,
                        "has_ambiguity": e.has_ambiguity,
                        "ambiguity_reason": e.ambiguity_reason,
                        "verification_status": (
                            vr_map[e.id].verification_status.value
                            if e.id in vr_map else "not_evaluated"
                        ),
                        "risk_level": (
                            vr_map[e.id].risk_level.value
                            if e.id in vr_map and vr_map[e.id].risk_level else "low"
                        ),
                        "reason": vr_map[e.id].reason if e.id in vr_map else None,
                        "char_start": e.char_start,
                        "char_end": e.char_end,
                    }
                    for e in entities
                ],
                "audio_quality": {
                    "speech_confidence_note": (
                        "Gnani API v3 does not return per-segment confidence scores. "
                        "Display: Not available."
                    ),
                },
                "warnings": [
                    {
                        "type": "speech_recognition",
                        "message": (
                            "Speech recognition errors can affect accuracy, especially "
                            "for numbers, names and time expressions. "
                            "Listen to the original recording to verify critical details."
                        ),
                    }
                ],
            }

            # Check if report already exists
            existing_report = await db.execute(
                select(VoicemailReport).where(VoicemailReport.voicemail_id == voicemail_id)
            )
            report = existing_report.scalar_one_or_none()

            if report:
                # Update existing report
                report.overall_status = overall
                report.total_entities = len(entities)
                report.flagged_entities = flagged
                report.critical_risk_count = critical
                report.has_negation_risk = has_negation
                report.has_financial_risk = has_financial
                report.findings_json = findings
                report.generated_at = datetime.now(timezone.utc)
            else:
                report = VoicemailReport(
                    voicemail_id=voicemail_id,
                    overall_status=overall,
                    total_entities=len(entities),
                    flagged_entities=flagged,
                    critical_risk_count=critical,
                    has_negation_risk=has_negation,
                    has_financial_risk=has_financial,
                    speech_confidence=None,  # Gnani v3 doesn't provide this
                    findings_json=findings,
                    generated_at=datetime.now(timezone.utc),
                )
                db.add(report)

            await db.commit()
            log.info(
                "Report generated",
                overall=overall,
                entities=len(entities),
                flagged=flagged,
            )

        except Exception as exc:
            log.error("Report generation failed", error=str(exc), exc_info=True)
