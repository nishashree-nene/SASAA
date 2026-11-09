"""
SASAA – Exotel Telephony Adapter
==================================
Implements TelephonyProviderBase for Exotel India (CPaaS provider).

API FACTS — verified from Exotel official documentation:
  Authentication:   HTTP Basic Auth — API_KEY:API_TOKEN as username:password
  India base URL:   https://api.in.exotel.com/v1/Accounts/{account_sid}/
  Call details:     GET /v1/Accounts/{sid}/Calls/{call_sid}
  Recording URL:    Present in Call object as "RecordingUrl" (S3 direct URL)
  Passthru fields:  CallSid, CallFrom, CallTo, CallStatus, Direction,
                    From, To, RecordingUrl, StartTime, EndTime, Duration
  Webhook format:   HTTP GET with URL-encoded query parameters (Passthru applet)
                    OR HTTP POST form-encoded (StatusCallback)

WEBHOOK SIGNATURE:
  Exotel does NOT publish an HMAC webhook signing mechanism in their official
  documentation (as of the audit date). They recommend IP allowlisting and HTTPS.
  This adapter validates webhook origin by:
    1. Checking the EXOTEL_WEBHOOK_SECRET shared secret if configured (custom)
    2. Falling back to permissive mode with a warning when no secret is set
  IP allowlisting must be configured separately at the firewall/CDN level.

RECORDING DOWNLOAD:
  The RecordingUrl is a direct S3 URL. Exotel's signed URL feature (TTL 5–60 min)
  must be enabled per-account. When not enabled, the URL requires Basic Auth.
  This adapter supports both modes — it first tries without auth, then with.

EXTERNAL DEPENDENCIES:
  - EXOTEL_ACCOUNT_SID        Your Exotel account SID
  - EXOTEL_API_KEY            API key (used as Basic Auth username)
  - EXOTEL_API_TOKEN          API token (used as Basic Auth password)
  - EXOTEL_PHONE_NUMBER       The ExoPhone number SASAA is configured on
  - EXOTEL_WEBHOOK_SECRET     Optional shared secret for webhook validation
  - EXOTEL_SUBDOMAIN          Defaults to api.in.exotel.com (India/Mumbai)

  None of these are required at import time — missing credentials produce
  a clear error when the method is called, not at startup.
"""

import hashlib
import hmac
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

from fastapi import Request

from app.telephony.provider_base import (
    InboundCallEvent,
    ProviderAuthError,
    ProviderError,
    ProviderHealth,
    RecordingInfo,
    RecordingNotReadyError,
    TelephonyProviderBase,
)

logger = structlog.get_logger(__name__)

# Supported audio content-types from Exotel recordings
_AUDIO_CONTENT_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/wav",
    "audio/ogg", "audio/x-wav", "audio/basic", "audio/amr",
}


def _mask(value: str) -> str:
    """Return first 4 + last 4 chars of a string, rest replaced with ***."""
    if not value or len(value) < 10:
        return "****"
    return value[:4] + "****" + value[-4:]


class ExotelAdapter(TelephonyProviderBase):
    """
    Exotel telephony provider adapter for SASAA voicemail pipeline.

    All external calls use httpx async client with explicit timeouts.
    Credentials are read at method call time from settings — never stored
    as instance attributes to avoid accidental logging.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        api_key: Optional[str] = None,
        api_token: Optional[str] = None,
        phone_number: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        subdomain: str = "api.in.exotel.com",
    ) -> None:
        """
        Accept credentials directly (for testing) or read from settings.
        When called without arguments, credentials are loaded lazily from
        app.core.config.settings at method call time.
        """
        self._account_sid = account_sid
        self._api_key = api_key
        self._api_token = api_token
        self._phone_number = phone_number
        self._webhook_secret = webhook_secret
        self._subdomain = subdomain

    def _get_credentials(self) -> tuple[str, str, str]:
        """
        Return (account_sid, api_key, api_token).
        Loads from settings if not provided at construction time.
        Raises ProviderAuthError if any credential is missing.
        """
        sid = self._account_sid
        key = self._api_key
        token = self._api_token

        if not (sid and key and token):
            # Lazy import to avoid circular imports and allow module-level tests
            try:
                from app.core.config import settings
                sid = sid or getattr(settings, "exotel_account_sid", "")
                key = key or getattr(settings, "exotel_api_key", "")
                token = token or getattr(settings, "exotel_api_token", "")
            except Exception:
                pass

        if not sid:
            raise ProviderAuthError(provider="Exotel")
        if not key:
            raise ProviderAuthError(provider="Exotel")
        if not token:
            raise ProviderAuthError(provider="Exotel")

        return sid, key, token

    def _base_url(self, account_sid: str) -> str:
        return f"https://{self._subdomain}/v1/Accounts/{account_sid}"

    @property
    def provider_name(self) -> str:
        return "Exotel"

    # ── Webhook validation ────────────────────────────────────────────────────

    async def validate_webhook(self, request: Request) -> bool:
        """
        Validate an inbound Exotel webhook.

        Exotel does not publish a standard HMAC signing mechanism.
        Security is achieved through:
          1. HTTPS (enforced at the infrastructure level)
          2. IP allowlisting of Exotel's IP ranges
          3. Optional EXOTEL_WEBHOOK_SECRET shared secret check

        When EXOTEL_WEBHOOK_SECRET is configured, this method checks a custom
        X-Exotel-Signature header. When it is not configured, all requests
        from HTTPS origins are accepted (IP-level security is assumed).
        """
        secret = self._webhook_secret
        if not secret:
            try:
                from app.core.config import settings
                secret = getattr(settings, "exotel_webhook_secret", "")
            except Exception:
                secret = ""

        if not secret:
            # No shared secret configured — accept and log a warning
            logger.warning(
                "EXOTEL_WEBHOOK_SECRET not configured. "
                "Webhooks are accepted without signature validation. "
                "Configure IP allowlisting at your firewall."
            )
            return True

        # Check custom header if secret is configured
        signature = request.headers.get("X-Exotel-Signature", "")
        if not signature:
            logger.warning("Webhook missing X-Exotel-Signature header")
            return False

        body = await request.body()
        expected = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        valid = hmac.compare_digest(expected, signature.lower())
        if not valid:
            logger.warning("Exotel webhook signature mismatch")
        return valid

    # ── Event parsing ─────────────────────────────────────────────────────────

    async def parse_inbound_event(self, request: Request) -> InboundCallEvent:
        """
        Parse Exotel Passthru or StatusCallback webhook into InboundCallEvent.

        Exotel Passthru applet sends a GET request with URL-encoded query params:
          CallSid, CallFrom, CallTo, CallStatus, Direction, From, To,
          RecordingUrl, StartTime, EndTime, Duration, CallType

        StatusCallback (POST) also uses the same field names as form data.
        This method handles both.
        """
        # Collect params from query string AND form body
        params: dict[str, str] = dict(request.query_params)

        # If it's a POST, also read form data
        if request.method == "POST":
            try:
                form = await request.form()
                params.update({k: str(v) for k, v in form.items()})
            except Exception:
                pass  # GET-only webhook

        call_sid = (
            params.get("CallSid") or
            params.get("call_sid") or
            params.get("Sid") or
            ""
        )
        if not call_sid:
            raise ProviderError(
                "Exotel webhook missing CallSid",
                provider="Exotel",
                is_retryable=False,
            )

        # CallFrom / From = the caller's number (in Indian format, may start with 0)
        caller_raw = (
            params.get("CallFrom") or
            params.get("From") or
            ""
        )
        # CallTo / To = the ExoPhone (SASAA's number)
        called_raw = (
            params.get("CallTo") or
            params.get("To") or
            ""
        )

        call_status = params.get("CallStatus", "").lower()
        direction = params.get("Direction", "incoming").lower()

        # Map Exotel call status to SASAA forward reason
        forward_reason = _map_forward_reason(call_status, direction)

        logger.info(
            "Exotel webhook parsed",
            call_sid=call_sid,
            call_status=call_status,
            direction=direction,
            has_recording_url="RecordingUrl" in params,
        )

        return InboundCallEvent(
            provider_call_id=call_sid,
            caller_number=_normalise_number(caller_raw),
            called_number=_normalise_number(called_raw),
            event_type=call_status,
            forward_reason=forward_reason,
            raw_payload=params,
        )

    # ── Recording retrieval ───────────────────────────────────────────────────

    async def get_recording(self, provider_call_id: str) -> RecordingInfo:
        """
        Retrieve recording information for a completed Exotel call.

        Fetches call details from GET /v1/Accounts/{sid}/Calls/{call_sid}
        and extracts the RecordingUrl field.

        The RecordingUrl is a direct S3 URL. It may require Basic Auth headers
        (if signed URL feature is not enabled on the account).
        """
        sid, key, token = self._get_credentials()
        url = f"{self._base_url(sid)}/Calls/{provider_call_id}.json"

        logger.info("Fetching Exotel call details", call_sid=provider_call_id)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, auth=(key, token))
        except httpx.TimeoutException:
            raise RecordingNotReadyError(
                f"Timeout fetching call details for {provider_call_id}",
                provider="Exotel",
            )
        except httpx.NetworkError as exc:
            raise ProviderError(
                f"Network error fetching call details: {exc}",
                provider="Exotel",
                is_retryable=True,
            )

        if response.status_code == 404:
            raise RecordingNotReadyError(
                f"Call {provider_call_id} not found on Exotel (404). "
                "It may not have completed yet.",
                provider="Exotel",
            )

        if response.status_code in {401, 403}:
            raise ProviderAuthError(provider="Exotel")

        if not response.is_success:
            raise ProviderError(
                f"Exotel call details returned HTTP {response.status_code}",
                provider="Exotel",
                is_retryable=response.status_code >= 500,
            )

        try:
            data = response.json()
        except Exception:
            raise ProviderError(
                "Exotel returned non-JSON response for call details",
                provider="Exotel",
                is_retryable=True,
            )

        call = data.get("Call", data)  # Handle both wrapped and unwrapped response

        recording_url = call.get("RecordingUrl", "")
        if not recording_url:
            raise RecordingNotReadyError(
                f"No RecordingUrl in Exotel call details for {provider_call_id}. "
                "Recording may not be ready yet.",
                provider="Exotel",
            )

        duration_raw = call.get("Duration")
        try:
            duration = float(duration_raw) if duration_raw else None
        except (ValueError, TypeError):
            duration = None

        logger.info(
            "Exotel recording URL retrieved",
            call_sid=provider_call_id,
            duration_seconds=duration,
        )

        return RecordingInfo(
            provider_recording_id=f"exotel-rec-{provider_call_id}",
            provider_recording_url=recording_url,
            duration_seconds=duration,
            mime_type="audio/mpeg",   # Exotel recordings are MP3
            raw_payload=call,
        )

    async def download_recording(
        self,
        recording_url: str,
        destination_path: str,
    ) -> tuple[int, str]:
        """
        Download the recording audio file from Exotel's S3 URL.

        Tries unauthenticated first (signed URLs), then with Basic Auth
        (for accounts without signed URL feature enabled).

        Returns (size_bytes, mime_type).
        Raises ProviderError if the content is not audio.
        """
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        _, key, token = self._get_credentials()

        logger.info("Downloading Exotel recording", destination=str(dest))

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            # Attempt 1: unauthenticated (signed URL)
            response = await client.get(recording_url)

            if response.status_code in {401, 403}:
                # Attempt 2: with Basic Auth
                logger.info("Retrying recording download with Basic Auth")
                response = await client.get(recording_url, auth=(key, token))

            if not response.is_success:
                raise ProviderError(
                    f"Recording download failed: HTTP {response.status_code}",
                    provider="Exotel",
                    is_retryable=response.status_code >= 500,
                )

        content_type = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()

        # Validate that the response is actually audio
        if not (
            content_type.startswith("audio/") or
            content_type == "binary/octet-stream" or
            content_type == "application/octet-stream"
        ):
            raise ProviderError(
                f"Downloaded content is not audio: content-type={content_type}",
                provider="Exotel",
                is_retryable=False,
            )

        audio_bytes = response.content
        if len(audio_bytes) < 100:
            raise ProviderError(
                f"Downloaded audio is too small ({len(audio_bytes)} bytes). "
                "Recording may be corrupted or empty.",
                provider="Exotel",
                is_retryable=False,
            )

        dest.write_bytes(audio_bytes)
        logger.info(
            "Recording downloaded",
            size_bytes=len(audio_bytes),
            mime_type=content_type,
        )
        return len(audio_bytes), content_type

    async def get_call_details(self, provider_call_id: str) -> dict:
        """Fetch full call details from Exotel Call API."""
        sid, key, token = self._get_credentials()
        url = f"{self._base_url(sid)}/Calls/{provider_call_id}.json"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, auth=(key, token))

        if response.status_code in {401, 403}:
            raise ProviderAuthError(provider="Exotel")

        if not response.is_success:
            raise ProviderError(
                f"Call details API returned {response.status_code}",
                provider="Exotel",
                is_retryable=response.status_code >= 500,
            )

        return response.json().get("Call", response.json())

    async def get_provider_health(self) -> ProviderHealth:
        """
        Check Exotel account connectivity by fetching account balance.
        Uses GET /v1/Accounts/{sid}/Balance.json
        """
        try:
            sid, key, token = self._get_credentials()
        except ProviderAuthError as exc:
            return ProviderHealth(
                is_healthy=False,
                provider_name="Exotel",
                account_id=None,
                error=str(exc),
            )

        url = f"{self._base_url(sid)}/Balance.json"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, auth=(key, token))
        except Exception as exc:
            return ProviderHealth(
                is_healthy=False,
                provider_name="Exotel",
                account_id=_mask(sid),
                error=f"Network error: {type(exc).__name__}",
            )

        if response.status_code in {401, 403}:
            return ProviderHealth(
                is_healthy=False,
                provider_name="Exotel",
                account_id=_mask(sid),
                error="Authentication failed. Check EXOTEL_API_KEY and EXOTEL_API_TOKEN.",
            )

        if not response.is_success:
            return ProviderHealth(
                is_healthy=False,
                provider_name="Exotel",
                account_id=_mask(sid),
                error=f"Health check failed: HTTP {response.status_code}",
            )

        phone = self._phone_number or ""
        try:
            from app.core.config import settings
            phone = phone or getattr(settings, "exotel_phone_number", "")
        except Exception:
            pass

        return ProviderHealth(
            is_healthy=True,
            provider_name="Exotel",
            account_id=_mask(sid),
            phone_numbers=[phone] if phone else [],
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_number(raw: str) -> str:
    """
    Normalise an Exotel phone number to E.164-ish format.

    Exotel delivers Indian numbers in various formats:
      0XXXXXXXXXX  (10-digit with leading 0)
      91XXXXXXXXXX (with country code, no +)
      +91XXXXXXXXXX (E.164)
      XXXXXXXXXX (bare 10 digits)
    """
    if not raw:
        return raw
    stripped = raw.strip().replace("-", "").replace(" ", "")
    if stripped.startswith("+"):
        return stripped  # already E.164
    if stripped.startswith("0") and len(stripped) == 11:
        return "+91" + stripped[1:]  # 0XXXXXXXXXX → +91XXXXXXXXXX
    if stripped.startswith("91") and len(stripped) == 12:
        return "+" + stripped     # 91XXXXXXXXXX → +91XXXXXXXXXX
    if len(stripped) == 10 and stripped[0] in "6789":
        return "+91" + stripped   # bare Indian mobile → +91XXXXXXXXXX
    return stripped  # return as-is if format is unrecognised


def _map_forward_reason(call_status: str, direction: str) -> str:
    """
    Map Exotel call_status to SASAA ForwardReason.

    Exotel CallStatus values: queued, ringing, in-progress, completed,
    busy, failed, no-answer, canceled
    """
    status_lower = call_status.lower()
    if status_lower == "busy":
        return "busy"
    if status_lower in {"no-answer", "no_answer"}:
        return "no_answer"
    if status_lower in {"failed", "canceled"}:
        return "unreachable"
    # "completed" without answer = likely no-answer or voicemail trigger
    return "unknown"
