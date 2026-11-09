"""
SASAA – Models Package
========================
Import all ORM models here so that:
  1. Alembic can discover all tables by importing this package
  2. SQLAlchemy's relationship() can resolve forward references
  3. The rest of the app can do: from app.models import User, Message, etc.

Import order matters: base first, then models with no foreign keys,
then models that reference them.
"""

from app.models.base import Base, TimestampMixin  # noqa: F401

# User tables (no FK dependencies except self-referential)
from app.models.user import User, UserProfile, UserPreferences, UserSession  # noqa: F401

# Message tables
from app.models.message import Message, MessageAudio, MessageStatus, MessagePriority  # noqa: F401

# Transcript and entity tables (depend on Message)
from app.models.transcript import (  # noqa: F401
    Transcript,
    TranscriptVersion,
    TranscriptSegment,
    ExtractedEntity,
    VerificationResult,
    VerificationStatus,
    EntityType,
    RiskLevel,
)

# Alert table (depends on Message)
from app.models.alert import PriorityAlert, AlertType, AlertSeverity  # noqa: F401

# Notification tables
from app.models.notification import (  # noqa: F401
    Notification,
    NotificationPreferences,
    NotificationChannel,
    NotificationType,
)

# Device tables
from app.models.device import DeviceToken, WebPushSubscription  # noqa: F401

# Audit log
from app.models.audit import AuditLog  # noqa: F401

# Voicemail pipeline tables (missed-call voicemail feature)
from app.models.voicemail import (  # noqa: F401
    Voicemail,
    VoicemailRecording,
    ProcessingJob,
    TelephonyEvent,
    VoicemailReport,
    NotificationDelivery,
    VoicemailCallStatus,
    VoicemailProcessingStatus,
    ForwardReason,
    JobType,
    JobStatus,
    TelephonyProvider,
)

# Total: 19 tables
# users, user_profiles, user_preferences, user_sessions,
# messages, message_audio,
# transcripts, transcript_versions, extracted_entities, verification_results,
# priority_alerts,
# notifications, notification_preferences,
# device_tokens, web_push_subscriptions,
# audit_logs
# + language_preferences and user_keywords (added in Phase 6)
