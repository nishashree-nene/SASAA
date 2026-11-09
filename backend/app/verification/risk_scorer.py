"""
SASAA – Risk Scorer
=====================
Assigns a RiskLevel and VerificationStatus to each extracted entity
based on transparent, explainable rules.

Design rules:
  - Rules are explicit and documented — no opaque ML scores
  - We never invent certainty; NEEDS_REVIEW is the default
  - Financial ambiguity and negation errors get the highest risk
  - Risk is based on entity type + ambiguity + context, not word matching alone
"""

from dataclasses import dataclass
from typing import Any, Optional

from app.models.transcript import EntityType, RiskLevel, VerificationStatus


@dataclass
class ScoredEntity:
    entity_type: EntityType
    raw_value: str
    normalized_value: Optional[str]
    suggested_interpretation: Optional[str]
    has_ambiguity: bool
    ambiguity_reason: Optional[str]
    extraction_confidence: float
    char_start: Optional[int]
    char_end: Optional[int]
    # Risk assessment
    verification_status: VerificationStatus
    risk_level: RiskLevel
    reason: str
    evidence: dict[str, Any]


def _build_evidence(entity_type: EntityType, raw: str, normalized: Optional[str],
                    has_ambiguity: bool, confidence: float) -> dict:
    """Build a structured evidence dict stored in VerificationResult.evidence."""
    return {
        "entity_type": entity_type.value,
        "raw_value": raw[:200],
        "normalized_value": normalized,
        "has_ambiguity": has_ambiguity,
        "extraction_confidence": round(confidence, 3),
        "scoring_method": "rule_based_v1",
    }


def score_entity(
    entity_type: EntityType,
    raw_value: str,
    normalized_value: Optional[str],
    suggested_interpretation: Optional[str],
    has_ambiguity: bool,
    ambiguity_reason: Optional[str],
    extraction_confidence: float,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> ScoredEntity:
    """
    Assign risk level and verification status to a single extracted entity.

    Rules (in priority order):
    ┌────────────────────────────────────────────────────────────────────┐
    │ Entity Type     │ Ambiguous?  │ Risk     │ Status              │
    ├────────────────────────────────────────────────────────────────────┤
    │ NEGATION         │ always      │ HIGH     │ NEEDS_REVIEW        │
    │ AMOUNT           │ yes         │ CRITICAL │ FLAGGED             │
    │ AMOUNT           │ no          │ HIGH     │ NEEDS_REVIEW        │
    │ PHONE_NUMBER     │ yes         │ HIGH     │ NEEDS_REVIEW        │
    │ PHONE_NUMBER     │ no          │ MEDIUM   │ NEEDS_REVIEW        │
    │ TIME             │ yes (no AM) │ HIGH     │ FLAGGED             │
    │ TIME             │ no          │ LOW      │ VERIFIED            │
    │ DATE             │ yes         │ MEDIUM   │ NEEDS_REVIEW        │
    │ DATE             │ no          │ LOW      │ VERIFIED            │
    │ PERSON_NAME      │ always      │ MEDIUM   │ NEEDS_REVIEW        │
    │ NUMBER           │ no          │ LOW      │ NOT_EVALUATED       │
    │ OTHER            │ any         │ LOW      │ NOT_EVALUATED       │
    └────────────────────────────────────────────────────────────────────┘
    """
    evidence = _build_evidence(entity_type, raw_value, normalized_value,
                               has_ambiguity, extraction_confidence)

    # ── NEGATION: always high risk regardless of confidence ──────────────
    if entity_type == EntityType.NEGATION:
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=has_ambiguity,
            ambiguity_reason=ambiguity_reason,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.NEEDS_REVIEW,
            risk_level=RiskLevel.HIGH,
            reason=(
                "Negation detected. Dropped or misheard negation words reverse the "
                "meaning of an instruction. Verify the intended meaning is preserved."
            ),
            evidence=evidence,
        )

    # ── AMOUNT ────────────────────────────────────────────────────────────
    if entity_type == EntityType.AMOUNT:
        if has_ambiguity:
            return ScoredEntity(
                entity_type=entity_type,
                raw_value=raw_value,
                normalized_value=normalized_value,
                suggested_interpretation=suggested_interpretation,
                has_ambiguity=has_ambiguity,
                ambiguity_reason=ambiguity_reason,
                extraction_confidence=extraction_confidence,
                char_start=char_start,
                char_end=char_end,
                verification_status=VerificationStatus.FLAGGED,
                risk_level=RiskLevel.CRITICAL,
                reason=(
                    "Ambiguous financial amount detected. Speech recognition errors "
                    "on numbers (e.g. fifteen vs fifty) can cause significant financial "
                    "harm. Verify against the original recording."
                ),
                evidence=evidence,
            )
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=False,
            ambiguity_reason=None,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.NEEDS_REVIEW,
            risk_level=RiskLevel.HIGH,
            reason="Financial amount detected. Verify the value is correct.",
            evidence=evidence,
        )

    # ── PHONE_NUMBER ──────────────────────────────────────────────────────
    if entity_type == EntityType.PHONE_NUMBER:
        risk = RiskLevel.HIGH if has_ambiguity else RiskLevel.MEDIUM
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=has_ambiguity,
            ambiguity_reason=ambiguity_reason,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.NEEDS_REVIEW,
            risk_level=risk,
            reason=(
                "Phone number detected. "
                + ("Digit count does not match standard format — please verify. " if has_ambiguity else "")
                + "Compare with the original audio to ensure digits are correct."
            ),
            evidence=evidence,
        )

    # ── TIME ──────────────────────────────────────────────────────────────
    if entity_type == EntityType.TIME:
        if has_ambiguity:
            return ScoredEntity(
                entity_type=entity_type,
                raw_value=raw_value,
                normalized_value=normalized_value,
                suggested_interpretation=suggested_interpretation,
                has_ambiguity=True,
                ambiguity_reason=ambiguity_reason,
                extraction_confidence=extraction_confidence,
                char_start=char_start,
                char_end=char_end,
                verification_status=VerificationStatus.FLAGGED,
                risk_level=RiskLevel.HIGH,
                reason=(
                    "Time detected without explicit AM/PM. "
                    "5 AM and 5 PM are completely different — verify the intended time."
                ),
                evidence=evidence,
            )
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=False,
            ambiguity_reason=None,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.VERIFIED,
            risk_level=RiskLevel.LOW,
            reason="Time with explicit AM/PM extracted.",
            evidence=evidence,
        )

    # ── DATE ──────────────────────────────────────────────────────────────
    if entity_type == EntityType.DATE:
        if has_ambiguity:
            return ScoredEntity(
                entity_type=entity_type,
                raw_value=raw_value,
                normalized_value=normalized_value,
                suggested_interpretation=suggested_interpretation,
                has_ambiguity=True,
                ambiguity_reason=ambiguity_reason,
                extraction_confidence=extraction_confidence,
                char_start=char_start,
                char_end=char_end,
                verification_status=VerificationStatus.NEEDS_REVIEW,
                risk_level=RiskLevel.MEDIUM,
                reason=(
                    "Date detected. Relative dates (today/tomorrow) depend on the "
                    "message recording time. Verify the intended date."
                ),
                evidence=evidence,
            )
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=False,
            ambiguity_reason=None,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.VERIFIED,
            risk_level=RiskLevel.LOW,
            reason="Specific calendar date extracted.",
            evidence=evidence,
        )

    # ── PERSON_NAME ───────────────────────────────────────────────────────
    if entity_type == EntityType.PERSON_NAME:
        return ScoredEntity(
            entity_type=entity_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            suggested_interpretation=suggested_interpretation,
            has_ambiguity=True,
            ambiguity_reason=ambiguity_reason,
            extraction_confidence=extraction_confidence,
            char_start=char_start,
            char_end=char_end,
            verification_status=VerificationStatus.NEEDS_REVIEW,
            risk_level=RiskLevel.MEDIUM,
            reason=(
                "Potential name detected. Speech recognition can mishear proper nouns. "
                "Verify the name is transcribed correctly."
            ),
            evidence=evidence,
        )

    # ── NUMBER / OTHER (low risk) ─────────────────────────────────────────
    return ScoredEntity(
        entity_type=entity_type,
        raw_value=raw_value,
        normalized_value=normalized_value,
        suggested_interpretation=suggested_interpretation,
        has_ambiguity=has_ambiguity,
        ambiguity_reason=ambiguity_reason,
        extraction_confidence=extraction_confidence,
        char_start=char_start,
        char_end=char_end,
        verification_status=VerificationStatus.NOT_EVALUATED,
        risk_level=RiskLevel.LOW,
        reason=f"{entity_type.value} detected — low priority, not evaluated in detail.",
        evidence=evidence,
    )
