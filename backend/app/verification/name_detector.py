"""
SASAA – Name and Entity Detector
===================================
Detects potential person names and other proper nouns.

We use a lightweight rule-based approach (capitalized words, common
Indian name patterns) rather than a full NLP model, because:
  1. No spaCy model is required at runtime
  2. Tamil/Hindi names are often not covered by English NER models
  3. False positives are acceptable — we flag for review, not correct

Detected names are stored with NEEDS_REVIEW status. We never claim
to have identified a name with certainty.
"""

import re
from dataclasses import dataclass


@dataclass
class NameMatch:
    raw_value: str
    char_start: int
    char_end: int
    extraction_confidence: float
    ambiguity_reason: str


# Title-case sequence of 2-4 words as a heuristic for a name
# Works for both English and transliterated Indian names
_CAPITALIZED_NAME_RE = re.compile(
    r"\b([A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20}){1,3}\b"
)

# Common Indian honorifics/titles that precede names
_HONORIFICS = re.compile(
    r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Sri\.?|Smt\.?|Shri\.?|"
    r"Thiru|Thirumathi|Selvi|Kalvi|Er\.?)\s+([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){0,3})\b"
)

# Tamil transliterated name patterns (common patterns)
_TAMIL_NAME_CONTEXT = re.compile(
    r"(?:அவர்கள்|அவர்|அம்மா|அப்பா|அண்ணா|அக்கா)\s*"
    r"([^\s,।]+(?:\s+[^\s,।]+)?)"
)


def detect_names(text: str) -> list[NameMatch]:
    """
    Detect potential person names. All matches are flagged with
    NEEDS_REVIEW — we never claim certainty on name extraction.
    """
    matches: list[NameMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # Honorific + name (highest confidence)
    for m in _HONORIFICS.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        matches.append(NameMatch(
            raw_value=m.group().strip(),
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.80,
            ambiguity_reason=(
                "Name detected following a title/honorific. Speech recognition may "
                "mishear proper nouns — please verify the name is correct."
            ),
        ))

    # Capitalized word sequence (lower confidence)
    for m in _CAPITALIZED_NAME_RE.finditer(text):
        span = (m.start(), m.end())
        overlap = any(r[0] <= m.start() < r[1] for r in seen_ranges)
        if overlap:
            continue
        seen_ranges.add(span)
        matches.append(NameMatch(
            raw_value=m.group().strip(),
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.55,
            ambiguity_reason=(
                "Potential name detected (capitalized sequence). Confidence is low — "
                "please verify this is actually a person or organization name."
            ),
        ))

    return matches
