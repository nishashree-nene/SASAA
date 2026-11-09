"""
SASAA – Language Capability Routes
=====================================
GET /languages              – list all supported languages
GET /languages/capabilities – detailed capability registry per language

These endpoints are NOT protected — they return static configuration data
that the frontend needs before a user is even logged in (e.g. onboarding
language selection screen).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/languages", tags=["Languages"])


class LanguageInfo(BaseModel):
    """Information about one supported language."""
    code: str               # BCP-47 e.g. ta-IN
    name: str               # Display name e.g. Tamil
    native_name: str        # Name in the language itself e.g. தமிழ்
    stt_supported: bool     # Whether Gnani STT supports this language
    translation_supported: bool
    code_switching: Optional[str] = None  # e.g. "ta-IN + en-IN (Tanglish)"
    notes: Optional[str] = None


# Language capability registry
# stt_supported values are based on Gnani Prisma v3 documentation.
# If a language is not confirmed, stt_supported=False to avoid false claims.
SUPPORTED_LANGUAGES: List[LanguageInfo] = [
    LanguageInfo(code="ta-IN",  name="Tamil",     native_name="தமிழ்",       stt_supported=True,  translation_supported=True, code_switching="ta-IN + en-IN (Tanglish)"),
    LanguageInfo(code="en-IN",  name="English",   native_name="English",     stt_supported=True,  translation_supported=True),
    LanguageInfo(code="hi-IN",  name="Hindi",     native_name="हिन्दी",      stt_supported=True,  translation_supported=True),
    LanguageInfo(code="te-IN",  name="Telugu",    native_name="తెలుగు",      stt_supported=True,  translation_supported=True),
    LanguageInfo(code="ml-IN",  name="Malayalam", native_name="മലയാളം",     stt_supported=True,  translation_supported=True),
    LanguageInfo(code="kn-IN",  name="Kannada",   native_name="ಕನ್ನಡ",       stt_supported=True,  translation_supported=True),
    LanguageInfo(code="bn-IN",  name="Bengali",   native_name="বাংলা",      stt_supported=True,  translation_supported=True),
    LanguageInfo(code="mr-IN",  name="Marathi",   native_name="मराठी",       stt_supported=True,  translation_supported=True),
    LanguageInfo(code="gu-IN",  name="Gujarati",  native_name="ગુજરાતી",    stt_supported=True,  translation_supported=True),
    LanguageInfo(code="pa-IN",  name="Punjabi",   native_name="ਪੰਜਾਬੀ",    stt_supported=True,  translation_supported=True),
    LanguageInfo(code="ur-IN",  name="Urdu",      native_name="اردو",        stt_supported=True,  translation_supported=True),
]


@router.get("", response_model=List[LanguageInfo])
async def list_languages():
    """
    Return the full list of languages SASAA supports.
    stt_supported=False means transcription is unavailable for that language
    — the frontend should show a warning rather than silently failing.
    """
    return SUPPORTED_LANGUAGES


@router.get("/capabilities", response_model=List[LanguageInfo])
async def language_capabilities():
    """
    Detailed per-language capability breakdown.
    Used by the frontend to show accurate language support information
    on the onboarding and settings screens.
    """
    return SUPPORTED_LANGUAGES
