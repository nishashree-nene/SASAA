"""
SASAA – Verification Engine
==============================
Orchestrates all detectors and the risk scorer on a single transcript.

Workflow:
  1. Run all detectors on transcript.raw_text
  2. Score each detection with the risk scorer
  3. Return a flat list of ScoredEntity objects

The engine does NOT write to the database — that is the caller's
responsibility. This keeps the engine pure and testable.

Priority:
  - Phone numbers first (most common critical data in voice messages)
  - Amounts (financial risk)
  - Times (AM/PM ambiguity)
  - Dates
  - Negations (meaning reversal)
  - Names (lower confidence)
  - Standalone numbers (informational only)
"""

from dataclasses import dataclass
from typing import Optional

from app.models.transcript import EntityType
from app.verification.amount_detector import detect_amounts
from app.verification.date_detector import detect_dates
from app.verification.name_detector import detect_names
from app.verification.negation_detector import detect_negations
from app.verification.number_detector import detect_numbers
from app.verification.phone_detector import detect_phones
from app.verification.risk_scorer import ScoredEntity, score_entity
from app.verification.time_detector import detect_times


@dataclass
class VerificationSummary:
    """Summary statistics returned alongside the entity list."""
    total_entities: int
    flagged_count: int        # FLAGGED status
    needs_review_count: int   # NEEDS_REVIEW status
    verified_count: int       # VERIFIED status
    critical_risk_count: int
    high_risk_count: int
    has_financial: bool
    has_negation: bool
    has_time_ambiguity: bool
    message_needs_verification: bool  # True if any FLAGGED or CRITICAL entities


def run_verification(raw_text: str) -> tuple[list[ScoredEntity], VerificationSummary]:
    """
    Run the complete verification pipeline on a transcript text string.

    Args:
        raw_text: The immutable raw transcript from Gnani STT.

    Returns:
        (entities, summary) where entities is a flat list of ScoredEntity
        and summary contains aggregate statistics.

    This function is synchronous and has no I/O — safe to call from
    async code via run_in_executor if needed.
    """
    entities: list[ScoredEntity] = []

    # ── Phone numbers ─────────────────────────────────────────────────────
    for ph in detect_phones(raw_text):
        entities.append(score_entity(
            entity_type=EntityType.PHONE_NUMBER,
            raw_value=ph.raw_value,
            normalized_value=ph.normalized_value,
            suggested_interpretation=f"Phone: {ph.normalized_value}",
            has_ambiguity=ph.has_ambiguity,
            ambiguity_reason=ph.ambiguity_reason,
            extraction_confidence=ph.extraction_confidence,
            char_start=ph.char_start,
            char_end=ph.char_end,
        ))

    # ── Amounts ───────────────────────────────────────────────────────────
    for am in detect_amounts(raw_text):
        entities.append(score_entity(
            entity_type=EntityType.AMOUNT,
            raw_value=am.raw_value,
            normalized_value=am.normalized_value,
            suggested_interpretation=f"{am.currency} {am.normalized_value}",
            has_ambiguity=am.has_ambiguity,
            ambiguity_reason=am.ambiguity_reason,
            extraction_confidence=am.extraction_confidence,
            char_start=am.char_start,
            char_end=am.char_end,
        ))

    # ── Times ─────────────────────────────────────────────────────────────
    for tm in detect_times(raw_text):
        meridiem_hint = tm.meridiem or ("24h" if tm.is_24h else "unknown AM/PM")
        entities.append(score_entity(
            entity_type=EntityType.TIME,
            raw_value=tm.raw_value,
            normalized_value=(
                f"{tm.hour:02d}:{tm.minute:02d} {tm.meridiem}"
                if tm.meridiem else f"{tm.hour:02d}:{tm.minute:02d}"
            ) if tm.hour is not None else tm.raw_value,
            suggested_interpretation=(
                f"{tm.hour}:{tm.minute:02d} {tm.meridiem}"
                if tm.meridiem else
                f"{tm.hour}:{tm.minute:02d} (AM/PM unknown)"
            ) if tm.hour is not None else None,
            has_ambiguity=tm.is_ambiguous,
            ambiguity_reason=tm.ambiguity_reason,
            extraction_confidence=tm.extraction_confidence,
            char_start=tm.char_start,
            char_end=tm.char_end,
        ))

    # ── Dates ─────────────────────────────────────────────────────────────
    for dt in detect_dates(raw_text):
        entities.append(score_entity(
            entity_type=EntityType.DATE,
            raw_value=dt.raw_value,
            normalized_value=dt.raw_value,
            suggested_interpretation=dt.raw_value,
            has_ambiguity=dt.is_ambiguous,
            ambiguity_reason=dt.ambiguity_reason,
            extraction_confidence=dt.extraction_confidence,
            char_start=dt.char_start,
            char_end=dt.char_end,
        ))

    # ── Negations ─────────────────────────────────────────────────────────
    for neg in detect_negations(raw_text):
        entities.append(score_entity(
            entity_type=EntityType.NEGATION,
            raw_value=neg.raw_value,
            normalized_value=neg.raw_value,
            suggested_interpretation=f"Context: {neg.context[:100]}",
            has_ambiguity=True,
            ambiguity_reason=neg.ambiguity_reason,
            extraction_confidence=neg.extraction_confidence,
            char_start=neg.char_start,
            char_end=neg.char_end,
        ))

    # ── Names ─────────────────────────────────────────────────────────────
    for nm in detect_names(raw_text):
        entities.append(score_entity(
            entity_type=EntityType.PERSON_NAME,
            raw_value=nm.raw_value,
            normalized_value=nm.raw_value,
            suggested_interpretation=nm.raw_value,
            has_ambiguity=True,
            ambiguity_reason=nm.ambiguity_reason,
            extraction_confidence=nm.extraction_confidence,
            char_start=nm.char_start,
            char_end=nm.char_end,
        ))

    # ── Standalone numbers (only if text is short enough to be meaningful) ─
    if len(raw_text) <= 500:
        for num in detect_numbers(raw_text):
            # Only include if not already covered by a higher-priority entity
            covered = any(
                e.char_start is not None and e.char_end is not None and
                e.char_start <= num.char_start < e.char_end
                for e in entities
            )
            if not covered:
                entities.append(score_entity(
                    entity_type=EntityType.NUMBER,
                    raw_value=num.raw_value,
                    normalized_value=num.normalized_value,
                    suggested_interpretation=num.normalized_value,
                    has_ambiguity=False,
                    ambiguity_reason=None,
                    extraction_confidence=num.extraction_confidence,
                    char_start=num.char_start,
                    char_end=num.char_end,
                ))

    # ── Tamil-script quantities (numbers without currency context) ─────────
    try:
        from app.verification.tamil_mapper import extract_tamil_entities, has_tamil_script
        if has_tamil_script(raw_text):
            existing_ranges = {
                (e.char_start, e.char_end)
                for e in entities
                if e.char_start is not None and e.char_end is not None
            }
            for tent in extract_tamil_entities(raw_text):
                if tent.entity_hint == "number" and tent.numeric_value is not None:
                    span = (tent.char_start, tent.char_end)
                    if span in existing_ranges:
                        continue
                    entities.append(score_entity(
                        entity_type=EntityType.NUMBER,
                        raw_value=tent.raw_value,
                        normalized_value=str(tent.numeric_value),
                        suggested_interpretation=str(tent.numeric_value),
                        has_ambiguity=False,
                        ambiguity_reason=None,
                        extraction_confidence=0.70,
                        char_start=tent.char_start,
                        char_end=tent.char_end,
                    ))
    except ImportError:
        pass

    # ── Summary ────────────────────────────────────────────────────────────
    from app.models.transcript import VerificationStatus, RiskLevel
    flagged = sum(1 for e in entities if e.verification_status == VerificationStatus.FLAGGED)
    needs_review = sum(1 for e in entities if e.verification_status == VerificationStatus.NEEDS_REVIEW)
    verified = sum(1 for e in entities if e.verification_status == VerificationStatus.VERIFIED)
    critical = sum(1 for e in entities if e.risk_level == RiskLevel.CRITICAL)
    high = sum(1 for e in entities if e.risk_level == RiskLevel.HIGH)

    summary = VerificationSummary(
        total_entities=len(entities),
        flagged_count=flagged,
        needs_review_count=needs_review,
        verified_count=verified,
        critical_risk_count=critical,
        high_risk_count=high,
        has_financial=any(e.entity_type == EntityType.AMOUNT for e in entities),
        has_negation=any(e.entity_type == EntityType.NEGATION for e in entities),
        has_time_ambiguity=any(
            e.entity_type == EntityType.TIME and e.has_ambiguity
            for e in entities
        ),
        message_needs_verification=flagged > 0 or critical > 0,
    )

    return entities, summary
