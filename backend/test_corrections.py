"""
SASAA – Corrections Endpoint Test Suite
=========================================
Tests POST /messages/{id}/corrections

Run from backend/ directory:
    python test_corrections.py

Requires server running on port 8001.
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

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []
state: dict = {}


def _req(method, path, body=None, token=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def get(p, tok=None): return _req("GET", p, token=tok)
def post(p, b=None, tok=None): return _req("POST", p, b, tok)


def check(name, passed, detail=""):
    ok = bool(passed)
    print(f"  {PASS if ok else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, ok, detail))


# ── helpers ──────────────────────────────────────────────────────────────────

def find_audio():
    for f in [SAMPLE_DIR / "test.wav.mp3",
              SAMPLE_DIR / "number_test.wav.ogg",
              SAMPLE_DIR / "time_test.wav.ogg"]:
        if f.exists() and f.stat().st_size > 0:
            return f
    return None


# ═══════════════════════════════════════════════════════════
print()
print("=" * 58)
print("  SASAA Corrections Endpoint Test Suite")
print(f"  Server: {BASE_URL}")
print("=" * 58)


# ── T01: Server health ────────────────────────────────────────
print("\n[T01] Server Health")
s, b = get("/health")
check("Server is up", s == 200, f"status={s}")
check("DB connected", b.get("database", {}).get("status") == "connected")
if s != 200:
    print("  Server not running. Start with:")
    print("  cd backend && python -m uvicorn app.main:app --port 8001 --no-access-log")
    sys.exit(1)


# ── T02: Swagger exposes request body schema ──────────────────
print("\n[T02] Swagger / OpenAPI Schema")
s, schema = get("/openapi.json")
check("GET /openapi.json returns 200", s == 200)
path_key = "/api/v1/messages/{message_id}/corrections"
post_op = schema.get("paths", {}).get(path_key, {}).get("post", {})
request_body = post_op.get("requestBody")
check("requestBody present in schema", request_body is not None,
      "Missing = body param not declared with Body()")
if request_body:
    content = request_body.get("content", {})
    check("application/json content type", "application/json" in content)
    json_schema = content.get("application/json", {}).get("schema", {})
    ref = json_schema.get("$ref", "")
    check("Schema references CorrectionRequest", "CorrectionRequest" in ref, ref)
    check("requestBody is required", request_body.get("required") is True)

# Also check CorrectionRequest schema has corrected_text
cr_schema = schema.get("components", {}).get("schemas", {}).get("CorrectionRequest", {})
props = cr_schema.get("properties", {})
check("corrected_text property present", "corrected_text" in props)
check("change_summary property present", "change_summary" in props)
required_fields = cr_schema.get("required", [])
check("corrected_text is required field", "corrected_text" in required_fields)


# ── T03: Setup — register + message + audio + transcription ──
print("\n[T03] Setup")
RUN_ID = uuid.uuid4().hex[:8]
s, b = post("/api/v1/auth/register", {
    "email": f"corr_{RUN_ID}@example.com",
    "password": "TestPass123!",
    "full_name": "Correction Tester",
})
check("Register returns 201", s == 201, f"got {s}")
if s != 201:
    sys.exit(1)
tok = b["access_token"]
state["tok"] = tok

s, b = post("/api/v1/messages", {"caller_name": "Test"}, tok)
check("Create message", s == 201, f"got {s}")
mid = b["id"]
state["mid"] = mid

audio = find_audio()
if audio:
    with httpx.Client(timeout=30) as c:
        with open(audio, "rb") as f:
            r = c.post(f"{BASE_URL}/api/v1/messages/{mid}/audio",
                       headers={"Authorization": f"Bearer {tok}"},
                       files={"audio_file": (audio.name, f, "audio/mpeg")})
    check("Audio uploaded", r.status_code == 200, f"got {r.status_code}")
    # Transcribe
    s, b = post(f"/api/v1/messages/{mid}/transcribe", {"language_code": "ta-IN"}, tok)
    check("Transcription triggered (202)", s == 202, f"got {s}")
    # Wait for transcript
    print("  Waiting for transcription (up to 60s)...")
    deadline = time.time() + 60
    while time.time() < deadline:
        s2, b2 = get(f"/api/v1/messages/{mid}/transcription", tok)
        if s2 == 200 and b2.get("has_transcript"):
            state["raw_text"] = b2["transcript"]["raw_text"]
            check("Transcript available", True, f"len={len(state['raw_text'])}")
            break
        time.sleep(3)
    else:
        check("Transcript available (timed out)", False)
else:
    # No audio file — create a message with a fake transcript state
    check("Audio file found", False, "Skipping audio/transcription")
    # We can still test by using an existing transcribed message from DB
    # Look up in DB directly
    state["raw_text"] = None


# ── T04: Corrections on message without transcript ────────────
print("\n[T04] Corrections Without Transcript (404)")
s, b = post("/api/v1/messages", {"caller_name": "No transcript"}, tok)
if s == 201:
    no_trans_mid = b["id"]
    s2, b2 = post(f"/api/v1/messages/{no_trans_mid}/corrections", {
        "corrected_text": "Some correction",
    }, tok)
    check("Corrections on no-transcript message -> 404", s2 == 404, f"got {s2}")
    check("Error mentions transcript", "transcript" in str(b2).lower(),
          str(b2.get("detail", ""))[:60])
else:
    check("No-transcript test (message creation failed)", False)


# ── T05: Empty body -> 422 ────────────────────────────────────
print("\n[T05] Validation — Empty Body")
s, b = post(f"/api/v1/messages/{mid}/corrections", {}, tok)
check("Empty body -> 422", s == 422, f"got {s} (should be 422)")
check("Error mentions corrected_text", "corrected_text" in str(b).lower(),
      str(b)[:100])


# ── T06: Missing corrected_text -> 422 ───────────────────────
print("\n[T06] Validation — Missing corrected_text")
s, b = post(f"/api/v1/messages/{mid}/corrections", {
    "change_summary": "Only summary, no text",
}, tok)
check("Missing corrected_text -> 422", s == 422, f"got {s}")


# ── T07: Empty string corrected_text -> 422 ──────────────────
print("\n[T07] Validation — Empty String corrected_text")
s, b = post(f"/api/v1/messages/{mid}/corrections", {
    "corrected_text": "",
}, tok)
check("Empty corrected_text -> 422", s == 422, f"got {s}")


# ── T08: Valid correction — version 1 ────────────────────────
print("\n[T08] Valid Correction — Version 1")
correction_text = "This is the corrected transcript text."
s, b = post(f"/api/v1/messages/{mid}/corrections", {
    "corrected_text": correction_text,
    "change_summary": "First manual correction",
}, tok)
check("POST /corrections returns 201", s == 201, f"got {s}")
if s == 201:
    check("version_number is 1", b.get("version_number") == 1,
          str(b.get("version_number")))
    check("corrected_text saved correctly", b.get("corrected_text") == correction_text)
    check("change_summary saved", b.get("change_summary") == "First manual correction")
    check("transcript_id present", bool(b.get("transcript_id")))
    check("id (version UUID) present", bool(b.get("id")))
    check("created_at present", bool(b.get("created_at")))
    state["v1_id"] = b["id"]
    state["transcript_id"] = b["transcript_id"]


# ── T09: Valid correction — version 2 ────────────────────────
print("\n[T09] Valid Correction — Version 2 (increments)")
s, b = post(f"/api/v1/messages/{mid}/corrections", {
    "corrected_text": "Second corrected transcript text.",
    "change_summary": "Second correction",
}, tok)
check("Second correction returns 201", s == 201, f"got {s}")
if s == 201:
    check("version_number is 2", b.get("version_number") == 2,
          str(b.get("version_number")))
    check("Different id from v1", b.get("id") != state.get("v1_id"))
    check("Same transcript_id as v1", b.get("transcript_id") == state.get("transcript_id"))


# ── T10: With structured corrections list ────────────────────
print("\n[T10] Correction With Entity Corrections List")
s, b = post(f"/api/v1/messages/{mid}/corrections", {
    "corrected_text": "Third version with structured corrections.",
    "change_summary": "Fixed entity values",
    "corrections": [
        {
            "entity_id": str(uuid.uuid4()),
            "original": "fity",
            "corrected": "fifty",
            "action": "EDITED",
        }
    ],
}, tok)
check("Correction with entity list returns 201", s == 201, f"got {s}")
if s == 201:
    check("version_number is 3", b.get("version_number") == 3,
          str(b.get("version_number")))


# ── T11: Original transcript unchanged ───────────────────────
print("\n[T11] Original Transcript Immutability")
s, b = get(f"/api/v1/messages/{mid}/transcription", tok)
check("GET /transcription returns 200", s == 200, f"got {s}")
if s == 200 and b.get("has_transcript") and state.get("raw_text"):
    current_raw = b["transcript"]["raw_text"]
    check("raw_text unchanged after 3 corrections",
          current_raw == state["raw_text"],
          f"original_len={len(state['raw_text'])} current_len={len(current_raw)}")
else:
    check("Immutability (no raw_text to compare)", True, "Skipped — no baseline")


# ── T12: Unauthorized access ─────────────────────────────────
print("\n[T12] Security")
s, _ = post(f"/api/v1/messages/{mid}/corrections", {
    "corrected_text": "Unauthorized attempt",
})
check("No token -> 403", s in {401, 403}, f"got {s}")

s, _ = post(f"/api/v1/messages/{uuid.uuid4()}/corrections", {
    "corrected_text": "Nonexistent message",
}, tok)
check("Nonexistent message -> 404", s == 404, f"got {s}")

# Register second user
s2, b2 = post("/api/v1/auth/register", {
    "email": f"corr_other_{RUN_ID}@example.com",
    "password": "OtherPass456!",
    "full_name": "Other User",
})
if s2 == 201:
    other_tok = b2["access_token"]
    s3, b3 = post(f"/api/v1/messages/{mid}/corrections", {
        "corrected_text": "Cross-user attack",
    }, other_tok)
    check("Cross-user correction -> 404", s3 == 404, f"got {s3}")
else:
    check("Cross-user test (second registration failed)", False)


# ── Summary ───────────────────────────────────────────────────
print()
print("=" * 58)
passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
total = len(results)
print(f"  Results: {passed}/{total} passed  |  {failed} failed")
if failed:
    print()
    print("  FAILED:")
    for name, ok, detail in results:
        if not ok:
            print(f"    x {name}  [{detail}]")
print()
print(f"  Test message ID: {state.get('mid')}")
print("=" * 58)
print()
sys.exit(0 if failed == 0 else 1)
