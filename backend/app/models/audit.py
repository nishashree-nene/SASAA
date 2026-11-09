"""
SASAA – Audit Log Model
=========================
Records security-relevant events for each user.

WHY AUDIT LOGS:
  Voice messages contain sensitive personal information.
  Users have the right to know:
  - When their account was accessed
  - When audio was played
  - When data was deleted
  - When settings were changed

  The audit log is append-only – rows are never updated or deleted
  (even on account deletion, the log is anonymised rather than removed).
"""

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """
    Immutable record of a user action or system event.

    action examples:
      USER_LOGIN, USER_LOGOUT, AUDIO_PLAYED, AUDIO_DELETED,
      TRANSCRIPT_VIEWED, CORRECTION_SAVED, ACCOUNT_DELETED,
      SETTINGS_CHANGED, PASSWORD_CHANGED, DATA_EXPORT_REQUESTED
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,     # NULL if the user account has been deleted
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="The action that was performed e.g. AUDIO_PLAYED",
    )

    # What the action was performed on
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="The type of resource e.g. message, transcript, user",
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="The ID of the specific resource that was accessed",
    )

    # Network information
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Additional context as structured JSON
    details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional event-specific details",
    )

    # Outcome
    success: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="False if the action was attempted but failed",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog action={self.action} "
            f"user_id={self.user_id} resource={self.resource_type}/{self.resource_id}>"
        )
