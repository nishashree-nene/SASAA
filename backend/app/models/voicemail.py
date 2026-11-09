"""
SASAA – Voicemail Database Models
====================================
Six tables for the missed-call voicemail pipeline:

  voicemails          – one row per missed call / forwarded call
  voicemail_recordings– audio file metadata (separate from voicemails for clarity)
  processing_jobs     – durable job queue (fault-tolerant, retryable)
  telephony_events    – idempotency log (prevents duplicate processing)
  voicemail_reports   – accuracy analysis output per voicemail
  notification_deliveries – per-notification delivery tracking

Design decisions:
  - voicemails.message_id → messages.id (FK) links the voicemail record to the
    existing SASAA messages table so the entire transcription + verification
    pipeline reuses all existing logic unchanged.
  - telephony_events has a UNIQUE constraint on (provider, provider_event_id)
    to prevent duplicate webhook processing even under provider retries.
  - processing_jobs supports exponential backoff via next_retry_at.
  - voicemail_reports stores findings_json as JSONB for flexible schema evolution.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


# ── Enumerations ──────────────────────────────────────────────────────────────

class VoicemailCallStatus(str, enum.Enum):
    """Status of the inbound call that created this voicemail."""
    RECEIVED = "received"           # webhook received, call in progress
    RECORDING = "recording"         # caller is leaving a message
    RECORDED = "recorded"           # recording complete, audio available
    FAILED = "failed"               # call or recording failed


class VoicemailProcessingStatus(str, enum.Enum):
    """Processing lifecycle of this voicemail record."""
    QUEUED = "queued"               # waiting for worker to pick up
    DOWNLOADING = "downloading"     # fetching audio from provider
    TRANSCRIBING = "transcribing"   # Gnani STT in progress
    VERIFYING = "verifying"         # entity extraction + verification
    COMPLETED = "completed"         # all processing done
    FAILED = "failed"               # unrecoverable error
    PENDING_RETRY = "pending_retry" # scheduled for retry


class ForwardReason(str, enum.Enum):
    """Why the call was forwarded to SASAA."""
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    UNREACHABLE = "unreachable"
    REJECTED = "rejected"           # carrier maps rejection to busy in some cases
    UNCONDITIONAL = "unconditional" # should not happen in normal use
    UNKNOWN = "unknown"


class JobType(str, enum.Enum):
    DOWNLOAD_RECORDING = "download_recording"
    TRANSCRIBE = "transcribe"
    VERIFY = "verify"
    GENERATE_REPORT = "generate_report"
    SEND_NOTIFICATION = "send_notification"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"               # exceeded max retries, needs manual intervention


class TelephonyProvider(str, enum.Enum):
    EXOTEL = "exotel"
    TWILIO = "twilio"
    MOCK = "mock"               # automated tests only


class NotificationChannel(str, enum.Enum):
    PUSH_ANDROID = "push_android"
    PUSH_WEB = "push_web"
    EMAIL = "email"


class NotificationDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"         # user preference disabled this channel


# ── Models ────────────────────────────────────────────────────────────────────

class Voicemail(Base, TimestampMixin):
    """
    One row per missed/forwarded call that SASAA receives.

    The `message_id` FK points to the existing `messages` table so the
    complete SASAA pipeline (transcription, entity extraction, verification,
    alerts) runs on the voicemail without any modification.

    Lifecycle:
      call received → recording → recorded → [processing pipeline] → completed
    """
    __tablename__ = "voicemails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The owner who configured SASAA to receive their missed calls
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The SASAA messages record created for this voicemail
    # NULL until the recording is available and the message record is created
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="FK to messages table — links voicemail to the full SASAA pipeline",
    )

    # Telephony provider information
    provider: Mapped[TelephonyProvider] = mapped_column(
        Enum(TelephonyProvider, name="telephony_provider_enum"),
        nullable=False,
        comment="Which telephony provider delivered this call",
    )
    provider_call_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="The call SID / call ID from the provider (e.g. Exotel CallSid)",
    )

    # Caller and routing information
    caller_number: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="The caller's phone number as received from the provider (E.164)",
    )
    called_number: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="The SASAA VoIP/ExoPhone number that received the forwarded call",
    )
    forward_reason: Mapped[ForwardReason] = mapped_column(
        Enum(ForwardReason, name="forward_reason_enum"),
        default=ForwardReason.UNKNOWN,
        nullable=False,
        comment="Why the call was forwarded — busy, no_answer, unreachable, etc.",
    )

    # Call timing
    call_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    call_ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status tracking
    call_status: Mapped[VoicemailCallStatus] = mapped_column(
        Enum(VoicemailCallStatus, name="voicemail_call_status_enum"),
        default=VoicemailCallStatus.RECEIVED,
        nullable=False,
        index=True,
    )
    processing_status: Mapped[VoicemailProcessingStatus] = mapped_column(
        Enum(VoicemailProcessingStatus, name="voicemail_processing_status_enum"),
        default=VoicemailProcessingStatus.QUEUED,
        nullable=False,
        index=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Read state for the owner
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # ── Unique constraint: one record per provider + call ──────────────────
    __table_args__ = (
        UniqueConstraint("provider", "provider_call_id", name="uq_voicemail_provider_call"),
        Index("ix_voicemail_user_status", "user_id", "processing_status"),
    )

    # ── Relationships ──────────────────────────────────────────────────────
    recording: Mapped[Optional["VoicemailRecording"]] = relationship(
        "VoicemailRecording",
        back_populates="voicemail",
        uselist=False,
        cascade="all, delete-orphan",
    )
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        "ProcessingJob",
        back_populates="voicemail",
        cascade="all, delete-orphan",
        order_by="ProcessingJob.created_at",
    )
    report: Mapped[Optional["VoicemailReport"]] = relationship(
        "VoicemailReport",
        back_populates="voicemail",
        uselist=False,
        cascade="all, delete-orphan",
    )
    notification_deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery",
        back_populates="voicemail",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Voicemail id={self.id} provider={self.provider.value} "
            f"caller={self.caller_number} status={self.processing_status.value}>"
        )


class VoicemailRecording(Base, TimestampMixin):
    """
    Audio file metadata for a voicemail recording.

    The actual audio bytes are stored on disk (same audio_storage/ path as
    MessageAudio). The storage_key is the relative path from AUDIO_STORAGE_PATH.
    """
    __tablename__ = "voicemail_recordings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    voicemail_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voicemails.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Provider's URL for the recording (used during download only — never exposed to clients)
    provider_recording_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Provider-supplied URL to fetch the recording. Kept for audit. Never exposed to clients.",
    )
    provider_recording_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Provider's recording ID / SID",
    )

    # Local storage
    storage_key: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Relative path from AUDIO_STORAGE_PATH. NULL until download completes.",
    )
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 hex digest of the downloaded audio file",
    )

    # Retention
    retention_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this recording should be deleted per user retention policy",
    )

    voicemail: Mapped["Voicemail"] = relationship("Voicemail", back_populates="recording")

    def __repr__(self) -> str:
        return f"<VoicemailRecording voicemail_id={self.voicemail_id} key={self.storage_key}>"


class ProcessingJob(Base, TimestampMixin):
    """
    Durable job record for the voicemail processing pipeline.

    One voicemail creates multiple jobs in sequence:
      download_recording → transcribe → verify → generate_report → send_notification

    Jobs support retry with exponential backoff. After max_attempts the
    status becomes DEAD and manual intervention is required.
    """
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    voicemail_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voicemails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, name="processing_job_type_enum"),
        nullable=False,
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="processing_job_status_enum"),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When this job should next be attempted. NULL = attempt immediately.",
    )

    # Optional JSON payload for the job (e.g. language_code for transcription)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    voicemail: Mapped["Voicemail"] = relationship("Voicemail", back_populates="processing_jobs")

    __table_args__ = (
        Index("ix_processing_job_pending", "status", "next_retry_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessingJob id={self.id} type={self.job_type.value} "
            f"status={self.status.value} attempts={self.attempts}>"
        )


class TelephonyEvent(Base):
    """
    Idempotency log for inbound webhook events from telephony providers.

    Every received webhook is recorded here FIRST. If the (provider, event_id)
    pair already exists, the webhook is a duplicate and is discarded without
    creating a second voicemail record.

    Uses SHA-256 of the webhook body (payload_hash) for integrity tracking.
    Does NOT extend TimestampMixin — received_at is the only timestamp needed.
    """
    __tablename__ = "telephony_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    provider: Mapped[TelephonyProvider] = mapped_column(
        Enum(TelephonyProvider, name="telephony_provider_event_enum"),
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="The unique event ID from the provider (e.g. CallSid for Exotel). Used for idempotency.",
    )

    voicemail_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voicemails.id", ondelete="SET NULL"),
        nullable=True,
        comment="The voicemail record created/updated by this event. NULL for pre-voicemail events.",
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Provider-specific event type string",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this webhook was received by SASAA",
    )
    payload_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 hash of the raw webhook body for integrity",
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_telephony_event"),
    )

    def __repr__(self) -> str:
        return (
            f"<TelephonyEvent provider={self.provider.value} "
            f"event_id={self.provider_event_id} type={self.event_type}>"
        )


class VoicemailReport(Base, TimestampMixin):
    """
    Detailed accuracy report generated after transcription + verification.

    findings_json stores the full structured report (entities, uncertainties,
    audio quality, recommendations) in JSONB for flexibility. The scalar
    fields provide quick filtering without parsing JSON.
    """
    __tablename__ = "voicemail_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    voicemail_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voicemails.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Summary scalars for filtering and display
    overall_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="clean | needs_review | high_risk",
    )
    total_entities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flagged_entities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_risk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_negation_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_financial_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Provider-supplied speech confidence (NULL if not available — never invented)
    speech_confidence: Mapped[Optional[float]] = mapped_column(
        nullable=True,
        comment="Average speech confidence from STT provider. NULL = not provided.",
    )

    # Full structured findings
    findings_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Complete report structure: entities, uncertainties, audio quality, recommendations",
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this report was generated",
    )

    voicemail: Mapped["Voicemail"] = relationship("Voicemail", back_populates="report")

    def __repr__(self) -> str:
        return (
            f"<VoicemailReport voicemail_id={self.voicemail_id} "
            f"status={self.overall_status} entities={self.total_entities}>"
        )


class NotificationDelivery(Base, TimestampMixin):
    """
    Tracks each notification attempt per voicemail per channel.
    Prevents duplicate notifications and enables delivery audit.
    """
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voicemail_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voicemails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notif_channel_enum"),
        nullable=False,
    )
    status: Mapped[NotificationDeliveryStatus] = mapped_column(
        Enum(NotificationDeliveryStatus, name="notif_delivery_status_enum"),
        default=NotificationDeliveryStatus.PENDING,
        nullable=False,
    )

    # Reason for failure or skip
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Idempotency: one delivery per user + voicemail + channel + event_type
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="new_voicemail | transcript_ready | review_required",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "voicemail_id", "channel", "event_type",
            name="uq_notif_delivery",
        ),
    )

    voicemail: Mapped["Voicemail"] = relationship(
        "Voicemail", back_populates="notification_deliveries"
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery user={self.user_id} "
            f"channel={self.channel.value} status={self.status.value}>"
        )
