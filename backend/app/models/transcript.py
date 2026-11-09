"""
SASAA – Transcript and Entity Models
======================================
Four tables for the core intelligence layer:

  transcripts           – the immutable raw transcript from Gnani STT
  transcript_versions   – user-edited versions (never overwrites raw)
  extracted_entities    – detected phone numbers, times, amounts, names, etc.
  verification_results  – per-entity verification status and risk level

IMMUTABILITY RULE:
  Once a Transcript row is created with raw_text from Gnani, that raw_text
  is NEVER modified. User corrections are stored in TranscriptVersion rows.
  This is the core product principle:
    "Never silently modify the original transcript."

  The frontend always shows both:
    - The original raw transcript (always available)
    - The latest user-approved version (if one exists)
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class VerificationStatus(str, enum.Enum):
    """
    How confident we are about a particular piece of extracted information.

    VERIFIED        – strong evidence the value is correct
    NEEDS_REVIEW    – something looks suspicious, user should check
    FLAGGED         – high-risk inconsistency detected
    NOT_EVALUATED   – detector did not run on this entity
    USER_CONFIRMED  – the user has explicitly accepted this value
    USER_CORRECTED  – the user has provided a correction
    USER_REJECTED   – the user has rejected the suggested interpretation
    """
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FLAGGED = "FLAGGED"
    NOT_EVALUATED = "NOT_EVALUATED"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_CORRECTED = "USER_CORRECTED"
    USER_REJECTED = "USER_REJECTED"


class EntityType(str, enum.Enum):
    """Types of critical information the extraction engine can detect."""
    PHONE_NUMBER = "PHONE_NUMBER"
    AMOUNT = "AMOUNT"
    DATE = "DATE"
    TIME = "TIME"
    PERSON_NAME = "PERSON_NAME"
    ADDRESS = "ADDRESS"
    NEGATION = "NEGATION"
    NUMBER = "NUMBER"
    INSTRUCTION = "INSTRUCTION"
    OTHER = "OTHER"


class RiskLevel(str, enum.Enum):
    """
    Risk assigned by the risk scorer to a flagged entity.
    Determines alert colour and notification urgency.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Transcript(Base, TimestampMixin):
    """
    The raw, immutable transcript produced by Gnani STT.

    raw_text is set once and never updated. Any display_text shown to
    users that differs from raw_text must come from a TranscriptVersion row.

    provider_response stores the full JSON response from Gnani so we
    can inspect it later without making another API call.
    """
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The immutable original transcript – never modify this after creation
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Exact text returned by Gnani STT. IMMUTABLE. Never updated.",
    )

    # Gnani response metadata
    detected_language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Language code detected by Gnani e.g. ta-IN",
    )
    provider_confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Confidence score from the STT provider (0.0–1.0). NULL if not provided.",
    )
    processing_latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="End-to-end latency reported by Gnani (milliseconds)",
    )

    # Full raw API response stored as JSON for debugging and re-processing
    provider_response: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Complete JSON response from Gnani STT. For debugging only.",
    )

    # Translation (separate from original – never replaces it)
    english_translation: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="English translation of the transcript. Separate from raw_text.",
    )
    translation_source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Which service provided the translation e.g. google_translate",
    )

    # Verification tracking
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the verification engine last ran on this transcript. NULL = not yet run.",
    )

    # ── Relationships ──────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="transcripts",
    )
    versions: Mapped[list["TranscriptVersion"]] = relationship(
        "TranscriptVersion",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptVersion.version_number",
    )
    entities: Mapped[list["ExtractedEntity"]] = relationship(
        "ExtractedEntity",
        back_populates="transcript",
        cascade="all, delete-orphan",
    )
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_ms.asc().nullslast()",
    )

    def __repr__(self) -> str:
        preview = self.raw_text[:50] if self.raw_text else ""
        return f"<Transcript id={self.id} lang={self.detected_language} text='{preview}...'>"


class TranscriptVersion(Base, TimestampMixin):
    """
    A user-approved corrected version of a transcript.

    Each time a user accepts, rejects, or edits a suggestion, a new
    TranscriptVersion is created with version_number incremented.
    The original Transcript.raw_text is never touched.

    version_number=1 is the first user correction.
    The frontend shows the latest version by default, with an option
    to view the original raw transcript.
    """
    __tablename__ = "transcript_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="The user who created this version",
    )

    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential version number starting at 1",
    )

    corrected_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The full transcript text after user corrections",
    )

    # Summary of what changed
    change_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable summary of what the user changed",
    )

    # Structured record of individual corrections (JSON array)
    corrections: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Array of {entity_id, original, corrected, action} objects",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    transcript: Mapped["Transcript"] = relationship(
        "Transcript",
        back_populates="versions",
    )

    def __repr__(self) -> str:
        return (
            f"<TranscriptVersion transcript_id={self.transcript_id} "
            f"v={self.version_number}>"
        )


class ExtractedEntity(Base, TimestampMixin):
    """
    One row per piece of critical information extracted from a transcript.

    Examples:
      - A phone number: entity_type=PHONE_NUMBER, raw_value="five five five
        one two three four", normalized_value="5551234"
      - A time: entity_type=TIME, raw_value="five in the evening",
        normalized_value="5:00 PM", has_ambiguity=True
        ambiguity_reason="AM/PM not explicitly stated in audio"

    extracted_value is what the NLP engine detected.
    normalized_value is the cleaned-up version (e.g. "fifty thousand" → "50000").
    suggested_interpretation is what we think it might mean.

    IMPORTANT: suggested_interpretation is NEVER presented as fact.
    The verification_status shows how confident we are.
    """
    __tablename__ = "extracted_entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type_enum"),
        nullable=False,
        index=True,
    )

    # The exact text span in the transcript where this entity was found
    raw_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The exact text from the transcript as extracted",
    )

    # The cleaned interpretation of raw_value
    normalized_value: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Normalized form e.g. '50000' from 'fifty thousand'",
    )

    # What we think it means (never marked as verified unless evidence supports it)
    suggested_interpretation: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI's best guess at the intended meaning. Always shown with uncertainty label.",
    )

    # Uncertainty information
    has_ambiguity: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True when the meaning is uncertain e.g. AM/PM missing",
    )
    ambiguity_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Plain-language explanation of why this is ambiguous",
    )

    # Confidence from this specific extractor (0.0–1.0)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Confidence of the extraction algorithm (not the STT confidence)",
    )

    # Position in transcript for segment playback
    char_start: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Character position where this entity starts in raw_text",
    )
    char_end: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Character position where this entity ends in raw_text",
    )

    # ── Relationships ──────────────────────────────────────────────────────
    transcript: Mapped["Transcript"] = relationship(
        "Transcript",
        back_populates="entities",
    )
    verification_result: Mapped[Optional["VerificationResult"]] = relationship(
        "VerificationResult",
        back_populates="entity",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ExtractedEntity type={self.entity_type} "
            f"value='{self.raw_value}' ambiguous={self.has_ambiguity}>"
        )


class VerificationResult(Base, TimestampMixin):
    """
    The outcome of running the verification engine on one extracted entity.

    This is what the frontend displays in the correction comparison table:
    - What the transcript says
    - What we think it means
    - How confident we are
    - What the user decided

    user_decision is set when the user clicks Accept / Reject / Edit
    on the Message Analysis screen.
    """
    __tablename__ = "verification_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extracted_entities.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status_enum"),
        default=VerificationStatus.NOT_EVALUATED,
        nullable=False,
    )

    risk_level: Mapped[Optional[RiskLevel]] = mapped_column(
        Enum(RiskLevel, name="risk_level_enum"),
        nullable=True,
        comment="Risk level assigned by the risk scorer. NULL if not evaluated.",
    )

    # The evidence that influenced this result (stored as JSON)
    evidence: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Signals that influenced the verification result",
    )

    # Plain-language explanation shown to the user
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Explanation of why this entity was flagged or verified",
    )

    # What the user decided on the Message Analysis screen
    user_decision: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="ACCEPTED, REJECTED, or EDITED",
    )
    user_correction: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="The corrected value if the user chose EDITED",
    )
    user_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the user made their decision",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    entity: Mapped["ExtractedEntity"] = relationship(
        "ExtractedEntity",
        back_populates="verification_result",
    )

    def __repr__(self) -> str:
        return (
            f"<VerificationResult entity_id={self.entity_id} "
            f"status={self.verification_status} risk={self.risk_level}>"
        )


# Resolve forward reference from message.py
from app.models.message import Message  # noqa: E402


class TranscriptSegment(Base, TimestampMixin):
    """
    Word- or phrase-level segment with optional timing from the STT provider.

    Created when the STT provider returns time-aligned results.
    Used for:
      - Highlighted uncertain phrases in the accuracy report
      - Segment-level audio playback (play this specific part)
      - Fine-grained user review

    IMMUTABILITY: segment text is written once from the provider response and
    never modified. User corrections go to TranscriptVersion rows.
    """
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Timing within the audio file (milliseconds from start)
    start_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Start time of this segment in ms from audio start",
    )
    end_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="End time of this segment in ms from audio start",
    )

    # Segment text (immutable once set from provider)
    text: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Spoken words as returned by the STT provider. Immutable.",
    )

    # Speech confidence — NULL if provider does not supply it. NEVER invented.
    speech_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment=(
            "Confidence score (0.0–1.0) from the STT provider. "
            "NULL = provider did not supply this value. Never estimated."
        ),
    )

    # Human review state
    review_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
        comment="pending | reviewed | corrected | confirmed",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    transcript: Mapped["Transcript"] = relationship(
        "Transcript", back_populates="segments",
    )

    def __repr__(self) -> str:
        return (
            f"<TranscriptSegment transcript_id={self.transcript_id} "
            f"{self.start_ms}–{self.end_ms}ms text='{self.text[:40]}'>"
        )
