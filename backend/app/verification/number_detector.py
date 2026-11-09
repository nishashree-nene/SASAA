"""
SASAA – General Number Detector
==================================
Detects standalone numeric sequences that don't clearly belong to
phone numbers or amounts — digit sequences, quantities, and numbers
written in words.

These are flagged at lower priority unless they appear in an important
context (e.g. adjacent to a measurement or count).
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class NumberMatch:
    raw_value: str
    normalized_value: str
    char_start: int
    char_end: int
    extraction_confidence: float


# Standalone numbers (not already captured as phone/amount)
_STANDALONE_NUMBER_RE = re.compile(r"\b\d{1,6}(?:\.\d+)?\b")

_NUMBER_WORDS = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred)\b",
    re.IGNORECASE,
)


def detect_numbers(text: str) -> list[NumberMatch]:
    """
    Detect numeric expressions. Returns only digit-form numbers —
    spoken word numbers are already handled by amount_detector and
    phone_detector. This catches residual short sequences.
    """
    matches: list[NumberMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    for m in _STANDALONE_NUMBER_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        matches.append(NumberMatch(
            raw_value=m.group(),
            normalized_value=m.group().strip(),
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.70,
        ))

    return matches
