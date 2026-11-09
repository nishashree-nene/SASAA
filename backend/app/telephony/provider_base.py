"""
SASAA – Telephony Provider Interface
=======================================
Abstract base class that every telephony provider adapter must implement.

Design goals:
  - Provider-independent: swap Exotel for Twilio without touching the
    voicemail pipeline logic
  - Testable: the mock adapter implements this interface for automated tests
  - Safe: never expose provider credentials in return values

Terminology:
  call_id    – our internal ID for a call (maps to voicemail.id)
  provider_call_id – the call SID / reference from the telephony provider
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Request


# ── Provider response types ───────────────────────────────────────────────────

@dataclass
class InboundCallEvent:
    """
    Normalised representation of an inbound call / missed-call webhook event.
    All fields come directly from the provider webhook — nothing is invented.
    """
    provider_call_id: str          # Provider's unique call identifier
    caller_number: str             # E.164 caller number (or best available)
    called_number: str             # The SASAA VoIP number that received the call
    event_type: str                # Raw event type string from provider
    forward_reason: str            # "busy", "no_answer", "unreachable", "unknown"
    raw_payload: dict              # Complete raw webhook payload for debugging


@dataclass
class RecordingInfo:
    """
    Information about a provider recording, returned after recording completes.
    """
    provider_recording_id: str
    provider_recording_url: str    # Fetch URL — NEVER stored in DB as-is after download
    duration_seconds: Optional[float]
    mime_type: str                 # Best guess; validate after download
    raw_payload: dict


@dataclass
class ProviderHealth:
    """Current health status of the telephony provider account."""
    is_healthy: bool
    provider_name: str
    account_id: Optional[str]      # Masked — first 4 + last 4 chars only
    phone_numbers: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ── Abstract interface ─────────────────────────────────────────────────────────

class TelephonyProviderBase(ABC):
    """
    Abstract contract for all telephony provider adapters.

    Implementations:
      MockTelephonyAdapter    – automated tests
      ExotelAdapter           – Exotel India CPaaS
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name e.g. 'Exotel' or 'Mock'."""

    @abstractmethod
    async def validate_webhook(self, request: Request) -> bool:
        """
        Validate the HMAC signature on an inbound webhook request.

        Returns True if the signature is valid.
        Returns False if invalid — the webhook must be rejected (HTTP 403).

        Never raise an exception that leaks signature details.
        """

    @abstractmethod
    async def parse_inbound_event(self, request: Request) -> InboundCallEvent:
        """
        Parse the raw webhook body into a normalised InboundCallEvent.

        Called only after validate_webhook() returns True.
        Must handle all event types the provider sends (call initiated,
        recording ready, call ended, etc.).
        """

    @abstractmethod
    async def get_recording(self, provider_call_id: str) -> RecordingInfo:
        """
        Retrieve recording metadata for a completed call.

        Returns RecordingInfo with the URL to download the audio.
        The caller is responsible for downloading and storing the audio —
        this method only returns the metadata.

        Raises ProviderError on failure.
        """

    @abstractmethod
    async def download_recording(
        self,
        recording_url: str,
        destination_path: str,
    ) -> tuple[int, str]:
        """
        Download the recording audio to destination_path.

        Returns (size_bytes, mime_type).
        Validates that the downloaded content is audio before writing.
        Raises ProviderError on failure.
        """

    @abstractmethod
    async def get_call_details(self, provider_call_id: str) -> dict:
        """
        Fetch full call details from the provider.
        Used to backfill missing fields when webhook data is incomplete.
        """

    @abstractmethod
    async def get_provider_health(self) -> ProviderHealth:
        """
        Check provider account connectivity and return health info.
        Used by the telephony configuration screen.
        """


# ── Exception types ───────────────────────────────────────────────────────────

class ProviderError(Exception):
    """Base exception for all telephony provider errors."""
    def __init__(self, message: str, provider: str, is_retryable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.is_retryable = is_retryable


class WebhookSignatureError(ProviderError):
    """Raised when HMAC signature validation fails."""
    def __init__(self, provider: str):
        super().__init__(
            "Webhook signature validation failed.",
            provider=provider,
            is_retryable=False,
        )


class RecordingNotReadyError(ProviderError):
    """Raised when the recording is not yet available (needs retry)."""


class ProviderAuthError(ProviderError):
    """Raised when provider credentials are invalid."""
    def __init__(self, provider: str):
        super().__init__(
            "Provider authentication failed. Check credentials in .env.",
            provider=provider,
            is_retryable=False,
        )
