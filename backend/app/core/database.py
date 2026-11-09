"""
SASAA – Database Connection and Session Management
====================================================
This module sets up the connection between the FastAPI backend and PostgreSQL.

HOW SQLAlchemy WORKS (beginner explanation):
  - Engine: the actual connection to the database (holds the connection pool)
  - Session: a temporary workspace for one request. You use it to read/write
    rows. When the request ends, the session is closed and returned to the pool.
  - Base: the parent class all our ORM models inherit from. When we call
    Base.metadata.create_all(), SQLAlchemy creates the tables.

WHY TWO ENGINES:
  - Sync engine (psycopg2): used by Alembic for migrations, and for any
    synchronous code
  - Async engine (asyncpg): used by FastAPI route handlers. FastAPI is
    async-first, so async database calls let it handle many requests at once
    without blocking
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# ── Synchronous engine ──────────────────────────────────────────────────────
# Used by Alembic migrations and any sync code.
# pool_pre_ping=True: test the connection before using it from the pool.
# This prevents "connection was closed" errors after the DB restarts.
sync_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=settings.is_development,   # Prints SQL statements in development
    pool_size=5,                    # Keep 5 connections open at all times
    max_overflow=10,                # Allow up to 10 extra connections under load
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,   # We manage transactions manually (commit/rollback)
    autoflush=False,    # Don't flush automatically – explicit is better
    expire_on_commit=False,  # Keep accessing attributes after commit
)

# ── Asynchronous engine ─────────────────────────────────────────────────────
# Used by FastAPI route handlers.
# asyncpg is the driver; it replaces psycopg2 in the URL automatically.
async_engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    echo=settings.is_development,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ── Async session dependency ────────────────────────────────────────────────

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session to route handlers.

    Usage in a route:
        @router.get("/example")
        async def my_route(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(User))

    The `async with` block guarantees the session is always closed after the
    request, even if an exception is raised. This prevents connection leaks.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Sync session dependency ─────────────────────────────────────────────────

def get_sync_db() -> Session:
    """
    Synchronous session for use in non-async code (e.g. background workers).
    """
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Connection health check ─────────────────────────────────────────────────

async def check_database_connection() -> dict:
    """
    Test the database connection. Used by the /health endpoint.

    Returns a dict with status and PostgreSQL version string.
    """
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            return {
                "status": "connected",
                "database": "sasaa_db",
                "postgresql_version": version,
            }
    except Exception as error:
        return {
            "status": "error",
            "detail": str(error),
        }
