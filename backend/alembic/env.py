"""
Alembic Environment Configuration
===================================
This is the script Alembic runs whenever you use any alembic command.
It does two important things:

1. Reads the real DATABASE_URL from .env (not the placeholder in alembic.ini)
2. Points Alembic at our SQLAlchemy models so it can auto-detect schema changes

HOW TO USE (run these from the backend/ directory):

  Generate a migration after changing models:
      alembic revision --autogenerate -m "add user table"

  Apply all pending migrations to the database:
      alembic upgrade head

  See what migrations have been applied:
      alembic history

  Roll back the last migration:
      alembic downgrade -1
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Path setup ──────────────────────────────────────────────────────────────
# Add the backend/ directory to Python's path so we can import our app modules.
# This file lives at backend/alembic/env.py, so we go up one level.
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Load environment variables from .env ────────────────────────────────────
# We load .env here so DATABASE_URL is available before Alembic connects.
# The .env file is at the project root (one level above backend/).
from dotenv import load_dotenv

env_file = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_file)

# ── Import our models ────────────────────────────────────────────────────────
# Importing app.models registers all 16 tables with SQLAlchemy's metadata.
# Alembic uses this metadata to detect what changed since the last migration.
# If you add a new model file, import it here too.
from app.models import Base  # noqa: F401 – registers all models
# The individual imports below are not strictly necessary but make it explicit
# which tables Alembic should manage.
from app.models.user import User, UserProfile, UserPreferences, UserSession  # noqa: F401
from app.models.message import Message, MessageAudio  # noqa: F401
from app.models.transcript import (  # noqa: F401
    Transcript, TranscriptVersion, ExtractedEntity, VerificationResult
)
from app.models.alert import PriorityAlert  # noqa: F401
from app.models.notification import Notification, NotificationPreferences  # noqa: F401
from app.models.device import DeviceToken, WebPushSubscription  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401

# ── Alembic configuration ────────────────────────────────────────────────────
config = context.config

# Set up Python logging using the [loggers] section in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell Alembic which metadata to compare against the database.
# Base.metadata contains all our table definitions.
target_metadata = Base.metadata

# ── Read DATABASE_URL from environment ──────────────────────────────────────
# This overrides the placeholder sqlalchemy.url in alembic.ini with the
# real database URL from our .env file. The password stays out of alembic.ini.
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Make sure your .env file has DATABASE_URL and that "
        "YOUR_PASSWORD has been replaced with your actual PostgreSQL password."
    )

# Alembic uses the sync psycopg2 driver (asyncpg is for FastAPI async routes)
# If the URL uses asyncpg, swap it for psycopg2
if database_url.startswith("postgresql+asyncpg"):
    database_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

config.set_main_option("sqlalchemy.url", database_url)


# ── Migration functions ──────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without an actual database connection.
    Useful for generating SQL scripts to review before applying.

    Usage: alembic upgrade head --sql > migration.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare server defaults so Alembic detects column default changes
        compare_server_default=True,
        # Detect when a column becomes nullable or non-nullable
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations with a live database connection.
    This is the normal mode used by: alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # Don't pool connections for migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
            compare_type=True,
            # Render the schema name in CREATE TABLE statements
            # include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ──────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
