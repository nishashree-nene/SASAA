"""
SASAA – Notification Routes
==============================
GET  /notifications               – in-app notification list
POST /notifications/register-device – register FCM token or web push subscription
PATCH /notifications/preferences  – update notification settings
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
async def list_notifications(current_user=Depends(get_current_user)):
    """Return in-app notification list for the current user."""
    raise HTTPException(status_code=501, detail="Notification list – implementation in Phase 7.")


@router.post("/register-device", response_model=SuccessResponse)
async def register_device(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Register an Android FCM token or browser Web Push subscription.
    Body format depends on the platform:
      Android: { "type": "fcm", "token": "...", "device_id": "...", "device_name": "..." }
      Web:     { "type": "web_push", "subscription": { "endpoint": "...", "keys": {...} } }
    """
    raise HTTPException(status_code=501, detail="Device registration – implementation in Phase 7.")


@router.patch("/preferences", response_model=SuccessResponse)
async def update_notification_preferences(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update which notification types and channels the user wants."""
    raise HTTPException(status_code=501, detail="Notification preferences – implementation in Phase 7.")
