"""
SASAA – Message and Audio Models
==================================
Two tables that represent a voice message and its audio file:

  messages        – the message record (status, caller info, priority)
  message_audio   – the audio file metadata (path, duration, format)

MESSAGE STATUS STATE MACHINE:
  Every message moves through these states in order:

    UPLOADED       – audio file received and stored securely
        ↓
    VALIDATING     – checking file format, size, duration
        ↓
    PROCESSING     – converting audio format if needed
        ↓
    TRANSCRIBING   – Gnani AI is processing the audio
        ↓
    ANALYZING      – verification engine extracting entities
        ↓
    COMPLETED      – all processing done, message ready to read
        ↓
    NEEDS_VERIFICATION  – flagged items require the user's attention
        ↓ (or stays here until user resolves it)
    FAILED         – an unrecoverable error occurred (details in error_message)

  The frontend polls the message status to show a real-time progress indicator.
  Duplicate processing is prevented by checking the current status before
  starting any processing step.
"""

import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MessageStatus(str, enum.Enum):
    """
    All valid states for a message.
    Using str as a base means the values are stored as strings in PostgreSQL,
    which is readable and debuggable in pgAdmin.
    """
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    FAILED = "FAILED"


class MessagePriority(str, enum.Enum):
    """Priority levels assigned by the priority detection engine."""
    NORMAL = "NORMAL"
    IMPORTANT = "IMPORTANT"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class Message(Base, TimestampMixin):
    """
    One row per voice message.

    A message is created when a user submits a new voice note (either
    via the simulated missed-call flow or by uploading an audio file).
    The status field tracks which processing stage the message is in.
    """
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Owner – the user whose inbox this message belongs to
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The user who owns this message",
    )

    # Caller information (from simulated call or future telephony integration)
    caller_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Display name of the caller, if known",
    )
    caller_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Caller's phone number in E.164 format",
    )

    # Processing state
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, name="message_status_enum"),
        default=MessageStatus.UPLOADED,
        nullable=False,
        index=True,
        comment="Current processing state. See MessageStatus enum.",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable error description if status=FAILED",
    )

    # Priority (set by the priority detection engine after analysis)
    priority: Mapped[MessagePriority] = mapped_column(
        Enum(MessagePriority, name="message_priority_enum"),
        default=MessagePriority.NORMAL,
        nullable=False,
        index=True,
    )

    # Language detected during transcription
    detected_language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="BCP-47 code of the detected language e.g. ta-IN",
    )

    # Read/unread state
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # Whether the message has been archived (hidden from inbox, not deleted)
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    audio: Mapped[Optional["MessageAudio"]] = relationship(
        "MessageAudio",
        back_populates="message",
        uselist=False,
        cascade="all, delete-orphan",
    )
    transcripts: Mapped[list["Transcript"]] = relationship(
        "Transcript",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["PriorityAlert"]] = relationship(
        "PriorityAlert",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} status={self.status} "
            f"priority={self.priority}>"
        )


class MessageAudio(Base, TimestampMixin):
    """
    Stores metadata about the audio file associated with a message.

    The actual audio bytes live on disk at storage_path (relative to
    AUDIO_STORAGE_PATH in settings). We never store binary audio data in
    the database — that would make the database enormous and slow.

    One message → one audio file. If the audio needs to be converted
    (e.g. from .ogg to .wav for Gnani), the converted copy's path is
    stored in converted_storage_path and the original is preserved.
    """
    __tablename__ = "message_audio"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # File location and metadata
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="The filename as uploaded by the user",
    )
    storage_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Path to the original audio file on disk, relative to AUDIO_STORAGE_PATH",
    )
    converted_storage_path: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Path to converted audio file (e.g. .ogg → .wav). NULL if no conversion needed.",
    )

    # File properties
    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="MIME type e.g. audio/ogg, audio/mpeg, audio/wav",
    )
    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Size of the original file in bytes",
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=10, scale=3),
        nullable=True,
        comment="Duration of the audio in seconds (extracted from file metadata)",
    )

    # Processing time for performance monitoring
    processing_latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Time taken to send to Gnani and receive the transcript (milliseconds)",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship("Message", back_populates="audio")

    def __repr__(self) -> str:
        return (
            f"<MessageAudio message_id={self.message_id} "
            f"mime={self.mime_type} size={self.file_size_bytes}>"
        )


# Import here to avoid circular imports at module level
from app.models.transcript import Transcript  # noqa: E402
from app.models.alert import PriorityAlert     # noqa: E402
