"""
SASAA – Security Utilities
===========================
Handles two critical security concerns:

1. PASSWORD HASHING
   Uses bcrypt via passlib. Bcrypt is deliberately slow — that's the point.
   It makes brute-force attacks against stolen password hashes impractical.
   We NEVER store plaintext passwords. Ever.

2. JWT TOKENS
   JSON Web Tokens carry the user's identity between requests.
   - Access token: short-lived (30 min), sent with every API request
   - Refresh token: longer-lived (7 days), used only to get a new access token
   Both are signed with SECRET_KEY so the server can verify they weren't tampered with.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ── Password hashing ────────────────────────────────────────────────────────

# CryptContext configures which hashing algorithm to use.
# bcrypt is the industry standard for passwords.
# deprecated="auto" means if we ever switch algorithms, old hashes are
# automatically recognised and users are migrated on their next login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Example:
        hashed = hash_password("mysecretpassword")
        # hashed looks like: "$2b$12$..."
        # The original password cannot be recovered from this string.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check whether a plaintext password matches a stored bcrypt hash.

    Returns True if they match, False otherwise.
    Never raises an exception for a wrong password — just returns False.

    Example:
        is_correct = verify_password("mysecretpassword", stored_hash)
    """
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT token creation ──────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        subject: The user's ID (as a string). Stored in the "sub" claim.
        expires_delta: Override the default expiry time. Used in tests.

    Returns:
        A signed JWT string that the client includes in the
        Authorization header: "Bearer <token>"

    The token payload contains:
        sub  – user ID
        exp  – expiry timestamp
        type – "access" (so we can reject refresh tokens used as access tokens)
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)

    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "sub": subject,        # subject = user ID
        "exp": expire,         # expiry time
        "type": "access",      # token type guard
    }

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a longer-lived JWT refresh token.

    Refresh tokens are stored in the database so they can be revoked
    (e.g. on logout or password change). Access tokens are stateless
    and cannot be individually revoked before expiry.

    Args:
        subject: The user's ID.
        expires_delta: Override the default expiry time.

    Returns:
        A signed JWT string used only to request a new access token.
    """
    if expires_delta is None:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)

    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",     # Must be "refresh" – rejected by access token routes
    }

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


# ── JWT token verification ──────────────────────────────────────────────────

def decode_access_token(token: str) -> Optional[str]:
    """
    Decode and verify a JWT access token.

    Returns the user ID (subject) if the token is valid, or None if:
    - The token is expired
    - The signature is invalid (tampered)
    - The token type is not "access"

    We return None rather than raising an exception here.
    The actual HTTP 401 error is raised by the dependency in dependencies.py.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        # Guard: reject refresh tokens presented as access tokens
        if payload.get("type") != "access":
            return None

        user_id: Optional[str] = payload.get("sub")
        return user_id

    except JWTError:
        # Covers: expired tokens, invalid signatures, malformed tokens
        return None


def decode_refresh_token(token: str) -> Optional[str]:
    """
    Decode and verify a JWT refresh token.

    Returns the user ID if valid, or None if invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != "refresh":
            return None

        user_id: Optional[str] = payload.get("sub")
        return user_id

    except JWTError:
        return None
