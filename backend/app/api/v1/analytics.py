"""
SASAA – Analytics Routes
==========================
GET /analytics/dashboard      – real dashboard stats from the database
GET /analytics/transcription  – transcription accuracy metrics
GET /analytics/verification   – verification engine metrics
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.message import Message, MessageStatus, MessagePriority
from app.schemas.message import DashboardStats

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return real dashboard statistics from the database.
    All values are live counts — never hardcoded.

    Returns zero counts for new users (proper empty state).
    """
    user_id = current_user.id

    # Helper: count messages matching a condition for this user
    async def count_messages(where_clauses):
        result = await db.execute(
            select(func.count(Message.id)).where(
                Message.user_id == user_id,
                Message.deleted_at.is_(None),
                *where_clauses,
            )
        )
        return result.scalar() or 0

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())

    total = await count_messages([])
    unread = await count_messages([Message.is_read == False])
    needs_verification = await count_messages([
        Message.status == MessageStatus.NEEDS_VERIFICATION
    ])
    high_priority = await count_messages([
        Message.priority.in_([MessagePriority.HIGH, MessagePriority.EMERGENCY])
    ])
    emergency = await count_messages([
        Message.priority == MessagePriority.EMERGENCY
    ])
    today = await count_messages([Message.created_at >= today_start])
    this_week = await count_messages([Message.created_at >= week_start])

    return DashboardStats(
        total_messages=total,
        unread_messages=unread,
        messages_needing_verification=needs_verification,
        high_priority_messages=high_priority,
        emergency_messages=emergency,
        messages_today=today,
        messages_this_week=this_week,
        guardian_active=True,
    )


@router.get("/transcription")
async def get_transcription_metrics(current_user=Depends(get_current_user)):
    """Transcription success rate and latency metrics. Full implementation in Phase 9."""
    raise HTTPException(status_code=501, detail="Transcription metrics – implementation in Phase 9.")


@router.get("/verification")
async def get_verification_metrics(current_user=Depends(get_current_user)):
    """Verification engine accuracy metrics. Full implementation in Phase 9."""
    raise HTTPException(status_code=501, detail="Verification metrics – implementation in Phase 9.")
