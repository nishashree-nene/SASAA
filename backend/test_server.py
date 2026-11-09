"""
SASAA – Live Server Test
==========================
Run this AFTER the server is already running in another terminal.

Prerequisites:
  1. .env has real PostgreSQL password (not YOUR_PASSWORD)
  2. sasaa_db database exists in pgAdmin
  3. Migrations ran: python run_migrations.py
  4. Server is running: python -m uvicorn app.main:app --reload --port 8000

Then run this in a SECOND terminal:
    cd backend
    python test_server.py
"""

import sys
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"
PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(label, passed, detail=""):
    status = PASS if passed else FAIL
    suffix = f" - {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    results.append((label, passed))


def get(path: str, follow_redirects: bool = True) -> tuple[int, dict]:
    """Make a GET request, return (status_code, json_body)."""
    try:
        url = BASE_URL + path
        req = urllib.request.Request(url)
        if follow_redirects:
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        else:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=10) as resp:
            raw = resp.read()
            try:
                body = json.loads(raw)
            except Exception:
                body = {"_raw_length": len(raw)}
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


print("\n" + "=" * 55)
print("  SASAA Live Server Test")
print("=" * 55)

# ── 1. Server reachability ────────────────────────────────────────
print("\n[1] Server Reachability")

status, body = get("/")
check("GET / returns 200", status == 200, f"status={status}")
if status == 200:
    check("API name in response", "SASAA" in str(body))
    check("Docs URL in response", "/docs" in str(body))

# ── 2. Health check ───────────────────────────────────────────────
print("\n[2] Health Check")

status, body = get("/health")
check("GET /health returns 200", status == 200, f"status={status}")

if status == 200:
    health_status = body.get("status", "")
    check("Health status field present", "status" in body)

    db = body.get("database", {})
    db_status = db.get("status", "")
    check(f"Database connected", db_status == "connected",
          f"db_status={db_status} (if 'error', check your .env password)")

    if db_status == "connected":
        pg_version = db.get("postgresql_version", "")
        check("PostgreSQL version reported", "PostgreSQL" in pg_version, pg_version[:50])

    check("App name correct",   body.get("app_name") == "SASAA")
    check("Version present",    body.get("version") == "1.0.0")
    check("Gnani configured",   body.get("gnani_configured") is True,
          "If False: check GNANI_API_KEY in .env")

    overall = body.get("status")
    if overall == "healthy":
        print("\n  *** DATABASE CONNECTION: CONFIRMED ***")
    else:
        print(f"\n  WARNING: Health status is '{overall}' - check database connection")

# ── 3. API endpoints ──────────────────────────────────────────────
print("\n[3] API Endpoint Accessibility")

# Languages endpoint (no auth required - should return 200)
status, body = get("/api/v1/languages")
check("GET /languages returns 200", status == 200, f"status={status}")
if status == 200:
    check(f"Returns 11 languages", len(body) == 11, f"got {len(body)}")
    codes = [l.get("code") for l in body]
    check("ta-IN in language list", "ta-IN" in codes)
    check("en-IN in language list", "en-IN" in codes)

# Protected endpoint without auth should return 403 or 401
status, body = get("/api/v1/users/me")
check("GET /users/me without token returns 403", status in {401, 403},
      f"status={status} (expected 401 or 403)")

# Messages without auth should return 403 or 401
status, body = get("/api/v1/messages")
check("GET /messages without token returns 403", status in {401, 403},
      f"status={status}")

# Unimplemented stub should return 501 (but needs auth)
# We just check it returns auth error, not 500
status, body = get("/api/v1/analytics/dashboard")
check("GET /analytics/dashboard without token is 401/403", status in {401, 403},
      f"status={status}")

# OpenAPI docs should be accessible
status, _ = get("/docs")
check("GET /docs returns 200", status == 200, "Swagger UI accessible")

status, body = get("/openapi.json")
check("GET /openapi.json returns 200", status == 200, "OpenAPI schema accessible")
if status == 200 and "_raw_length" not in body:
    route_count = len(body.get("paths", {}))
    check(f"OpenAPI schema has {route_count} paths", route_count >= 20, f"{route_count} paths")

# ── 4. Error response format ──────────────────────────────────────
print("\n[4] Error Response Format")

status, body = get("/api/v1/nonexistent-route")
check("Unknown route returns 404", status == 404, f"status={status}")

status, body = get("/api/v1/users/me")
if "error" in body or "detail" in body:
    check("Auth error has structured response", True)

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 55)
passed = sum(1 for _, p in results if p)
failed = sum(1 for _, p in results if not p)

print(f"  Results: {passed}/{len(results)} passed  |  {failed} failed")

if failed > 0:
    print("\n  Failed checks:")
    for label, p in results:
        if not p:
            print(f"    x {label}")
    print()
    print("  Common fixes:")
    print("  - 'Database connected' fails: update YOUR_PASSWORD in .env")
    print("  - Server not reachable: run uvicorn first in another terminal")
    print("  - 'Gnani configured' fails: check GNANI_API_KEY in .env")
else:
    print()
    print("  Phase 2 server test: ALL CHECKS PASSED")
    print()
    print("  Your SASAA backend is running and connected to PostgreSQL.")
    print("  Open http://localhost:8000/docs to explore the full API.")

print("=" * 55)
sys.exit(0 if failed == 0 else 1)
