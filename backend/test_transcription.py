"""
SASAA – Transcription Endpoint Test Suite
===========================================
Tests POST /messages/{id}/transcribe and GET /messages/{id}/transcription.

The POST endpoint triggers the real Gnani STT API. The test polls
GET /transcription until the status is COMPLETED or FAILED, with a
120-second timeout.

Test cases:
  T01  Server health
  T02  Register + login
  T03  Create message
  T04  Upload audio
  T05  Trigger transcription (POST)
  T06  Poll for completion (GET) — verifies real Gnani transcript
  T07  Verify transcript content (text, language, timestamps)
  T08  Duplicate transcription (409)
  T09  Transcribe without audio (404)
  T10  Nonexistent message (404)
  T11  Unauthorized (403)
  T12  GET transcription for message without audio
  T13  GET transcription for nonexistent message
  T14  GET transcription unauthorized

Run from backend/ directory:
    python test_transcription.py
"""

import json
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8001"
SAMPLE_DIR = Path(__file__).parent.parent / "sample"
POLL_INTERVAL = 3        # seconds between GET polls
POLL_TIMEOUT = 150       # max seconds to wait for transcription

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []
state: dict = {}


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _json_req(method, path, body=None, token=None):
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def post_json(path, body=None, token=None):
    return _json_req("POST", path, body, token)

def get_json(path, token=None):
    return _json_req("GET", path, token=token)

def check(name, passed, detail=""):
    icon = PASS if passed else FAIL
    line = f"  {icon} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    results.append((name, passed, detail))


def find_sample_audio():
    candidates = [
        SAMPLE_DIR / "test.wav.mp3",
        SAMPLE_DIR / "number_test.wav.ogg",
        SAMPLE_DIR / "time_test.wav.ogg",
    ]
    for f in candidates:
        if f.exists() and f.stat().st_size > 0:
            return f
    return None


# ═════════════════════════════════════════════════════════════
print()
print("=" * 58)
print("  SASAA Transcription Test Suite")
print(f"  Server: {BASE_URL}")
print("=" * 58)

# ── T01: Server health ────────────────────────────────────────
print("\n[T01] Server Health")
status, body = get_json("/health")
check("GET /health returns 200", status == 200, f"status={status}")
check("DB connected", body.get("database", {}).get("status") == "connected")
check("Gnani configured", body.get("gnani_configured") is True)
if status != 200:
    print("\n  SERVER NOT RUNNING. Start with:")
    print("  cd backend && python -m uvicorn app.main:app --port 8001 --no-access-log")
    sys.exit(1)

# ── T02: Register + login ─────────────────────────────────────
print("\n[T02] Register Test User")
RUN_ID = uuid.uuid4().hex[:8]
TEST_EMAIL = f"trans_test_{RUN_ID}@example.com"
status, body = post_json("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": "TestPass123!",
    "full_name": "Transcription Tester",
})
check("Registration returns 201", status == 201, f"got {status}")
if status != 201:
    print("\n  Cannot proceed. Aborting.")
    sys.exit(1)
state["access_token"] = body["access_token"]
check("Access token stored", bool(state["access_token"]))

# ── T03: Create message ───────────────────────────────────────
print("\n[T03] Create Message")
status, body = post_json("/api/v1/messages", {
    "caller_name": "Test Caller",
    "caller_phone": "+919876543210",
}, token=state["access_token"])
check("POST /messages returns 201", status == 201, f"got {status}")
state["message_id"] = body.get("id")
check("Message ID present", bool(state["message_id"]))

# Create a second message (no audio) for later tests
status2, body2 = post_json("/api/v1/messages", {}, token=state["access_token"])
if status2 == 201:
    state["message_no_audio_id"] = body2.get("id")

# ── T04: Upload audio ────────────────────────────────────────
print("\n[T04] Upload Audio")
sample_file = find_sample_audio()
if sample_file is None:
    check("Sample audio found", False, "No sample files in ../sample/")
    sys.exit(1)
check(f"Sample file: {sample_file.name}", True, f"{sample_file.stat().st_size} bytes")

with httpx.Client(timeout=30.0) as client:
    with open(sample_file, "rb") as f:
        resp = client.post(
            f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
            headers={"Authorization": f"Bearer {state['access_token']}"},
            files={"audio_file": (sample_file.name, f, "audio/mpeg")},
        )
check("Upload returns 200", resp.status_code == 200, f"got {resp.status_code}")

# ── T05: Trigger transcription ───────────────────────────────
print("\n[T05] POST /transcribe — Trigger")
status, body = post_json(
    f"/api/v1/messages/{state['message_id']}/transcribe",
    body={"language_code": "ta-IN"},
    token=state["access_token"],
)
check("POST /transcribe returns 202", status == 202, f"got {status}")
if status == 202:
    check("Success message", body.get("success") is True, str(body.get("message", ""))[:80])
else:
    print(f"  [INFO] Response: {body}")
    print("  Transcription may not be possible if Gnani API is unreachable.")

# ── T06: Poll for completion ─────────────────────────────────
print("\n[T06] Poll GET /transcription — Wait for Gnani")

poll_start = time.time()
transcript_data = None
final_status = None

while time.time() - poll_start < POLL_TIMEOUT:
    status, body = get_json(
        f"/api/v1/messages/{state['message_id']}/transcription",
        token=state["access_token"],
    )
    if status != 200:
        print(f"  [WARN] GET returned {status}")
        time.sleep(POLL_INTERVAL)
        continue

    current_status = body.get("status", "")
    has_transcript = body.get("has_transcript", False)
    elapsed = int(time.time() - poll_start)

    if has_transcript and body.get("transcript"):
        transcript_data = body.get("transcript")
        final_status = current_status
        check(f"Transcription completed in {elapsed}s", True, f"status={current_status}")
        break

    if current_status == "FAILED":
        final_status = current_status
        error_msg = body.get("error_message", "Unknown error")
        check(f"Transcription failed after {elapsed}s", False,
              f"status=FAILED, error={error_msg[:80]}")
        print(f"  [INFO] Error: {error_msg}")
        break

    # Still in progress
    print(f"  ...waiting ({elapsed}s elapsed, status={current_status})")
    time.sleep(POLL_INTERVAL)
else:
    check("Transcription completed within timeout", False,
          f"Timed out after {POLL_TIMEOUT}s, last status={current_status}")

# ── T07: Verify transcript content ────────────────────────────
print("\n[T07] Verify Transcript Content")

if transcript_data is None:
    check("Transcript data available", False, "No transcript — Gnani may be unavailable")
    check("raw_text present", False, "Skipped")
    check("detected_language present", False, "Skipped")
    check("created_at present", False, "Skipped")
    check("processing_latency_ms present", False, "Skipped")
    # Continue with error-case tests even if Gnani failed
else:
    check("Transcript data available", True)
    check("raw_text is non-empty string",
          isinstance(transcript_data.get("raw_text"), str) and len(transcript_data["raw_text"]) > 0,
          f"len={len(transcript_data.get('raw_text', ''))}")
    check("message_id matches",
          transcript_data.get("message_id") == state["message_id"])
    check("detected_language present",
          transcript_data.get("detected_language") is not None,
          str(transcript_data.get("detected_language")))
    check("created_at present",
          transcript_data.get("created_at") is not None)
    check("updated_at present",
          transcript_data.get("updated_at") is not None)
    check("processing_latency_ms present",
          transcript_data.get("processing_latency_ms") is not None,
          str(transcript_data.get("processing_latency_ms")))
    check("id is a UUID string",
          bool(transcript_data.get("id")))
    # Show a preview of the transcript
    preview = transcript_data.get("raw_text", "")[:100]
    print(f"  [INFO] Transcript preview: {preview}")

    # Verify the message status is COMPLETED
    check("Message status is COMPLETED", final_status == "COMPLETED",
          f"got {final_status}")

# ── T08: Duplicate transcription (409) ────────────────────────
print("\n[T08] Duplicate Transcription — 409")

# If transcription succeeded, trying again should return 409
# If it failed, retrying might be allowed — test both paths
if final_status == "COMPLETED":
    status, body = post_json(
        f"/api/v1/messages/{state['message_id']}/transcribe",
        body={"language_code": "ta-IN"},
        token=state["access_token"],
    )
    check("Duplicate transcription -> 409", status == 409, f"got {status}")
else:
    # If transcription failed, we can retry. But if it's still in progress, 409.
    status, body = post_json(
        f"/api/v1/messages/{state['message_id']}/transcribe",
        body={"language_code": "ta-IN"},
        token=state["access_token"],
    )
    check(f"Retry returns {status} (expected 202 for retry or 409 if in progress)",
          status in {202, 409}, f"got {status}")

# ── T09: Transcribe without audio (404) ──────────────────────
print("\n[T09] Transcribe Without Audio — 404")

if "message_no_audio_id" not in state:
    check("No-audio transcribe test", False, "Skipped — message creation failed")
else:
    status, body = post_json(
        f"/api/v1/messages/{state['message_no_audio_id']}/transcribe",
        body={"language_code": "ta-IN"},
        token=state["access_token"],
    )
    check("Transcribe without audio -> 404", status == 404, f"got {status}")
    check("Error mentions audio", "audio" in str(body).lower(), str(body.get("detail", ""))[:80])

# ── T10: Nonexistent message (404) ────────────────────────────
print("\n[T10] Nonexistent Message — 404")

fake_id = str(uuid.uuid4())
status, body = post_json(
    f"/api/v1/messages/{fake_id}/transcribe",
    body={"language_code": "ta-IN"},
    token=state["access_token"],
)
check("POST /transcribe fake UUID -> 404", status == 404, f"got {status}")

# ── T11: Unauthorized POST (403) ──────────────────────────────
print("\n[T11] Unauthorized POST — 403")

status, body = post_json(
    f"/api/v1/messages/{state['message_id']}/transcribe",
    body={"language_code": "ta-IN"},
)
check("POST /transcribe without token -> 403", status in {401, 403}, f"got {status}")

# ── T12: GET transcription for message without audio ──────────
print("\n[T12] GET Transcription — No Audio")

if "message_no_audio_id" not in state:
    check("GET no-audio transcription", False, "Skipped")
else:
    status, body = get_json(
        f"/api/v1/messages/{state['message_no_audio_id']}/transcription",
        token=state["access_token"],
    )
    check("GET returns 200", status == 200, f"got {status}")
    if status == 200:
        check("has_transcript is False", body.get("has_transcript") is False)
        check("status is UPLOADED", body.get("status") == "UPLOADED", body.get("status"))

# ── T13: GET transcription for nonexistent message ────────────
print("\n[T13] GET Transcription — Nonexistent Message")

status, body = get_json(
    f"/api/v1/messages/{fake_id}/transcription",
    token=state["access_token"],
)
check("GET /transcription fake UUID -> 404", status == 404, f"got {status}")

# ── T14: GET transcription unauthorized ───────────────────────
print("\n[T14] GET Transcription — No Token")

status, body = get_json(
    f"/api/v1/messages/{state['message_id']}/transcription",
)
check("GET /transcription without token -> 403", status in {401, 403}, f"got {status}")

# ── Summary ───────────────────────────────────────────────────
print()
print("=" * 58)
passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
total = len(results)
pct = int(passed / total * 100) if total else 0

print(f"  Results: {passed}/{total} passed ({pct}%)  |  {failed} failed")

if failed > 0:
    print()
    print("  FAILED TESTS:")
    for name, ok, detail in results:
        if not ok:
            print(f"    x {name}  [{detail}]")

print()
print(f"  Test user: {TEST_EMAIL}")
print(f"  Message ID: {state.get('message_id')}")
if transcript_data:
    print(f"  Transcript language: {transcript_data.get('detected_language')}")
    print(f"  Transcript length: {len(transcript_data.get('raw_text', ''))} chars")
print("=" * 58)
print()

sys.exit(0 if failed == 0 else 1)
