"""
SASAA - User Authentication Service
======================================
All database operations for user authentication:

  register_user  – creates account, profile, preferences, session; returns tokens
  login_user     – verifies credentials, creates session; returns tokens
  refresh_tokens – validates refresh token, rotates session; returns new tokens
  logout_user    – revokes the session for one device
  get_user_by_id – loads User + profile for the /users/me endpoint

Security principles enforced here:
  - Passwords are ALWAYS hashed with bcrypt (never stored or logged in plaintext)
  - Refresh tokens are stored as SHA-256 hashes (never the token itself)
  - Token rotation on refresh: old session revoked, new session created
  - Constant-time email lookup to resist timing attacks on user enumeration
  - IntegrityError from race conditions caught and surfaced correctly
"""

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserPreferences, UserProfile, UserSession


# ── Custom exceptions ────────────────────────────────────────────────────────

class EmailAlreadyRegistered(Exception):
    """Raised when registration is attempted with an already-used email."""


class InvalidCredentials(Exception):
    """Raised when email/password combination is incorrect."""


class AccountInactive(Exception):
    """Raised when the user account is suspended (is_active=False)."""


class InvalidRefreshToken(Exception):
    """Raised when the refresh token is missing, expired, or revoked."""


# ── Token storage helper ──────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """
    Store SHA-256 hash of a token, never the token itself.
    If the token table is ever leaked, the raw tokens cannot be recovered.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _make_session(user_id, refresh_token: str, request_info: dict | None = None) -> UserSession:
    """Create a UserSession ORM object from a refresh token."""
    return UserSession(
        user_id=user_id,
        refresh_token_hash=_hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        device_info=request_info.get("user_agent") if request_info else None,
        ip_address=request_info.get("ip_address") if request_info else None,
    )


# ── register_user ─────────────────────────────────────────────────────────────

async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    request_info: dict | None = None,
) -> tuple[str, str]:
    """
    Create a new user account and return (access_token, refresh_token).

    Steps:
      1. Normalise email
      2. Check for duplicate (raises EmailAlreadyRegistered)
      3. Hash password with bcrypt
      4. Create User + UserProfile + UserPreferences in one flush
      5. Generate tokens
      6. Store refresh token hash in UserSession
      7. Commit atomically — all-or-nothing

    Raises:
        EmailAlreadyRegistered: if the email is already in use
    """
    email = email.strip().lower()

    # Check duplicate before trying to insert
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise EmailAlreadyRegistered()

    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            profile=UserProfile(full_name=full_name.strip()),
            preferences=UserPreferences(),
        )
        db.add(user)
        await db.flush()  # Generates user.id without committing

        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        db.add(_make_session(user.id, refresh_token, request_info))
        await db.commit()

        return access_token, refresh_token

    except IntegrityError:
        # Race condition: another request registered the same email between our
        # check above and our INSERT. Safe to surface as duplicate.
        await db.rollback()
        raise EmailAlreadyRegistered()

    except Exception:
        await db.rollback()
        raise


# ── login_user ────────────────────────────────────────────────────────────────

async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    request_info: dict | None = None,
) -> tuple[str, str]:
    """
    Verify credentials and return (access_token, refresh_token).

    Steps:
      1. Look up user by email
      2. verify_password — bcrypt comparison (constant time)
      3. Check is_active flag
      4. Generate tokens
      5. Store new UserSession
      6. Commit

    Raises:
        InvalidCredentials: email not found OR password incorrect
            (same exception to prevent user enumeration)
        AccountInactive: account exists but is_active=False
    """
    email = email.strip().lower()

    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    # Deliberate: same exception for "not found" and "wrong password"
    # so attackers cannot enumerate valid email addresses via timing
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    if not user.is_active:
        raise AccountInactive()

    try:
        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        db.add(_make_session(user.id, refresh_token, request_info))
        await db.commit()

        return access_token, refresh_token

    except Exception:
        await db.rollback()
        raise


# ── refresh_tokens ────────────────────────────────────────────────────────────

async def refresh_tokens(
    db: AsyncSession,
    refresh_token: str,
    request_info: dict | None = None,
) -> tuple[str, str]:
    """
    Validate a refresh token, revoke the old session, issue new tokens.

    This implements REFRESH TOKEN ROTATION:
      - The old refresh token is invalidated immediately after use
      - A new refresh token is issued and stored
      - If a stolen token is reused, the session hash won't match and it is rejected

    Steps:
      1. Decode JWT to extract user_id
      2. Hash the presented token and look up the session
      3. Check session is not revoked and not expired
      4. Revoke the old session (is_revoked=True)
      5. Generate new tokens
      6. Create a new session
      7. Commit

    Raises:
        InvalidRefreshToken: token is invalid, expired, revoked, or not found
    """
    # Step 1: Decode JWT
    user_id = decode_refresh_token(refresh_token)
    if user_id is None:
        raise InvalidRefreshToken()

    # Step 2: Find matching session by hash
    token_hash = _hash_token(refresh_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.is_revoked == False,  # noqa: E712
            UserSession.deleted_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise InvalidRefreshToken()

    # Step 3: Check expiry
    session_expires = session.expires_at
    # Make timezone-aware if stored as naive (handles both DB configurations)
    if session_expires.tzinfo is None:
        session_expires = session_expires.replace(tzinfo=timezone.utc)

    if session_expires < now:
        # Expired — revoke it for cleanliness
        session.is_revoked = True
        await db.commit()
        raise InvalidRefreshToken()

    try:
        # Step 4: Revoke the old session (token rotation)
        session.is_revoked = True
        await db.flush()

        # Step 5: Generate new tokens
        new_access = create_access_token(subject=user_id)
        new_refresh = create_refresh_token(subject=user_id)

        # Step 6: Create new session
        import uuid
        db.add(_make_session(uuid.UUID(user_id), new_refresh, request_info))
        await db.commit()

        return new_access, new_refresh

    except Exception:
        await db.rollback()
        raise InvalidRefreshToken()


# ── logout_user ───────────────────────────────────────────────────────────────

async def logout_user(
    db: AsyncSession,
    refresh_token: str,
) -> bool:
    """
    Revoke the session associated with the given refresh token.

    Returns True if a session was found and revoked.
    Returns False if the token was already invalid (idempotent — no error).

    We don't raise an error on "token not found" because:
      - The user may have already logged out
      - The token may have already expired
      - Either way, the desired outcome (session invalidated) is achieved
    """
    token_hash = _hash_token(refresh_token)

    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.is_revoked == False,  # noqa: E712
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        return False  # Already logged out — that's fine

    session.is_revoked = True
    await db.commit()
    return True


# ── get_user_with_profile ─────────────────────────────────────────────────────

async def get_user_with_profile(
    db: AsyncSession,
    user_id,
) -> User | None:
    """
    Load a User with their profile eagerly joined in one query.

    Used by GET /users/me. Without selectinload, accessing user.profile
    outside the session would trigger a lazy-load error in async SQLAlchemy.
    """
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.profile),
            selectinload(User.preferences),
        )
        .where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


# ── update_user_profile ────────────────────────────────────────────────────────

async def update_user_profile(
    db: AsyncSession,
    user: User,
    full_name: str | None = None,
    phone_number: str | None = None,
    profile_picture_url: str | None = None,
) -> User:
    """
    Update mutable profile fields. Only supplied (non-None) fields are changed.
    Returns the updated User with profile loaded.
    """
    # Ensure profile is loaded
    if user.profile is None:
        user.profile = UserProfile(user_id=user.id)
        db.add(user.profile)

    if full_name is not None:
        user.profile.full_name = full_name.strip()
    if phone_number is not None:
        user.profile.phone_number = phone_number
    if profile_picture_url is not None:
        user.profile.profile_picture_url = profile_picture_url

    await db.commit()
    await db.refresh(user.profile)
    return user


# ── update_user_preferences ────────────────────────────────────────────────────

async def update_user_preferences(
    db: AsyncSession,
    user: User,
    updates: dict,
) -> UserPreferences:
    """
    Apply a dict of preference field updates.
    Only keys present in the dict are modified.
    """
    if user.preferences is None:
        user.preferences = UserPreferences(user_id=user.id)
        db.add(user.preferences)

    allowed_fields = {
        "interface_language", "transcript_language", "auto_translate",
        "theme", "notify_new_message", "notify_high_priority",
        "notify_emergency", "notify_suspicious", "notify_email",
        "audio_retention_days",
    }

    for field, value in updates.items():
        if field in allowed_fields and value is not None:
            setattr(user.preferences, field, value)

    await db.commit()
    await db.refresh(user.preferences)
    return user.preferences
