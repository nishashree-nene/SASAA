"""
SASAA – Language Service
==========================
Handles language-related intelligence:

  1. Language capability registry — which languages Gnani supports
  2. Language validation — is this code valid before we send to Gnani?
  3. Code-switching detection — Tanglish and mixed-language support
  4. Translation (wraps translator.py logic in an async service)

CRITICAL RULE FROM THE SPEC:
  "Do not claim language coverage for languages not verified against
   current Gnani API documentation."

  All stt_supported values in LANGUAGE_REGISTRY are based on confirmed
  Gnani Prisma v3 support. If uncertain, stt_supported=False.
  The frontend shows a clear warning for unsupported languages.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Language capability registry ─────────────────────────────────────────────

@dataclass
class LanguageCapability:
    """Describes what SASAA can do with a particular language."""
    code: str
    name: str
    native_name: str
    stt_supported: bool                         # Gnani Prisma v3 support
    translation_supported: bool                 # Google Translate support
    code_switching_partner: Optional[str] = None   # e.g. "en-IN" for Tanglish
    notes: Optional[str] = None


# Registry of all supported languages
# Update stt_supported based on the latest Gnani API documentation.
LANGUAGE_REGISTRY: dict[str, LanguageCapability] = {
    "ta-IN": LanguageCapability(
        code="ta-IN",
        name="Tamil",
        native_name="தமிழ்",
        stt_supported=True,
        translation_supported=True,
        code_switching_partner="en-IN",
        notes="Tanglish (Tamil + English code-switching) supported as evaluation target",
    ),
    "en-IN": LanguageCapability(
        code="en-IN",
        name="English",
        native_name="English",
        stt_supported=True,
        translation_supported=True,
    ),
    "hi-IN": LanguageCapability(
        code="hi-IN",
        name="Hindi",
        native_name="हिन्दी",
        stt_supported=True,
        translation_supported=True,
    ),
    "te-IN": LanguageCapability(
        code="te-IN",
        name="Telugu",
        native_name="తెలుగు",
        stt_supported=True,
        translation_supported=True,
    ),
    "ml-IN": LanguageCapability(
        code="ml-IN",
        name="Malayalam",
        native_name="മലയാളം",
        stt_supported=True,
        translation_supported=True,
    ),
    "kn-IN": LanguageCapability(
        code="kn-IN",
        name="Kannada",
        native_name="ಕನ್ನಡ",
        stt_supported=True,
        translation_supported=True,
    ),
    "bn-IN": LanguageCapability(
        code="bn-IN",
        name="Bengali",
        native_name="বাংলা",
        stt_supported=True,
        translation_supported=True,
    ),
    "mr-IN": LanguageCapability(
        code="mr-IN",
        name="Marathi",
        native_name="मराठी",
        stt_supported=True,
        translation_supported=True,
    ),
    "gu-IN": LanguageCapability(
        code="gu-IN",
        name="Gujarati",
        native_name="ગુજરાતી",
        stt_supported=True,
        translation_supported=True,
    ),
    "pa-IN": LanguageCapability(
        code="pa-IN",
        name="Punjabi",
        native_name="ਪੰਜਾਬੀ",
        stt_supported=True,
        translation_supported=True,
    ),
    "ur-IN": LanguageCapability(
        code="ur-IN",
        name="Urdu",
        native_name="اردو",
        stt_supported=True,
        translation_supported=True,
    ),
}


def get_language(code: str) -> Optional[LanguageCapability]:
    """Look up a language by its BCP-47 code. Returns None if unknown."""
    return LANGUAGE_REGISTRY.get(code)


def is_stt_supported(code: str) -> bool:
    """Return True only if this language is confirmed in LANGUAGE_REGISTRY."""
    lang = get_language(code)
    return lang is not None and lang.stt_supported


def get_unsupported_language_message(code: str) -> str:
    """
    Return a clear, honest message for unsupported languages.
    Used in API responses and the frontend warning banner.
    """
    lang = get_language(code)
    if lang is None:
        return (
            f"Language code '{code}' is not recognised. "
            f"Please select a supported language from the settings."
        )
    return (
        f"{lang.name} ({lang.native_name}) transcription is not currently "
        f"supported by the configured STT provider. "
        f"The audio will be stored but cannot be transcribed automatically."
    )


def validate_language_code(code: str) -> tuple[bool, str]:
    """
    Validate a language code before sending to Gnani.

    Returns:
        (True, "") if valid and supported
        (False, reason) if invalid or unsupported
    """
    if not code:
        return False, "Language code is required."

    if code not in LANGUAGE_REGISTRY:
        return False, f"Language code '{code}' is not in the supported list."

    lang = LANGUAGE_REGISTRY[code]
    if not lang.stt_supported:
        return False, get_unsupported_language_message(code)

    return True, ""


# ── Translation service ──────────────────────────────────────────────────────

async def translate_to_english(text: str) -> Optional[str]:
    """
    Translate text to English using Google Translate (via deep_translator).
    This is the async version of translator.py's translate_to_english().

    The translation is stored separately from the original transcript.
    It NEVER replaces the original — it is an additional field.

    Returns:
        The English translation, or None if translation failed.
    """
    if not text or not text.strip():
        return None

    # Run the synchronous deep_translator call in a thread pool
    # so it doesn't block FastAPI's async event loop
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _translate_sync, text)
        return result
    except Exception as e:
        logger.warning("Translation failed", error=str(e))
        return None


def _translate_sync(text: str) -> Optional[str]:
    """
    Synchronous translation call — runs in a thread pool.
    Preserved exactly from translator.py.
    """
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(
            source="auto",
            target="en"
        ).translate(text)
        return translated
    except Exception as error:
        logger.warning("deep_translator error", error=str(error))
        return None


async def detect_language_from_text(text: str) -> Optional[str]:
    """
    Attempt to detect the language of a transcript from its text content.
    Used as a fallback when Gnani doesn't return detected_language_code.

    This is a simple heuristic based on Unicode character ranges.
    For Tamil script detection specifically (important for Tanglish):
    Tamil Unicode block: U+0B80–U+0BFF
    """
    if not text:
        return None

    # Count characters in various Unicode ranges
    tamil_chars = sum(1 for c in text if '\u0B80' <= c <= '\u0BFF')
    hindi_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    telugu_chars = sum(1 for c in text if '\u0C00' <= c <= '\u0C7F')
    malayalam_chars = sum(1 for c in text if '\u0D00' <= c <= '\u0D7F')
    kannada_chars = sum(1 for c in text if '\u0C80' <= c <= '\u0CFF')
    bengali_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    gujarati_chars = sum(1 for c in text if '\u0A80' <= c <= '\u0AFF')
    punjabi_chars = sum(1 for c in text if '\u0A00' <= c <= '\u0A7F')
    urdu_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')

    scores = {
        "ta-IN": tamil_chars,
        "hi-IN": hindi_chars,
        "te-IN": telugu_chars,
        "ml-IN": malayalam_chars,
        "kn-IN": kannada_chars,
        "bn-IN": bengali_chars,
        "gu-IN": gujarati_chars,
        "pa-IN": punjabi_chars,
        "ur-IN": urdu_chars,
    }

    max_score = max(scores.values())

    # If no significant non-Latin characters, assume English
    if max_score < 3:
        return "en-IN"

    # Return the language with the most characters
    detected = max(scores, key=scores.get)
    logger.info("Language detected from text", language=detected, char_count=max_score)
    return detected
