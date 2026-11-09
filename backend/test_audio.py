"""
SASAA – Audio Endpoint Test Suite
===================================
Tests the audio upload and streaming endpoints:

  POST /messages/{id}/audio   – upload
  GET  /messages/{id}/audio   – stream/playback

Test cases:
  1. Successful upload
  2. Successful playback (verify content + MIME type)
  3. Missing audio (message exists, no audio uploaded)
  4. Nonexistent message
  5. Unauthorized access (no token)
  6. Duplicate upload (409)
  7. Unsupported format (415)
  8. Access another user's message (404, not 403 — no info leak)

Requirements:
  - Server running on the port specified below
  - Sample audio files in ../sample/ relative to backend/

Run from backend/ directory:
    python test_audio.py
"""

import sys
import os
import json
import uuid
import urllib.request
import urllib.error
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8001"
SAMPLE_DIR = Path(__file__).parent.parent / "sample"

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []
state: dict = {}

# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _json_req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    """JSON request via urllib (lightweight, no extra deps for JSON calls)."""
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


def check(name: str, passed: bool, detail: str = "") -> None:
    icon = PASS if passed else FAIL
    line = f"  {icon} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    results.append((name, passed, detail))


def find_sample_audio() -> Path | None:
    """Find a usable sample audio file for testing."""
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
print("  SASAA Audio Endpoint Test Suite")
print(f"  Server: {BASE_URL}")
print("=" * 58)

# ── T01: Server health ────────────────────────────────────────
print("\n[T01] Server Health")

status, body = get_json("/health")
check("GET /health returns 200", status == 200, f"status={status}")
check("DB connected", body.get("database", {}).get("status") == "connected")

if status != 200:
    print("\n  SERVER NOT RUNNING. Start it with:")
    print("  cd backend && python -m uvicorn app.main:app --port 8001 --no-access-log")
    sys.exit(1)


# ── T02: Register and login ───────────────────────────────────
print("\n[T02] Register Test User")

RUN_ID = uuid.uuid4().hex[:8]
TEST_EMAIL = f"audio_test_{RUN_ID}@example.com"
TEST_PASSWORD = "TestPass123!"
TEST_NAME = "Audio Test User"

status, body = post_json("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "full_name": TEST_NAME,
})
check("Registration returns 201", status == 201, f"got {status}")

if status != 201:
    print("\n  Cannot proceed without registration. Aborting.")
    sys.exit(1)

state["access_token"] = body["access_token"]
state["refresh_token"] = body["refresh_token"]
check("Access token stored", bool(state.get("access_token")))

# Also register a second user for cross-user testing
status2, body2 = post_json("/api/v1/auth/register", {
    "email": f"audio_test2_{RUN_ID}@example.com",
    "password": "TestPass456!",
    "full_name": "Second User",
})
if status2 == 201:
    state["other_token"] = body2["access_token"]
    state["other_registered"] = True
else:
    state["other_registered"] = False


# ── T03: Create a message ─────────────────────────────────────
print("\n[T03] Create Message")

status, body = post_json("/api/v1/messages", {
    "caller_name": "Test Caller",
    "caller_phone": "+919876543210",
}, token=state["access_token"])
check("POST /messages returns 201", status == 201, f"got {status}")
check("Message has UUID id", bool(body.get("id")))
state["message_id"] = body.get("id")
print(f"  [INFO] Message ID: {state['message_id']}")

# Create a second message for "no audio" test
status, body = post_json("/api/v1/messages", {
    "caller_name": "No Audio Caller",
}, token=state["access_token"])
if status == 201:
    state["message_no_audio_id"] = body.get("id")


# ── T04: Upload audio ─────────────────────────────────────────
print("\n[T04] Upload Audio")

sample_file = find_sample_audio()
if sample_file is None:
    check("Sample audio file found", False, "No sample files in ../sample/")
    print("\n  Cannot test upload without a sample file. Aborting.")
    sys.exit(1)

check(f"Sample file found: {sample_file.name}", True, f"{sample_file.stat().st_size} bytes")

# Upload using httpx (handles multipart natively)
with httpx.Client(timeout=30.0) as client:
    with open(sample_file, "rb") as f:
        resp = client.post(
            f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
            headers={"Authorization": f"Bearer {state['access_token']}"},
            files={"audio_file": (sample_file.name, f, "audio/mpeg")},
        )

check("POST /audio returns 200", resp.status_code == 200, f"got {resp.status_code}")
if resp.status_code == 200:
    body = resp.json()
    check("Success response", body.get("success") is True, str(body))
    check("Message mentions upload", "upload" in body.get("message", "").lower(), body.get("message", ""))
else:
    print(f"  [INFO] Response body: {resp.text[:200]}")


# ── T05: Get audio (successful playback) ─────────────────────
print("\n[T05] GET Audio — Successful Playback")

with httpx.Client(timeout=30.0) as client:
    resp = client.get(
        f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
        headers={"Authorization": f"Bearer {state['access_token']}"},
    )

check("GET /audio returns 200", resp.status_code == 200, f"got {resp.status_code}")

if resp.status_code == 200:
    check("Content-Type is audio/*", resp.headers.get("content-type", "").startswith("audio/"),
          resp.headers.get("content-type", ""))
    check("Response body is non-empty", len(resp.content) > 0, f"{len(resp.content)} bytes")
    check("Content-Disposition is inline", "inline" in resp.headers.get("content-disposition", ""),
          resp.headers.get("content-disposition", "")[:80])
    # Verify the returned bytes match the original file
    original_bytes = sample_file.read_bytes()
    check("Returned audio matches original file", resp.content == original_bytes,
          f"original={len(original_bytes)} vs response={len(resp.content)}")


# ── T06: Missing audio (message exists, no audio uploaded) ──
print("\n[T06] GET Audio — No Audio Attached")

if "message_no_audio_id" not in state:
    check("No-audio message test", False, "Skipped — message creation failed")
else:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{BASE_URL}/api/v1/messages/{state['message_no_audio_id']}/audio",
            headers={"Authorization": f"Bearer {state['access_token']}"},
        )
    check("GET /audio without upload -> 404", resp.status_code == 404, f"got {resp.status_code}")
    check("Error message mentions audio", "audio" in resp.json().get("detail", "").lower(),
          resp.json().get("detail", ""))


# ── T07: Nonexistent message ─────────────────────────────────
print("\n[T07] GET Audio — Nonexistent Message")

fake_id = str(uuid.uuid4())
with httpx.Client(timeout=10.0) as client:
    resp = client.get(
        f"{BASE_URL}/api/v1/messages/{fake_id}/audio",
        headers={"Authorization": f"Bearer {state['access_token']}"},
    )
check("GET /audio with fake UUID -> 404", resp.status_code == 404, f"got {resp.status_code}")


# ── T08: Unauthorized access (no token) ──────────────────────
print("\n[T08] GET Audio — No Token")

with httpx.Client(timeout=10.0) as client:
    resp = client.get(
        f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
    )
check("GET /audio without token -> 403", resp.status_code in {401, 403}, f"got {resp.status_code}")


# ── T09: Cross-user access (another user's message) ──────────
print("\n[T09] GET Audio — Another User's Message")

if not state.get("other_registered"):
    check("Cross-user test", False, "Skipped — second user not registered")
else:
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
            headers={"Authorization": f"Bearer {state['other_token']}"},
        )
    check("Other user GET -> 404 (not 403)", resp.status_code == 404, f"got {resp.status_code}")
    check("No audio data leaked", len(resp.content) == 0 or resp.headers.get("content-type", "").startswith("application/json"),
          f"content-type={resp.headers.get('content-type', '?')}")


# ── T10: Duplicate upload (409) ───────────────────────────────
print("\n[T10] Duplicate Upload")

with httpx.Client(timeout=30.0) as client:
    with open(sample_file, "rb") as f:
        resp = client.post(
            f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
            headers={"Authorization": f"Bearer {state['access_token']}"},
            files={"audio_file": (sample_file.name, f, "audio/mpeg")},
        )
check("Duplicate upload -> 409", resp.status_code == 409, f"got {resp.status_code}")
if resp.status_code == 409:
    check("Error mentions already uploaded", "already" in resp.json().get("detail", "").lower(),
          resp.json().get("detail", ""))


# ── T11: Unsupported format (415) ──────────────────────────────
print("\n[T11] Unsupported Format")

# Create a new message for this test
status, body = post_json("/api/v1/messages", {}, token=state["access_token"])
if status == 201:
    bad_msg_id = body["id"]
    # Upload a non-audio file (a .txt file)
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{BASE_URL}/api/v1/messages/{bad_msg_id}/audio",
            headers={"Authorization": f"Bearer {state['access_token']}"},
            files={"audio_file": ("test.txt", b"this is not audio", "text/plain")},
        )
    check("Text file upload -> 415", resp.status_code == 415, f"got {resp.status_code}")
    if resp.status_code == 415:
        check("Error mentions format", "format" in resp.json().get("detail", "").lower() or "supported" in resp.json().get("detail", "").lower(),
              resp.json().get("detail", ""))
else:
    check("Unsupported format test", False, "Message creation failed")


# ── T12: Upload without token ──────────────────────────────────
print("\n[T12] POST Audio — No Token")

with httpx.Client(timeout=10.0) as client:
    with open(sample_file, "rb") as f:
        resp = client.post(
            f"{BASE_URL}/api/v1/messages/{state['message_id']}/audio",
            files={"audio_file": (sample_file.name, f, "audio/mpeg")},
        )
check("POST /audio without token -> 403", resp.status_code in {401, 403}, f"got {resp.status_code}")


# ── T13: Verify message status updated after upload ──────────
print("\n[T13] Message Status After Upload")

status, body = get_json(f"/api/v1/messages/{state['message_id']}", token=state["access_token"])
check("GET /messages/{id} returns 200", status == 200, f"got {status}")
if status == 200:
    check("Status is VALIDATING", body.get("status") == "VALIDATING", body.get("status"))
    check("MIME type stored", bool(body.get("mime_type")), body.get("mime_type"))
    check("File size stored", isinstance(body.get("file_size_bytes"), int), str(body.get("file_size_bytes")))
    check("Original filename stored", bool(body.get("original_filename")), body.get("original_filename"))


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
print("=" * 58)
print()

sys.exit(0 if failed == 0 else 1)
