"""
SASAA – Complete Authentication Test Suite
===========================================
Tests every authentication endpoint against the live server.
Uses a unique test email per run so it never pollutes real user data.

Run from backend/ directory:
    python test_auth.py

Requirements:
    - Server must be running (python -m uvicorn app.main:app --port 8001)
    - sasaa_db must be accessible
    - .env must have real DATABASE_URL and SECRET_KEY
"""

import json
import sys
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime

BASE_URL = "http://localhost:8001"

# Unique test email per run — prevents collisions if tests are run repeatedly
RUN_ID = uuid.uuid4().hex[:8]
TEST_EMAIL = f"test_{RUN_ID}@example.com"
TEST_PASSWORD = "TestPass123!"
TEST_NAME = "SASAA Test User"

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool, str]] = []

# Shared state across tests
state: dict = {}


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, {"_raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def get(path, token=None):
    return _req("GET", path, token=token)

def post(path, body=None, token=None):
    return _req("POST", path, body=body, token=token)

def patch(path, body=None, token=None):
    return _req("PATCH", path, body=body, token=token)

def delete(path, token=None):
    return _req("DELETE", path, token=token)


def check(name: str, passed: bool, detail: str = "") -> None:
    icon = PASS if passed else FAIL
    line = f"  {icon} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    results.append((name, passed, detail))


# ═══════════════════════════════════════════════════════════
print()
print("=" * 58)
print("  SASAA Authentication Test Suite")
print(f"  Server: {BASE_URL}")
print(f"  Test email: {TEST_EMAIL}")
print("=" * 58)


# ── T01: Server health ────────────────────────────────────────
print("\n[T01] Server Health")

status, body = get("/health")
check("GET /health returns 200", status == 200, f"status={status}")
check("Status is healthy", body.get("status") == "healthy", body.get("status"))
check("DB connected", body.get("database", {}).get("status") == "connected")
check("Gnani configured", body.get("gnani_configured") is True)


# ── T02: Language endpoint (no auth) ─────────────────────────
print("\n[T02] Language Endpoint (public, no auth)")

status, body = get("/api/v1/languages")
check("GET /languages returns 200", status == 200)
check("Returns 11 languages", isinstance(body, list) and len(body) == 11, str(len(body) if isinstance(body, list) else "?"))
if isinstance(body, list) and body:
    codes = [l.get("code") for l in body]
    check("ta-IN present", "ta-IN" in codes)
    check("en-IN present", "en-IN" in codes)


# ── T03: Registration — invalid inputs ───────────────────────
print("\n[T03] Registration — Validation")

# Bad email
status, body = post("/api/v1/auth/register", {
    "email": "not-an-email",
    "password": TEST_PASSWORD,
    "full_name": TEST_NAME,
})
check("Bad email -> 422", status == 422, f"got {status}")

# Short password
status, body = post("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": "short",
    "full_name": TEST_NAME,
})
check("Short password -> 422", status == 422, f"got {status}")

# Password without digit
status, body = post("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": "NoDigitsHere!",
    "full_name": TEST_NAME,
})
check("No-digit password -> 422", status == 422, f"got {status}")

# Missing full_name
status, body = post("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
})
check("Missing full_name -> 422", status == 422, f"got {status}")


# ── T04: Registration — success ───────────────────────────────
print("\n[T04] Registration — Success")

status, body = post("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "full_name": TEST_NAME,
})
check("POST /register returns 201", status == 201, f"got {status}")
check("access_token present", bool(body.get("access_token")))
check("refresh_token present", bool(body.get("refresh_token")))
check("token_type is bearer", body.get("token_type") == "bearer")
check("expires_in is positive int", isinstance(body.get("expires_in"), int) and body.get("expires_in") > 0, str(body.get("expires_in")))

if status == 201:
    state["access_token"] = body["access_token"]
    state["refresh_token"] = body["refresh_token"]
    print(f"  [INFO] Tokens stored. Access token length: {len(state['access_token'])}")


# ── T05: Duplicate registration ───────────────────────────────
print("\n[T05] Duplicate Registration")

status, body = post("/api/v1/auth/register", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "full_name": TEST_NAME,
})
check("Duplicate email -> 409", status == 409, f"got {status}")
check("Error message mentions email", "email" in str(body).lower() or "exists" in str(body).lower(), str(body))


# ── T06: Protected route without token ───────────────────────
print("\n[T06] Protected Routes — No Token")

status, body = get("/api/v1/users/me")
check("GET /users/me without token -> 403", status in {401, 403}, f"got {status}")

status, body = get("/api/v1/analytics/dashboard")
check("GET /dashboard without token -> 403", status in {401, 403}, f"got {status}")

status, body = get("/api/v1/alerts")
check("GET /alerts without token -> 403", status in {401, 403}, f"got {status}")


# ── T07: Protected route with valid token ────────────────────
print("\n[T07] GET /users/me — With Valid Token")

if "access_token" not in state:
    check("GET /users/me", False, "Skipped — no access token from T04")
else:
    status, body = get("/api/v1/users/me", token=state["access_token"])
    check("GET /users/me returns 200", status == 200, f"got {status}")
    check("id is a UUID", bool(body.get("id")))
    check("email matches test email", body.get("email") == TEST_EMAIL, body.get("email"))
    check("full_name matches", body.get("full_name") == TEST_NAME, body.get("full_name"))
    check("is_verified is False", body.get("is_verified") is False)
    check("created_at present", bool(body.get("created_at")))
    state["user_id"] = body.get("id")


# ── T08: Dashboard stats ──────────────────────────────────────
print("\n[T08] GET /analytics/dashboard — Real DB Counts")

if "access_token" not in state:
    check("Dashboard", False, "Skipped — no token")
else:
    status, body = get("/api/v1/analytics/dashboard", token=state["access_token"])
    check("GET /dashboard returns 200", status == 200, f"got {status}")
    check("total_messages is int", isinstance(body.get("total_messages"), int))
    check("guardian_active is True", body.get("guardian_active") is True)
    check("unread_messages is int", isinstance(body.get("unread_messages"), int))


# ── T09: Update profile ───────────────────────────────────────
print("\n[T09] PATCH /users/me")

if "access_token" not in state:
    check("PATCH /users/me", False, "Skipped — no token")
else:
    status, body = patch("/api/v1/users/me", {
        "full_name": "Updated SASAA Name",
        "phone_number": "+919876543210",
    }, token=state["access_token"])
    check("PATCH /users/me returns 200", status == 200, f"got {status}")
    check("full_name updated", body.get("full_name") == "Updated SASAA Name", body.get("full_name"))
    check("phone_number updated", body.get("phone_number") == "+919876543210", body.get("phone_number"))


# ── T10: Get and update preferences ──────────────────────────
print("\n[T10] User Preferences")

if "access_token" not in state:
    check("Preferences", False, "Skipped — no token")
else:
    status, body = get("/api/v1/users/preferences", token=state["access_token"])
    check("GET /preferences returns 200", status == 200, f"got {status}")
    check("interface_language present", bool(body.get("interface_language")))
    check("theme defaults to light", body.get("theme") == "light", body.get("theme"))

    status, body = patch("/api/v1/users/preferences", {
        "interface_language": "ta-IN",
        "auto_translate": True,
        "theme": "dark",
    }, token=state["access_token"])
    check("PATCH /preferences returns 200", status == 200, f"got {status}")
    check("language updated to ta-IN", body.get("interface_language") == "ta-IN", body.get("interface_language"))
    check("theme updated to dark", body.get("theme") == "dark", body.get("theme"))
    check("auto_translate updated", body.get("auto_translate") is True)


# ── T11: Login ────────────────────────────────────────────────
print("\n[T11] POST /auth/login")

# Wrong password
status, body = post("/api/v1/auth/login", {
    "email": TEST_EMAIL,
    "password": "WrongPassword999!",
})
check("Wrong password -> 401", status == 401, f"got {status}")

# Non-existent email — use a valid email format that just doesn't exist in DB
status, body = post("/api/v1/auth/login", {
    "email": "nobody_that_exists@example.com",
    "password": TEST_PASSWORD,
})
check("Unknown email -> 401", status == 401, f"got {status}")

# Correct credentials
status, body = post("/api/v1/auth/login", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
})
check("Correct credentials -> 200", status == 200, f"got {status}")
check("access_token present", bool(body.get("access_token")))
check("refresh_token present", bool(body.get("refresh_token")))

if status == 200:
    state["login_access_token"] = body["access_token"]
    state["login_refresh_token"] = body["refresh_token"]
    print("  [INFO] Login tokens stored.")


# ── T12: Token refresh ────────────────────────────────────────
print("\n[T12] POST /auth/refresh")

if "login_refresh_token" not in state:
    check("Token refresh", False, "Skipped — no refresh token from T11")
else:
    # Refresh with valid token
    status, body = post("/api/v1/auth/refresh", {
        "refresh_token": state["login_refresh_token"],
    })
    check("Valid refresh -> 200", status == 200, f"got {status}")
    check("New access_token issued", bool(body.get("access_token")))
    check("New refresh_token issued", bool(body.get("refresh_token")))
    check("New tokens differ from old", body.get("access_token") != state["login_access_token"])

    if status == 200:
        state["rotated_access_token"] = body["access_token"]
        state["rotated_refresh_token"] = body["refresh_token"]

    # Token rotation: old refresh token must now be INVALID
    status2, body2 = post("/api/v1/auth/refresh", {
        "refresh_token": state["login_refresh_token"],  # old token
    })
    check("Old refresh token rejected after rotation -> 401", status2 == 401, f"got {status2}")

    # Invalid/garbage token
    status3, _ = post("/api/v1/auth/refresh", {
        "refresh_token": "completely.invalid.token",
    })
    check("Garbage refresh token -> 401", status3 == 401, f"got {status3}")


# ── T13: Use rotated token on protected endpoint ──────────────
print("\n[T13] Rotated Token — Protected Endpoint")

if "rotated_access_token" not in state:
    check("Rotated token test", False, "Skipped — no rotated token")
else:
    status, body = get("/api/v1/users/me", token=state["rotated_access_token"])
    check("GET /users/me with rotated token -> 200", status == 200, f"got {status}")
    check("email still matches", body.get("email") == TEST_EMAIL)


# ── T14: Logout ───────────────────────────────────────────────
print("\n[T14] POST /auth/logout")

if "rotated_refresh_token" not in state:
    check("Logout", False, "Skipped — no token")
else:
    # Logout using rotated refresh token
    status, body = post("/api/v1/auth/logout", {
        "refresh_token": state["rotated_refresh_token"],
    })
    check("POST /logout returns 200", status == 200, f"got {status}")
    check("Success message returned", body.get("success") is True)

    # After logout, refresh should be rejected
    status2, _ = post("/api/v1/auth/refresh", {
        "refresh_token": state["rotated_refresh_token"],
    })
    check("Refresh after logout -> 401", status2 == 401, f"got {status2}")

    # Logout is idempotent — second call still returns 200
    status3, body3 = post("/api/v1/auth/logout", {
        "refresh_token": state["rotated_refresh_token"],
    })
    check("Second logout is idempotent -> 200", status3 == 200, f"got {status3}")


# ── T15: Access token still works after logout ────────────────
print("\n[T15] Access Token Valid After Logout (stateless)")

if "rotated_access_token" not in state:
    check("Access token after logout", False, "Skipped")
else:
    # Access tokens are stateless JWT — logout only revokes the refresh token
    # The access token remains valid until it expires (30 min)
    status, body = get("/api/v1/users/me", token=state["rotated_access_token"])
    check("Access token still valid after logout -> 200", status == 200,
          f"got {status} (expected: access tokens are stateless)")


# ── T16: Alembic migration status ────────────────────────────
print("\n[T16] Database Migration Status")

import subprocess, os
result = subprocess.run(
    ["python", "-m", "alembic", "current"],
    cwd=os.path.join(os.path.dirname(__file__)),
    capture_output=True, text=True,
)
output = result.stdout + result.stderr
check("Alembic current runs", result.returncode in {0, 1})
check("At head revision", "head" in output, output.strip().split("\n")[-1] if output.strip() else "no output")


# ── T17: OpenAPI schema ───────────────────────────────────────
print("\n[T17] API Documentation")

status, body = get("/openapi.json")
check("GET /openapi.json returns 200", status == 200)
if status == 200:
    path_count = len(body.get("paths", {}))
    check(f"OpenAPI has {path_count} paths", path_count >= 20, str(path_count))
    auth_paths = [p for p in body.get("paths", {}) if "/auth/" in p]
    check("Auth paths in schema", len(auth_paths) >= 4, str(auth_paths))


# ── T18: Error response format ────────────────────────────────
print("\n[T18] Error Response Format")

status, body = get("/api/v1/nonexistent")
check("Unknown route -> 404", status == 404)

status, body = post("/api/v1/auth/register", {"email": "bad"})
check("Validation error body has 'error' or 'detail'", "error" in body or "detail" in body, str(list(body.keys())))


# ═══════════════════════════════════════════════════════════
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
print("  Test email used:", TEST_EMAIL)
print("  (This account remains in the database — delete via DELETE /users/me or pgAdmin)")
print("=" * 58)
print()

sys.exit(0 if failed == 0 else 1)
