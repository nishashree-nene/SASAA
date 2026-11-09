"""
SASAA – Guardian Alert Routes
================================
GET   /alerts                     – list all alerts for current user
PATCH /alerts/{id}/acknowledge    – mark as read and actioned
PATCH /alerts/{id}/dismiss        – hide from the alert list
"""

import math
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.alert import AlertSeverity, AlertType, PriorityAlert
from app.schemas.alert import AlertListResponse, AlertResponse
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/alerts", tags=["Guardian Alerts"])


async def _get_owned_alert(
    db: AsyncSession,
    alert_id: uuid.UUID,
    user_id: uuid.UUID,
) -> PriorityAlert:
    """Fetch an alert only if it belongs to the current user."""
    result = await db.execute(
        select(PriorityAlert).where(
            PriorityAlert.id == alert_id,
            PriorityAlert.user_id == user_id,
            PriorityAlert.deleted_at.is_(None),
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return alert


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    alert_type: Optional[AlertType] = Query(None),
    severity: Optional[AlertSeverity] = Query(None),
    is_read: Optional[bool] = Query(None),
    is_dismissed: bool = Query(False),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return all alerts for the current user, most recent first.

    By default excludes dismissed alerts. Set is_dismissed=True to include them.
    """
    filters = [
        PriorityAlert.user_id == current_user.id,
        PriorityAlert.deleted_at.is_(None),
        PriorityAlert.is_dismissed == is_dismissed,
    ]
    if alert_type is not None:
        filters.append(PriorityAlert.alert_type == alert_type)
    if severity is not None:
        filters.append(PriorityAlert.severity == severity)
    if is_read is not None:
        filters.append(PriorityAlert.is_read == is_read)

    total_result = await db.execute(
        select(func.count(PriorityAlert.id)).where(*filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(PriorityAlert)
        .where(*filters)
        .order_by(PriorityAlert.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    alerts = result.scalars().all()
    total_pages = math.ceil(total / page_size) if total else 0

    return AlertListResponse(
        items=[AlertResponse.model_validate(a) for a in alerts],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total > 0,
    )


@router.patch("/{alert_id}/acknowledge", response_model=SuccessResponse)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Mark an alert as read and acknowledged (the user has seen and actioned it)."""
    alert = await _get_owned_alert(db, alert_id, current_user.id)
    alert.is_read = True
    alert.is_acknowledged = True
    await db.commit()
    return SuccessResponse(success=True, message="Alert acknowledged.")


@router.patch("/{alert_id}/dismiss", response_model=SuccessResponse)
async def dismiss_alert(
    alert_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Dismiss an alert so it no longer appears in the default alert list."""
    alert = await _get_owned_alert(db, alert_id, current_user.id)
    alert.is_dismissed = True
    alert.is_read = True
    await db.commit()
    return SuccessResponse(success=True, message="Alert dismissed.")
