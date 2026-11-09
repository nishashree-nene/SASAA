"""
SASAA – Alert Service
=======================
Creates PriorityAlert records from verification results.

Design rules:
  - One alert per distinct risk type per message (no spam)
  - Alert type maps directly to entity type and risk level
  - Alerts are only created for FLAGGED and CRITICAL entities,
    plus a catch-all VERIFICATION_REQUIRED when any entity needs review
  - Duplicate prevention: check for existing alerts of same type before inserting
"""

import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertSeverity, AlertType, PriorityAlert
from app.models.message import MessagePriority
from app.models.transcript import EntityType, RiskLevel, VerificationStatus
from app.verification.risk_scorer import ScoredEntity
from app.verification.verification_engine import VerificationSummary

logger = structlog.get_logger(__name__)


def _risk_to_severity(risk: RiskLevel) -> AlertSeverity:
    return {
        RiskLevel.CRITICAL: AlertSeverity.CRITICAL,
        RiskLevel.HIGH: AlertSeverity.HIGH,
        RiskLevel.MEDIUM: AlertSeverity.WARNING,
        RiskLevel.LOW: AlertSeverity.INFO,
    }[risk]


def _entity_to_alert_type(entity_type: EntityType) -> AlertType:
    mapping = {
        EntityType.AMOUNT: AlertType.FINANCIAL,
        EntityType.PHONE_NUMBER: AlertType.VERIFICATION_REQUIRED,
        EntityType.TIME: AlertType.TIME_SENSITIVE,
        EntityType.DATE: AlertType.TIME_SENSITIVE,
        EntityType.NEGATION: AlertType.HIGH_PRIORITY,
        EntityType.PERSON_NAME: AlertType.VERIFICATION_REQUIRED,
    }
    return mapping.get(entity_type, AlertType.SUSPICIOUS_TRANSCRIPT)


async def _alert_exists(
    db: AsyncSession,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    alert_type: AlertType,
) -> bool:
    """Check if an alert of this type already exists for the message."""
    result = await db.execute(
        select(PriorityAlert).where(
            PriorityAlert.message_id == message_id,
            PriorityAlert.user_id == user_id,
            PriorityAlert.alert_type == alert_type,
            PriorityAlert.deleted_at.is_(None),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_alerts_from_verification(
    db: AsyncSession,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    entities: list[ScoredEntity],
    summary: VerificationSummary,
) -> list[PriorityAlert]:
    """
    Create PriorityAlert records based on verification results.

    Only creates alerts for:
      - FLAGGED entities (verification_status=FLAGGED)
      - CRITICAL or HIGH risk entities
      - A catch-all VERIFICATION_REQUIRED when entities need review

    Returns the list of newly created alerts (not yet committed — caller commits).
    """
    created: list[PriorityAlert] = []

    # ── 1. Entity-specific alerts for high-risk findings ─────────────────
    # Deduplicate: only one alert per alert_type per message
    seen_alert_types: set[AlertType] = set()

    for entity in entities:
        # Only alert for FLAGGED or CRITICAL
        if entity.verification_status not in {
            VerificationStatus.FLAGGED,
        } and entity.risk_level not in {
            RiskLevel.CRITICAL, RiskLevel.HIGH,
        }:
            continue

        alert_type = _entity_to_alert_type(entity.entity_type)
        if alert_type in seen_alert_types:
            continue

        # Check database for existing alert of this type
        if await _alert_exists(db, message_id, user_id, alert_type):
            seen_alert_types.add(alert_type)
            continue

        seen_alert_types.add(alert_type)

        severity = _risk_to_severity(entity.risk_level)

        title = {
            AlertType.FINANCIAL: "Financial Amount Detected",
            AlertType.TIME_SENSITIVE: "Time-Sensitive Information",
            AlertType.HIGH_PRIORITY: "Negation Detected — Meaning May Be Reversed",
            AlertType.VERIFICATION_REQUIRED: "Critical Information Requires Verification",
            AlertType.SUSPICIOUS_TRANSCRIPT: "Suspicious Transcription Detected",
        }.get(alert_type, "Verification Required")

        suggested_action = {
            AlertType.FINANCIAL: "Listen to the original audio and verify the exact amount.",
            AlertType.TIME_SENSITIVE: "Verify the time or date against the original recording.",
            AlertType.HIGH_PRIORITY: (
                "Listen to the original audio carefully. "
                "A misheard or dropped 'not' reverses the entire instruction."
            ),
            AlertType.VERIFICATION_REQUIRED: "Review the extracted information against the original audio.",
            AlertType.SUSPICIOUS_TRANSCRIPT: "Review the flagged text against the original audio.",
        }.get(alert_type, "Review and confirm the transcription.")

        alert = PriorityAlert(
            message_id=message_id,
            user_id=user_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            reason=entity.reason,
            related_transcript_segment=entity.raw_value[:500],
            suggested_action=suggested_action,
        )
        db.add(alert)
        created.append(alert)

        logger.info(
            "Alert created",
            message_id=str(message_id),
            alert_type=alert_type.value,
            severity=severity.value,
            entity_type=entity.entity_type.value,
        )

    # ── 2. Catch-all VERIFICATION_REQUIRED alert ─────────────────────────
    if summary.needs_review_count > 0 or summary.flagged_count > 0:
        vr_type = AlertType.VERIFICATION_REQUIRED
        if vr_type not in seen_alert_types and not await _alert_exists(db, message_id, user_id, vr_type):
            severity = AlertSeverity.WARNING if summary.flagged_count == 0 else AlertSeverity.HIGH
            counts = []
            if summary.flagged_count:
                counts.append(f"{summary.flagged_count} flagged")
            if summary.needs_review_count:
                counts.append(f"{summary.needs_review_count} needing review")
            summary_text = " and ".join(counts)

            alert = PriorityAlert(
                message_id=message_id,
                user_id=user_id,
                alert_type=vr_type,
                severity=severity,
                title="Message Contains Items Requiring Verification",
                reason=f"Verification engine found {summary_text} in this message.",
                suggested_action="Open Message Analysis to review all flagged items.",
            )
            db.add(alert)
            created.append(alert)

    return created


def derive_message_priority(summary: VerificationSummary) -> MessagePriority:
    """
    Suggest a MessagePriority based on verification results.
    Called after verification to update the message's priority field.
    """
    if summary.critical_risk_count > 0:
        return MessagePriority.EMERGENCY
    if summary.high_risk_count > 0 or summary.has_negation:
        return MessagePriority.HIGH
    if summary.needs_review_count > 0:
        return MessagePriority.IMPORTANT
    return MessagePriority.NORMAL
