"""
SASAA – FastAPI Application Entry Point
=========================================
This is the top-level application file. It:

  1. Creates the FastAPI app instance
  2. Configures CORS so the React frontend can call the API
  3. Registers all API routes under /api/v1
  4. Sets up consistent error response formatting
  5. Provides a /health endpoint for connection testing
  6. Ensures the audio storage directory exists on startup

To run the development server (from the backend/ directory):
    python -m uvicorn app.main:app --reload --port 8000

Then open:
    http://localhost:8000/docs   – Interactive API documentation (Swagger UI)
    http://localhost:8000/health – Health check
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import check_database_connection
from app.schemas.common import ErrorResponse, HealthStatus

# ── Structured logging setup ────────────────────────────────────────────────
# structlog gives us JSON-formatted logs that are easy to search in production
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger(__name__)


# ── Application lifespan ─────────────────────────────────────────────────────
# The lifespan context manager runs startup code before the first request
# and shutdown code after the last request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: verify configuration and create required directories.
    Shutdown: close any open resources.
    """
    logger.info("SASAA starting up", environment=settings.environment, version=settings.app_version)

    # Create audio storage directory if it doesn't exist
    audio_path = Path(settings.audio_storage_path)
    audio_path.mkdir(parents=True, exist_ok=True)
    logger.info("Audio storage ready", path=str(audio_path.resolve()))

    # Warn about optional services that aren't configured
    if not settings.gnani_api_key:
        logger.warning("GNANI_API_KEY not set – transcription will not work")
    if not settings.email_enabled:
        logger.info("Email notifications disabled (SMTP not configured)")
    if not settings.firebase_enabled:
        logger.info("Firebase push disabled (credentials not configured)")

    yield  # Application is now running and handling requests

    logger.info("SASAA shutting down")


# ── FastAPI application instance ─────────────────────────────────────────────
app = FastAPI(
    title="SASAA – AI Voice Note Guardian",
    description=(
        "SASAA protects the meaning of voice messages by detecting and "
        "flagging suspicious speech-to-text errors in phone numbers, times, "
        "amounts, names, and negations."
    ),
    version=settings.app_version,
    docs_url="/docs",           # Swagger UI
    redoc_url="/redoc",         # ReDoc UI
    openapi_url="/openapi.json",
    lifespan=lifespan,
    # Hide 500 error details from clients in production
    debug=settings.is_development,
)


# ── CORS middleware ───────────────────────────────────────────────────────────
# CORS (Cross-Origin Resource Sharing) allows the React frontend at
# http://localhost:5173 to call this API at http://localhost:8000.
# In production, replace with your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    settings.frontend_url,
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
],              # Authorization, Content-Type, etc.
)


# ── Error response standardisation ───────────────────────────────────────────
# These handlers ensure every error (validation, auth, server) uses the
# same ErrorResponse shape instead of FastAPI's default formats.

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle Pydantic validation errors (e.g. wrong field type, missing required field).
    Returns HTTP 422 with a clear description of what was wrong.
    """
    errors = exc.errors()
    # Build a readable message from the first validation error
    first_error = errors[0] if errors else {}
    field = " → ".join(str(loc) for loc in first_error.get("loc", []))
    msg = first_error.get("msg", "Validation error")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="VALIDATION_ERROR",
            message=f"Invalid input: {msg}",
            detail=f"Field: {field}" if field else None,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unexpected server errors.
    In development: shows the error message to help with debugging.
    In production: returns a generic message (never leaks internal details).
    """
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )

    detail = str(exc) if settings.is_development else None

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred. Please try again.",
            detail=detail,
        ).model_dump(),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

# Mount all API v1 routes at /api/v1
app.include_router(api_v1_router, prefix="/api/v1")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthStatus,
    tags=["Health"],
    summary="Server and database health check",
)
async def health_check():
    """
    Check that the server is running and can connect to the database.

    This is the first endpoint to test after starting the server.
    Open http://localhost:8000/health in your browser.

    Expected response when everything is working:
    {
        "status": "healthy",
        "app_name": "SASAA",
        "version": "1.0.0",
        "environment": "development",
        "database": {
            "status": "connected",
            "database": "sasaa_db",
            "postgresql_version": "PostgreSQL 18.6 ..."
        },
        "gnani_configured": true,
        ...
    }
    """
    db_status = await check_database_connection()

    overall_status = "healthy" if db_status.get("status") == "connected" else "degraded"

    return HealthStatus(
        status=overall_status,
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database=db_status,
        gnani_configured=bool(settings.gnani_api_key),
        email_configured=settings.email_enabled,
        firebase_configured=settings.firebase_enabled,
        web_push_configured=settings.web_push_enabled,
    )


@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    """Redirect root to the API documentation."""
    return {
        "message": "SASAA – AI Voice Note Guardian API",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
    }
