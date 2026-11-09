"""
SASAA – Currency Amount Detector
==================================
Extracts monetary amounts from transcripts including:
  - Digit form: "50000 rupees", "₹1,50,000"
  - Spoken word form: "fifty thousand rupees", "two lakhs"
  - Indian number system: thousands, lakhs, crores

IMPORTANT: We extract and flag amounts for review. We never
"correct" a transcribed amount — speech recognition errors on
financial values (e.g. 15 vs 50) are exactly what SASAA exists to catch.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class AmountMatch:
    raw_value: str
    normalized_value: str      # numeric string e.g. "50000"
    currency: str              # "INR" or "UNKNOWN"
    char_start: int
    char_end: int
    has_ambiguity: bool
    ambiguity_reason: Optional[str]
    extraction_confidence: float


# ── Word-to-number tables ────────────────────────────────────────────────────
_UNITS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE: dict[str, int] = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
}
_ALL_WORDS = set(_UNITS) | set(_TENS) | set(_SCALE)

# Currency indicators
_CURRENCY_WORDS = r"(?:rupees?|rs\.?|inr|₹)"
_CURRENCY_RE = re.compile(_CURRENCY_WORDS, re.IGNORECASE)

# Digit amount patterns (commas ok for Indian numbering: 1,50,000)
_DIGIT_AMOUNT_RE = re.compile(
    r"(?:₹\s*|rs\.?\s*|inr\s*)?"
    r"(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:rupees?|rs\.?|inr|lakhs?|lacs?|crores?|thousands?|cr\b))?",
    re.IGNORECASE,
)

# Spoken word pattern — looks for number words followed by currency/scale
# Requires at least ONE number word (not two), followed by optional currency
_SPOKEN_AMOUNT_RE = re.compile(
    r"\b(?:(?:" + "|".join(sorted(_ALL_WORDS | {"and", "a"}, key=len, reverse=True)) +
    r")[\s\-]*){1,10}"    # changed from {2,10} to {1,10}
    r"(?:rupees?|rs\.?|inr|₹)",  # currency is now REQUIRED for single-word amounts
    re.IGNORECASE,
)


def _words_to_number(text: str) -> Optional[int]:
    """Convert a spoken number phrase to an integer. Returns None if unparseable."""
    tokens = re.split(r"[\s\-,]+", text.lower())
    result = 0
    current = 0
    for token in tokens:
        if token in ("and", "a", ""):
            continue
        if token in _UNITS:
            current += _UNITS[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token == "hundred":
            current = max(current, 1) * 100
        elif token in _SCALE:
            scale = _SCALE[token]
            if current == 0:
                current = 1
            result += current * scale
            current = 0
        # ignore unrecognised tokens (could be currency words)
    result += current
    return result if result > 0 else None


def _strip_commas(s: str) -> str:
    return s.replace(",", "")


def detect_amounts(text: str) -> list[AmountMatch]:
    """
    Detect monetary amounts in a transcript string.
    Handles English/Latin text and Tamil Unicode script.
    Returns one AmountMatch per candidate; higher-confidence digit matches
    are preferred over lower-confidence spoken matches for the same span.
    """
    matches: list[AmountMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # ── 1. Digit form ────────────────────────────────────────────────────
    for m in _DIGIT_AMOUNT_RE.finditer(text):
        raw = m.group().strip()
        digits_part = m.group(1)
        if not digits_part:
            continue
        value_str = _strip_commas(digits_part)
        try:
            value = float(value_str)
        except ValueError:
            continue
        if value <= 0:
            continue

        has_currency = bool(_CURRENCY_RE.search(raw))
        # Skip sequences that look like phone numbers (>= 7 digits with no separators)
        stripped_digits = re.sub(r"[^\d]", "", digits_part)
        if len(stripped_digits) >= 7 and not has_currency:
            continue

        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)

        # Large amounts (>= 1 lakh) without explicit currency mention are ambiguous
        ambiguous = not has_currency and value >= 100_000
        matches.append(AmountMatch(
            raw_value=raw,
            normalized_value=str(int(value) if value == int(value) else value),
            currency="INR" if has_currency else "UNKNOWN",
            char_start=m.start(),
            char_end=m.end(),
            has_ambiguity=ambiguous,
            ambiguity_reason=(
                "Large amount detected without explicit currency mention. "
                "Please verify this is a monetary value."
            ) if ambiguous else None,
            extraction_confidence=0.85 if has_currency else 0.55,
        ))

    # ── 2. Spoken form ───────────────────────────────────────────────────
    for m in _SPOKEN_AMOUNT_RE.finditer(text):
        raw = m.group().strip()
        value = _words_to_number(raw)
        if value is None or value <= 0:
            continue
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)

        has_currency = bool(_CURRENCY_RE.search(raw))
        matches.append(AmountMatch(
            raw_value=raw,
            normalized_value=str(value),
            currency="INR" if has_currency else "UNKNOWN",
            char_start=m.start(),
            char_end=m.end(),
            has_ambiguity=True,
            ambiguity_reason=(
                "Amount extracted from spoken words. Speech recognition errors on "
                "financial values (e.g. fifteen vs fifty) can occur. Please verify."
            ),
            extraction_confidence=0.65 if has_currency else 0.45,
        ))

    # ── 3. Tamil script amounts ──────────────────────────────────────────
    try:
        from app.verification.tamil_mapper import extract_tamil_entities, has_tamil_script
        if has_tamil_script(text):
            for tent in extract_tamil_entities(text):
                # Only include as a financial amount if there's explicit currency context
                if tent.entity_hint == "amount" and tent.numeric_value is not None and tent.has_currency:
                    span = (tent.char_start, tent.char_end)
                    if span in seen_ranges:
                        continue
                    seen_ranges.add(span)
                    matches.append(AmountMatch(
                        raw_value=tent.raw_value,
                        normalized_value=str(tent.numeric_value),
                        currency="INR",
                        char_start=tent.char_start,
                        char_end=tent.char_end,
                        has_ambiguity=True,
                        ambiguity_reason=(
                            "Tamil financial keyword detected. Speech recognition errors "
                            "on Tamil number words can occur. Please verify."
                        ),
                        extraction_confidence=0.72,
                    ))
    except ImportError:
        pass  # Tamil mapper optional

    return matches
