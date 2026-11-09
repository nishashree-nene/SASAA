"""
SASAA – Phase 2 Complete Test Suite
=====================================
Run from the backend/ directory:
    python test_phase2.py

Tests every module built in Phase 2.
Works WITHOUT a real database connection or real PostgreSQL password.
"""

import asyncio
import os
import sys
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# ── Inject test environment variables BEFORE importing any app module ────────
# This bypasses pydantic-settings reading from .env so the test runs
# without needing YOUR_PASSWORD replaced yet.
os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:testpass@localhost:5432/sasaa_db"
os.environ["ASYNC_DATABASE_URL"] = "postgresql+asyncpg://postgres:testpass@localhost:5432/sasaa_db"
os.environ["SECRET_KEY"] = "test-secret-key-abcdef1234567890abcdef1234567890abcdef12"
os.environ["GNANI_API_KEY"] = "test-gnani-key-for-unit-tests-only"
os.environ["GNANI_STT_URL"] = "https://api.vachana.ai/stt/v3"
os.environ["ENVIRONMENT"] = "development"

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool]] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    suffix = f" – {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    results.append((label, passed))


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
print("  SASAA Phase 2 – Complete Test Suite")
print("=" * 62)


# ── 1. Core Modules ──────────────────────────────────────────────────────────
print("\n[1] Core Modules")

try:
    from app.core.config import get_settings
    get_settings.cache_clear()   # Ensure test env vars are used
    s = get_settings()
    check("config.py loads",          True,           f"app={s.app_name} env={s.environment}")
    check("Gnani URL set",            bool(s.gnani_stt_url), s.gnani_stt_url)
    check("Gnani API key set",        bool(s.gnani_api_key), "key present")
    check("SECRET_KEY accepted",      len(s.secret_key) >= 32)
    check("max_audio_size_bytes",     s.max_audio_size_bytes == 50 * 1024 * 1024,
          f"{s.max_audio_size_mb} MB = {s.max_audio_size_bytes} bytes")
    check("is_development flag",      s.is_development)
    check("email_enabled defaults False", not s.email_enabled)
except Exception as e:
    check("config.py", False, str(e))


try:
    from app.core.security import (
        hash_password, verify_password,
        create_access_token, decode_access_token,
        create_refresh_token, decode_refresh_token,
    )
    hashed = hash_password("SecurePass123!")
    check("hash_password bcrypt prefix",        hashed.startswith("$2b$"))
    check("verify_password correct password",   verify_password("SecurePass123!", hashed))
    check("verify_password wrong password",     not verify_password("wrongpass", hashed))

    access = create_access_token("user-test-uuid")
    check("access token decodes correctly",     decode_access_token(access) == "user-test-uuid")
    refresh = create_refresh_token("user-test-uuid")
    check("refresh rejected as access token",   decode_access_token(refresh) is None)
    check("access rejected as refresh token",   decode_refresh_token(access) is None)
    check("refresh token decodes correctly",    decode_refresh_token(refresh) == "user-test-uuid")
except Exception as e:
    check("security.py", False, str(e))


try:
    from app.core.database import get_async_db, check_database_connection, sync_engine, async_engine
    check("database.py imports OK", True, "engines created (not yet connected)")
except Exception as e:
    check("database.py", False, str(e))


try:
    from app.core.dependencies import get_current_user_id, get_current_user, get_optional_user
    check("dependencies.py imports OK", True)
except Exception as e:
    check("dependencies.py", False, str(e))


# ── 2. ORM Models ────────────────────────────────────────────────────────────
print("\n[2] SQLAlchemy ORM Models")

try:
    from app.models import (
        Base, User, UserProfile, UserPreferences, UserSession,
        Message, MessageAudio, MessageStatus, MessagePriority,
        Transcript, TranscriptVersion, ExtractedEntity, VerificationResult,
        VerificationStatus, EntityType, RiskLevel,
        PriorityAlert, AlertType, AlertSeverity,
        Notification, NotificationPreferences,
        DeviceToken, WebPushSubscription, AuditLog,
    )
    tables = sorted(Base.metadata.tables.keys())
    check(f"{len(tables)} tables registered",       len(tables) == 16, ", ".join(tables))
    check("MessageStatus: 8 states",                len(list(MessageStatus)) == 8)
    check("MessageStatus: NEEDS_VERIFICATION",      MessageStatus.NEEDS_VERIFICATION.value == "NEEDS_VERIFICATION")
    check("MessagePriority: EMERGENCY level",       MessagePriority.EMERGENCY.value == "EMERGENCY")
    check("EntityType: TIME exists",                EntityType.TIME.value == "TIME")
    check("EntityType: PHONE_NUMBER exists",        EntityType.PHONE_NUMBER.value == "PHONE_NUMBER")
    check("EntityType: NEGATION exists",            EntityType.NEGATION.value == "NEGATION")
    check("VerificationStatus: 7 states",           len(list(VerificationStatus)) == 7)
    check("AlertType: FINANCIAL exists",            AlertType.FINANCIAL.value == "FINANCIAL")
    check("RiskLevel: CRITICAL exists",             RiskLevel.CRITICAL.value == "CRITICAL")
    check("Transcript has raw_text column",         hasattr(Transcript, "raw_text"))
    check("User has password_hash column",          hasattr(User, "password_hash"))
    check("Message has status column",              hasattr(Message, "status"))
except Exception as e:
    check("ORM models", False, str(e))


# ── 3. Pydantic Schemas ──────────────────────────────────────────────────────
print("\n[3] Pydantic Schemas")

try:
    from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
    from app.schemas.user import UserProfileResponse, UpdateProfileRequest, UserPreferencesResponse
    from app.schemas.message import (
        MessageSummaryResponse, DashboardStats, CreateMessageRequest, UpdateMessageRequest
    )
    from app.schemas.common import PaginatedResponse, ErrorResponse, SuccessResponse, HealthStatus

    # Validation: bad email
    try:
        RegisterRequest(email="not-an-email", password="GoodPass123", full_name="Test")
        check("RegisterRequest rejects bad email", False, "should have raised ValidationError")
    except Exception:
        check("RegisterRequest rejects bad email", True)

    # Validation: password without digit
    try:
        RegisterRequest(email="test@test.com", password="NoDigitHere!", full_name="Test")
        check("RegisterRequest rejects no-digit password", False, "should have raised")
    except Exception:
        check("RegisterRequest rejects no-digit password", True)

    # Validation: valid input
    good = RegisterRequest(email="user@sasaa.app", password="GoodPass123", full_name="Nisha")
    check("RegisterRequest accepts valid data",    good.email == "user@sasaa.app")

    # DashboardStats empty state (new user)
    stats = DashboardStats(
        total_messages=0, unread_messages=0, messages_needing_verification=0,
        high_priority_messages=0, emergency_messages=0, messages_today=0,
        messages_this_week=0, guardian_active=True,
    )
    check("DashboardStats: empty state works",    stats.total_messages == 0 and stats.guardian_active)

    # ErrorResponse shape
    err = ErrorResponse(error="UNAUTHORIZED", message="Token expired.")
    check("ErrorResponse shape",                   err.error == "UNAUTHORIZED" and err.detail is None)

except Exception as e:
    check("Schemas", False, str(e))


# ── 4. AI Modules ────────────────────────────────────────────────────────────
print("\n[4] AI Modules")

try:
    from app.ai.audio_service import (
        ACCEPTED_MIME_TYPES, ACCEPTED_EXTENSIONS, AudioValidationError,
        _safe_filename, _detect_mime_from_extension,
    )
    check("audio_service: 12 MIME types",       len(ACCEPTED_MIME_TYPES) == 12, str(len(ACCEPTED_MIME_TYPES)))
    check("audio_service: .ogg accepted",       ".ogg" in ACCEPTED_EXTENSIONS)
    check("audio_service: .mp3 accepted",       ".mp3" in ACCEPTED_EXTENSIONS)
    check("audio_service: .webm accepted",      ".webm" in ACCEPTED_EXTENSIONS)
    check("audio_service: .ogg MIME detected",  _detect_mime_from_extension("test.ogg") == "audio/ogg")
    check("audio_service: .mp3 MIME detected",  _detect_mime_from_extension("test.mp3") == "audio/mpeg")
    safe = _safe_filename("../../etc/passwd.ogg", "msg-123")
    check("audio_service: path traversal blocked", ".." not in safe and "msg-123" in safe)
except Exception as e:
    check("audio_service.py", False, str(e))


try:
    from app.ai.gnani_client import (
        transcribe_audio, GnaniError, GnaniTranscriptResult, NON_RETRYABLE_STATUS_CODES
    )
    check("gnani_client: 401 non-retryable",    401 in NON_RETRYABLE_STATUS_CODES)
    check("gnani_client: 403 non-retryable",    403 in NON_RETRYABLE_STATUS_CODES)
    check("gnani_client: 400 non-retryable",    400 in NON_RETRYABLE_STATUS_CODES)
    check("gnani_client: 413 non-retryable",    413 in NON_RETRYABLE_STATUS_CODES)

    async def test_gnani_errors():
        # Missing file
        r1 = await transcribe_audio("/no/such/file.ogg", "ta-IN", "audio/ogg")
        assert isinstance(r1, GnaniError) and r1.error_type == "FILE_NOT_FOUND" and not r1.is_retryable
        check("gnani_client: FILE_NOT_FOUND not retryable", True)

        # Verify GnaniTranscriptResult dataclass
        r2 = GnaniTranscriptResult(
            transcript="ஐந்து மணிக்கு அழைக்கவும்",
            detected_language_code="ta-IN",
            end_to_end_latency=1250,
            our_latency_ms=1380,
            raw_response={"transcript": "test"},
        )
        assert r2.transcript and r2.detected_language_code == "ta-IN"
        check("GnaniTranscriptResult dataclass fields", True)

    asyncio.run(test_gnani_errors())
except Exception as e:
    check("gnani_client.py", False, str(e))


try:
    from app.ai.language_service import (
        LANGUAGE_REGISTRY, validate_language_code, is_stt_supported,
        detect_language_from_text, get_unsupported_language_message,
    )
    check("language_service: 11 languages",         len(LANGUAGE_REGISTRY) == 11)
    ok, _ = validate_language_code("ta-IN")
    check("language_service: ta-IN valid",           ok)
    ok, _ = validate_language_code("xx-XX")
    check("language_service: xx-XX invalid",         not ok)
    ok, _ = validate_language_code("")
    check("language_service: empty string invalid",  not ok)
    check("language_service: ta-IN STT supported",  is_stt_supported("ta-IN"))
    check("language_service: zz-ZZ not supported",  not is_stt_supported("zz-ZZ"))

    msg = get_unsupported_language_message("xx-XX")
    check("language_service: unknown lang message",  "not recognised" in msg or "not" in msg.lower())

    tamil = asyncio.run(detect_language_from_text("என்னுடைய தொலைபேசி எண்"))
    check("language_service: Tamil detects ta-IN",   tamil == "ta-IN", f"got={tamil}")
    english = asyncio.run(detect_language_from_text("Call me at five PM tomorrow morning"))
    check("language_service: English detects en-IN", english == "en-IN", f"got={english}")
except Exception as e:
    check("language_service.py", False, str(e))


try:
    from app.ai.transcription_service import run_transcription_pipeline, TranscriptionResult
    check("transcription_service imports OK", True)
    check("TranscriptionResult has success field", hasattr(TranscriptionResult, "__dataclass_fields__") and "success" in TranscriptionResult.__dataclass_fields__)
except Exception as e:
    check("transcription_service.py", False, str(e))


# ── 5. API Routes ────────────────────────────────────────────────────────────
print("\n[5] API Routes")

try:
    from app.main import app

    all_routes = [r for r in app.routes if hasattr(r, "methods")]
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    check(f"Total routes: {len(all_routes)}", len(all_routes) >= 35, f"{len(all_routes)} registered")

    must_exist = [
        ("/api/v1/auth/register",                   "POST  /auth/register"),
        ("/api/v1/auth/login",                       "POST  /auth/login"),
        ("/api/v1/auth/refresh",                     "POST  /auth/refresh"),
        ("/api/v1/users/me",                         "GET   /users/me"),
        ("/api/v1/users/preferences",                "GET   /users/preferences"),
        ("/api/v1/messages",                         "GET   /messages"),
        ("/api/v1/messages/{message_id}",            "GET   /messages/{id}"),
        ("/api/v1/messages/{message_id}/audio",      "POST  /messages/{id}/audio"),
        ("/api/v1/messages/{message_id}/transcribe", "POST  /messages/{id}/transcribe"),
        ("/api/v1/messages/{message_id}/verify",     "POST  /messages/{id}/verify"),
        ("/api/v1/messages/{message_id}/corrections","POST  /messages/{id}/corrections"),
        ("/api/v1/alerts",                           "GET   /alerts"),
        ("/api/v1/languages",                        "GET   /languages"),
        ("/api/v1/analytics/dashboard",              "GET   /analytics/dashboard"),
        ("/health",                                  "GET   /health"),
    ]
    for path, label in must_exist:
        check(f"Route: {label}", path in paths)

except Exception as e:
    check("API routes", False, str(e))


# ── 6. Functional Endpoint Tests (no DB) ────────────────────────────────────
print("\n[6] Functional Endpoints (no database needed)")

try:
    from app.api.v1.languages import list_languages

    langs = asyncio.run(list_languages())
    check(f"GET /languages: {len(langs)} languages", len(langs) == 11)

    codes = {l.code for l in langs}
    for code in ["ta-IN", "en-IN", "hi-IN", "te-IN", "ml-IN", "kn-IN", "bn-IN"]:
        check(f"  language {code} present", code in codes)

    tamil = next(l for l in langs if l.code == "ta-IN")
    check("ta-IN has Tanglish code-switching", bool(tamil.code_switching))
    check("ta-IN native name is Tamil script", "தமிழ்" in tamil.native_name)

    stt_supported = [l.code for l in langs if l.stt_supported]
    check(f"All 11 languages STT supported", len(stt_supported) == 11)

except Exception as e:
    check("Languages endpoint", False, str(e))


try:
    # Test error response serialisation
    from app.schemas.common import ErrorResponse
    err = ErrorResponse(error="TEST_ERROR", message="Something went wrong", detail="field: body.email")
    serialised = err.model_dump()
    check("ErrorResponse serialises correctly", serialised["error"] == "TEST_ERROR")
    check("ErrorResponse detail field present", serialised.get("detail") == "field: body.email")
except Exception as e:
    check("Error response serialisation", False, str(e))


# ── Final Summary ────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
passed_count = sum(1 for _, p in results if p)
failed_count = sum(1 for _, p in results if not p)
total_count  = len(results)

print(f"  Results: {passed_count}/{total_count} passed  |  {failed_count} failed")

if failed_count > 0:
    print("\n  Failed tests:")
    for label, p in results:
        if not p:
            print(f"    x {label}")
    print()
    print("  ACTION: Fix the failed tests before proceeding.")
else:
    print("  Status: ALL TESTS PASSED")
    print()
    print("  Phase 2 backend is ready. Next steps:")
    print()
    print("  1. Open .env and replace YOUR_PASSWORD with your PostgreSQL password")
    print("  2. In pgAdmin, create database: sasaa_db")
    print("  3. Run migrations:")
    print("       cd backend")
    print("       python run_migrations.py")
    print("  4. Start the server:")
    print("       python -m uvicorn app.main:app --reload --port 8000")
    print("  5. Open http://localhost:8000/health")
    print("  6. Open http://localhost:8000/docs")

print("=" * 62)

sys.exit(0 if failed_count == 0 else 1)
