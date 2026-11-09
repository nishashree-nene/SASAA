"""
SASAA – Telephony Webhook Router
===================================
Handles inbound webhook events from telephony providers.

POST /api/v1/telephony/webhooks/{provider}
GET  /api/v1/telephony/configuration
POST /api/v1/telephony/test
GET  /api/v1/telephony/test/{test_id}

The webhook endpoint is intentionally unauthenticated (no Bearer token) because
telephony providers call it from their own systems. Security is provided by:
  1. HTTPS (enforced at infra level)
  2. Webhook signature validation (provider-specific)
  3. IP allowlisting (configured at firewall)
  4. Idempotency checks (duplicate events are silently discarded)

The configuration and test endpoints require user authentication.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.voicemail import TelephonyProvider, Voicemail
from app.schemas.common import SuccessResponse
from app.services.voicemail_service import (
    get_or_create_voicemail,
    link_event_to_voicemail,
    mark_voicemail_recording,
    process_voicemail_recording,
    record_telephony_event,
)
from app.telephony.provider_base import ProviderError, RecordingNotReadyError, WebhookSignatureError
from app.telephony.registry import get_provider

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/telephony", tags=["Telephony"])

# In-memory test job store (in production, use a DB-backed store)
_test_jobs: dict[str, dict] = {}


# ── Webhook endpoint ─────────────────────────────────────────────────────────

@router.post(
    "/webhooks/{provider_name}",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound telephony webhook",
)
async def receive_webhook(
    provider_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Receive and process an inbound telephony event.

    Returns HTTP 200 immediately — all processing is asynchronous.
    Providers that don't receive 200 within their timeout will retry,
    which is handled by idempotency checks.

    Security: signature validation happens before any processing.
    """
    log = logger.bind(provider=provider_name)

    # ── 1. Resolve provider ───────────────────────────────────────────────────
    try:
        # Try exact match first, then case-insensitive
        try:
            provider_enum = TelephonyProvider(provider_name.lower())
        except ValueError:
            provider_enum = TelephonyProvider(provider_name.upper())
    except ValueError:
        log.warning("Unknown provider in webhook URL")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_name}' is not supported.",
        )

    adapter = get_provider()

    # Verify the provider matches what's configured
    if adapter.provider_name.lower() != provider_name.lower() and provider_name.lower() != "mock":
        log.warning(
            "Webhook provider mismatch",
            configured=adapter.provider_name,
            received=provider_name,
        )
        # Accept anyway — the signature check below will be the real gate

    # ── 2. Validate signature ─────────────────────────────────────────────────
    try:
        is_valid = await adapter.validate_webhook(request)
    except Exception as exc:
        log.error("Signature validation error", error=str(exc))
        raise HTTPException(status_code=500, detail="Webhook validation error.")

    if not is_valid:
        log.warning("Webhook signature invalid — rejecting")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook signature validation failed.",
        )

    # ── 3. Compute payload hash for idempotency ───────────────────────────────
    raw_body = await request.body()
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    # ── 4. Parse event ────────────────────────────────────────────────────────
    try:
        # Re-parse (validate_webhook may have consumed the body)
        event = await adapter.parse_inbound_event(request)
    except ProviderError as exc:
        log.error("Failed to parse webhook event", error=str(exc))
        # Return 200 to prevent provider retries for malformed events
        return {"status": "error", "message": "Could not parse event — logged for investigation."}
    except Exception as exc:
        log.error("Unexpected parse error", error=str(exc), exc_info=True)
        return {"status": "error", "message": "Parse error."}

    log.info(
        "Webhook received",
        call_id=event.provider_call_id,
        event_type=event.event_type,
        caller=event.caller_number,
    )

    # ── 5. Idempotency check ──────────────────────────────────────────────────
    # Use call_id + event_type as the unique event identifier
    event_key = f"{event.provider_call_id}:{event.event_type}"
    is_duplicate, existing_voicemail_id = await record_telephony_event(
        db=db,
        provider=provider_enum,
        provider_event_id=event_key,
        event_type=event.event_type,
        payload_hash=payload_hash,
    )

    if is_duplicate:
        log.info("Duplicate webhook — returning 200 without reprocessing")
        return {"status": "ok", "message": "Duplicate event acknowledged."}

    # ── 6. Find the user who owns this ExoPhone ───────────────────────────────
    # In production, look up by called_number → user mapping.
    # For MVP: use the first active user (single-tenant assumption).
    # TODO: Multi-tenant — map called_number to user_id.
    from app.models.user import User
    user_result = await db.execute(
        select(User).where(
            User.deleted_at.is_(None),
            User.is_active == True,  # noqa: E712
        ).limit(1)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        log.error("No active user found to assign voicemail to")
        await db.commit()
        return {"status": "error", "message": "No user configured."}

    # ── 7. Create or update voicemail record ──────────────────────────────────
    voicemail, created = await get_or_create_voicemail(
        db=db,
        user_id=user.id,
        provider=provider_enum,
        event=event,
    )
    await link_event_to_voicemail(db, provider_enum, event_key, voicemail.id)

    # Check if recording URL is already in the webhook payload
    recording_url = event.raw_payload.get("RecordingUrl", "")
    if recording_url:
        from app.telephony.provider_base import RecordingInfo
        recording_info = RecordingInfo(
            provider_recording_id=f"{event.provider_call_id}-rec",
            provider_recording_url=recording_url,
            duration_seconds=_parse_duration(event.raw_payload.get("Duration")),
            mime_type="audio/mpeg",
            raw_payload=event.raw_payload,
        )
        await mark_voicemail_recording(db, voicemail, recording_info)
    else:
        # Recording not in webhook — will be fetched asynchronously
        await mark_voicemail_recording(db, voicemail, None)

    await db.commit()

    log.info(
        "Voicemail record ready",
        voicemail_id=str(voicemail.id),
        created=created,
        has_recording_url=bool(recording_url),
    )

    # ── 8. Schedule background processing ────────────────────────────────────
    background_tasks.add_task(process_voicemail_recording, voicemail.id)

    return {"status": "ok", "voicemail_id": str(voicemail.id)}


def _parse_duration(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


# ── Configuration endpoint ───────────────────────────────────────────────────

@router.get("/configuration", summary="Get telephony configuration status")
async def get_configuration(
    current_user=Depends(get_current_user),
):
    """
    Return the current telephony configuration status.
    Used by the setup screen to show connection health.
    """
    from app.core.config import settings

    provider_name = settings.telephony_provider
    adapter = get_provider()

    try:
        health = await adapter.get_provider_health()
    except Exception as exc:
        health = None
        health_error = str(exc)
    else:
        health_error = None

    is_live = provider_name.lower() != "mock"

    return {
        "provider": provider_name,
        "is_live_provider": is_live,
        "is_configured": settings.exotel_configured if is_live else False,
        "health": {
            "is_healthy": health.is_healthy if health else False,
            "provider_name": health.provider_name if health else provider_name,
            "account_id_masked": health.account_id if health else None,
            "phone_numbers": health.phone_numbers if health else [],
            "error": health.error if health else health_error,
        },
        "webhook_url": f"{settings.backend_url}/api/v1/telephony/webhooks/{provider_name.lower()}",
        "forwarding_instructions": _forwarding_instructions(provider_name),
        "dev_note": (
            "Using mock provider for local development. "
            "Set TELEPHONY_PROVIDER=exotel and configure EXOTEL_* variables "
            "in .env to enable real missed-call voicemail."
        ) if not is_live else None,
    }


def _forwarding_instructions(provider: str) -> dict:
    """Return carrier forwarding setup instructions."""
    return {
        "overview": (
            "Configure conditional call forwarding on your existing mobile number "
            "so that missed calls are forwarded to SASAA's telephony number. "
            "This does NOT affect normal calls when you answer."
        ),
        "conditions": [
            {
                "condition": "When Busy",
                "description": "Your phone is on another call",
                "note": "Callers get your SASAA voicemail instead of a busy tone",
            },
            {
                "condition": "When Unanswered",
                "description": "You don't pick up within the ring time",
                "note": "Default ring time is usually 15–30 seconds",
            },
            {
                "condition": "When Unreachable",
                "description": "Your phone is switched off or outside network coverage",
                "note": "Works even when your phone is completely offline",
            },
        ],
        "carrier_instructions": {
            "jio": (
                "Contact Jio care (199) to configure conditional forwarding to your ExoPhone number. "
                "USSD activation codes may not work on all Jio plans."
            ),
            "airtel": (
                "Go to My Airtel app → Services → Call Settings → Call Forwarding, "
                "or call 121. Set conditional forwarding to your ExoPhone number."
            ),
            "vi_vodafone_idea": (
                "Call 198 or use the Vi app to configure call forwarding. "
                "Set busy, no-answer, and unreachable conditions."
            ),
            "bsnl": (
                "Dial *67*<ExoPhone>*11# for busy forwarding and "
                "*61*<ExoPhone>*11*30# for no-answer forwarding. "
                "Verify USSD support with your local BSNL office."
            ),
            "general": (
                "Contact your mobile carrier's customer care and request "
                "'conditional call forwarding' to the number: "
                f"{provider.upper()} ExoPhone (configured in your telephony settings). "
                "Do not enable unconditional forwarding."
            ),
        },
        "important_notes": [
            "Do NOT enable unconditional (always-on) forwarding — this would forward ALL calls.",
            "Test by calling your number from another phone while it is busy or unanswered.",
            "Forwarding charges may apply depending on your mobile plan.",
            "The forwarded number comes from the telephony provider's ExoPhone, not your number.",
        ],
    }


# ── Test endpoint ─────────────────────────────────────────────────────────────

@router.post("/test", summary="Simulate an inbound missed call for testing")
async def trigger_test_call(
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Simulate a complete missed-call voicemail flow for testing.
    Uses the mock adapter regardless of TELEPHONY_PROVIDER setting.
    Creates a real voicemail record and processes it through the full pipeline.
    """
    from app.telephony.mock_adapter import MockTelephonyAdapter
    from app.telephony.provider_base import InboundCallEvent
    from app.models.voicemail import TelephonyProvider as TP

    test_id = uuid.uuid4().hex[:8]
    _test_jobs[test_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    mock = MockTelephonyAdapter()
    call_id = f"test-call-{test_id}"
    event = InboundCallEvent(
        provider_call_id=call_id,
        caller_number="+919876543210",
        called_number="+911234567890",
        event_type="no-answer",
        forward_reason="no_answer",
        raw_payload={"CallSid": call_id, "From": "+919876543210", "To": "+911234567890"},
    )

    # Check idempotency
    event_key = f"{call_id}:no-answer"
    is_duplicate, _ = await record_telephony_event(
        db, TP.MOCK, event_key, "no-answer", payload_hash=test_id,
    )

    if is_duplicate:
        return {"test_id": test_id, "status": "duplicate_ignored", "message": "Test call already exists."}

    voicemail, _ = await get_or_create_voicemail(
        db=db, user_id=current_user.id, provider=TP.MOCK, event=event,
    )
    await link_event_to_voicemail(db, TP.MOCK, event_key, voicemail.id)

    # Inject a mock recording so the pipeline can proceed
    sample_dir = Path(__file__).parent.parent.parent.parent / "sample"
    sample_files = list(sample_dir.glob("*.mp3")) + list(sample_dir.glob("*.ogg"))
    if sample_files:
        from app.telephony.provider_base import RecordingInfo
        rec_info = RecordingInfo(
            provider_recording_id=f"test-rec-{call_id}",
            provider_recording_url=f"file://{sample_files[0]}",
            duration_seconds=5.0,
            mime_type="audio/mpeg",
            raw_payload={"mock": True},
        )
        await mark_voicemail_recording(db, voicemail, rec_info)

    await db.commit()

    _test_jobs[test_id]["voicemail_id"] = str(voicemail.id)

    async def _run_test():
        try:
            await process_voicemail_recording(voicemail.id)
            _test_jobs[test_id]["status"] = "completed"
        except Exception as exc:
            _test_jobs[test_id]["status"] = "failed"
            _test_jobs[test_id]["error"] = str(exc)

    background_tasks.add_task(_run_test)

    return {
        "test_id": test_id,
        "voicemail_id": str(voicemail.id),
        "status": "started",
        "message": (
            "Test voicemail created and processing started. "
            f"Poll GET /api/v1/telephony/test/{test_id} for status."
        ),
    }


@router.get("/test/{test_id}", summary="Get status of a test call")
async def get_test_status(
    test_id: str,
    current_user=Depends(get_current_user),
):
    """Return the status of a simulated test call."""
    job = _test_jobs.get(test_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Test job '{test_id}' not found.")
    return {"test_id": test_id, **job}
