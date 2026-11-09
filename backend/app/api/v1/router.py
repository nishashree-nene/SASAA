"""
SASAA – API v1 Router
======================
Combines all sub-routers into one v1 router.
This is imported by main.py and mounted at /api/v1.

To add a new route group:
  1. Create backend/app/api/v1/my_feature.py with an APIRouter
  2. Import it here
  3. Add it with api_v1_router.include_router(my_feature.router)
"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    users,
    messages,
    audio,
    transcription,
    verification,
    alerts,
    notifications,
    languages,
    analytics,
    voicemails,
)
from app.telephony.webhook_router import router as telephony_router

api_v1_router = APIRouter()

# Authentication
api_v1_router.include_router(auth.router)

# User profile and preferences
api_v1_router.include_router(users.router)

# Voice messages (manual upload workflow)
api_v1_router.include_router(messages.router)

# Audio upload and streaming
api_v1_router.include_router(audio.router)

# Transcription
api_v1_router.include_router(transcription.router)

# Verification engine
api_v1_router.include_router(verification.router)

# Guardian alerts
api_v1_router.include_router(alerts.router)

# Notifications
api_v1_router.include_router(notifications.router)

# Language capabilities (public)
api_v1_router.include_router(languages.router)

# Analytics and dashboard
api_v1_router.include_router(analytics.router)

# Voicemails (missed-call voicemail inbox)
api_v1_router.include_router(voicemails.router)

# Telephony webhooks + configuration
api_v1_router.include_router(telephony_router)
