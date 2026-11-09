"""
SASAA – Negation Detector
===========================
Detects negation words and phrases in transcripts.

This is one of the highest-risk detection categories because speech
recognition systems can:
  - Drop "not" entirely: "do not call" → "do call"
  - Mishear "don't" as "do" or vice versa
  - Merge contractions incorrectly

We flag ALL negation occurrences and their surrounding context so the
user can verify the intended meaning.

Handles both English and common Tamil negation patterns.
"""

import re
from dataclasses import dataclass


@dataclass
class NegationMatch:
    raw_value: str           # the negation word/phrase
    context: str             # surrounding sentence for user review
    char_start: int
    char_end: int
    extraction_confidence: float
    ambiguity_reason: str


# ── English negation patterns ────────────────────────────────────────────────
_NEGATION_WORDS = re.compile(
    r"\b("
    r"not|never|no|don'?t|doesn'?t|didn'?t|won'?t|wouldn'?t|"
    r"can'?t|cannot|couldn'?t|shouldn'?t|mustn'?t|mightn'?t|"
    r"isn'?t|aren'?t|wasn'?t|weren'?t|haven'?t|hasn'?t|hadn'?t|"
    r"neither|nor|nobody|nothing|nowhere|none|"
    r"without|except|unless|refuse|deny|reject|stop|avoid|prevent"
    r")\b",
    re.IGNORECASE,
)

# High-impact negation patterns (action + negation)
_ACTION_NEGATION = re.compile(
    r"\b(?:do|does|did|will|would|can|could|should|must|may|might)"
    r"\s+(?:not|n'?t)\b",
    re.IGNORECASE,
)

# Tamil negation suffixes and words (common forms)
_TAMIL_NEGATION = re.compile(
    r"(?:இல்லை|வேண்டாம்|இல்ல|வேண்டா|கூடாது|முடியாது|செய்யாதே|வரவேண்டாம்)"
)

_CONTEXT_WINDOW = 60  # characters on each side for context extraction


def _extract_context(text: str, start: int, end: int) -> str:
    """Extract a readable snippet around the negation."""
    ctx_start = max(0, start - _CONTEXT_WINDOW)
    ctx_end = min(len(text), end + _CONTEXT_WINDOW)
    snippet = text[ctx_start:ctx_end].strip()
    # Trim to sentence boundary if possible
    for sep in [".", "!", "?", "\n"]:
        parts = snippet.split(sep)
        # find the part containing our match
        for i, part in enumerate(parts):
            if len("".join(parts[:i + 1])) >= (start - ctx_start):
                return parts[i].strip()
    return snippet


def detect_negations(text: str) -> list[NegationMatch]:
    """
    Detect all negation expressions in a transcript.

    Every negation match is flagged for review because:
      - Dropped negation = completely reversed meaning
      - Speech recognition has known issues with "not/now", "don't/do"
    """
    matches: list[NegationMatch] = []
    seen_ranges: set[tuple[int, int]] = set()

    # First pass: high-impact action negations (highest confidence)
    for m in _ACTION_NEGATION.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        context = _extract_context(text, m.start(), m.end())
        matches.append(NegationMatch(
            raw_value=m.group(),
            context=context,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.90,
            ambiguity_reason=(
                f"Action negation '{m.group()}' detected. Speech recognition can "
                "accidentally drop 'not' or mishear 'don't' as 'do', reversing the "
                "intended instruction. Please verify."
            ),
        ))

    # Second pass: standalone negation words
    for m in _NEGATION_WORDS.finditer(text):
        span = (m.start(), m.end())
        # Skip if already covered by action-negation
        already = any(
            r[0] <= m.start() < r[1]
            for r in seen_ranges
        )
        if already:
            continue
        seen_ranges.add(span)
        context = _extract_context(text, m.start(), m.end())
        matches.append(NegationMatch(
            raw_value=m.group(),
            context=context,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.80,
            ambiguity_reason=(
                f"Negation word '{m.group()}' detected. Verify that the transcription "
                "has preserved the correct negative meaning."
            ),
        ))

    # Tamil negations
    for m in _TAMIL_NEGATION.finditer(text):
        span = (m.start(), m.end())
        if span in seen_ranges:
            continue
        seen_ranges.add(span)
        context = _extract_context(text, m.start(), m.end())
        matches.append(NegationMatch(
            raw_value=m.group(),
            context=context,
            char_start=m.start(),
            char_end=m.end(),
            extraction_confidence=0.85,
            ambiguity_reason=(
                "Tamil negation detected. Verify the transcription has preserved "
                "the correct meaning."
            ),
        ))

    # Tamil-script negations from mapper (covers transliterations like நாட்)
    try:
        from app.verification.tamil_mapper import extract_tamil_entities, has_tamil_script
        if has_tamil_script(text):
            for tent in extract_tamil_entities(text):
                if tent.entity_hint == "negation":
                    span = (tent.char_start, tent.char_end)
                    if span in seen_ranges:
                        continue
                    seen_ranges.add(span)
                    context = _extract_context(text, tent.char_start, tent.char_end)
                    matches.append(NegationMatch(
                        raw_value=tent.raw_value,
                        context=context,
                        char_start=tent.char_start,
                        char_end=tent.char_end,
                        extraction_confidence=0.82,
                        ambiguity_reason=(
                            f"Tamil negation/contrast keyword detected. "
                            "Speech recognition may drop negation words reversing intended meaning. "
                            "Please verify."
                        ),
                    ))
    except ImportError:
        pass

    # Sort by position in text
    matches.sort(key=lambda m: m.char_start)
    return matches
