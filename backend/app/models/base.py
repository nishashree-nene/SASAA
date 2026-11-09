"""
SASAA – SQLAlchemy Declarative Base
=====================================
Every ORM model inherits from Base. SQLAlchemy uses this shared parent to:
  - Track all table definitions in one registry
  - Allow Alembic to auto-detect tables for migrations
  - Enable Base.metadata.create_all() for table creation

TimestampMixin adds created_at, updated_at, and deleted_at to every model
that inherits from it. Soft deletion (deleted_at) means we keep the row in
the database but treat it as deleted — this preserves audit history and
prevents dangling foreign keys.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return the current UTC time. Used as a default for timestamp columns."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """
    Shared base class for all SASAA ORM models.

    Using SQLAlchemy 2.0's DeclarativeBase gives us:
    - Type-safe mapped_column() definitions
    - Automatic __tablename__ is NOT set here — each model sets its own
    - All tables are registered in Base.metadata for Alembic
    """
    pass


class TimestampMixin:
    """
    Adds three timestamp columns to any model that inherits this mixin.

    created_at  – set once when the row is inserted, never changed
    updated_at  – updated automatically whenever the row is changed
    deleted_at  – NULL means active; a timestamp means soft-deleted

    WHY SOFT DELETE:
    Instead of removing rows, we set deleted_at. This means:
    - Audio message history is preserved for the user's retention period
    - Foreign keys never break (a deleted user's messages still reference them)
    - We can restore accidentally deleted items
    - Audit logs remain complete
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        comment="UTC timestamp when this row was created",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
        comment="UTC timestamp of last modification",
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="NULL = active. Set to a timestamp to soft-delete this row.",
    )
