"""
SASAA – Common Pydantic Schemas
=================================
Shared response shapes used across all API endpoints.

WHY PYDANTIC SCHEMAS (beginner explanation):
  SQLAlchemy models define database tables.
  Pydantic schemas define what the API sends and receives over HTTP.
  They are intentionally separate — the database row might have fields
  you never want to expose (like password_hash), and the API response
  might include computed fields that aren't columns.

  FastAPI uses these schemas to:
  - Validate incoming request bodies (wrong type → 422 error automatically)
  - Serialise outgoing response bodies to JSON
  - Generate the OpenAPI documentation at /docs
"""

from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel

# T is a placeholder type — PaginatedResponse works for any item type
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Standard wrapper for any list endpoint that supports pagination.

    Example response for GET /messages?page=2&page_size=20:
    {
        "items": [...],
        "total": 87,
        "page": 2,
        "page_size": 20,
        "total_pages": 5,
        "has_next": true,
        "has_previous": true
    }
    """
    items: List[T]
    total: int                  # Total number of matching rows
    page: int                   # Current page number (1-indexed)
    page_size: int              # Items per page
    total_pages: int            # ceil(total / page_size)
    has_next: bool
    has_previous: bool


class ErrorResponse(BaseModel):
    """
    Standard error shape returned by all API error responses.

    FastAPI's default error format is different — we override it in main.py
    so every error (validation, auth, server) uses this consistent format.

    Example 401 response:
    {
        "error": "UNAUTHORIZED",
        "message": "Invalid or expired authentication token.",
        "detail": null
    }
    """
    error: str                      # Machine-readable error code
    message: str                    # Human-readable explanation
    detail: Optional[str] = None    # Extra context (never stack traces)


class SuccessResponse(BaseModel):
    """Simple acknowledgement for operations that don't return data."""
    success: bool = True
    message: str


class HealthStatus(BaseModel):
    """Response shape for the /health endpoint."""
    status: str                         # "healthy" or "degraded"
    app_name: str
    version: str
    environment: str
    database: dict                      # Connection status from check_database_connection()
    gnani_configured: bool              # Whether the Gnani API key is set
    email_configured: bool
    firebase_configured: bool
    web_push_configured: bool
