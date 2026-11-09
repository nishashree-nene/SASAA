"""
SASAA – Alert Pydantic Schemas
"""

import uuid
import math
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AlertResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    alert_type: str
    severity: str
    title: str
    reason: str
    related_transcript_segment: Optional[str] = None
    suggested_action: Optional[str] = None
    is_read: bool
    is_acknowledged: bool
    is_dismissed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
