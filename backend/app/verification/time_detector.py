"""
SASAA – Time Detector
======================
Evolved directly from guardian.py's check_time() function.

The core SASAA use case: speech-to-text may mishear "5 AM" as "5 PM"
or drop the AM/PM entirely, turning "meet me at 5 AM" into an ambiguous
"meet me at 5". We must flag this — never silently assume.

Rules (from the original guardian.py logic):
  - If AM/PM is explicitly present → status EXTRACTED, no ambiguity
  - If a time-like number is present but no AM/PM → status AMBIGUOUS, flag it
  - Never guess AM or PM when it is absent from the transcript

Also handles:
  - Contextual meridiem: "in the morning/afternoon/evening/night"
  - 24-hour format: "14:30" → unambiguous
  - Words: "midnight", "noon", "midday"
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class TimeMatch:
    raw_value: str
    hour: Optional[int]
    minute: Optional[int]
    meridiem: Optional[str]        # "AM", "PM", or None if absent
    is_24h: bool
    is_ambiguous: bool
    ambiguity_reason: Optional[str]
    char_start: int
    char_end: int
    extraction_confidence: float


# ── Patterns (from guardian.py, extended) ───────────────────────────────────

# Explicit digit time with AM/PM (guardian.py primary pattern)
_TIME_WITH_MERIDIEM = re.compile(
    r"\b(1[0-2]|0?[1-9])"
    r"(?::([0-5]\d))?"
    r"\s*(AM|PM|a\.m\.|p\.m\.)\b",
    re.IGNORECASE,
)

# 24-hour format: 14:30, 00:00
_TIME_24H = re.compile(
    r"\b([01]\d|2[0-3]):([0-5]\d)\b"
)

# Digit time WITHOUT meridiem (guardian.py fallback pattern)
_TIME_WITHOUT_MERIDIEM = re.compile(
    r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\b"
)

# Contextual meridiem hints in surrounding words
_MORNING_RE = re.compile(r"\b(?:morning|am|a\.m\.)\b", re.IGNORECASE)
_AFTERNOON_RE = re.compile(r"\b(?:afternoon|noon|midday)\b", re.IGNORECASE)
_EVENING_RE = re.compile(r"\b(?:evening|pm|p\.m\.)\b", re.IGNORECASE)
_NIGHT_RE = re.compile(r"\b(?:night|midnight)\b", re.IGNORECASE)

# Special words
_SPECIAL_TIMES = re.compile(r"\b(noon|midday|midnight)\b", re.IGNORECASE)


def _normalise_meridiem(raw: str) -> str:
    raw = raw.upper().replace(".", "")
    return raw  # "AM" or "PM"


def _context_hint(text: str, start: int, end: int, window: int = 30) -> Optional[str]:
    """Look ±window characters around the match for contextual meridiem hints."""
    snippet = text[max(0, start - window): end + window].lower()
    if _MORNING_RE.search(snippet):
        return "AM"
    if _EVENING_RE.search(snippet) or _NIGHT_RE.search(snippet):
        return "PM"
    if _AFTERNOON_RE.search(snippet):
        return "PM"
    return None


def detect_times(text: str) -> list[TimeMatch]:
    """
    Detect time expressions in a transcript.

    Follows guardian.py logic exactly:
    - Explicit AM/PM → confident extraction
    - No AM/PM with a numeric time → flagged as ambiguous
    Never invents a meridiem when one is absent.
    """
    matches: list[TimeMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # ── 1. Special named times (noon, midnight) ──────────────────────────
    for m in _SPECIAL_TIMES.finditer(text):
        name = m.group(1).lower()
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        hour = 12 if name in ("noon", "midday") else 0
        meridiem = "PM" if name in ("noon", "midday") else "AM"
        matches.append(TimeMatch(
            raw_value=m.group(),
            hour=hour,
            minute=0,
            meridiem=meridiem,
            is_24h=False,
            is_ambiguous=False,
            ambiguity_reason=None,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.95,
        ))

    # ── 2. 24-hour format (unambiguous) ─────────────────────────────────
    for m in _TIME_24H.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        hour = int(m.group(1))
        minute = int(m.group(2))
        matches.append(TimeMatch(
            raw_value=m.group(),
            hour=hour,
            minute=minute,
            meridiem=None,
            is_24h=True,
            is_ambiguous=False,
            ambiguity_reason=None,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.95,
        ))

    # ── 3. Digit time with explicit AM/PM (guardian.py primary) ─────────
    for m in _TIME_WITH_MERIDIEM.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = _normalise_meridiem(m.group(3))
        matches.append(TimeMatch(
            raw_value=m.group(),
            hour=hour,
            minute=minute,
            meridiem=meridiem,
            is_24h=False,
            is_ambiguous=False,
            ambiguity_reason=None,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.92,
        ))

    # ── 4. Digit time WITHOUT meridiem (guardian.py fallback) ────────────
    for m in _TIME_WITHOUT_MERIDIEM.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        # Only flag if not already covered by a longer match
        overlap = any(
            r[0] <= m.start() < r[1] or r[0] < m.end() <= r[1]
            for r in seen_ranges
        )
        if overlap:
            continue
        seen_ranges.add(span)
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0

        # Check context for meridiem hint (but do NOT assert it — only note it)
        context_meridiem = _context_hint(text, m.start(), m.end())

        matches.append(TimeMatch(
            raw_value=m.group(),
            hour=hour,
            minute=minute,
            meridiem=None,                  # NOT set — never invent meridiem
            is_24h=False,
            is_ambiguous=True,              # guardian.py rule: flag it
            ambiguity_reason=(
                "Time detected but AM/PM is not explicitly stated in the transcript. "
                + (f"Context suggests {context_meridiem} but this is not confirmed. " if context_meridiem else "")
                + "Manual verification required."
            ),
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.60,
        ))

    return matches
