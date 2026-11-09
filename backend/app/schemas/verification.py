"""
SASAA – Verification Pydantic Schemas
"""

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class ExtractedEntityResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    raw_value: str
    normalized_value: Optional[str] = None
    suggested_interpretation: Optional[str] = None
    has_ambiguity: bool
    ambiguity_reason: Optional[str] = None
    extraction_confidence: Optional[float] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    # Nested verification result
    verification_status: Optional[str] = None
    risk_level: Optional[str] = None
    reason: Optional[str] = None
    evidence: Optional[dict] = None
    user_decision: Optional[str] = None
    user_correction: Optional[str] = None
    user_decided_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class VerificationResultResponse(BaseModel):
    message_id: uuid.UUID
    status: str                        # message status
    has_results: bool
    entities: list[ExtractedEntityResponse] = []
    total_entities: int = 0
    flagged_count: int = 0
    needs_review_count: int = 0
    verified_count: int = 0
    critical_risk_count: int = 0
    high_risk_count: int = 0
    message: Optional[str] = None


class CorrectionRequest(BaseModel):
    corrected_text: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="The full corrected transcript text.",
    )
    change_summary: Optional[str] = Field(
        None,
        max_length=1000,
        description="Plain-language description of what was changed.",
    )
    corrections: Optional[list[dict[str, Any]]] = Field(
        None,
        description=(
            "Optional structured list of individual corrections: "
            "[{entity_id, original, corrected, action}]"
        ),
    )


class CorrectionResponse(BaseModel):
    id: uuid.UUID
    transcript_id: uuid.UUID
    version_number: int
    corrected_text: str
    change_summary: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
