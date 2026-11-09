"""
SASAA – Notification Models
=============================
Two tables:
  notifications              – log of every notification sent
  notification_preferences   – per-user channel and category settings
"""

import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class NotificationChannel(str, enum.Enum):
    """The delivery channel used for this notification."""
    PUSH_ANDROID = "PUSH_ANDROID"   # Firebase Cloud Messaging
    PUSH_WEB = "PUSH_WEB"           # Web Push API
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"               # Stored for display inside the app


class NotificationType(str, enum.Enum):
    """Category of event that triggered the notification."""
    NEW_MESSAGE = "NEW_MESSAGE"
    HIGH_PRIORITY = "HIGH_PRIORITY"
    EMERGENCY = "EMERGENCY"
    SUSPICIOUS_TRANSCRIPT = "SUSPICIOUS_TRANSCRIPT"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    SYSTEM = "SYSTEM"


class Notification(Base, TimestampMixin):
    """
    Log of every notification generated for a user.

    Keeping a log lets us:
    - Show a notification centre inside the app
    - Avoid sending duplicate notifications for the same event
    - Track delivery failures
    """
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        comment="The message this notification is about (if applicable)",
    )

    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type_enum"),
        nullable=False,
        index=True,
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel_enum"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Delivery status
    is_delivered: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True when the notification was successfully sent to the channel",
    )
    delivery_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if delivery failed",
    )

    def __repr__(self) -> str:
        return (
            f"<Notification type={self.notification_type} "
            f"channel={self.channel} user_id={self.user_id}>"
        )


class NotificationPreferences(Base, TimestampMixin):
    """
    Per-user, per-channel notification settings.
    One row per user – created with defaults on registration.
    """
    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Android push
    android_push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    android_vibration: Mapped[bool] = mapped_column(Boolean, default=True)

    # Web push
    web_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Email
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Category toggles (apply across all enabled channels)
    new_message_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    high_priority_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    emergency_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    suspicious_transcript_alerts: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<NotificationPreferences user_id={self.user_id}>"
