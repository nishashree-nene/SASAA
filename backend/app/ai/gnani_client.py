"""
SASAA – Gnani AI Speech-to-Text Client
========================================
This module is a direct evolution of the working guardian.py file.

What is preserved from guardian.py:
  - API endpoint: https://api.vachana.ai/stt/v3
  - Auth header: X-API-Key-ID
  - Retry logic: up to 3 attempts
  - 504 gateway timeout handling with 5-second delay
  - 120-second request timeout
  - Multipart form upload with audio_file field

What is added:
  - Async HTTP using httpx (FastAPI-native, non-blocking)
  - Config-driven (URL, key, timeout, retries from settings)
  - Typed response dataclass (never invents fields)
  - Proper latency measurement
  - All response fields from main.py captured:
      transcript, detected_language_code, end_to_end_latency
  - Model parameter: prisma-v3.0 (from main.py)
  - Structured logging
  - No retries on auth failures (403) — prevents key lockout

IMPORTANT SECURITY RULE:
  The API key is read from settings (which reads from .env).
  It is NEVER hardcoded, logged, or included in any response to clients.
  FastAPI routes never receive or return the API key.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


# ── Response types ──────────────────────────────────────────────────────────

@dataclass
class GnaniTranscriptResult:
    """
    The result of a successful Gnani STT call.

    All fields come directly from the Gnani API response.
    We never invent values — if a field is absent from the response,
    it is stored as None.

    Fields documented from Gnani Prisma v3 API (matching main.py usage):
      transcript            – the transcribed text
      detected_language_code – BCP-47 code e.g. "ta-IN"
      end_to_end_latency    – processing time in milliseconds (from Gnani)
      our_latency_ms        – time we measured (upload + wait + download)
    """
    transcript: str
    detected_language_code: Optional[str]
    end_to_end_latency: Optional[int]   # milliseconds, from Gnani
    our_latency_ms: int                  # milliseconds, measured by us
    raw_response: dict                   # full response stored for debugging


@dataclass
class GnaniError:
    """
    Returned when transcription fails after all retries.
    Contains enough information to show a clear error message.
    """
    status_code: Optional[int]
    error_type: str       # "TIMEOUT", "AUTH_FAILED", "API_ERROR", "NETWORK_ERROR"
    message: str          # Safe to show in logs (never contains the API key)
    is_retryable: bool    # False for auth errors and invalid audio


# ── Error types that should NOT be retried ──────────────────────────────────
# Retrying these wastes time and could lock the API key
NON_RETRYABLE_STATUS_CODES = {
    401,   # Invalid API key
    403,   # Forbidden
    400,   # Bad request (invalid audio format / parameters)
    413,   # File too large
}


async def transcribe_audio(
    audio_file_path: str,
    language_code: str = "ta-IN",
    mime_type: str = "audio/ogg",
) -> GnaniTranscriptResult | GnaniError:
    """
    Send an audio file to Gnani STT and return the transcript.

    This is the async version of guardian.py's transcribe_audio() function.
    It uses httpx instead of requests to avoid blocking FastAPI's event loop.

    Args:
        audio_file_path: Absolute path to the audio file on disk
        language_code:   BCP-47 language code e.g. "ta-IN", "en-IN"
        mime_type:       MIME type of the audio file e.g. "audio/ogg"

    Returns:
        GnaniTranscriptResult on success
        GnaniError on failure (after all retries exhausted)

    Example:
        result = await transcribe_audio("/path/to/audio.ogg", "ta-IN")
        if isinstance(result, GnaniTranscriptResult):
            print(result.transcript)
        else:
            print(f"Failed: {result.message}")
    """
    api_key = settings.gnani_api_key
    api_url = settings.gnani_stt_url
    max_retries = settings.gnani_max_retries
    timeout_secs = settings.gnani_timeout_seconds

    if not api_key:
        return GnaniError(
            status_code=None,
            error_type="CONFIG_ERROR",
            message="GNANI_API_KEY is not set in .env",
            is_retryable=False,
        )

    # SSL verification: secure by default, can be disabled for development
    # environments with certificate store issues via GNANI_VERIFY_SSL=False
    verify_ssl = settings.gnani_verify_ssl
    if not verify_ssl:
        logger.warning(
            "SSL certificate verification is DISABLED for Gnani API. "
            "This is insecure — only use in development."
        )

    audio_path = Path(audio_file_path)
    if not audio_path.exists():
        return GnaniError(
            status_code=None,
            error_type="FILE_NOT_FOUND",
            message=f"Audio file not found: {audio_path.name}",
            is_retryable=False,
        )

    logger.info(
        "Starting Gnani STT transcription",
        file=audio_path.name,
        language=language_code,
        mime_type=mime_type,
        max_retries=max_retries,
    )

    # ── Retry loop (preserved from guardian.py) ────────────────────────────
    for attempt in range(1, max_retries + 1):
        logger.info(f"Gnani API attempt {attempt}/{max_retries}")

        start_time = time.monotonic()
        response = None

        try:
            async with httpx.AsyncClient(timeout=timeout_secs, verify=verify_ssl) as client:

                with open(audio_path, "rb") as audio_file:
                    files = {
                        "audio_file": (
                            audio_path.name,
                            audio_file,
                            mime_type,
                        )
                    }
                    data = {
                        "model": "prisma-v3.0",       # from main.py
                        "language_code": language_code,
                        "format": "verbatim",          # from guardian.py
                    }

                    response = await client.post(
                        api_url,
                        headers={
                            "X-API-Key-ID": api_key   # from guardian.py
                        },
                        files=files,
                        data=data,
                    )

            our_latency_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "Gnani API response received",
                status_code=response.status_code,
                latency_ms=our_latency_ms,
                attempt=attempt,
            )

            # ── 504 Gateway Timeout — retry (from guardian.py) ──────────────
            if response.status_code == 504:
                logger.warning("Gnani gateway timeout (504)", attempt=attempt)
                if attempt < max_retries:
                    import asyncio
                    logger.info("Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                return GnaniError(
                    status_code=504,
                    error_type="GATEWAY_TIMEOUT",
                    message=f"Gnani API gateway timed out after {max_retries} attempts.",
                    is_retryable=False,
                )

            # ── Non-retryable errors ─────────────────────────────────────────
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                error_body = _safe_response_text(response)
                logger.error(
                    "Gnani API non-retryable error",
                    status_code=response.status_code,
                    # Never log the API key — only log the status code
                )
                return GnaniError(
                    status_code=response.status_code,
                    error_type="AUTH_FAILED" if response.status_code in {401, 403} else "API_ERROR",
                    message=f"Gnani API returned {response.status_code}. Check API key and audio format.",
                    is_retryable=False,
                )

            # ── Other HTTP errors — retry if attempts remain ─────────────────
            if response.status_code >= 400:
                logger.warning(
                    "Gnani API error",
                    status_code=response.status_code,
                    attempt=attempt,
                )
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(3)
                    continue
                return GnaniError(
                    status_code=response.status_code,
                    error_type="API_ERROR",
                    message=f"Gnani API returned HTTP {response.status_code}.",
                    is_retryable=True,
                )

            # ── Successful response ──────────────────────────────────────────
            try:
                result = response.json()
            except Exception:
                logger.error("Gnani API returned invalid JSON")
                return GnaniError(
                    status_code=response.status_code,
                    error_type="INVALID_RESPONSE",
                    message="Gnani API returned an unreadable response.",
                    is_retryable=True,
                )

            # Extract transcript — field name confirmed from guardian.py and main.py
            transcript = result.get("transcript", "")

            if not transcript:
                logger.warning("Gnani returned empty transcript", response_keys=list(result.keys()))
                return GnaniError(
                    status_code=200,
                    error_type="EMPTY_TRANSCRIPT",
                    message="Gnani processed the audio but returned an empty transcript.",
                    is_retryable=False,
                )

            # Extract optional fields (from main.py response handling)
            detected_language = result.get("detected_language_code")
            gnani_latency = result.get("end_to_end_latency")

            # Convert latency to int if it's a string or float
            if gnani_latency is not None:
                try:
                    gnani_latency = int(float(gnani_latency))
                except (ValueError, TypeError):
                    gnani_latency = None

            logger.info(
                "Gnani transcription successful",
                language=detected_language,
                gnani_latency_ms=gnani_latency,
                our_latency_ms=our_latency_ms,
                transcript_length=len(transcript),
            )

            return GnaniTranscriptResult(
                transcript=transcript,
                detected_language_code=detected_language,
                end_to_end_latency=gnani_latency,
                our_latency_ms=our_latency_ms,
                raw_response=result,
            )

        except httpx.TimeoutException:
            logger.warning("Gnani request timed out", attempt=attempt, timeout_secs=timeout_secs)
            if attempt < max_retries:
                import asyncio
                logger.info("Retrying in 5 seconds...")
                await asyncio.sleep(5)
                continue
            return GnaniError(
                status_code=None,
                error_type="TIMEOUT",
                message=f"Gnani API timed out after {timeout_secs}s on all {max_retries} attempts.",
                is_retryable=True,
            )

        except httpx.NetworkError as e:
            logger.error("Gnani network error", error=str(e), attempt=attempt)
            return GnaniError(
                status_code=None,
                error_type="NETWORK_ERROR",
                message="Could not connect to Gnani API. Check your internet connection.",
                is_retryable=True,
            )

        except Exception as e:
            logger.error("Unexpected Gnani error", error=str(e), attempt=attempt, exc_info=True)
            return GnaniError(
                status_code=None,
                error_type="UNEXPECTED_ERROR",
                message=f"Unexpected error during transcription: {type(e).__name__}",
                is_retryable=False,
            )

    # Should not reach here, but be explicit
    return GnaniError(
        status_code=None,
        error_type="EXHAUSTED",
        message=f"All {max_retries} Gnani API attempts failed.",
        is_retryable=True,
    )


def _safe_response_text(response: httpx.Response) -> str:
    """
    Safely get response body for logging.
    Truncated to 500 chars to avoid flooding logs.
    Never returns anything that could contain the API key.
    """
    try:
        text = response.text[:500]
        # Remove any occurrence of the API key from log output
        return text.replace(settings.gnani_api_key, "[REDACTED]")
    except Exception:
        return "[unreadable response]"
