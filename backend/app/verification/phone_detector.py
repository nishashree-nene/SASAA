"""
SASAA – Phone Number Detector
================================
Extracts phone numbers and digit sequences from transcripts.

Handles both digit-form (9876543210) and spoken-word form
(nine eight seven six five four three two one zero) for Indian numbers.
Supports 10-digit Indian mobile numbers, landline formats, and sequences
that look like they could be phone numbers.

IMPORTANT: We flag extracted numbers as needing review when the
spoken form is ambiguous — we never silently "correct" a transcript.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PhoneMatch:
    raw_value: str                # exact text span from transcript
    normalized_value: str         # digits only e.g. "9876543210"
    char_start: int
    char_end: int
    has_ambiguity: bool
    ambiguity_reason: Optional[str]
    extraction_confidence: float  # 0.0 – 1.0


# ── Digit-to-word mapping for Indian spoken numbers ─────────────────────────
_DIGIT_WORDS: dict[str, str] = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

# Spoken word form: "nine eight seven six five four three two one zero"
_WORD_DIGIT_PATTERN = re.compile(
    r"\b(?:(?:" + "|".join(_DIGIT_WORDS.keys()) + r")[\s\-]*){7,11}\b",
    re.IGNORECASE,
)

# Digit sequences that could be phone numbers (7–15 digits, with optional
# separators: spaces, hyphens, dots)
_DIGIT_SEQUENCE_PATTERN = re.compile(
    r"\b(\+?\d[\d\s\-\.]{8,16}\d)\b"
)

# Indian mobile: 10 digits starting with 6–9
_INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")

# With country code: +91 followed by 10 digits
_INDIAN_CC_RE = re.compile(r"^\+91[6-9]\d{9}$")


def _spoken_to_digits(text: str) -> str:
    """Convert a spoken digit sequence to its numeric string."""
    digits = []
    for token in re.split(r"[\s\-]+", text.lower()):
        if token in _DIGIT_WORDS:
            digits.append(_DIGIT_WORDS[token])
    return "".join(digits)


def _is_plausible_phone(digits: str) -> bool:
    """Return True if the digit string could plausibly be a phone number."""
    return bool(_INDIAN_MOBILE_RE.match(digits) or _INDIAN_CC_RE.match(digits) or
                (7 <= len(digits) <= 15))


def _strip_separators(s: str) -> str:
    return re.sub(r"[\s\-\.\(\)]", "", s)


def detect_phones(text: str) -> list[PhoneMatch]:
    """
    Detect phone numbers in a transcript string.

    Returns a list of PhoneMatch objects, one per detected candidate.
    Matches may overlap if both word-form and digit-form appear; callers
    should deduplicate by char_start if needed.
    """
    matches: list[PhoneMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # ── 1. Spoken word form ──────────────────────────────────────────────
    for m in _WORD_DIGIT_PATTERN.finditer(text):
        digits = _spoken_to_digits(m.group())
        if not _is_plausible_phone(digits):
            continue
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)

        ambiguous = len(digits) != 10 and not _INDIAN_CC_RE.match(digits)
        matches.append(PhoneMatch(
            raw_value=m.group().strip(),
            normalized_value=digits,
            char_start=m.start(),
            char_end=m.end(),
            has_ambiguity=ambiguous,
            ambiguity_reason=(
                "Phone number extracted from spoken words — digit count does not match "
                "a standard 10-digit Indian mobile number. Please verify."
            ) if ambiguous else None,
            extraction_confidence=0.75 if not ambiguous else 0.5,
        ))

    # ── 2. Digit sequence form ───────────────────────────────────────────
    for m in _DIGIT_SEQUENCE_PATTERN.finditer(text):
        digits = _strip_separators(m.group())
        if not _is_plausible_phone(digits):
            continue
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)

        is_mobile = bool(_INDIAN_MOBILE_RE.match(digits) or _INDIAN_CC_RE.match(digits))
        ambiguous = not is_mobile
        matches.append(PhoneMatch(
            raw_value=m.group().strip(),
            normalized_value=digits,
            char_start=m.start(),
            char_end=m.end(),
            has_ambiguity=ambiguous,
            ambiguity_reason=(
                f"Digit sequence detected ({len(digits)} digits). "
                "Could not confirm it is a standard Indian mobile number. Please verify."
            ) if ambiguous else None,
            extraction_confidence=0.90 if is_mobile else 0.60,
        ))

    return matches
