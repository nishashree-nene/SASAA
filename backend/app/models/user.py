"""
SASAA – User Models
====================
Four tables that together represent a complete user account:

  users               – authentication identity (email + hashed password)
  user_profiles       – display information (name, phone, picture)
  user_preferences    – language and UI settings
  user_sessions       – refresh tokens (allows logout and token revocation)

DESIGN DECISION – why split users and user_profiles?
  The users table is accessed on EVERY authenticated request (to validate the
  token subject). Keeping it small (just id, email, password_hash) means that
  lookup stays fast. Profile data (name, picture, phone) is only needed when
  displaying the user's information, so it lives in a separate table.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """
    Core authentication table. One row per registered account.

    Rules:
    - email is unique across all users
    - password_hash is ALWAYS a bcrypt hash – never plaintext
    - is_active=False blocks login without deleting the account
    - is_verified tracks email verification status
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Primary key – UUID so IDs are not guessable",
    )

    email: Mapped[str] = mapped_column(
        String(320),     # RFC 5321 maximum email length
        unique=True,
        nullable=False,
        index=True,      # Indexed for fast login lookup
        comment="User's email address – unique login identifier",
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash of the user's password. Never store plaintext.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="False = account suspended. User cannot log in.",
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True when the user has verified their email address.",
    )

    # ── Relationships ──────────────────────────────────────────────────────
    # back_populates creates a two-way link:
    #   user.profile   → the UserProfile row for this user
    #   profile.user   → the User row for this profile
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,           # One-to-one relationship
        cascade="all, delete-orphan",
    )
    preferences: Mapped[Optional["UserPreferences"]] = relationship(
        "UserPreferences",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


class UserProfile(Base, TimestampMixin):
    """
    Display information for a user.
    Created automatically when a user registers.
    """
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,      # One profile per user
        nullable=False,
        index=True,
    )

    full_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User's display name",
    )

    phone_number: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Phone number in E.164 format e.g. +919876543210",
    )

    profile_picture_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="URL to the user's profile picture",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return f"<UserProfile user_id={self.user_id} name={self.full_name}>"


class UserPreferences(Base, TimestampMixin):
    """
    Per-user application settings.
    Controls language, theme, and notification behaviour.
    """
    __tablename__ = "user_preferences"

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

    # Language settings
    interface_language: Mapped[str] = mapped_column(
        String(10),
        default="en-IN",
        nullable=False,
        comment="BCP-47 language tag for the UI language e.g. ta-IN",
    )
    transcript_language: Mapped[str] = mapped_column(
        String(10),
        default="ta-IN",
        nullable=False,
        comment="Preferred language for transcription",
    )
    auto_translate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="If True, automatically translate transcripts to English",
    )

    # Theme
    theme: Mapped[str] = mapped_column(
        String(10),
        default="light",
        nullable=False,
        comment="UI theme: light or dark",
    )

    # Notification preferences
    notify_new_message: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_high_priority: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_emergency: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_suspicious: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audio retention
    audio_retention_days: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        comment="Days to keep audio before auto-delete. NULL = keep forever.",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<UserPreferences user_id={self.user_id}>"


class UserSession(Base, TimestampMixin):
    """
    Stores refresh tokens so they can be revoked.

    When a user logs out, we set is_revoked=True on their session.
    When they log in on a new device, a new session row is created.
    This allows a user to be logged in on multiple devices simultaneously,
    and to log out of individual devices.
    """
    __tablename__ = "user_sessions"

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

    refresh_token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="SHA-256 hash of the refresh token. Not the token itself.",
    )

    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True when the user has logged out from this session.",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this refresh token expires.",
    )

    device_info: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="User-Agent string or device name for the session list display.",
    )

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),       # IPv6 max length
        nullable=True,
        comment="IP address at login time. For security audit display.",
    )

    # ── Relationship ───────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<UserSession user_id={self.user_id} revoked={self.is_revoked}>"
