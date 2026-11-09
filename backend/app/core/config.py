"""
SASAA – Application Configuration
==================================
This module uses pydantic-settings to read every environment variable
from the .env file and expose them as typed Python attributes.

WHY THIS APPROACH:
  Instead of calling os.getenv("GNANI_API_KEY") scattered everywhere,
  every part of the app imports `settings` from here. This means:
  - One place to change variable names
  - Type validation (e.g. DATABASE_URL must be a string, port must be int)
  - Missing required variables are caught at startup, not mid-request
"""

from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    """
    All application settings, loaded from the .env file.
    pydantic-settings automatically maps UPPERCASE env var names
    to lowercase Python attribute names.
    """

    # ── Database ────────────────────────────────────────────
    # psycopg2 is used by Alembic (migrations) – synchronous driver
    database_url: str
    # asyncpg is used by SQLAlchemy async engine – for FastAPI routes
    async_database_url: str

    # ── Security ────────────────────────────────────────────
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ── Gnani AI STT ────────────────────────────────────────
    gnani_api_key: str
    gnani_stt_url: str = "https://api.vachana.ai/stt/v3"
    gnani_timeout_seconds: int = 120
    gnani_max_retries: int = 3
    # SSL verification — defaults to True (secure). Set GNANI_VERIFY_SSL=False
    # in .env only for development environments with certificate store issues.
    gnani_verify_ssl: bool = True

    # ── Application ─────────────────────────────────────────
    app_name: str = "SASAA"
    app_version: str = "1.0.0"
    environment: str = "development"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # ── Audio ───────────────────────────────────────────────
    audio_storage_path: str = "./audio_storage"
    max_audio_size_mb: int = 50

    # ── Email (optional) ────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@sasaa.app"

    # ── Firebase (optional) ─────────────────────────────────
    firebase_credentials_path: str = ""

    # ── Web Push VAPID (optional) ───────────────────────────
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = "admin@sasaa.app"

    # ── Logging ─────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Exotel Telephony (optional) ─────────────────────────
    # Required for live missed-call voicemail with Exotel India.
    # Leave empty to use mock adapter for local development.
    exotel_account_sid: str = ""
    exotel_api_key: str = ""
    exotel_api_token: str = ""
    exotel_phone_number: str = ""        # The ExoPhone SASAA uses
    exotel_webhook_secret: str = ""     # Optional shared secret for webhook validation
    exotel_subdomain: str = "api.in.exotel.com"  # India/Mumbai region

    # ── Telephony general ────────────────────────────────────
    # Set to "exotel", "twilio", or "mock" (default for development)
    telephony_provider: str = "mock"
    # Maximum voicemail recording duration in seconds
    max_voicemail_duration_seconds: int = 120
    # Default recording disclosure message (played before recording starts)
    voicemail_greeting: str = (
        "Hello, you have reached SASAA voicemail. "
        "This call will be recorded and transcribed for accuracy verification. "
        "Please leave your message after the tone."
    )

    @property
    def exotel_configured(self) -> bool:
        """True when Exotel credentials are fully configured."""
        return bool(
            self.exotel_account_sid and
            self.exotel_api_key and
            self.exotel_api_token and
            self.exotel_phone_number
        )

    # ── Computed properties ─────────────────────────────────

    @property
    def is_development(self) -> bool:
        """True when running locally. Enables extra debug information."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """True when deployed. Disables debug output, tightens security."""
        return self.environment == "production"

    @property
    def max_audio_size_bytes(self) -> int:
        """File size limit converted from MB to bytes for validation."""
        return self.max_audio_size_mb * 1024 * 1024

    @property
    def email_enabled(self) -> bool:
        """Only send emails if SMTP is configured."""
        return bool(self.smtp_host and self.smtp_username)

    @property
    def firebase_enabled(self) -> bool:
        """Only use Firebase if credentials file path is set."""
        return bool(self.firebase_credentials_path)

    @property
    def web_push_enabled(self) -> bool:
        """Only use Web Push if VAPID keys are configured."""
        return bool(self.vapid_private_key and self.vapid_public_key)

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_not_be_placeholder(cls, value: str) -> str:
        """
        Prevent accidentally running with the placeholder secret key.
        Generate a real one with:
            python -c "import secrets; print(secrets.token_hex(32))"
        """
        if value == "change-this-to-a-long-random-secret-key-before-running":
            raise ValueError(
                "SECRET_KEY is still set to the placeholder value. "
                "Generate a real key with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return value

    # Tell pydantic-settings to read from .env file

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )



@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    @lru_cache means this only reads the .env file ONCE, no matter how many
    times get_settings() is called across the application.
    This is more efficient than reading the file on every request.
    """
    return Settings()


# Single shared instance – import this throughout the app:
#   from app.core.config import settings
settings = get_settings()