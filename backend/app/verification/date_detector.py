"""
SASAA – Date Detector
=======================
Extracts date expressions from transcripts including:
  - Relative: today, tomorrow, yesterday
  - Calendar: 15th March, March 15, 15/03/2024
  - Named: "next Monday", "this Friday"

IMPORTANT: Relative dates (today, tomorrow) depend on the message
timestamp. We store the raw expression; the caller must resolve it
using the message creation time. We never silently resolve ambiguous
dates ourselves.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DateMatch:
    raw_value: str
    is_relative: bool          # True for "today", "tomorrow", etc.
    is_ambiguous: bool
    ambiguity_reason: Optional[str]
    char_start: int
    char_end: int
    extraction_confidence: float


_MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
)
_ORDINAL = r"(?:\d{1,2}(?:st|nd|rd|th)?)"
_YEAR = r"(?:19|20)\d{2}"

# Relative dates
_RELATIVE_RE = re.compile(
    r"\b(today|tomorrow|yesterday|day after tomorrow|day before yesterday|"
    r"next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)|"
    r"this\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)|"
    r"last\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month))\b",
    re.IGNORECASE,
)

# Specific calendar date with month name: "15th March" or "March 15"
_NAMED_DATE_RE = re.compile(
    r"\b(?:"
    + _ORDINAL + r"\s+" + _MONTHS
    + r"|" + _MONTHS + r"\s+" + _ORDINAL
    + r"(?:\s*,?\s*" + _YEAR + r")?)\b",
    re.IGNORECASE,
)

# Numeric formats: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
_NUMERIC_DATE_RE = re.compile(
    r"\b(0?[1-9]|[12]\d|3[01])[/\-\.](0?[1-9]|1[0-2])[/\-\.](\d{2}|\d{4})\b"
)


def detect_dates(text: str) -> list[DateMatch]:
    matches: list[DateMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # Relative
    for m in _RELATIVE_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        raw = m.group().strip()
        matches.append(DateMatch(
            raw_value=raw,
            is_relative=True,
            is_ambiguous=True,
            ambiguity_reason=(
                f"Relative date '{raw}' depends on when the message was recorded. "
                "Verify against the message timestamp."
            ),
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.85,
        ))

    # Named calendar date
    for m in _NAMED_DATE_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        matches.append(DateMatch(
            raw_value=m.group().strip(),
            is_relative=False,
            is_ambiguous=False,
            ambiguity_reason=None,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.88,
        ))

    # Numeric date
    for m in _NUMERIC_DATE_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        matches.append(DateMatch(
            raw_value=m.group().strip(),
            is_relative=False,
            is_ambiguous=True,
            ambiguity_reason="Numeric date format detected. Day/month order may be ambiguous.",
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.75,
        ))

    return matches
