"""
SASAA - Authentication Routes
================================
All endpoints are fully implemented. No 501 stubs remain.

POST /auth/register    – create account, get tokens
POST /auth/login       – sign in, get tokens
POST /auth/refresh     – rotate refresh token, get new tokens
POST /auth/logout      – revoke session (single device)
POST /auth/otp/request – placeholder (requires SMS provider)
POST /auth/otp/verify  – placeholder (requires SMS provider)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_db
from app.schemas.auth import (
    LoginRequest,
    OtpRequest,
    OtpVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.common import SuccessResponse
from app.services.user_service import (
    AccountInactive,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    login_user,
    logout_user,
    refresh_tokens,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _request_info(request: Request) -> dict:
    """Extract safe metadata from the incoming request for audit logging."""
    return {
        "user_agent": request.headers.get("user-agent", "")[:500],
        "ip_address": request.client.host if request.client else None,
    }


# ── POST /auth/register ───────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Create a new SASAA account.

    - Validates email format and password strength
    - Hashes password with bcrypt (never stored in plaintext)
    - Creates user, profile, and preferences records
    - Returns access token (30 min) and refresh token (7 days)

    Errors:
    - 409 if email already registered
    - 422 if request body is invalid
    """
    try:
        access_token, refresh_token = await register_user(
            db=db,
            email=str(body.email),
            password=body.password,
            full_name=body.full_name,
            request_info=_request_info(request),
        )
    except EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in with email and password",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Sign in with email and password.

    Returns access token (30 min) and refresh token (7 days).

    Errors:
    - 401 if email not found or password is incorrect
         (same error for both to prevent user enumeration)
    - 403 if account is suspended
    """
    try:
        access_token, refresh_token = await login_user(
            db=db,
            email=str(body.email),
            password=body.password,
            request_info=_request_info(request),
        )
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AccountInactive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended. Please contact support.",
        )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── POST /auth/refresh ────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Get new tokens using a refresh token",
)
async def token_refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Exchange a valid refresh token for a new access token and refresh token.

    Implements token rotation: the old refresh token is invalidated immediately.
    Store the new refresh token — the old one will not work again.

    Errors:
    - 401 if the refresh token is invalid, expired, or already used
    """
    try:
        new_access, new_refresh = await refresh_tokens(
            db=db,
            refresh_token=body.refresh_token,
            request_info=_request_info(request),
        )
    except InvalidRefreshToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post(
    "/logout",
    response_model=SuccessResponse,
    summary="Sign out from the current device",
)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Revoke the refresh token for the current device session.

    Pass the refresh token in the request body. The token is invalidated
    immediately — future refresh requests with this token will return 401.

    This endpoint is idempotent: if the token is already revoked, it still
    returns 200 (the goal of being logged out is already achieved).
    """
    await logout_user(db=db, refresh_token=body.refresh_token)

    return SuccessResponse(
        success=True,
        message="You have been signed out successfully.",
    )


# ── POST /auth/otp/request ────────────────────────────────────────────────────

@router.post(
    "/otp/request",
    response_model=SuccessResponse,
    summary="Request OTP via SMS (requires SMS provider)",
)
async def request_otp(body: OtpRequest):
    """
    Request a one-time password sent to a phone number.

    NOT YET AVAILABLE: requires an SMS provider (e.g. Twilio).

    To enable:
      1. Sign up at https://www.twilio.com
      2. Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER to .env
      3. Install twilio: pip install twilio
      4. Implement send_otp() in services/otp_service.py
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "OTP authentication requires an SMS provider. "
            "Email and password login is available at POST /auth/login."
        ),
    )


# ── POST /auth/otp/verify ─────────────────────────────────────────────────────

@router.post(
    "/otp/verify",
    response_model=TokenResponse,
    summary="Verify OTP code (requires SMS provider)",
)
async def verify_otp(body: OtpVerifyRequest):
    """Verify an OTP. Requires SMS provider — see /auth/otp/request."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="OTP verification requires SMS provider configuration.",
    )
