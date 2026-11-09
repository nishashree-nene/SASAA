"""
SASAA – Tamil Script Entity Mapper
=====================================
Translates Tamil Unicode script financial and negation keywords
into their English equivalents so the existing detectors can process them.

The Gnani STT returns native Tamil Unicode script. The existing regex
detectors only work on Latin characters. This module:
  1. Detects Tamil keywords for numbers, currency, negation
  2. Returns a normalised parallel text annotated with detected entities
  3. Also returns entities detected directly from the Tamil text

This approach avoids a full romanization (which would distort text positions).
Instead we run parallel detection: native Tamil + any Latin portion.

Key Tamil vocabulary covered:
  Numbers (spoken): ஐந்து (5), பத்து (10), நூறு (100), ஆயிரம் (1000)...
  Currency: ரூபாய் / ரூபீஸ் (rupees), லட்சம் (lakh), கோடி (crore)
  Negation: இல்லை, வேண்டாம், நாட் (transliteration of "not")
  Amounts in transliteration: ஃபிஃப்டி (fifty), ஃபிஃப்டீன் (fifteen), ஃபோர் (four)
"""

import re
from dataclasses import dataclass
from typing import Optional


# ── Tamil spoken number words (native script) ────────────────────────────────
_TAMIL_NUMBERS: dict[str, int] = {
    # Units
    "ஒன்று": 1, "ஒரு": 1,
    "இரண்டு": 2, "இரு": 2,
    "மூன்று": 3,
    "நான்கு": 4,
    "ஐந்து": 5,
    "ஆறு": 6,
    "ஏழு": 7,
    "எட்டு": 8,
    "ஒன்பது": 9,
    "பத்து": 10,
    "பதினொரு": 11,
    "பன்னிரண்டு": 12,
    "பதிமூன்று": 13,
    "பதினான்கு": 14,
    "பதினைந்து": 15,
    "பதினாறு": 16,
    "பதினேழு": 17,
    "பதினெட்டு": 18,
    "பத்தொன்பது": 19,
    "இருபது": 20,
    "முப்பது": 30,
    "நாற்பது": 40,
    "ஐம்பது": 50,
    "அறுபது": 60,
    "எழுபது": 70,
    "எண்பது": 80,
    "தொண்ணூறு": 90,
    "நூறு": 100,
    "ஆயிரம்": 1_000,
    "லட்சம்": 100_000,
    "கோடி": 10_000_000,
}

# Tamil currency words
_TAMIL_CURRENCY_RE = re.compile(
    r"(?:ரூபாய்|ரூபீஸ்|ரூ\.|ரூ\b|ரூபை)",
    re.IGNORECASE,
)

# Tamil negation words (native + common transliterations)
_TAMIL_NEGATION_RE = re.compile(
    r"(?:"
    r"இல்லை|வேண்டாம்|இல்ல|வேண்டா|கூடாது|முடியாது|"
    r"நாட்\b|நாட் |நாட்$|"   # transliteration of "not"
    r"ஃபிஃப்டீன்|ஃபிஃப்டி"  # fifty/fifteen — mark for review together
    r")",
)

# Transliterated English number words in Tamil script
# e.g. ஃபிஃப்டி = fifty, ஃபிஃப்டீன் = fifteen, ஃபோர் = four
_TAMIL_TRANSLITERATED_AMOUNTS = {
    "ஃபிஃப்டி": ("fifty", 50),
    "ஃபிஃப்டீன்": ("fifteen", 15),
    "ஃபோர்": ("four", 4),
    "ஒன்": ("one", 1),
    "ட்டூ": ("two", 2),
    "த்ரீ": ("three", 3),
    "ஃபைவ்": ("five", 5),
    "சிக்ஸ்": ("six", 6),
    "செவன்": ("seven", 7),
    "ஏட்": ("eight", 8),
    "நைன்": ("nine", 9),
    "டென்": ("ten", 10),
}

# "நாட்" = transliteration of "not"
_TAMIL_NOT_RE = re.compile(r"\bநாட்\b")


@dataclass
class TamilEntity:
    raw_value: str
    entity_hint: str       # "amount", "negation", "number"
    numeric_value: Optional[int]
    has_currency: bool
    char_start: int
    char_end: int


def extract_tamil_entities(text: str) -> list[TamilEntity]:
    """
    Extract financial and negation entities directly from Tamil Unicode text.

    Returns TamilEntity objects. The caller converts these to the standard
    entity types used by the verification engine.
    """
    results: list[TamilEntity] = []
    seen: set[tuple[int, int]] = set()

    # ── 1. Transliterated amounts (ஃபிஃப்டி, ஃபிஃப்டீன், ஃபோர்) ─────────
    for tamil_word, (english_word, numeric) in _TAMIL_TRANSLITERATED_AMOUNTS.items():
        for m in re.finditer(re.escape(tamil_word), text):
            span = (m.start(), m.end())
            if span in seen:
                continue
            # Check if followed by currency word within 5 chars
            lookahead = text[m.end(): m.end() + 15]
            has_currency = bool(_TAMIL_CURRENCY_RE.search(lookahead))
            seen.add(span)
            results.append(TamilEntity(
                raw_value=m.group(),
                entity_hint="amount",
                numeric_value=numeric,
                has_currency=has_currency,
                char_start=m.start(),
                char_end=m.end(),
            ))

    # ── 2. Native Tamil number words ─────────────────────────────────────
    for tamil_num, value in _TAMIL_NUMBERS.items():
        for m in re.finditer(re.escape(tamil_num), text):
            span = (m.start(), m.end())
            if span in seen:
                continue
            lookahead = text[m.end(): m.end() + 15]
            has_currency = bool(_TAMIL_CURRENCY_RE.search(lookahead))
            seen.add(span)
            results.append(TamilEntity(
                raw_value=m.group(),
                entity_hint="amount" if has_currency else "number",
                numeric_value=value,
                has_currency=has_currency,
                char_start=m.start(),
                char_end=m.end(),
            ))

    # ── 3. Tamil "not" transliteration ───────────────────────────────────
    for m in _TAMIL_NOT_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen:
            continue
        seen.add(span)
        results.append(TamilEntity(
            raw_value=m.group(),
            entity_hint="negation",
            numeric_value=None,
            has_currency=False,
            char_start=m.start(),
            char_end=m.end(),
        ))

    # ── 4. Native Tamil negation words ───────────────────────────────────
    for m in _TAMIL_NEGATION_RE.finditer(text):
        span = (m.start(), m.end())
        if span in seen:
            continue
        seen.add(span)
        results.append(TamilEntity(
            raw_value=m.group(),
            entity_hint="negation",
            numeric_value=None,
            has_currency=False,
            char_start=m.start(),
            char_end=m.end(),
        ))

    # Sort by position
    results.sort(key=lambda e: e.char_start)
    return results


def has_tamil_script(text: str) -> bool:
    """Return True if the text contains Tamil Unicode characters."""
    return any('\u0B80' <= ch <= '\u0BFF' for ch in text)
