"""O'zbekcha son so'zlarini butun songa aylantirish.

"qirq besh" -> 45, "o'n besh" -> 15, "sakkiz yuz o'n olti ming" -> 816000.
Ovoz balandligi kabi buyruqlar uchun kerak; arifmetika LLM'ga topshirilmaydi.
"""

from __future__ import annotations

import re

UNITS = {
    "nol": 0, "nol'": 0, "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5,
    "olti": 6, "yetti": 7, "etti": 7, "sakkiz": 8, "to'qqiz": 9,
}

TENS = {
    "o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50,
    "oltmish": 60, "yetmish": 70, "etmish": 70, "sakson": 80, "to'qson": 90,
}

SCALES = {
    "yuz": 100,
    "ming": 1000,
    "million": 1_000_000,
    "milliard": 1_000_000_000,
}

_WORD_RE = re.compile(r"[a-z'`]+")
_DIGITS_RE = re.compile(r"\d+")

ALL_NUMBER_WORDS = set(UNITS) | set(TENS) | set(SCALES)


def words_to_int(text: str) -> int | None:
    """So'zlar ketma-ketligidan sonni ajratadi. Son topilmasa None."""
    if not text:
        return None

    digits = _DIGITS_RE.search(text)
    if digits:
        try:
            return int(digits.group())
        except ValueError:
            return None

    tokens = [t for t in _WORD_RE.findall(text.lower()) if t in ALL_NUMBER_WORDS]
    if not tokens:
        return None

    total = 0
    current = 0
    seen = False

    for token in tokens:
        if token in UNITS:
            current += UNITS[token]
            seen = True
        elif token in TENS:
            current += TENS[token]
            seen = True
        elif token == "yuz":
            current = (current or 1) * 100
            seen = True
        else:
            scale = SCALES[token]
            total += (current or 1) * scale
            current = 0
            seen = True

    if not seen:
        return None
    return total + current


def contains_number(text: str) -> bool:
    return words_to_int(text) is not None
