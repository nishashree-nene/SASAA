"""
SASAA – Priority Alert Model
==============================
One table for the Guardian Alerts screen.

Alerts are generated automatically when the analysis engine detects:
  - Emergency keywords in context
  - Financial amounts above a threshold
  - Time-sensitive instructions
  - Suspicious transcription issues
  - Missing critical information (e.g. AM/PM on a time)

IMPORTANT RULE:
  An alert is only created when contextual evidence supports it.
  A message is NOT marked EMERGENCY just because it contains the word
  "urgent" — the surrounding context must be evaluated.
"""

import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AlertType(str, enum.Enum):
    """Categories shown on the Guardian Alerts screen."""
    EMERGENCY = "EMERGENCY"
    HIGH_PRIORITY = "HIGH_PRIORITY"
    FINANCIAL = "FINANCIAL"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    SUSPICIOUS_TRANSCRIPT = "SUSPICIOUS_TRANSCRIPT"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"


class AlertSeverity(str, enum.Enum):
    """Visual severity level – maps to the colour system in the UI."""
    INFO = "INFO"           # Grey
    WARNING = "WARNING"     # Yellow
    HIGH = "HIGH"           # Orange
    CRITICAL = "CRITICAL"   # Red


class PriorityAlert(Base, TimestampMixin):
    """
    One row per alert generated for a message.

    A single message can generate multiple alerts:
    e.g. one FINANCIAL alert for an amount + one TIME_SENSITIVE alert
    for a missing AM/PM on a meeting time.

    Alerts are dismissed per-user, not globally.
    """
    __tablename__ = "priority_alerts"

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

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The user this alert belongs to",
    )

    alert_type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type_enum"),
        nullable=False,
        index=True,
    )

    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, name="alert_severity_enum"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Short alert title shown in the alert list",
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Plain-language explanation of why this alert was generated",
    )

    # The specific transcript segment that triggered this alert
    related_transcript_segment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="The exact text that triggered this alert",
    )

    # Suggested action shown to the user
    suggested_action: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="What the user should do about this alert",
    )

    # User interaction state
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Relationship ───────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="alerts",
    )

    def __repr__(self) -> str:
        return (
            f"<PriorityAlert type={self.alert_type} "
            f"severity={self.severity} message_id={self.message_id}>"
        )


from app.models.message import Message  # noqa: E402
