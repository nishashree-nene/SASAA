"""
SASAA – Authentication Pydantic Schemas
=========================================
Request and response shapes for all /auth endpoints.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Body for POST /auth/register"""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        """
        Enforce a basic password policy.
        At least 8 chars with at least one digit.
        """
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must contain at least one number.")
        return value


class LoginRequest(BaseModel):
    """Body for POST /auth/login"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """
    Returned after a successful login or token refresh.
    The access_token is short-lived (30 min).
    The refresh_token is longer-lived (7 days) and used only to get
    a new access_token via POST /auth/refresh.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int             # Access token lifetime in seconds


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh"""
    refresh_token: str


class OtpRequest(BaseModel):
    """Body for POST /auth/otp/request"""
    phone_number: str = Field(
        min_length=10,
        max_length=15,
        description="Phone number in E.164 format e.g. +919876543210",
    )


class OtpVerifyRequest(BaseModel):
    """Body for POST /auth/otp/verify"""
    phone_number: str
    otp_code: str = Field(min_length=4, max_length=8)
